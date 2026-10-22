# Maintenance without arbitrary remote execution

Implemented: Dependabot configuration, CI tests/builds, and a signed data-only rule updater. Not implemented: a hosted update catalog, scheduled production rollout, automatic live health rollback, release image publishing or an AI patching agent.

Version 0.2 also tests/builds the optional native bridge on AMD64/ARM64, starts it unpaired in observe mode, verifies authenticated sanitized status and checks that its protocol dependency is not installed in the core image. Real device behavior is a separate validation gate. Dependency update checks include the bridge's own package pins and Dockerfile.

The signed catalog envelope is JSON with `payload_b64` and `signature_b64`. Decode `payload_b64` to the **exact signed bytes**. The pinned public key must be PEM Ed25519. The payload has exactly these fields:

```json
{
  "version": 2,
  "expires": 1900000000,
  "block_rules": [{"id": "owned-ad", "host": "media.example.org", "path": "/ads.js"}],
  "canaries": [
    {"host": "media.example.org", "path": "/ads.js", "method": "GET", "expected": "block"},
    {"host": "media.example.org", "path": "/content", "method": "GET", "expected": "pass"}
  ]
}
```

Set `expires` to a real Unix timestamp in the next 31 days. Sign locally with your private release key and distribute only its pinned public key separately. No private signing key is generated or distributed by this project.

The verifier checks signature, expiry, strictly increasing version, schema, scoped rule hosts and supplied canary behavior. The updater can change block rules only; it cannot enable filtering, expand inspected hosts, remove bypasses, alter certificate trust, install code or change routing. Supplied canaries are a sanity check, not proof that production playback is safe. Add independent local regression fixtures and real device canaries before enabling unattended rule changes.

To opt into scheduled rule fetching later, schedule the documented update command on your own host with cron/systemd and restart only after verification succeeds. Pin the public key outside the repository. The updater exits unsuccessfully on replays or unchanged versions, so a timer wrapper must handle “no new version” distinctly before treating it as an incident. No timer is enabled by this release.

Before installation, the previous policy is copied to `config/policy.previous.json`; a temporary file is then atomically renamed to `policy.json`. To roll back, restore the previous file and restart the proxy. Because the version also rolls back, anti-replay history currently follows that local file. An independent monotonic high-water mark is future work.

For code/image changes use reviewed PRs, tests, immutable image digests, staged rollout and a known-good image for rollback. Do not give a running network proxy a Docker socket, host root privileges or an agent that executes downloaded “repair” scripts. TLS CA rotation is an explicit operator operation: losing/replacing the CA requires re-enrollment.
