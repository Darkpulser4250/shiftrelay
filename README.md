# ShiftRelay

**A standalone, self-hosted research platform for selective network ad filtering and native-device ad suppression.** Docker targets: Raspberry Pi 4/5 running a 64-bit OS, and x86-64 mini servers.

**Primary goal:** prevent ads from being delivered or shown in the official **YouTube, Netflix, Hulu, Facebook and Instagram apps**, using our own Docker-hosted server. Aim for complete ad removal wherever technically achievable, with normal content and app functions preserved. Website-only filtering and muting alone do not satisfy that full goal. See the [product goals and acceptance criteria](docs/product-goals.md).

**Status: experimental v0.4.** Opt-in [server response filters](docs/platform-filters.md) now edit recognized YouTube player JSON, Instagram timeline JSON and Facebook GraphQL JSON/JSON-lines. These require decrypted compatible responses; official Android app compatibility is unvalidated. This is **not** a universal server-only official-app blocker. YouTube's unverified binary formats and Netflix/Hulu remain unsupported. The [Android WireGuard lab](docs/android-s26.md), probe APK and optional YouTube-on-TV bridge remain available. No browser extension, app patch or root is required by the server filters. Pi-hole and AdGuard are optional independent neighbors, not dependencies.

**Samsung phone setup:** follow [the Android server + APK guide](docs/android-s26.md). Use `compose.android.yaml` for that independent stack; the regular quick start below launches the explicit proxy. The Android default filters only our reserved test domains, so passing its test is not evidence of platform ad removal.

**First native-app experiment:** [YouTube-on-TV bridge setup and recovery](bridges/youtube_tv/README.md). This pairs with the TV app through its control service; it does not require a certificate or route the video through the proxy. It is partial suppression—volume reduction and optional native Skip requests—not full ad removal.

## Why this project exists

Network routing, visibility, ad recognition, and playback control are separate engineering problems. ShiftRelay investigates them separately, then aims to combine the approaches that work on each device:

1. **Selective HTTPS proxy:** inspect only explicitly configured hosts, and apply rules to compatible clients that accept your per-install CA.
2. **Native device control:** an optional YouTube-on-TV bridge implements pairing, observe mode, bounded volume reduction, native Skip requests and crash-recovery records. Some protocols communicate through the service rather than staying on the LAN. A physical-device test is still required.
3. **Perceptual sidecar:** recognize repeated ad audio/visual patterns after playback, then drive a supported device control. A file-based audio fingerprint experiment is included; live capture, muting hardware and remote-control adapters are not implemented.

This combination is a research direction, not a claim of a novel algorithm or universal compatibility.

## What works in this release

| Component | Implemented behavior | Evidence / limit |
|---|---|---|
| HTTPS proxy | Authenticated explicit HTTP proxy, selectively terminates TLS | Real local HTTPS integration tests |
| Filtering | Exact host + URL path rules; GET/HEAD only | Blocks the owned `/ads.js` fixture without contacting its origin |
| Owned-media HLS | Removes explicitly marked ad segments from simple clear VOD manifests | Fixture + HTTPS test; not a production service parser |
| Bypass | Non-target HTTPS connections are opaque tunnels | Integration test sees the real origin certificate |
| Enrollment | Consent page, public CA download, SHA-256 fingerprint | No automatic installation or device configuration |
| Status | Aggregate proxy counters and explicit scope | No device discovery, raw traffic recording or cloud telemetry |
| Rule updates | Pinned Ed25519 verification, expiry, monotonic versions, schema + canary checks | Data-only; no scope expansion or code execution |
| Audio experiment | Local WAV fingerprint comparison with unknown/candidate output | Synthetic offset/gain/noise test, no real-world accuracy claim |
| Native YouTube-on-TV control | Pairing, observe mode, optional volume-zero and enabled Skip requests, bounded recovery | Real library + simulated Lounge server; physical TV unvalidated |
| Android ingress + probe | Per-app WireGuard, owned HTTPS origin, native APK, optional private hostname discovery | Automated tests; physical S26 Ultra unvalidated |
| Platform response adapters | Opt-in YouTube player, Instagram timeline and Facebook GraphQL filters for known JSON schemas | Real local TLS fixtures; official phone apps unvalidated; no Netflix/Hulu or Android protobuf adapter |
| Autonomous AI repair | Proposed maintenance workflow | Not implemented; no autonomous code agent |

## Quick start

Install Docker Engine with Compose on your 64-bit Linux host. From this repository:

```bash
python3 scripts/setup.py
docker compose up -d --build
docker compose ps
```

Open `http://127.0.0.1:8787`. The admin key is in `.env`. Start with the supplied empty, observe-only policy: it inspects no HTTPS hosts and blocks nothing.

The service uses mitmproxy as its transport implementation. We do not implement our own TLS or weaken upstream certificate validation. Its dependencies and base images need routine maintenance.

### Use it from another computer

Recommended first test: keep both ports on loopback and forward them over SSH:

```bash
ssh -N -L 8080:127.0.0.1:8080 -L 8787:127.0.0.1:8787 user@your-pi
```

On that computer, open `http://127.0.0.1:8787/enroll`. Read the inspection disclosure. Compare the displayed certificate fingerprint with the server owner over a trusted channel; then download the public certificate if you agree. Install/trust it using your OS instructions. This page does not install or trust it for you.

