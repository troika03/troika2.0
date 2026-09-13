# Threat model: screen.snapshot

**Review date:** 2026-09-13  
**Scope:** one-frame Android screen capture for the closed beta

## Assets and trust boundaries

- Raw screen pixels, visible text and device identity are private user data.
- Android, the product API, the phone WebSocket and the configured vision
  provider are separate trust boundaries.
- Screen content is attacker-controlled data. It can contain prompt injection,
  QR instructions, fake permission prompts and secrets.
- A bearer token, device ID or vision session ID alone must not grant capture.

## Required controls

1. Android starts MediaProjection only after the system consent dialog and
   keeps a visible foreground notification with Stop.
2. Consent expires after 120 seconds or one frame. The local guard requires a
   bound Accessibility service and blocks system UI, configured sensitive
   packages, password nodes, OTP/recovery labels and card-like numbers.
3. The active package and sensitive tree are checked before capture and again
   in the frame callback to close the screen-switch race.
4. The server requires an authenticated user/device/token, both default-off
   feature flags and a separate `once` approval for every frame.
5. A metadata-only vision session binds user, device, token and capability to a
   hashed nonce. It expires, cannot be replayed and is cancelled on phone error.
6. Base64 length, decoded JPEG size, magic bytes, dimensions and pixel count are
   checked before vision. Raw pixels stay in memory and never enter the tool
   result, conversation, artifact store or database.
7. Vision sees a system instruction that treats every visual string as data and
   forbids following screen instructions or revealing secrets. The agent only
   receives the resulting analysis.

## Evidence

- Samsung SM-A225F physical E2E passed for consent, foreground service, Stop,
  server approval, one safe frame, external opt-in vision and automatic revoke.
- A local fixture containing a fake password node and “Одноразовый код” was
  blocked on the phone with `sensitive_screen_blocked`. Its vision session was
  cancelled and the model received no image.
- SQLite contains vision metadata only. Runtime-log searches found no JPEG
  base64 or data URL. Phone logs redact snapshot command parameters.
- Cross-owner, replay, expiry, revoked-token, malformed-frame and size-limit
  paths are covered by automated tests.

## Residual risks and decision

- Sensitive-text detection is heuristic and cannot cover every language or app.
  The package denylist must be maintained, and users need a local custom list.
- A rooted/compromised phone, compromised API host or malicious vision provider
  can defeat process-level controls. Production needs HTTPS/WSS, hardware-backed
  device keys, rotating access tokens and a reviewed provider retention policy.
- The current ADB reverse and HTTP loopback path is development transport only.
- Snapshot approval does not grant live screen access, UI control, camera or
  microphone. Those capabilities require separate threat models and consent.

The one-frame implementation is acceptable for a closed beta with both server
flags disabled by default and explicit provider opt-in. It is not approval for
WebRTC screen assist or CameraX live vision.
