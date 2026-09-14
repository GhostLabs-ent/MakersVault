package presetconsent

import (
	"context"
	"io"
	"log"
	"net"
	"net/http"
	"sync"
	"time"

	"makersvault/slicer-bridge/internal/presetui"
)

// LocalServer owns one session and one ephemeral numeric-loopback listener.
// It is inactive in production: no main/protocol caller dispatches the UI helper.
// URL is a private local bearer URL, never a log field or remote import authority.
type LocalServer struct {
	ctx           context.Context
	launchMu      sync.Mutex
	launchStarted bool
	session       *Session
	url           string
	cancel        context.CancelFunc
	done          chan struct{}
	server        *http.Server
	listener      *limitedListener
}

type serverLimits struct {
	connections, headers                         int
	header, read, write, idle, request, shutdown time.Duration
}

func localLimits() serverLimits {
	return serverLimits{connections: 8, headers: 8 << 10, header: 3 * time.Second,
		read: 5 * time.Second, write: 20 * time.Second, idle: 5 * time.Second,
		request: 20 * time.Second, shutdown: 2 * time.Second}
}

// StartLocal never looks up a browser or reads local profiles. The caller owns
// explicit browser launch through OpenBrowser, or Close without launching.
func StartLocal(ctx context.Context, session *Session) (*LocalServer, error) {
	return startLocal(ctx, session, localLimits())
}

func startLocal(ctx context.Context, session *Session, limits serverLimits) (*LocalServer, error) {
	if session == nil || ctx == nil || ctx.Err() != nil {
		return nil, Code("consent_server_unavailable")
	}
	session.mu.Lock()
	if !session.live() || session.serverStarted {
		session.mu.Unlock()
		return nil, Code("consent_server_unavailable")
	}
	session.serverStarted = true // never attach a second host, even after shutdown
	session.mu.Unlock()
	hostctx, cancel := context.WithCancel(ctx)
	stopSession := context.AfterFunc(session.ctx, cancel)
	lc := net.ListenConfig{}
	listener, err := lc.Listen(hostctx, "tcp4", "127.0.0.1:0")
	if err != nil {
		stopSession()
		cancel()
		session.Close()
		return nil, Code("consent_server_unavailable")
	}
	handler, err := NewLocalHandler(session, listener.Addr().String())
	if err != nil || hostctx.Err() != nil {
		_ = listener.Close()
		stopSession()
		cancel()
		session.Close()
		return nil, Code("consent_server_unavailable")
	}
	bounded := &limitedListener{Listener: listener, slots: make(chan struct{}, limits.connections)}
	host := &LocalServer{ctx: hostctx, session: session, url: handler.URL(), cancel: cancel,
		done: make(chan struct{}), listener: bounded}
	protocols := new(http.Protocols)
	protocols.SetHTTP1(true) // no h2c multiplexing around the connection budget
	requests := make(chan struct{}, limits.connections)
	host.server = &http.Server{
		Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			// A peer can close a socket before its handler returns. Keep a separate
			// work cap so connection churn cannot multiply rendering/backend work.
			select {
			case requests <- struct{}{}:
				defer func() { <-requests }()
			default:
				w.Header().Set("Cache-Control", "no-store")
				http.Error(w, "Local preview busy", http.StatusServiceUnavailable)
				return
			}
			requestctx, release := context.WithTimeout(r.Context(), limits.request)
			defer release()
			handler.ServeHTTP(w, r.WithContext(requestctx))
		}),
		BaseContext:       func(net.Listener) context.Context { return hostctx },
		ReadHeaderTimeout: limits.header, ReadTimeout: limits.read, WriteTimeout: limits.write,
		IdleTimeout: limits.idle, MaxHeaderBytes: limits.headers, Protocols: protocols,
		ErrorLog: log.New(io.Discard, "", 0), // no nonce, URL, body, path or panic logging
	}
	served := make(chan struct{})
	go func() {
		defer close(served)
		_ = host.server.Serve(bounded)
		cancel() // also revoke on an unexpected accept/server failure
	}()
	go func() {
		<-hostctx.Done()
		session.Close() // cancel worker contexts before waiting for HTTP drain
		drain, release := context.WithTimeout(context.Background(), limits.shutdown)
		_ = host.server.Shutdown(drain)
		release()
		_ = host.server.Close() // forcibly close slow/incomplete connections
		_ = bounded.Close()
		<-served
		stopSession()
		close(host.done)
	}()
	return host, nil
}

func (h *LocalServer) URL() string { return h.url }

// OpenBrowser attempts one launch of this host's own URL. It is a local owner
// operation, never an HTTP action or caller-supplied target. Success only means
// the OS accepted the launch, not that a browser loaded the page. Failure revokes
// the host, without terminating a browser that the OS may already have opened.
func (h *LocalServer) OpenBrowser(ctx context.Context) error {
	return h.openBrowser(ctx, presetui.OpenBrowser)
}

func (h *LocalServer) openBrowser(ctx context.Context, open func(context.Context, string) error) error {
	h.launchMu.Lock()
	if h.launchStarted {
		h.launchMu.Unlock()
		return Code("consent_browser_already_attempted")
	}
	h.launchStarted = true
	h.launchMu.Unlock()
	if ctx == nil {
		h.Close()
		return Code("consent_browser_unavailable")
	}
	launchctx, cancel := context.WithTimeout(h.ctx, presetui.BrowserTimeout)
	stop := context.AfterFunc(ctx, cancel)
	defer stop()
	defer cancel()
	if ctx.Err() != nil {
		cancel()
	}
	if launchctx.Err() != nil {
		h.Close()
		return Code("consent_browser_unavailable")
	}
	err := open(launchctx, h.url)
	if err != nil || ctx.Err() != nil || launchctx.Err() != nil {
		h.Close()
		return Code("consent_browser_unavailable")
	}
	return nil
}

// Done closes after revocation, bounded drain and listener/connection closure.
// It does not assert that an arbitrary non-cooperative injected backend returned.
// Production workers retain their separately tested timeout/kill/reap contract.
func (h *LocalServer) Done() <-chan struct{} { return h.done }

// Close is concurrent-safe, idempotent and waits for bounded server teardown.
// Do not call it synchronously from this server's own HTTP handler.
func (h *LocalServer) Close() {
	h.cancel()
	<-h.done
}

// Accept rejects excess sockets before handing them to net/http (and before a
// per-connection handler goroutine). OS backlog/packet-rate protection is separate.
type limitedListener struct {
	net.Listener
	slots chan struct{}
}

func (l *limitedListener) Accept() (net.Conn, error) {
	for {
		conn, err := l.Listener.Accept()
		if err != nil {
			return nil, err
		}
		select {
		case l.slots <- struct{}{}:
			return &limitedConn{Conn: conn, release: func() { <-l.slots }}, nil
		default:
			_ = conn.Close()
		}
	}
}

type limitedConn struct {
	net.Conn
	once    sync.Once
	release func()
}

func (c *limitedConn) Close() error {
	err := c.Conn.Close()
	c.once.Do(c.release)
	return err
}
