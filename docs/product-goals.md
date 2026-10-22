# Product goals and acceptance criteria

## The intended product

ShiftRelay is an independently useful, open-source server hosted by its users in Docker on a Raspberry Pi 4/5 or a mini server. Its primary goal is complete ad blocking, where achievable, in the official native YouTube, Netflix, Hulu, Facebook and Instagram applications on opted-in phones, tablets and TVs. More platforms can follow.

The server should handle selected platforms efficiently and preserve normal content and application functions. It should support local use and private remote access such as Tailscale, clear device enrollment, an accessible dashboard, bypass and recovery, and verified maintenance updates. Pi-hole/AdGuard integration is optional; DNS blocking is not the core product.

The current release is research code, not delivery of this full product. An optional experimental YouTube-on-TV control adapter is implemented; it provides partial suppression requests and still requires physical-device validation. No production platform adapter or complete native-app ad-removal solution is shipped.

## Keep success definitions precise

| Outcome | Counts as complete ad blocking? | Required evidence |
|---|---|---|
| Ad request prevented before delivery | Potentially | Verify normal content and player behavior; no substitute ad/retry loop |
| Ad segments removed, ordinary playback preserved | Potentially | Real native-app playback, correct boundaries, no wait or stall |
| Ad omitted from a social feed | Potentially | No sponsored item shown; normal feed, comments, messaging and uploads still work |
| Native Skip pressed once available | Partial | Time-to-skip and remaining ad exposure |
| Ad audio muted / picture hidden | Partial | Detection/restore reliability; report remaining wait and download |
| Entire platform blocked | No | Denying access to YouTube/Netflix/etc. does not satisfy the goal |
| Browser-only result | No | Browser findings can inform adapters but do not prove native-app support |
| Owned test fixture filtered | Foundation only | Real platform support must be measured separately |

## Platform workstreams

| Platform | First investigation | Production acceptance |
|---|---|---|
| YouTube | Native TV pairing/control signals; official mobile app proxy/trust and endpoint probes | Actual ads prevented or removed in the tested native app; partial control actions labeled separately |
| Netflix / Hulu | Proxy handling, accepted trust, readable metadata, DRM boundaries, timing and playback checks | No ad exposure or added wait on tested ad-supported plans, with ordinary playback intact |
| Facebook / Instagram | Official-app trust/proxy behavior; feed delivery formats and sponsored-item boundaries | Sponsored feed/reel content omitted without breaking organic content or normal app functions |

These investigations are hypotheses. Certificate installation, VPN routing, metadata classification and a local model are not evidence of complete blocking by themselves. App versions, regions, plans and device types can differ.

## Validation gates

1. Demonstrate the route on one owned device without disrupting ordinary playback.
2. Record what is visible and controllable, and mark unavailable capabilities explicitly.
3. Demonstrate one real ad-removal operation with normal content preserved.
4. Run held-out sessions with ad and non-ad content. Measure false blocking, missed ads, exposure time, stalls and startup latency.
5. Test restart, disconnect, bypass, rollback and app updates.
6. Publish a versioned compatibility report before claiming support.

Use the least invasive access that works. Keep inference off the critical path until its latency and false positives have been measured. A failure should have a documented recovery route; users must know when full removal is unavailable rather than having a partial fallback silently presented as success.

## Maintenance goal

Aim for verified rule updates, regression checks, staged releases and rollback. An eventual AI maintainer may propose reviewed patches with evidence. Autonomous arbitrary-code updates and guaranteed self-repair are not implemented or promised.
