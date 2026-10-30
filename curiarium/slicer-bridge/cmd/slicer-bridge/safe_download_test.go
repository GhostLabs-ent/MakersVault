package main

import (
	"context"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"net/netip"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"testing"
)

// TEST-NET ranges are rejected by the address policy, so fake hosts resolve to
// genuine global addresses and are then routed to loopback servers.
const (
	publicIP       = "93.184.216.34"
	secondPublicIP = "8.8.8.8"
	thirdPublicIP  = "1.1.1.1"
)

type route struct {
	status   int
	location string
	body     string
}

// routingServer is a loopback HTTP server with a per-path route table and a
// request log.
type routingServer struct {
	server *httptest.Server
	routes map[string]route
	mu     sync.Mutex
	paths  []string
}

func newRoutingServer(routes map[string]route) *routingServer {
	s := &routingServer{routes: map[string]route{}}
	for path, handler := range routes {
		s.routes[path] = handler
	}
	s.server = httptest.NewServer(http.HandlerFunc(s.serve))
	return s
}

func (s *routingServer) serve(w http.ResponseWriter, r *http.Request) {
	s.mu.Lock()
	s.paths = append(s.paths, r.URL.Path)
	handler, ok := s.routes[r.URL.Path]
	s.mu.Unlock()
	if !ok {
		http.NotFound(w, r)
		return
	}
	if handler.location != "" {
		w.Header().Set("Location", handler.location)
	}
	status := handler.status
	if status == 0 {
		status = http.StatusOK
	}
	w.WriteHeader(status)
	_, _ = io.WriteString(w, handler.body)
}

func (s *routingServer) port() int {
	parsed, err := url.Parse(s.server.URL)
	if err != nil {
		panic(err)
	}
	port, err := strconv.Atoi(parsed.Port())
	if err != nil {
		panic(err)
	}
	return port
}

func (s *routingServer) url(path string) string {
	return s.server.URL + path
}

func (s *routingServer) requestedPaths() []string {
	s.mu.Lock()
	defer s.mu.Unlock()
	return append([]string{}, s.paths...)
}

func (s *routingServer) close() {
	s.server.Close()
}

// fakeNetwork is a fake resolver plus fake connector keyed on hostnames and
// (ip, port) pairs, so no test touches a real network.
type fakeNetwork struct {
	hosts    map[string][]netip.Addr
	routes   map[string]string
	mu       sync.Mutex
	attempts []string
	lookups  []string
	onLookup func(host string)
}

func newFakeNetwork() *fakeNetwork {
	return &fakeNetwork{hosts: map[string][]netip.Addr{}, routes: map[string]string{}}
}

func (n *fakeNetwork) pin(host, ip string, server *routingServer) {
	n.hosts[host] = []netip.Addr{netip.MustParseAddr(ip)}
	port := strconv.Itoa(server.port())
	n.routes[net.JoinHostPort(ip, port)] = net.JoinHostPort("127.0.0.1", port)
}

func (n *fakeNetwork) url(host string, server *routingServer, path string) string {
	return fmt.Sprintf("http://%s:%d%s", host, server.port(), path)
}

func (n *fakeNetwork) downloader() *downloader {
	d := newDownloader()
	d.lookup = n.lookup
	d.dial = n.dial
	return d
}

func (n *fakeNetwork) lookup(_ context.Context, host string) ([]netip.Addr, error) {
	n.mu.Lock()
	addresses, ok := n.hosts[host]
	hook := n.onLookup
	if ok {
		n.lookups = append(n.lookups, host)
	}
	n.mu.Unlock()
	if !ok {
		return nil, fmt.Errorf("no such host: %s", host)
	}
	if hook != nil {
		hook(host)
	}
	return append([]netip.Addr{}, addresses...), nil
}

func (n *fakeNetwork) dial(ctx context.Context, network, address string) (net.Conn, error) {
	n.mu.Lock()
	n.attempts = append(n.attempts, address)
	target, ok := n.routes[address]
	n.mu.Unlock()
	if !ok {
		return nil, fmt.Errorf("no route for %s", address)
	}
	var dialer net.Dialer
	return dialer.DialContext(ctx, network, target)
}

func (n *fakeNetwork) dialed() []string {
	n.mu.Lock()
	defer n.mu.Unlock()
	return append([]string{}, n.attempts...)
}

func (n *fakeNetwork) resolved() []string {
	n.mu.Lock()
	defer n.mu.Unlock()
	return append([]string{}, n.lookups...)
}

func targetPath(t *testing.T) string {
	t.Helper()
	return filepath.Join(t.TempDir(), "model.stl")
}

