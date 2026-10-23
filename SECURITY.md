# Security

This project performs opt-in TLS interception on selected hosts. A trusted CA is powerful: protect the proxy host, private CA and installation credentials. The portal receives only the public CA certificate. Deleting a certificate download does not remove its trust from your OS.

Do not publish secret keys, captures, app tokens or personal browsing data in issues. Use GitHub private vulnerability reporting if the repository owner enables it. This is an unaudited prototype with no guarantee of leak-free or failure-free operation.

Scope: no automatic root trust installation, no stealth enrollment, no default-router changes, no DRM key extraction and no disabled upstream TLS verification. Proxy Basic credentials need a protected network path. Tailscale/SSH can protect that path; the proxy's own listen port is HTTP CONNECT, not an HTTPS-wrapped proxy.

The explicit proxy can reach hosts that the server can reach. It is not an SSRF sandbox or an internet-facing shared proxy. Keep it restricted to your own trusted clients. Its auth key is currently shared per installation; per-device revocation is future work.

Default empty scope tunnels HTTPS, but passing a connection through still reveals destination/connection metadata to the relay. Lack of content inspection is not lack of all metadata.

The optional native bridge stores TV pairing tokens and volume-recovery records in a private volume, never in its dashboard status. Pair only from your interactive terminal. It communicates through YouTube's Lounge service; this is not a wholly offline/LAN-only protocol. Assist is opt-in and may change TV volume or request native Skip; restoration is best effort if connectivity or power is lost. Keep the physical remote available. Do not publish pairing/state files in issues.

The optional Android stack has a separate private CA/WireGuard volume and one peer. Its exported client config is a secret. Per-app selection is enforced by the phone client, not an authenticated app identity at the server. The relay can reach destinations available to its host; keep the peer restricted to your own trusted phone. Private DNS hostname discovery is off by default and never exposed through the portal. Toggling it off leaves the previous private record until erased. Both IP families enter the selected-app tunnel; limited upstream IPv6 support may interrupt traffic. See docs/android-s26.md for revocation and device-side bypass.
