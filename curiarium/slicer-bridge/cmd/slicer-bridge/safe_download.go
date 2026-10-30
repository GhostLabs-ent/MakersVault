package main

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/netip"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"
)

const (
	defaultMaxRedirects = 5
	downloadTimeout     = 5 * time.Minute
	dialTimeout         = 30 * time.Second
)

// Ranges that Python's is_reserved/is_private reject but netip reports as
// ordinary global unicast: CGNAT, IETF protocol assignments, TEST-NET-1/2/3,
// 6to4 relay anycast, benchmarking, reserved and IPv6 documentation.
//
// The IPv6 transition and embedding prefixes are blocked because they carry an
// IPv4 address that Python's is_private/is_reserved rejects for the inner
// address, and IsGlobalUnicast alone would let them through. IPv4-mapped
// addresses (::ffff:0:0/96) need no entry here: isBlockedAddress unmaps them
// before any check.
var blockedPrefixes = []netip.Prefix{
	netip.MustParsePrefix("100.64.0.0/10"),
	netip.MustParsePrefix("192.0.0.0/24"),
	netip.MustParsePrefix("192.0.2.0/24"),
	netip.MustParsePrefix("192.88.99.0/24"),
	netip.MustParsePrefix("198.18.0.0/15"),
	netip.MustParsePrefix("198.51.100.0/24"),
	netip.MustParsePrefix("203.0.113.0/24"),
	netip.MustParsePrefix("240.0.0.0/4"),
	netip.MustParsePrefix("2001:db8::/32"),
	netip.MustParsePrefix("::/8"),           // IPv4-compatible (::, ::1 already blocked)
	netip.MustParsePrefix("64:ff9b::/96"),   // NAT64 well-known prefix — embeds IPv4
	netip.MustParsePrefix("64:ff9b:1::/48"), // local-use NAT64
	netip.MustParsePrefix("2002::/16"),      // 6to4 — embeds IPv4
	netip.MustParsePrefix("2001::/23"),      // Teredo et al
	netip.MustParsePrefix("100::/64"),       // discard-only
	netip.MustParsePrefix("3fff::/20"),      // documentation
}

// downloader fetches a URL without trusting a single hop of it. Every hop is
// validated and resolved before a socket is opened, and the addresses that were
// validated are the only ones ever dialed.
//
// A downloader is single-flight: it is not safe for concurrent use. The pins map
// is deliberately not mutex-guarded because one downloader serves one download.
type downloader struct {
	maxRedirects int
	timeout      time.Duration
	lookup       func(ctx context.Context, host string) ([]netip.Addr, error)
	dial         func(ctx context.Context, network, address string) (net.Conn, error)
	pins         map[string][]netip.Addr
	client       *http.Client
}

func newDownloader() *downloader {
	d := &downloader{
		maxRedirects: defaultMaxRedirects,
		timeout:      downloadTimeout,
		lookup:       lookupHost,
		dial:         (&net.Dialer{Timeout: dialTimeout}).DialContext,
		pins:         map[string][]netip.Addr{},
	}
	d.client = &http.Client{
		Transport: &http.Transport{
			// A proxy connects on our behalf, which defeats IP pinning.
			Proxy:       nil,
			DialContext: d.dialPinned,
		},
		CheckRedirect: func(*http.Request, []*http.Request) error {
			return http.ErrUseLastResponse
		},
	}
	return d
}

func lookupHost(ctx context.Context, host string) ([]netip.Addr, error) {
	return net.DefaultResolver.LookupNetIP(ctx, "ip", host)
}

func isBlockedAddress(addr netip.Addr) bool {
	addr = addr.Unmap()
	if !addr.IsValid() {
		return true
	}
	if addr.IsLoopback() || addr.IsPrivate() || addr.IsLinkLocalUnicast() ||
		addr.IsLinkLocalMulticast() || addr.IsMulticast() || addr.IsUnspecified() ||
		!addr.IsGlobalUnicast() {
		return true
	}
	for _, prefix := range blockedPrefixes {
		if prefix.Contains(addr) {
			return true
		}
	}
	return false
}

func (d *downloader) download(ctx context.Context, rawURL, targetPath string) error {
	ctx, cancel := context.WithTimeout(ctx, d.timeout)
	defer cancel()

	res, err := d.get(ctx, rawURL)
	if err != nil {
		return err
	}
	defer res.Body.Close()
	if res.StatusCode < 200 || res.StatusCode >= 300 {
		return fmt.Errorf("download failed: %s", res.Status)
	}
	out, err := os.Create(targetPath)
	if err != nil {
		return fmt.Errorf("create file: %w", err)
	}
	defer out.Close()
	if _, err := io.Copy(out, res.Body); err != nil {
		return fmt.Errorf("save file: %w", err)
	}
	return nil
}