func downloadError(t *testing.T, d *downloader, rawURL, target string) error {
	t.Helper()
	err := d.download(context.Background(), rawURL, target)
	if err == nil {
		t.Fatalf("download(%s) unexpectedly succeeded", redactURL(rawURL))
	}
	return err
}

func assertNoDialTo(t *testing.T, dialed []string, port int) {
	t.Helper()
	for _, address := range dialed {
		_, rawPort, err := net.SplitHostPort(address)
		if err != nil {
			t.Fatalf("unparseable dial address %q: %v", address, err)
		}
		if rawPort == strconv.Itoa(port) {
			t.Fatalf("a connection was attempted to the hostile address: %s", address)
		}
	}
}

func assertNoRequests(t *testing.T, server *routingServer) {
	t.Helper()
	if paths := server.requestedPaths(); len(paths) != 0 {
		t.Fatalf("the hostile server received requests: %v", paths)
	}
}

func withCredentials(rawURL string) string {
	return strings.Replace(rawURL, "://", "://user:pass@", 1)
}

func TestIsBlockedAddress(t *testing.T) {
	tests := map[string]bool{
		"127.0.0.1":            true,
		"127.1.2.3":            true,
		"10.0.0.5":             true,
		"172.16.4.4":           true,
		"192.168.1.10":         true,
		"169.254.169.254":      true,
		"100.64.0.1":           true,
		"0.0.0.0":              true,
		"224.0.0.1":            true,
		"240.0.0.1":            true,
		"255.255.255.255":      true,
		"192.0.2.10":           true,
		"198.51.100.10":        true,
		"203.0.113.10":         true,
		"::1":                  true,
		"::":                   true,
		"fe80::1":              true,
		"fc00::1":              true,
		"ff02::1":              true,
		"2001:db8::1":          true,
		"::ffff:127.0.0.1":     true,
		"::7f00:1":             true,
		"64:ff9b::7f00:1":      true,
		"64:ff9b::a00:1":       true,
		"2002:7f00:1::":        true,
		"2001::7f00:1":         true,
		"100::1":               true,
		"3fff::1":              true,
		publicIP:               false,
		secondPublicIP:         false,
		thirdPublicIP:          false,
		"2606:4700:4700::1111": false,
	}

	for raw, blocked := range tests {
		if actual := isBlockedAddress(netip.MustParseAddr(raw)); actual != blocked {
			t.Errorf("isBlockedAddress(%s) = %v, expected %v", raw, actual, blocked)
		}
	}
}

func TestDownloadRefusesRedirectToLoopback(t *testing.T) {
	private := newRoutingServer(map[string]route{"/secret": {body: "secret"}})
	defer private.close()
	origin := newRoutingServer(map[string]route{
		"/start": {status: http.StatusFound, location: fmt.Sprintf("http://127.0.0.1:%d/secret", private.port())},
	})
	defer origin.close()

	network := newFakeNetwork()
	network.pin("one.example", publicIP, origin)

	err := downloadError(t, network.downloader(), network.url("one.example", origin, "/start"), targetPath(t))
	if !strings.Contains(err.Error(), "local addresses are not allowed") {
		t.Fatalf("unexpected error: %v", err)
	}
	assertNoDialTo(t, network.dialed(), private.port())
	assertNoRequests(t, private)
}

func TestDownloadRefusesRedirectToMetadataAddress(t *testing.T) {
	origin := newRoutingServer(map[string]route{
		"/start": {status: http.StatusFound, location: "http://169.254.169.254/latest/meta-data/"},
	})
	defer origin.close()

	network := newFakeNetwork()
	network.pin("one.example", publicIP, origin)

	err := downloadError(t, network.downloader(), network.url("one.example", origin, "/start"), targetPath(t))
	if !strings.Contains(err.Error(), "local addresses are not allowed") {
		t.Fatalf("unexpected error: %v", err)
	}
	if dialed := network.dialed(); len(dialed) != 1 || dialed[0] != net.JoinHostPort(publicIP, strconv.Itoa(origin.port())) {
		t.Fatalf("unexpected dial attempts: %v", dialed)
	}
}

func TestDownloadRefusesRedirectToPrivateNetwork(t *testing.T) {
	private := newRoutingServer(map[string]route{"/secret": {body: "secret"}})
	defer private.close()
	origin := newRoutingServer(map[string]route{
		"/start": {status: http.StatusFound, location: fmt.Sprintf("http://10.0.0.5:%d/secret", private.port())},
	})
	defer origin.close()

	network := newFakeNetwork()
	network.pin("one.example", publicIP, origin)

	err := downloadError(t, network.downloader(), network.url("one.example", origin, "/start"), targetPath(t))
	if !strings.Contains(err.Error(), "local addresses are not allowed") {
		t.Fatalf("unexpected error: %v", err)
	}
	assertNoDialTo(t, network.dialed(), private.port())
	assertNoRequests(t, private)
}