Configure a compatible client's HTTP/HTTPS proxy as `127.0.0.1:8080`, with the username/password from `SHIFTRELAY_PROXY_AUTH` in `.env`. The proxy password is separate from the dashboard key. Some apps ignore OS proxy settings, reject private CAs or use pinned certificates.

Choose exact test hosts in `config/policy.json`. Do not enable a whole streaming service until you have measured what its app exposes. For a host you own, a policy can look like:

```json
{
  "schema": 1,
  "version": 1,
  "mode": "filter",
  "inspect_hosts": ["media.example.org"],
  "bypass_hosts": [],
  "block_rules": [{"id": "owned-ad", "host": "media.example.org", "path": "/ads.js"}],
  "owned_hls_hosts": []
}
```

Replace the example host and path with a real test origin you control. Restart after policy changes:

```bash
docker compose restart proxy
```

The addon can notice changes on inspected requests, but a restart is required to apply TLS scope consistently. Existing TLS connections cannot switch between interception and tunneling in place.

### Bypass and recovery

Set `mode` to `bypass` and restart the proxy to tunnel all new HTTPS connections. To stop using the proxy entirely, disable the proxy setting on the client. Router/VPN rules need separate changes if you configured them. An unavailable explicit proxy does **not** automatically fall back to a direct connection.

Remove the CA from your device's trust store when you no longer use inspection. Do not publish `.env`, CA state, WireGuard keys, captures or personal app logs. Default Compose ports are loopback only. Binding an authenticated HTTP proxy to a LAN sends its Basic credentials without transport encryption on that LAN; prefer SSH or a private Tailscale path.

## Tailscale and network-wide deployment

See [deployment.md](docs/deployment.md). A Tailscale exit node changes the route and outer VPN encryption. It does not terminate the app's inner TLS connection, configure ShiftRelay, or decrypt DRM media.

The regular stack is an **explicit proxy**. The separate [Android stack](docs/android-s26.md) uses WireGuard for selected native apps. A router-wide transparent gateway, captive portal triggers, DHCP/PAC deployment and per-device enrollment enforcement are not implemented. Joining Wi-Fi is not consent to install a root CA.

## Run the proof

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r research.txt
.venv/bin/python -m unittest discover -s tests -v
```

The integration suite generates disposable certificates, starts a real local HTTPS origin and a real mitmdump process, and verifies filtering, preservation, CA rejection, proxy authentication and TLS passthrough. It makes no requests to streaming services. Docker and ARM64 execution need separate hardware/CI validation; passing Python tests does not certify those deployments.

The independent native bridge has its own dependencies and tests:

```bash
.venv/bin/pip install -r bridges/youtube_tv/requirements.txt
PYTHONPATH=bridges/youtube_tv .venv/bin/python -m unittest discover -s bridges/youtube_tv/tests -v
```

Its tests use a local simulated Lounge service with the actual pyytlounge library to check pairing, authentication round-trips, event decoding and outgoing commands. They do not connect to YouTube or certify device compatibility.

### Audio fingerprint experiment

Convert lawfully obtained/owned audio samples with FFmpeg to mono 8 kHz 16-bit PCM WAV, then:

```bash
.venv/bin/python -m shiftrelay.fingerprint known-ad.wav listening-window.wav
```

The result is an uncalibrated similarity score and an offset. It does not discover new ads, capture your microphone, mute anything, or classify all advertising. No copyrighted ad database is distributed. See [research.md](docs/research.md) for the experiment design and the acoustic-feedback problem after muting.

## Updates and maintenance

Dependabot proposes dependency/workflow updates. CI runs unit/integration tests and builds container images for AMD64 and ARM64 on pull requests. Images are not published automatically in this initial scaffold.

An optional signed rule updater is implemented:

```bash
.venv/bin/python -m shiftrelay.update \
  --catalog-url https://YOUR-TRUSTED-HOST/catalog.json \
  --public-key /path/to/pinned-release-key.pub \
  --policy config/policy.json
docker compose restart proxy
```

There is no live release catalog or release signing key bundled. Set up and verify your own publisher first. See [maintenance.md](docs/maintenance.md) for envelope format, opt-in scheduling, rollback and limits. Neither AI nor a signed rule pack may expand inspection scope. Autonomous code patching is a future PR-and-test workflow, not a claim that software maintains itself reliably.

## Research priorities

The current priority is **server-side filtering with unchanged official apps**: establish which actual phone responses can be inspected, verify their schemas, and measure ad removal while preserving normal playback. The shipped JSON adapters are a partial step, not verified native-app support. Netflix/Hulu still need trust/application-encryption/playback investigation. The optional YouTube TV bridge is separate partial suppression; its physical pairing, ad-state accuracy, volume recovery and latency remain unvalidated. It does not implement restart/resume.

See [research.md](docs/research.md), [architecture.md](docs/architecture.md), and [compatibility.md](docs/compatibility.md). Contributions should include a device/app version and measured failure modes, not claims that packet size or AI bypasses encryption.

## License

The proxy/portal core and root tests are MIT. The optional independent service under `bridges/youtube_tv/`, including its tests, is GPL-3.0-only and has its own license/notice because it uses pyytlounge. The core image does not import or install that library. Dependencies and external projects retain their licenses; no external implementation source is vendored. See [NOTICE.md](NOTICE.md).
