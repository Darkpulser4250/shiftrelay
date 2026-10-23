# Server-side platform response filters (v0.4)

The filters in this release run entirely on your Pi/mini server. They do not patch apps, install an accessibility service, root a phone or use a browser extension.

**This is not a working universal blocker for untouched official Android apps.** Filtering requires the relay to see a supported decrypted response. Routing traffic through the server does not supply TLS keys. A private CA cannot force an app to trust it. YouTube's unverified binary responses, Netflix/Hulu ad playback, and unsupported social-app formats remain unchanged. No official app or streaming account has been tested.

## Implemented filters

| Adapter | Exact request targets | Implemented action | Limits |
|---|---|---|---|
| `youtube_player` | `/youtubei/v1/player` on `youtubei.googleapis.com`, `www.youtube.com`, `m.youtube.com` | Removes nonempty top-level `adPlacements`, `playerAds`, `adSlots` arrays from recognized playable JSON responses | JSON only; no Android protobuf/SABR/SSAI support; no guarantee about client ad behavior |
| `instagram_timeline` | `/api/v1/feed/timeline/` on `i.instagram.com` | Drops timeline records with a positive `ad_id` plus an ad action or populated ad metadata | No Story/Reels adapter; ordinary posts, captions saying “sponsored” and paid partnerships remain |
| `facebook_graphql` | `/graphql` or `/api/graphql/` on `graph.facebook.com`, `b-graph.facebook.com`, `www.facebook.com`, `web.facebook.com` | Removes an ad `node` with category `SPONSORED` or a descendant typed `SponsoredData` | Recognized JSON/JSON-lines only; not a complete Facebook Android protocol implementation |
| Netflix / Hulu | None | No adapter shipped | Trust, application encryption, ad orchestration and actual app responses need further investigation |

Only GET/POST and complete HTTP 200 responses are eligible. Host scope, enabled adapter, endpoint, method and policy mode must all match. The existing `bypass_hosts` and global bypass mode take precedence. Signed responses, partial responses, unsupported formats and malformed schemas pass through.

## Enable on your existing server

Use the [Android server guide](android-s26.md) for the existing WireGuard/CA connection. On a phone, include the target app in the WireGuard configuration. The server cannot force routing from elsewhere on a LAN; the client/router must direct traffic to it. A server in another network still requires an accessible route, and an indirect path can add latency.

Start with one selected platform in observation mode:

```bash
python3 scripts/enable_platform.py --platform youtube --mode observe
docker compose -f compose.android.yaml restart android
```

The command updates `config/android.policy.json`, saves its previous version beside it, lists the exact expanded host scope, and preserves existing host bypasses. `--dry-run` prints the proposed policy instead. For the regular explicit proxy, add `--policy config/policy.json` and restart `proxy` in the regular stack instead.

You can select `--platform instagram`, `--platform facebook`, or repeat the argument. **Policy mode is global:** changing it also affects existing exact-request and owned-HLS rules, including the Android probe's `/ad` test. Observe mode preserves original body bytes and records candidates; it does not remove them.

Check the authenticated dashboard/API at `/v1/status`. A successful server heartbeat or VPN connection is not proof that these responses are visible. Each adapter reports:

- `eligible`: matching endpoint responses reached the filter, including unsupported formats.
- `candidate_units`: recognized ad records/metadata groups seen, including observe mode.
- `modified_responses` and `removed_units`: supported responses actually changed in filter mode.
- `binary_unhandled`, `unsupported_format`, `unsupported_encoding`, `unknown_schema`, `oversize`, `buffer_budget`, `no_match`: why eligible responses did not produce a supported edit.

These counters cannot identify an Android package, count all real ads, or prove that an ad disappeared on screen. YouTube's units are metadata entries and may overlap; they are not a count of distinct video ads. Private account/response content, video IDs, URLs, tokens and pagination values are not written to these counters.

If supported candidates are observed and normal app playback works through inspection, enable filtering explicitly:

```bash
python3 scripts/enable_platform.py --platform youtube --mode filter
docker compose -f compose.android.yaml restart android
```

Measure the visible result and normal playback in multiple sessions. A broken login, spinner, empty feed or blocked platform is a failure. If the app rejects inspection, remove its inspected hosts/restart or disable the phone tunnel; a server rule cannot repair its trust decision. Whole-domain blocking of a shared media service is not the fallback.

## Resource and preservation rules

Only selected metadata endpoints buffer. Video/audio segments and other responses keep their existing streaming path. Each candidate has a 2 MiB encoded and decoded limit; at most four candidates buffer concurrently. Gzip and zlib-wrapped deflate are handled with bounded decompression. Brotli/unknown encodings pass through. Oversized or malformed chunked data is forwarded without truncation; there is no global video body-size limit.

Filter mode drops stale content-length/digest/cache validators and sets `Cache-Control: no-store` on eligible metadata responses before streaming starts. This can also happen when the eventual body is passed through. Observe mode preserves original body bytes, including compressed bytes. A policy replacement during buffering cancels modification of that response. Errors release buffered state. Matching metadata responses incur bounded buffering latency; Pi performance is unmeasured.

The JSON parser rejects duplicate keys, nonfinite constants, excess nesting, excessive nodes and malformed records. Facebook multi-record edits commit only when the entire buffered response parses. Organic nodes, streaming data, license metadata, pagination cursors and feed continuation flags are preserved by the implemented transformations.

## Why binary/Netflix/Hulu support is not claimed

A historical iOS/tvOS YouTube experiment rewrote protobuf renderer tags near ad URLs. It does not supply a verified current Android schema. Generic renderer tags may wrap ordinary content too; this release counts unhandled protobuf responses and forwards them intact. It does not guess field IDs or mutate arbitrary bytes.

Published Netflix Android TV research reports an in-process app modification after manifest decryption. Its stated scope is one Android TV build, not Samsung's Netflix phone app and not a server-only network solution. This project has not reproduced that research. No Netflix/Hulu MSL, DRM, signature or app-integrity bypass is implemented. The requirement “install one server and automatically remove every official-app ad” remains unmet.

## Evidence and validation

The independent Python filters are informed by public protocol observations; no third-party implementation source or filter lists are vendored:

- [YouTube proxy response-property observations](https://github.com/irbis-sh/zen-desktop/discussions/341)
- [Instagram native timeline response types at 3a153c4](https://github.com/dilame/instagram-private-api/blob/3a153c4e807049e95d72af67e316d432c2fd1577/src/responses/timeline.feed.response.ts) and [timeline request](https://github.com/dilame/instagram-private-api/blob/3a153c4e807049e95d72af67e316d432c2fd1577/src/feeds/timeline.feed.ts)
- [Facebook/YouTube filter-maintainer observations at 0b1ddca](https://github.com/uBlockOrigin/uAssets/blob/0b1ddca13184b53ebe24a33774c063813e01a545/filters/quick-fixes.txt)
- [Historical YouTube protobuf experiment, iOS/tvOS](https://ericdraken.com/pfsense-decrypt-ad-traffic/)
- [Netflix Android TV author's reported in-process design](https://github.com/ajstrick81/morphe-androidtv-patches/blob/main/docs/NETFLIX_ATV_SYSTEM_DESIGN.md)
- [Android trust configuration](https://developer.android.com/privacy-and-security/security-config)

Tests exercise these documented response shapes using **synthetic owned fixtures**. Real HTTPS integration redirects every upstream connection to a local TLS origin: it verifies all three transformations, gzip, body/header preservation, observation counters, binary passthrough and a chunked response exceeding 2 MiB. No test contacts the services or establishes official-app compatibility. See [validation record](validation.md).
