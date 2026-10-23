# Compatibility is a measured result

No real streaming account or physical device has been tested in this release.

| Target | Proposed access | Main question | Current status |
|---|---|---|---|
| Controlled local HTTPS origin | Explicit proxy + test CA | Can we filter and preserve other content? | Integration tested |
| Clear, owned VOD manifest | Explicit proxy + custom markers | Can a selected ad segment be removed? | Byte-level transformation tested |
| YouTube app on a TV/streamer | Pairing/playback control protocol | Which devices expose correct ad state, volume and Skip? | Optional experimental bridge; actual library + simulated server tested; physical device unvalidated |
| Galaxy S26 Ultra / owned native probe | Per-app WireGuard + scoped user CA | Does the phone reach the server and preserve content while blocking the fixture? | Docker lab + APK implemented; physical phone unvalidated |
| YouTube Android app | Per-app WireGuard, then selective inspection/control research | Does this app version accept routing and CA trust? | Routing/probe tooling and conditional player-JSON filter implemented; official Android TLS/binary formats and end-to-end ad removal unvalidated |
| Netflix / Hulu native apps | Proxy, then permitted control/output probes | Trust/pinning, DRM and ad-state visibility? | Unknown; no adapters |
| Instagram app | Selective HTTPS response filtering | Can this app version expose the known timeline JSON and preserve playback? | Conditional timeline-JSON adapter implemented; official app unvalidated; Stories/Reels unsupported |
| Facebook app | Selective HTTPS response filtering | Does this app expose supported GraphQL JSON or an unsupported binary format? | Conditional GraphQL JSON adapter implemented; official app unvalidated; no complete feed/reel coverage |
| TV with external mic/camera | Acoustic/optical observation + IR/CEC/local remote | Recognition latency, control reliability, end-of-ad detection? | Concept; file-based audio matcher only |
| Phone with companion capture | OS-approved capture + local control | Is protected output unavailable? Can capture coexist with VPN? | Concept; not implemented |

For each actual test, record: OS/app version, hardware, transport mode, proxy honored, CA trusted, opaque/decoded media, visible ad cues, control operations, latency, false positives, playback failures, rollback procedure. Keep raw account data out of public issues.

Distinguish outcomes: `request blocked`, `ad segment removed`, `native skip pressed`, `audio muted`, `video hidden`, `ad wait eliminated`. They are different. Muting or hiding an unskippable ad does not eliminate the wait or its download.
