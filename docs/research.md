# Research plan: native apps first, measurable experiments

The goal is ad reduction across native apps and TVs, with the Pi as coordinator. The question is where each device permits observation and control. We will not treat an unavailable capability as implemented.

The product target is complete native-app ad blocking where achievable, including YouTube, Netflix, Hulu, Facebook and Instagram. Ad reduction experiments are intermediate work; see [product-goals.md](product-goals.md) for the difference between full success and partial suppression.

## 1. Native app control protocol

First target: a compatible YouTube TV app. iSponsorBlockTV demonstrates server-side pairing, ad muting, native Skip interaction, and SponsorBlock integration on supported devices. Study its pairing/playback protocol and test on one owned device. Reuse compatible libraries under their licenses or build an independently documented adapter. Do not infer Netflix/Hulu support from YouTube support.

Acceptance: 30 manually labeled ad breaks on the chosen app version, log state transitions locally, verify initial mute state restoration and disconnect recovery. Report skips only after the real Skip operation is available. Record network latency, false positives and failures. No adapter has been implemented in this scaffold.

## 2. Proxy capability probes

For a user-opted-in app: check whether it honors an explicit proxy; whether HTTPS is tunnelled or inspectable; which selected endpoints appear; and whether response bodies contain independent ad metadata. Do not log credentials, account tokens, entire playback responses or licensed video into GitHub. Avoid altering DRM/license endpoints.

If an app rejects the CA, mark `uninspectable` for that test configuration and use a bypass. Routing does not provide the TLS keys. If TLS works but the media is DRM-encrypted, distinguish readable manifest metadata from decoded media. Ad removal requires a service-specific timing/control proof, not just a successful TLS connection.

## 3. Perceptual sidecar hypothesis

**Hypothesis:** combine repeated-ad audio fingerprints, optical ad-label/countdown detection, and available native playback state to reduce false positives and control mute/visual suppression without inspecting the media transport.

This is a proposed combination of existing techniques. No novelty claim is made. Comskip, audio-fingerprinting systems and perceptual ad-blocking research are prior art. A static black frame, high loudness or repetitive music is weak evidence on its own.

The file-based `shiftrelay.fingerprint` experiment computes normalized spectral band features on mono PCM WAVs and aligns a sample against a reference using cosine similarity. The 0.85 candidate threshold is arbitrary and uncalibrated. It returns `unknown` on a mismatch. It does not use AI, capture live output, maintain a corpus or control playback. Synthetic tests cover a cropped, gain-reduced, noisy signal and an unrelated negative; they do not establish real advertising accuracy.

For a real test, collect opted-in/lawfully obtained reference samples. Hold out different ads, episode content, microphone placements, rooms and devices. Measure precision, recall, false suppressions per viewing hour, detection latency and end-of-ad error. Split by ad creative and recording session to avoid leakage.

**Important feedback problem:** muting the TV also removes the acoustic signal being used for detection. Options to test are an independent optical cue, a separate lawful audio observation path unaffected by speaker muting, a native playback-state signal, or a bounded timer with conservative restore. A microphone-only matcher cannot reliably recognize that an unknown ad ended after it has silenced its own input. A fixed-duration timer is a fallback, not a universal solution.

External cameras can observe what a person sees without asking the app for decrypted frames, but require physical placement and consent, may record private surroundings, and still need a reliable control channel. Protected digital capture may be blank. HDMI capture can be restricted by HDCP; no HDCP bypass is proposed. A phone microphone/capture agent introduces OS permissions and capability limits.

## 4. Traffic metadata hypothesis

Timing, packet sizes, direction, multiplexing and bitrate transitions may correlate with an ad on a particular device/version. They do not provide decoded content or stable HTTP request boundaries inside encrypted HTTP/2 or HTTP/3 sessions. Shared connections can carry ads and content together.

A candidate experiment should train on consent-labeled sessions, hold out device/network/app versions, evaluate precision-recall and concept drift, and abstain on uncertainty. Do not connect such a classifier to packet dropping until a replay test proves acceptable playback behavior. Arbitrary packet drops provoke transport retransmission and stalls; a guessed ad boundary is not an application-level Skip command.

## 5. Maintenance hypothesis

CI can detect changes to fixture behavior. Signed data-only rule updates can be automated after an operator configures a trusted publisher. A future AI maintainer should propose small pull requests with regression fixtures, run them against labeled captures, and require review for expanded trust/routing scope. A local LLM should remain off the critical stream-processing path, particularly on a Pi 4.

AI cannot promise bug-free autonomous repair. Unknown platform behavior should cause passthrough and a local diagnostic, not escalating packet manipulation.

## Primary references

- [mitmproxy certificates and pinning](https://docs.mitmproxy.org/stable/concepts/certificates/)
- [mitmproxy modes](https://docs.mitmproxy.org/stable/concepts/modes/)
- [Android network security configuration](https://developer.android.com/privacy-and-security/security-config)
- [Apple manual certificate trust](https://support.apple.com/en-us/102390)
- [W3C Encrypted Media Extensions](https://www.w3.org/TR/encrypted-media/)
- [Tailscale exit nodes](https://tailscale.com/docs/features/exit-nodes)
- [iSponsorBlockTV](https://github.com/dmunozv04/iSponsorBlockTV)
- [Comskip](https://github.com/erikkaashoek/Comskip)
- [AdVersarial: Perceptual Ad Blocking meets Adversarial Machine Learning](https://arxiv.org/abs/1811.03194)
