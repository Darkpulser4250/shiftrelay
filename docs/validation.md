# Validation record — October 22, 2026

Executed locally with CPython 3.12.14, mitmproxy 12.3.0 and NumPy 2.3.5 on x86-64 Linux.

`python -m unittest discover -s tests -v`: **22 tests passed**.

The suite includes real local HTTPS sessions through a mitmdump subprocess, exact-request blocking without contacting the origin, preservation of normal content, full streaming of a 2 MiB response, owned HLS fixture rewriting, rejection of an untrusted interception certificate, proxy-auth enforcement, observe mode and end-to-end TLS bypass using the real origin certificate. The local origin uses a disposable trusted CA; upstream TLS verification is enabled.

Other tests cover malformed/unsafe HLS passthrough, strict policy scope, enrollment CSRF/consent checks, exclusion of private CA material from downloads, signed-rule tamper/replay/expiry/scope/canary rejection, and synthetic audio fingerprint alignment with gain reduction and noise plus an unrelated negative.

`pip check`: no broken requirements. Python compilation, dashboard JavaScript syntax and YAML parsing passed. YAML parsing is not a substitute for Docker Compose validation.

Not executed: Docker build/Compose runtime, ARM64 image build, Raspberry Pi hardware benchmark, router integration, Tailscale networking, live streaming accounts, native TV/app pairing, microphone/camera capture or real ad accuracy tests. CI is configured to test/build AMD64 and ARM64 once hosted, but no GitHub run has occurred yet.

Dashboard browser visual QA was attempted, but no browser executable was installed and the browser download failed in this environment. HTTP enrollment/API behavior is covered by automated tests; visual layout remains unverified.
