# Pi, Tailscale and selective routing

Start on a wired Pi 4/5 with a 64-bit OS or a mini server. ARM64 package/image builds and actual Pi playback throughput must be validated. Avoid realtime video transcoding in the first iteration. Set the memory budget from measurements rather than a hardware promise.

## Explicit mode (implemented)

Loopback is the default. Use SSH forwarding as shown in the README for the first test. To serve a private network directly, change `SHIFTRELAY_BIND` in `.env` to the server's specific LAN or Tailscale IPv4 address and recreate containers. Restrict access with a host firewall/tailnet ACL. Do not bind to every interface or forward these ports from the public internet.

For a Tailscale deployment, install Tailscale on the host and client, confirm that they can connect, bind ShiftRelay to the host's Tailscale IP, and explicitly configure the client's proxy with that IP and port 8080. Enrollment can use port 8787 through the same private path, or use Tailscale Serve for HTTPS access to the loopback portal:

```bash
tailscale serve --bg http://127.0.0.1:8787
```

Serve publishes the portal within your tailnet; do not enable Funnel. Keep the admin API key. A Tailscale Serve certificate only authenticates your portal's hostname; it is not a CA for intercepting YouTube or Netflix.

An exit node sends traffic through your home but does not direct it into an explicit proxy. Apps can ignore OS proxy settings. Tailscale routing is one prerequisite, not a filtering implementation.

## Gateway mode (not implemented)

Transparent interception needs router/VLAN/gateway changes, IPv4 and IPv6 coverage, a return path, protocol handling and a tested bypass route. Do not publish generic iptables rules without knowing the user's topology. Router port mirroring observes traffic; it does not make the Pi the forwarding gateway.

HTTP/3 uses QUIC over UDP and needs an appropriate supported interception mode. Blocking UDP/443 sometimes induces fallback, but can cause failures; it neither decrypts TLS nor guarantees a fallback. ECH and shared CDNs complicate host-based routing. DNS manipulation is not a substitute for a measured routing plan.

The independent [Android WireGuard lab](android-s26.md) is implemented in `compose.android.yaml`; it routes selected apps without Wi-Fi proxy settings. It does not configure the router or bypass app TLS/DRM. Use WireGuard or Tailscale on the phone for the initial experiment, not both simultaneously.

## Performance budget

For remote playback through home, the video traverses your home's download and upload paths. Your home upload speed can become the bottleneck. An indirect path adds latency even when proxy processing is fast. No zero-latency or universal “no slowdown” claim is possible.

Measure direct versus relay startup time, time to first byte, throughput, stalls, CPU, memory, device temperature and 1/2/4 concurrent streams. Run sustained tests on the actual Pi, not just a laptop. Record median and p95 results. Keep opaque flows streaming, use bounded manifest inspection, and make uncertain decisions pass through.
