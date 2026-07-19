# Pending work

Living checklist of what is built vs. still open, so parallel work (hub, wearable,
hardware, app) stays coordinated. Grouped by area; each item notes why it's
pending and who/what unblocks it. The MVP is done when the two demo-script
scenarios run end to end on real hardware.

## Status snapshot

Built and tested (headless, no hardware): the UNO Q Linux-side **main controller**
and all four seams — `WearableServer`, `PoseVisionSource`, `HttpAppBus`, and the
`SerialAlertSink` protocol — wired into one process via `run_hub`. 29 hub tests
green. Pose classifier validated 5/5 on real YOLOv8n-pose detections. The wearable
IMU is up on the bench (see Hardware gates).

## Vision

- [ ] **On-device FPS on the UNO Q + C270.** All pose numbers so far are laptop-CPU.
  Measure real pose FPS on the board before committing the live-feed UX to a frame
  rate. *Gate: hardware agent (camera bring-up).* Biggest remaining vision risk.
- [ ] **`YoloPoseBackend` on real hardware.** Written but untested without a camera.
  Validate on a laptop webcam, then int8-export via App Lab / Edge Impulse and
  reduce `imgsz` for speed on the UNO Q.
- [ ] **`/feed` annotated-JPEG provider.** `run_hub --feed-camera` now supplies a
  live unannotated C270 MJPEG feed. `PoseVisionSource` still needs to expose its
  latest annotated frame as JPEG bytes and pass that callable as `frame_provider`.
- [ ] **`ON_BED` vs floor-lying.** The classifier emits `LYING`; distinguishing a
  bed from the floor needs a configured bed region (scene ROI) layered on top.

## App / API

- [x] **SSE client implemented.** `docs/app-api.md` specs SSE and the native iOS
  client consumes it with bounded reconnect backoff. The `AppBus` seam still keeps
  a future WebSocket switch out of fusion logic.
- [ ] **TLS + hub-side per-user token management.** The MVP hub uses a single shared
  bearer token over the LAN; the iOS client now stores it in the device-only
  Keychain. Add TLS and per-user tokens before any non-LAN exposure (see Networking).
- [ ] **Analyze-space real VLM adapter.** `VlmSpaceAnalyzer` validates output but
  isn't wired to a provider; `LocalSummaryAnalyzer` is the default. Per CLAUDE.md,
  verify capability/latency/cost/privacy first, keep the model on-device by
  default, keep credentials server-side, don't hard-code a provider.

## Networking (phone ↔ hub)

- [ ] **MVP connectivity: keep it local.** Phone and hub on the same LAN; recommended
  **hub-as-Wi-Fi-AP** so the demo doesn't depend on venue Wi-Fi, plus **mDNS**
  (`caremate.local` / `_caremate._tcp`) so the app discovers the hub instead of a
  typed IP. iOS has native Bonjour.
- [ ] **Do NOT expose the hub's IP publicly for the MVP.** No port-forwarding / public
  IP. It fights the "no internet dependency" demo rule, and a naked, TLS-less
  camera+alert device streaming an older adult is an unacceptable privacy/security
  surface.
- [ ] **Remote caregiver access (post-MVP, if the product needs it).** Not raw public
  exposure — use an **outbound cloud relay/rendezvous** (hub dials out, no inbound
  ports) or a **mesh VPN** (Tailscale/WireGuard), with **TLS end-to-end**, per-user
  auth, and explicit frame privacy/retention. Product scope, explicitly deferred.

## Fusion / reliability

- [ ] **Wearable-offline → visible fault.** `WearableServer.is_online()` exists but
  isn't wired into the controller as a `FAULT`/offline state. Architecture requires
  disconnected sensors to surface as visible faults, not silent "no fall".
- [ ] **Persist alert delivery + acknowledgement** separately from fall confirmation
  if the demo needs an audit trail (currently in logs/in-memory).

## Alert / MCU

- [ ] **Linux↔MCU transport is `Arduino_RouterBridge`, not raw serial.** On the UNO Q
  the MCU↔Linux channel is the RouterBridge (Bridge/Monitor), *not* `/dev/ttyACM0`
  pyserial (integration agent's finding). `SerialAlertSink` already takes an
  injected writer, so we swap only the writer to wrap the RouterBridge Linux-side
  API — but `run_hub --serial <dev>` assumes pyserial and must be revisited once
  that API is known. **Coordinate with the integration agent on the bridge's
  Linux-side read/write handle.**
- [ ] **MCU serial-protocol parser.** `SerialAlertSink` emits `STATUS <state> <level>`
  / `LCD <l1>|<l2>`; the UNO Q controller `.ino` doesn't parse them yet (it now
  does `Bridge.begin()`). Parse those messages off the bridge and drive the
  buzzer / red LED / 16×2 LCD.
- [ ] **Assign the hub-alert-wiring owner.** LCD/buzzer/red-LED wiring on the UNO Q
  still has no owner (open in CLAUDE.md).

## Hardware gates (wearable + hub bring-up)

- [x] **Wearable IMU bring-up.** Modulino Movement confirmed on I²C `0x6A` (LSM6DSOX),
  `SDA=GPIO4 / SCL=GPIO5 @ 3.3 V`; `Wire.begin(4,5)` before `Modulino.begin()`.
  FQBN needs `CDCOnBoot=cdc` or `Serial` output is dropped. *(Wearable agent.)*
- [ ] **Wearable battery + power/continuity checks.** *Owner: Ryaan.*
- [ ] **UNO Q camera bring-up** → unblocks `run_hub --camera`. *Gate: hardware agent.*
- [~] **UNO Q MCU↔Linux bridge** in progress: controller `.ino` now calls
  `Bridge.begin()` (`Arduino_RouterBridge`). *(Integration agent.)* → unblocks real
  MCU alerts once the Linux-side bridge writer is wired into `SerialAlertSink`.
- [ ] **Capture UNO Q environment setup** (drivers, App Lab, RouterBridge, ultralytics
  + camera deps) in a `docs/uno-q-setup.md` so `run_hub --camera`/`--serial`
  prerequisites are reproducible — this work currently lives only on the device.

## Definition of done (MVP)

Both demo-script scenarios on real hardware: (1) wearable candidate → vision
confirm → local buzzer/LED/LCD alert → app alert in real time; (2) app **Analyze
space** → fresh frame → activity + room summary back to the app.