func TestDownloadRefusesMalformedRedirectLocation(t *testing.T) {
	hostile := newRoutingServer(map[string]route{"/secret": {body: "secret"}})
	defer hostile.close()
	origin := newRoutingServer(map[string]route{
		"/start": {status: http.StatusFound, location: "http://[::1/x"},
	})
	defer origin.close()

	network := newFakeNetwork()
	network.pin("one.example", publicIP, origin)

	err := downloadError(t, network.downloader(), network.url("one.example", origin, "/start"), targetPath(t))
	// net/http parses the Location header before CheckRedirect runs, so this
	// input is rejected there rather than by our own redirect parsing.
	if !strings.Contains(err.Error(), "failed to parse Location header") {
		t.Fatalf("unexpected error: %v", err)
	}
	if dialed := network.dialed(); len(dialed) != 1 || dialed[0] != net.JoinHostPort(publicIP, strconv.Itoa(origin.port())) {
		t.Fatalf("unexpected dial attempts: %v", dialed)
	}
	assertNoRequests(t, hostile)
	assertNoDialTo(t, network.dialed(), hostile.port())
}

func TestDownloadRefusesRedirectToIPv6Loopback(t *testing.T) {
	private := newRoutingServer(map[string]route{"/secret": {body: "secret"}})
	defer private.close()
	origin := newRoutingServer(map[string]route{
		"/start": {status: http.StatusFound, location: fmt.Sprintf("http://[::1]:%d/secret", private.port())},
	})
	defer origin.close()

	network := newFakeNetwork()
	network.pin("one.example", publicIP, origin)

	err := downloadError(t, network.downloader(), network.url("one.example", origin, "/start"), targetPath(t))
	if !strings.Contains(err.Error(), "local addresses are not allowed") {
		t.Fatalf("unexpected error: %v", err)
	}
	assertNoRequests(t, private)
	assertNoDialTo(t, network.dialed(), private.port())
}

func TestDownloadRefusesCredentialInURL(t *testing.T) {
	landing := newRoutingServer(map[string]route{"/landing": {body: "never"}})
	defer landing.close()
	origin := newRoutingServer(map[string]route{
		"/start": {status: http.StatusFound, location: withCredentials(fmt.Sprintf("http://two.example:%d/landing", landing.port()))},
	})
	defer origin.close()

	network := newFakeNetwork()
	network.pin("one.example", publicIP, origin)
	network.pin("two.example", secondPublicIP, landing)

	t.Run("initial URL", func(t *testing.T) {
		initial := withCredentials(network.url("one.example", origin, "/start"))
		err := downloadError(t, network.downloader(), initial, targetPath(t))
		if !strings.Contains(err.Error(), "credentials in URL are not allowed") {
			t.Fatalf("unexpected error: %v", err)
		}
		if dialed := network.dialed(); len(dialed) != 0 {
			t.Fatalf("a connection was attempted before validation: %v", dialed)
		}
		assertNoRequests(t, origin)
	})

	t.Run("redirect location", func(t *testing.T) {
		err := downloadError(t, network.downloader(), network.url("one.example", origin, "/start"), targetPath(t))
		if !strings.Contains(err.Error(), "credentials in URL are not allowed") {
			t.Fatalf("unexpected error: %v", err)
		}
		assertNoRequests(t, landing)
		assertNoDialTo(t, network.dialed(), landing.port())
	})
}

func TestDownloadRefusesNonHTTPScheme(t *testing.T) {
	origin := newRoutingServer(map[string]route{
		"/start": {status: http.StatusFound, location: "file:///etc/passwd"},
	})
	defer origin.close()

	network := newFakeNetwork()
	network.pin("one.example", publicIP, origin)
	path := targetPath(t)

	err := downloadError(t, network.downloader(), network.url("one.example", origin, "/start"), path)
	if !strings.Contains(err.Error(), "URL must start with http:// or https://") {
		t.Fatalf("unexpected error: %v", err)
	}

	for _, rawURL := range []string{"ftp://one.example/model.stl", "gopher://one.example/model.stl"} {
		err := downloadError(t, network.downloader(), rawURL, path)
		if !strings.Contains(err.Error(), "URL must start with http:// or https://") {
			t.Fatalf("download(%s): unexpected error: %v", rawURL, err)
		}
	}
	if _, err := os.Stat(path); err == nil {
		t.Fatalf("a file was written for a refused download")
	}
}