func (d *downloader) get(ctx context.Context, rawURL string) (*http.Response, error) {
	current := rawURL
	for hop := 0; hop <= d.maxRedirects; hop++ {
		target, err := d.resolve(ctx, current)
		if err != nil {
			return nil, err
		}
		res, err := d.send(ctx, target)
		if err != nil {
			return nil, err
		}
		if !isRedirectStatus(res.StatusCode) {
			return res, nil
		}
		location := strings.TrimSpace(res.Header.Get("Location"))
		// Draining lets the connection be reused, but a hostile origin could
		// stream an endless 3xx body, so the drain is capped.
		_, _ = io.CopyN(io.Discard, res.Body, 1<<20)
		res.Body.Close()
		if location == "" {
			return nil, errors.New("redirect response is missing a location header")
		}
		if hop == d.maxRedirects {
			return nil, errors.New("too many redirects")
		}
		next, err := target.Parse(location)
		if err != nil {
			return nil, errors.New("invalid redirect URL")
		}
		current = next.String()
	}
	return nil, errors.New("too many redirects")
}

func (d *downloader) send(ctx context.Context, target *url.URL) (*http.Response, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, target.String(), nil)
	if err != nil {
		return nil, fmt.Errorf("request: %w", err)
	}
	res, err := d.client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("download %s: %w", redactURL(target.String()), redactError(err))
	}
	return res, nil
}

func (d *downloader) resolve(ctx context.Context, rawURL string) (*url.URL, error) {
	target, err := url.Parse(rawURL)
	if err != nil {
		return nil, errors.New("invalid URL")
	}
	scheme := strings.ToLower(target.Scheme)
	if scheme != "http" && scheme != "https" {
		return nil, errors.New("URL must start with http:// or https://")
	}
	if target.User != nil {
		return nil, errors.New("credentials in URL are not allowed")
	}
	host := target.Hostname()
	if host == "" {
		return nil, errors.New("invalid URL")
	}
	if err := validatePort(target.Port()); err != nil {
		return nil, err
	}
	addresses, err := d.resolveHost(ctx, host)
	if err != nil {
		return nil, err
	}
	d.pin(host, addresses)
	return target, nil
}

func validatePort(port string) error {
	if port == "" {
		return nil
	}
	number, err := strconv.Atoi(port)
	if err != nil || number < 0 || number > 65535 {
		return errors.New("invalid URL port")
	}
	return nil
}

func (d *downloader) resolveHost(ctx context.Context, host string) ([]netip.Addr, error) {
	lowered := strings.ToLower(host)
	if lowered == "localhost" || strings.HasSuffix(lowered, ".local") {
		return nil, errors.New("local addresses are not allowed")
	}
	if addr, err := netip.ParseAddr(host); err == nil {
		if isBlockedAddress(addr) {
			return nil, errors.New("local addresses are not allowed")
		}
		return []netip.Addr{addr.Unmap()}, nil
	}

	addresses, err := d.lookup(ctx, host)
	if err != nil || len(addresses) == 0 {
		return nil, errors.New("unable to resolve host")
	}
	validated := make([]netip.Addr, 0, len(addresses))
	for _, addr := range addresses {
		addr = addr.Unmap()
		if isBlockedAddress(addr) {
			return nil, errors.New("local addresses are not allowed")
		}
		validated = append(validated, addr)
	}
	return validated, nil
}

func (d *downloader) pin(host string, addresses []netip.Addr) {
	d.pins[strings.ToLower(host)] = addresses
}

// dialPinned ignores the hostname the transport asks for and dials the
// addresses that were validated for it, so a resolver that changes its answer
// between validation and connect cannot move the socket.
func (d *downloader) dialPinned(ctx context.Context, network, address string) (net.Conn, error) {
	host, port, err := net.SplitHostPort(address)
	if err != nil {
		return nil, fmt.Errorf("invalid dial address: %w", err)
	}
	addresses, ok := d.pins[strings.ToLower(host)]
	if !ok || len(addresses) == 0 {
		return nil, fmt.Errorf("no validated address for host %s", host)
	}
	var lastErr error
	for _, addr := range addresses {
		conn, err := d.dial(ctx, network, net.JoinHostPort(addr.String(), port))
		if err == nil {
			return conn, nil
		}
		lastErr = err
	}
	return nil, lastErr
}

func isRedirectStatus(status int) bool {
	switch status {
	case http.StatusMovedPermanently, http.StatusFound, http.StatusSeeOther,
		http.StatusTemporaryRedirect, http.StatusPermanentRedirect:
		return true
	}
	return false
}

func redactError(err error) error {
	var urlErr *url.Error
	if errors.As(err, &urlErr) {
		return fmt.Errorf("%s %s: %w", urlErr.Op, redactURL(urlErr.URL), urlErr.Err)
	}
	return err
}
