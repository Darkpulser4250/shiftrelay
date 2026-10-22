# Compatibility is a measured result

No real streaming account or physical device has been tested in this release.

| Target | Proposed access | Main question | v0.1 status |
|---|---|---|---|
| Controlled local HTTPS origin | Explicit proxy + test CA | Can we filter and preserve other content? | Integration tested |
| Clear, owned VOD manifest | Explicit proxy + custom markers | Can a selected ad segment be removed? | Byte-level transformation tested |
| YouTube TV app | Pairing/playback control protocol | Which devices expose ad state, mute and Skip? | Research; examine iSponsorBlockTV |
| YouTube Android app | Proxy or device control | Does this app version accept routing and CA trust? | Unknown |
| Netflix / Hulu native apps | Proxy, then permitted control/output probes | Trust/pinning, DRM and ad-state visibility? | Unknown; no adapters |
| Instagram app | Proxy or permitted UI signals | Separate ad response vs content, trust, app behavior? | Unknown; no adapters |
| Facebook app | Proxy or permitted UI signals | Sponsored feed/reel delivery boundaries; trust; organic-content preservation? | Unknown; no adapters |
| TV with external mic/camera | Acoustic/optical observation + IR/CEC/local remote | Recognition latency, control reliability, end-of-ad detection? | Concept; file-based audio matcher only |
| Phone with companion capture | OS-approved capture + local control | Is protected output unavailable? Can capture coexist with VPN? | Concept; not implemented |

For each actual test, record: OS/app version, hardware, transport mode, proxy honored, CA trusted, opaque/decoded media, visible ad cues, control operations, latency, false positives, playback failures, rollback procedure. Keep raw account data out of public issues.

Distinguish outcomes: `request blocked`, `ad segment removed`, `native skip pressed`, `audio muted`, `video hidden`, `ad wait eliminated`. They are different. Muting or hiding an unskippable ad does not eliminate the wait or its download.