func TestDownloadRefusesLocalhostHostname(t *testing.T) {
	server := newRoutingServer(map[string]route{"/model.stl": {body: "never"}})
	defer server.close()

	network := newFakeNetwork()
	for _, host := range []string{"localhost", "model.local", "LOCALHOST", "Model.Local"} {
		err := downloadError(t, network.downloader(), network.url(host, server, "/model.stl"), targetPath(t))
		if !strings.Contains(err.Error(), "local addresses are not allowed") {
			t.Fatalf("download(%s): unexpected error: %v", host, err)
		}
	}
	if dialed := network.dialed(); len(dialed) != 0 {
		t.Fatalf("a connection was attempted to a local hostname: %v", dialed)
	}
	assertNoRequests(t, server)
}

func TestDownloadRefusesInvalidPort(t *testing.T) {
	origin := newRoutingServer(map[string]route{
		"/start": {status: http.StatusFound, location: "http://one.example:99999/x"},
	})
	defer origin.close()

	network := newFakeNetwork()
	network.pin("one.example", publicIP, origin)

	err := downloadError(t, network.downloader(), network.url("one.example", origin, "/start"), targetPath(t))
	if !strings.Contains(err.Error(), "invalid URL port") {
		t.Fatalf("unexpected error: %v", err)
	}

	err = downloadError(t, network.downloader(), "http://one.example:99999/model.stl", targetPath(t))
	if !strings.Contains(err.Error(), "invalid URL port") {
		t.Fatalf("initial URL: unexpected error: %v", err)
	}
}

func TestDownloadRefusesRedirectWithoutLocation(t *testing.T) {
	origin := newRoutingServer(map[string]route{"/start": {status: http.StatusFound}})
	defer origin.close()

	network := newFakeNetwork()
	network.pin("one.example", publicIP, origin)

	err := downloadError(t, network.downloader(), network.url("one.example", origin, "/start"), targetPath(t))
	if !strings.Contains(err.Error(), "missing a location header") {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestDownloadFollowsRedirectChainWithinLimit(t *testing.T) {
	server := newRoutingServer(map[string]route{
		"/a": {status: http.StatusFound, location: "/b"},
		"/b": {status: http.StatusFound, location: "/c"},
		"/c": {body: "final-body"},
	})
	defer server.close()

	network := newFakeNetwork()
	network.pin("one.example", publicIP, server)
	path := targetPath(t)

	if err := network.downloader().download(context.Background(), network.url("one.example", server, "/a"), path); err != nil {
		t.Fatalf("download: %v", err)
	}
	body, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read target: %v", err)
	}
	if string(body) != "final-body" {
		t.Fatalf("target contains %q, expected %q", body, "final-body")
	}
	if paths := server.requestedPaths(); strings.Join(paths, ",") != "/a,/b,/c" {
		t.Fatalf("request log = %v, expected [/a /b /c]", paths)
	}
}

func TestDownloadRefusesRedirectLoopExceedingHopCap(t *testing.T) {
	server := newRoutingServer(map[string]route{"/loop": {status: http.StatusFound, location: "/loop"}})
	defer server.close()

	network := newFakeNetwork()
	network.pin("one.example", publicIP, server)

	err := downloadError(t, network.downloader(), network.url("one.example", server, "/loop"), targetPath(t))
	if !strings.Contains(err.Error(), "too many redirects") {
		t.Fatalf("unexpected error: %v", err)
	}
	if paths := server.requestedPaths(); len(paths) != defaultMaxRedirects+1 {
		t.Fatalf("server saw %d requests, expected %d", len(paths), defaultMaxRedirects+1)
	}
}

func TestDownloadRefusesTooManyHops(t *testing.T) {
	server := newRoutingServer(map[string]route{
		"/a": {status: http.StatusFound, location: "/b"},
		"/b": {status: http.StatusFound, location: "/c"},
		"/c": {body: "unreachable"},
	})
	defer server.close()

	network := newFakeNetwork()
	network.pin("one.example", publicIP, server)
	d := network.downloader()
	d.maxRedirects = 1

	err := downloadError(t, d, network.url("one.example", server, "/a"), targetPath(t))
	if !strings.Contains(err.Error(), "too many redirects") {
		t.Fatalf("unexpected error: %v", err)
	}
	if paths := server.requestedPaths(); strings.Join(paths, ",") != "/a,/b" {
		t.Fatalf("request log = %v, expected [/a /b]", paths)
	}
}

func TestClientDoesNotFollowRedirectsAutomatically(t *testing.T) {
	landing := newRoutingServer(map[string]route{"/landed": {body: "landed"}})
	defer landing.close()
	origin := newRoutingServer(map[string]route{
		"/start": {status: http.StatusFound, location: landing.url("/landed")},
	})
	defer origin.close()

	d := newDownloader()
	d.pin("127.0.0.1", []netip.Addr{netip.MustParseAddr("127.0.0.1")})

	req, err := http.NewRequest(http.MethodGet, origin.url("/start"), nil)
	if err != nil {
		t.Fatalf("request: %v", err)
	}
	res, err := d.client.Do(req)
	if err != nil {
		t.Fatalf("do: %v", err)
	}
	defer res.Body.Close()
	if res.StatusCode != http.StatusFound {
		t.Fatalf("status = %d, expected %d", res.StatusCode, http.StatusFound)
	}
	assertNoRequests(t, landing)
}

func TestDownloadPinsValidatedAddressAcrossDNSRebind(t *testing.T) {
	server := newRoutingServer(map[string]route{"/ok": {body: "ok"}})
	defer server.close()

	network := newFakeNetwork()
	network.pin("one.example", publicIP, server)
	network.onLookup = func(host string) {
		if host == "one.example" {
			network.hosts["one.example"] = []netip.Addr{netip.MustParseAddr("127.0.0.1")}
		}
	}
	path := targetPath(t)

	if err := network.downloader().download(context.Background(), network.url("one.example", server, "/ok"), path); err != nil {
		t.Fatalf("download: %v", err)
	}
	body, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read target: %v", err)
	}
	if string(body) != "ok" {
		t.Fatalf("target contains %q, expected %q", body, "ok")
	}
	if lookups := network.resolved(); len(lookups) != 1 {
		t.Fatalf("host resolved %d times, expected 1: %v", len(lookups), lookups)
	}
	dialed := network.dialed()
	if len(dialed) != 1 || dialed[0] != net.JoinHostPort(publicIP, strconv.Itoa(server.port())) {
		t.Fatalf("unexpected dial attempts: %v", dialed)
	}
	for _, address := range dialed {
		if strings.HasPrefix(address, "127.0.0.1:") {
			t.Fatalf("a connection was attempted to the rebound address: %s", address)
		}
	}
}

