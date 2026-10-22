# Galaxy S26 Ultra: native-app test server

The v0.3 phone lab targets your owned Samsung Galaxy S26 Ultra and a Pi 4/5 with a 64-bit OS or an x86-64 mini server. Record the phone's actual Android/One UI and app versions; a model/year alone does not establish compatibility. No root is required for this lab.

**Delivered:** Docker-hosted per-app WireGuard ingress, selective HTTPS filtering, an owned virtual HTTPS origin, a native Android probe APK, and optional private hostname discovery. Apps can reach the server even if they ignore Wi-Fi proxy settings. **Complete ad removal in the official YouTube, Netflix, Hulu, Facebook and Instagram apps remains unimplemented and unvalidated.** There are no pretend platform block rules bundled.

The probe is a native HTTPS client. It accepts user CAs for our single test domain; a separate system-only domain demonstrates that trust permission does not automatically transfer to other domains/apps. It never accesses another app's data or your streaming account.

## 1. Start the server on your LAN

Install Docker Engine + Compose and Python 3 on the server. Clone this repository, then run `python3 scripts/setup.py`. If `.env` already exists, keep it; setup intentionally refuses to overwrite credentials. Add these lines to `.env`, replacing `192.168.1.50` with **the server's LAN IPv4 address**:

```dotenv
SHIFTRELAY_ANDROID_BIND=192.168.1.50
SHIFTRELAY_ANDROID_PORTAL_BIND=192.168.1.50
SHIFTRELAY_ANDROID_DISCOVERY=false
```

```bash
docker compose -f compose.android.yaml up -d --build --wait
docker compose -f compose.android.yaml ps
docker compose -f compose.android.yaml exec -T android python -m shiftrelay.android doctor
```

This is an independent stack with its own CA, separate from the regular proxy/TV bridge. UDP 51820 carries the encrypted phone tunnel; TCP 8788 serves enrollment. Defaults are loopback until you supply LAN bindings. Keep both on your private LAN initially; no router forwarding is needed. The server container needs no privileged mode, NET_ADMIN or host TUN device.

`doctor` reports a heartbeat, aggregate counters and the public CA fingerprint. Healthy status does not prove a connected phone or removed ads. The server cannot identify an Android package from a flow.

## 2. Install the native probe and WireGuard

