# Validation record — October 22, 2026

Executed locally with CPython 3.12.14, mitmproxy 12.3.0 and NumPy 2.3.5 on x86-64 Linux.

`python -m unittest discover -s tests -v`: **22 tests passed**.

The suite includes real local HTTPS sessions through a mitmdump subprocess, exact-request blocking without contacting the origin, preservation of normal content, full streaming of a 2 MiB response, owned HLS fixture rewriting, rejection of an untrusted interception certificate, proxy-auth enforcement, observe mode and end-to-end TLS bypass using the real origin certificate. The local origin uses a disposable trusted CA; upstream TLS verification is enabled.

Other tests cover malformed/unsafe HLS passthrough, strict policy scope, enrollment CSRF/consent checks, exclusion of private CA material from downloads, signed-rule tamper/replay/expiry/scope/canary rejection, and synthetic audio fingerprint alignment with gain reduction and noise plus an unrelated negative.

`pip check`: no broken requirements. Python compilation, dashboard JavaScript syntax and YAML parsing passed. YAML parsing is not a substitute for Docker Compose validation.

After publication, [GitHub Actions run 39869467541](https://github.com/Darkpulser4250/shiftrelay/actions/runs/39869467541) passed all jobs for commit `7e2b657a155aea1c7fa8691b3ed111fc60970df7`: the Python suite and dependency checks, native AMD64/ARM64 container builds, Compose configuration validation, actual proxy/portal startup with their read-only filesystems and volumes, health checks, public-certificate/private-CA isolation and authenticated proxy forwarding. Disposable CI services and volumes were then removed.

Not executed: Raspberry Pi hardware benchmarks, sustained/concurrent streaming performance, router integration, Tailscale networking, live streaming accounts, native TV/app pairing, microphone/camera capture or real ad accuracy tests. Successful ARM64 CI runtime checks do not establish Pi thermal/throughput behavior or streaming-service compatibility.

Dashboard browser visual QA was attempted, but no browser executable was installed and the browser download failed in this environment. HTTP enrollment/API behavior is covered by automated tests; visual layout remains unverified.

## Version 0.2 native bridge — local validation

The updated core suite passes **28 tests**. The independent YouTube-on-TV bridge passes **26 tests**, for **54 total**. The bridge suite includes the actual pyytlounge 3.4.0 library connecting to a local aiohttp Lounge simulator: TV-code pairing, current auth serialization/loading, token refresh, connection/subscription framing, ad-state events and outgoing native volume/Skip commands. A full runtime session also completes against that local service. No test connects to the real YouTube service or a physical TV.

Controller tests cover passive observe mode, already-muted/zero-volume preservation, unknown volume/state abstention, manual volume overrides, the silence budget, Skip opt-in and retry limits, bounded command timeouts, device-bound journal recovery, journal expiry and command-acceptance without a TV acknowledgement. Additional tests verify hidden-prompt preconditions, owner-only pairing files, offline unpaired startup and sanitized/stale native status.

The optional bridge has a separate GPL-3.0-only image and private state volume. CI is extended to build both images on native AMD64/ARM64 runners and start the bridge unpaired in observe mode. Its startup test checks that it remains passive and that the MIT core image does not install its protocol library. Results for this new image/runtime configuration must be checked in the associated pull request before merging.

Remaining validation: actual TV pairing and ad-state accuracy; physical volume/Skip behavior; disconnect/crash recovery on the device; sustained Pi resource use. An accepted command and passing simulator test do not prove that an ad was suppressed or removed on a real app.

## Version 0.3 Android lab

The core suite now passes **39 tests** locally (11 new Android tests). Coverage includes persistent owner-only WireGuard keys, per-app configuration, endpoint injection rejection, both IP-family routes, opt-in bounded private DNS discovery, public-status privacy, virtual-origin scoping, real mitmdump content preservation/request blocking, untrusted-CA rejection and startup-log key exclusion. A real WireGuard server starts locally; the HTTPS fixture assertions use a second explicit transport with the same CA. The bridge remains independently tested.

CI additionally builds/verifies the native Android APK with Android SDK 36/build-tools 36.0.0 and JDK 17. Native AMD64/ARM64 jobs start the independent Docker stack and use a real Linux kernel WireGuard peer in a disposable network namespace to test tunneled DNS, HTTPS content, blocking, CA rejection and aggregate diagnostics. These new CI results must be checked before merge. The test client needs host privileges; the deployed server container does not.

Not established: execution of the APK on the S26 Ultra, trust behavior of any official streaming/social app, production ad removal, Pi hardware throughput/thermals, battery use, IPv6 compatibility, VPN handover or Tailscale coexistence. No streaming account or phone was accessed. See [phone test procedure](android-s26.md).
