# YouTube-on-TV bridge · experimental v0.2

This optional, independently running service pairs with **the YouTube app on a television or TV streaming device**. It is not the paid “YouTube TV” live-TV subscription, and it does not pair with the ordinary YouTube phone app as a playback screen.

Implemented: manual TV-code pairing, observe-only events, optional volume reduction during ad signals, native Skip requests only when enabled by the device, bounded retries, a 60 second silence budget, and a private recovery journal. Tests use the real pyytlounge library against a local simulated Lounge server. **No physical device has been validated.**

This is partial ad suppression. It does not prevent media delivery, hide the ad picture, eliminate unskippable ad waiting time, or provide Netflix/Hulu/Facebook/Instagram support. Full native-app ad removal remains the project goal.

## Pair without a certificate or browser extension

From the root of ShiftRelay, initialize `.env` if you have not already done so. Then build the optional image:

```bash
python3 scripts/setup.py  # First installation only; never overwrites an existing .env
docker compose --profile youtube-tv build youtube-tv
```

On the television's **YouTube app**, open **Settings → Link with TV code**. Keep that screen visible. In your own interactive server terminal:

```bash
docker compose --profile youtube-tv run --rm --no-deps youtube-tv pair
```

Enter the 12 digit code at the hidden prompt. Do not put it in chat, `.env`, shell arguments, logs or GitHub. Pairing contacts YouTube's Lounge service and stores private credentials in the `youtube_tv_state` Docker volume. It does not need a paid API key, TLS inspection or the core proxy to be in your TV's traffic path.

The bridge communicates through YouTube's service, rather than keeping every control message on your LAN. Only the adapter's decision logic and sanitized status stay local. No ad audio/video is downloaded or recorded.

## Observe first

```bash
docker compose --profile youtube-tv up -d youtube-tv
docker compose --profile youtube-tv exec youtube-tv python -m ytbridge.cli doctor
```

Observe is the default. It subscribes to the paired app's state and requests periodic now-playing updates to verify liveness. It sends no ad Skip or volume-reduction commands. If an earlier Assist session left a valid recovery journal, observe mode may send a volume-restoration request for that session; recovery is distinct from new assistance.

To include the normal dashboard:

```bash
docker compose --profile youtube-tv up -d
```

Authenticate at `http://127.0.0.1:8787` with the existing admin key. The native section shows mode, connection/ad signal, recovery state and **request counts**. Counts do not prove that a TV applied a command or that an ad was removed. They reset on a new connection. A stale status file cannot claim that a device is connected. No screen name, media ID, URL, TV code, pairing token or actual volume is sent to this dashboard.

## Explicitly enable assistance

After verifying that observations match the physical TV, run:

```bash
SHIFTRELAY_TV_MODE=assist SHIFTRELAY_TV_ALLOW_SKIP=true \
  docker compose --profile youtube-tv up -d youtube-tv
```

This opts into both volume reduction and native Skip requests. Set `SHIFTRELAY_TV_ALLOW_SKIP=false` to try volume reduction alone. Keep both environment values consistent on subsequent Compose invocations, or put these two non-secret settings in `.env` after choosing them.

The adapter uses the public `set_volume(0)` operation rather than toggling an unknown mute state. It only starts when it has a known, nonzero, unmuted volume from the current connection. It does not change a TV that was already muted or at zero. It never issues seek, pause, play, next-video or playlist-reset commands.

If a nonzero volume event arrives after our zero request, the adapter yields to that change rather than repeatedly forcing silence. Ad-end/unknown-state events, shutdown and the 60 second budget request restoration of the saved level. Native Skip requires a separate opt-in and the current protocol's enabled flag, with at most three attempts per ad break and five seconds between them.

## Recovery and bypass

```bash
SHIFTRELAY_TV_MODE=observe SHIFTRELAY_TV_ALLOW_SKIP=false \
  docker compose --profile youtube-tv up -d youtube-tv
```

Or stop only the optional bridge:

```bash
docker compose --profile youtube-tv stop youtube-tv
```

The process tries to restore its volume change before disconnecting. Network loss or a hard power cut can prevent that. Recovery is best effort, not guaranteed: keep the ordinary TV remote available.

Before lowering volume, the bridge writes a private, owner-only journal with the original level and a hashed device binding. It keeps that journal after command acceptance until a volume event confirms a nonzero level. On reconnection it only auto-recovers the same paired device, with a known current level of zero and a journal no older than 15 minutes. A different/nonzero current volume is respected. Old or mismatched recovery records require manual attention and block new lowering attempts.

If recovery is pending, restore the TV volume manually, keep the existing pairing, and run again so a fresh volume event can clear the record. Do not replace pairing or delete the private volume while a recovery is pending. If the saved record is invalid/mismatched and cannot be reconciled, first restore volume manually and stop the bridge; then remove only `restore.json` from its private state using your normal server administration workflow.

You cannot reliably distinguish every manual choice of zero/mute from an echo of the bridge's own zero command. Device event ordering, AirPlay/external audio systems, revoked pairing codes and application changes also need actual-device testing.

## Validation checklist

1. Record your TV/streamer model, OS and YouTube app version privately.
2. Pair and run observe-only while checking at least five real ad breaks.
3. Verify that normal video is never identified as an ad; check unknown/disconnect behavior.
4. Enable assistance only after observations are correct. Verify zero-volume, Skip availability and restoration on the TV itself.
5. Test your own volume change during an ad, an already-muted TV, stopping the bridge and a temporary connection loss.
6. Report false actions, missed actions, remaining ad wait and latency. Remove credentials/media identifiers from reports.

The bridge is a research adapter, not a platform-support certification. Device compatibility reports from other projects are useful prior evidence, not a guarantee for this implementation.

## Development

```bash
.venv/bin/pip install -r bridges/youtube_tv/requirements.txt
PYTHONPATH=bridges/youtube_tv .venv/bin/python -m unittest discover -s bridges/youtube_tv/tests -v
```

The optional bridge and its tests are GPL-3.0-only; the independent proxy/portal core remains MIT. See [NOTICE.md](NOTICE.md) and [LICENSE](LICENSE).