Install the official [WireGuard Android client](https://www.wireguard.com/install/). Download the `shiftrelay-android-probe` artifact from a successful [GitHub Actions run](https://github.com/Darkpulser4250/shiftrelay/actions/workflows/ci.yml), extract it, verify `shiftrelay-probe.apk` against its SHA-256 file, and install it on your own phone. Follow Samsung's on-screen installation prompts. The probe requests Internet access only.

The APK is a **lab build with a disposable signing identity**. Uninstall an older probe first if Android rejects a later build's changed signature. Artifacts expire after 30 days. To build it yourself, install JDK 17+, Android SDK platform 36 and build-tools 36.0.0, set `ANDROID_HOME`, then run:

```bash
python3 scripts/build_android_probe.py
```

No third-party Android libraries or account permissions are required. APK build/signature checks are not physical-device execution tests.

## 3. Export a private phone connection

On the server:

```bash
mkdir -p private
chmod 700 private
umask 077
docker compose -f compose.android.yaml exec -T android python -m shiftrelay.android client \
  --endpoint 192.168.1.50:51820 > private/s26.conf
```

Transfer `private/s26.conf` privately to the phone and import it into WireGuard. It contains a **private VPN key**; never paste it into GitHub, screenshots, support tickets or public QR generators. Remove extra transfer copies. Configurations are not served by the portal or printed during startup.

The imported configuration includes **only `org.shiftrelay.probe`**. Verify the per-app selection before enabling it. This release supports one phone peer per Android stack; copying its config to a second active phone is not multi-user enrollment.

Android normally permits one active VPN per user/profile. Disconnect the phone's Tailscale/other VPN for this experiment. Tailscale on the server does not remove that constraint. This initial LAN configuration does not provide roaming/mobile-data access.

## 4. Enroll the CA and run the native test

On the phone's browser, open `http://192.168.1.50:8788/enroll`. Compare the CA fingerprint with `doctor` over a separate trusted channel (ignore colon separators). Consent and download the public certificate. Use Settings search for **Install a CA certificate**, then follow Android's confirmation flow; menu names vary by One UI version.

Enrollment uses LAN HTTP, so verify the fingerprint. Do not enter an admin key over unprotected LAN HTTP; use SSH forwarding or private HTTPS for administration. The portal cannot read the CA private key or VPN key.

Enable WireGuard and open **ShiftRelay Probe → Run native HTTPS test**:

| Test | Expected | Evidence |
|---|---|---|
| Content preserved | PASS | Native HTTPS reached the owned origin and retained its body |
| Owned ad request blocked | PASS | Core filter returned a marked empty 204 for `/ad` |
| System-only trust control | PASS: private CA rejected | A system-only policy still rejects the user CA |

The server resolves reserved `relay-test.invalid` and `system-test.invalid` internally; no external domain/DNS blocker is needed. The supplied policy inspects only these two test hosts. The probe keeps Android's TLS verifier; it has no permissive trust manager.

**Copy result for review** shares only if you choose: model, Android API/version, results and elapsed test time. Nothing uploads automatically. This elapsed time is not a streaming benchmark.

If content fails, check endpoint, per-app inclusion, server health, CA installation and LAN connectivity. Trust-control rejection alone cannot count as success. Unexpected acceptance may indicate a system-store CA or other device modification.

## 5. Test official apps separately

After the owned test passes, export another configuration with one target app added:

```bash
umask 077
docker compose -f compose.android.yaml exec -T android python -m shiftrelay.android client \
  --endpoint 192.168.1.50:51820 --app youtube > private/s26.conf
```

Aliases: `youtube`, `netflix`, `hulu`, `instagram`, `facebook`. Update/reimport the tunnel and verify its app selection. The default policy tunnels their TLS without inspection, so **ads are expected to remain**. First compare direct versus relay playback, login, scrolling, startup time and stalls.

For optional candidate-host discovery, set `SHIFTRELAY_ANDROID_DISCOVERY=true` in `.env`, recreate the service, and use only that target app:

```bash
docker compose -f compose.android.yaml up -d --force-recreate android
docker compose -f compose.android.yaml exec -T android python -m shiftrelay.android destinations
```

Discovery stores at most 128 DNS question hostnames/counts, owner-only, in the private CA volume. No URL paths, queries, bodies, tokens, DNS answers or account content are recorded. Hostnames can still reveal activity. Discovery cannot attribute packages, identify ads, decrypt traffic, or prove ads use separate hosts. Caches, Private DNS, encrypted in-app DNS, ECH and QUIC limit visibility. Turning it off stops updates but leaves the last private record; remove `/ca/destinations.json` while the service is stopped to erase it. Restarting discovery begins a fresh in-memory window.

For one candidate, add its exact host to `config/android.policy.json`'s `inspect_hosts`, set `mode` to `observe`, leave production block rules empty, and restart `android`. Test one action. TLS failures may mean CA rejection, pinning, protocol handling or network loss; a counter alone cannot distinguish these. Remove the host/restart or turn off the tunnel if playback breaks. Never infer an ad from packet size or block a shared media CDN wholesale.

Only after inspection works and an ad request is distinguished from content should a narrowly scoped platform rule/adapter be tested. DRM remains a separate barrier. No root/pinning bypass, app patch, account credential capture or DRM decryption is included.

## Acceptance record

Record model, actual Android/One UI, app version, region/plan, network path, selected app, policy/scope and these outcomes separately:

- Routing works and normal content remains playable.
- The particular request can be inspected, or fails with a documented symptom.
- Ad requests/segments were actually prevented or removed.
- Ad visuals/audio and any mandatory wait were removed.
- Startup, seeks, captions, downloads, casting and later content still work.

Use multiple sessions and a direct baseline. A blank screen, stopped app, muted audio, spinner or blocked entire platform is **not** full blocking success. No official app has passed this record yet.

## Bypass and recovery

Turn WireGuard off for an immediate device-side return to the normal route. Leave Android's “block connections without VPN” off during initial testing. A server outage interrupts selected-app traffic rather than guaranteeing direct fallback. Reopen an app if it retains a failed connection.

Both IPv4 and IPv6 enter the tunnel for selected apps. Upstream IPv6 support is limited; IPv6 may fail inside this lab rather than bypass it directly. QUIC/ECH, cellular handover, battery cost, throughput and Pi thermals remain unvalidated. There is no automatic UDP/443 blocking or video transcoding.

Stop with `docker compose -f compose.android.yaml down`. Remove the CA from your phone when finished. To revoke the peer/reset **this Android stack's CA, keys and diagnostics**, run `docker compose -f compose.android.yaml down -v`. It destroys enrollment state: remove the old phone CA/tunnel and generate/enroll new ones after restart. The other stack's volumes are separate.

## Sources

- [mitmproxy modes / WireGuard and IPv6 limits](https://docs.mitmproxy.org/stable/concepts/modes/#wireguard)
- [Android user-CA trust](https://developer.android.com/privacy-and-security/security-config)
- [Android VPN / per-app routing](https://developer.android.com/develop/connectivity/vpn)
- [WireGuard Android IncludedApplications](https://git.zx2c4.com/wireguard-android/tree/tunnel/src/main/java/com/wireguard/config/Interface.java)
- [WireGuard namespaces](https://www.wireguard.com/netns/)