func TestDownloadRefusesMixedDNSAnswerWithPrivateAddress(t *testing.T) {
	server := newRoutingServer(map[string]route{"/ok": {body: "never"}})
	defer server.close()

	network := newFakeNetwork()
	network.pin("one.example", publicIP, server)
	network.hosts["one.example"] = []netip.Addr{
		netip.MustParseAddr(publicIP),
		netip.MustParseAddr("127.0.0.1"),
	}

	err := downloadError(t, network.downloader(), network.url("one.example", server, "/ok"), targetPath(t))
	if !strings.Contains(err.Error(), "local addresses are not allowed") {
		t.Fatalf("unexpected error: %v", err)
	}
	if dialed := network.dialed(); len(dialed) != 0 {
		t.Fatalf("a connection was attempted before validation: %v", dialed)
	}
	assertNoRequests(t, server)
}

func TestDownloadPinsEachRedirectHopSeparately(t *testing.T) {
	landing := newRoutingServer(map[string]route{"/landing": {body: "ok"}})
	defer landing.close()
	origin := newRoutingServer(map[string]route{
		"/start": {status: http.StatusFound, location: fmt.Sprintf("http://two.example:%d/landing", landing.port())},
	})
	defer origin.close()

	network := newFakeNetwork()
	network.pin("one.example", publicIP, origin)
	network.pin("two.example", secondPublicIP, landing)
	path := targetPath(t)

	if err := network.downloader().download(context.Background(), network.url("one.example", origin, "/start"), path); err != nil {
		t.Fatalf("download: %v", err)
	}
	body, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read target: %v", err)
	}
	if string(body) != "ok" {
		t.Fatalf("target contains %q, expected %q", body, "ok")
	}

	dialed := network.dialed()
	expected := []string{
		net.JoinHostPort(publicIP, strconv.Itoa(origin.port())),
		net.JoinHostPort(secondPublicIP, strconv.Itoa(landing.port())),
	}
	for _, address := range expected {
		found := false
		for _, actual := range dialed {
			if actual == address {
				found = true
			}
		}
		if !found {
			t.Fatalf("dial attempts %v are missing %s", dialed, address)
		}
	}
	if lookups := network.resolved(); strings.Join(lookups, ",") != "one.example,two.example" {
		t.Fatalf("lookups = %v, expected [one.example two.example]", lookups)
	}
}
