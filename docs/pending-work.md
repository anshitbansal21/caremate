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
- [ ] **`/feed` annotated-JPEG provider.** `HttpAppBus` serves MJPEG but returns 503
  until `PoseVisionSource` exposes its latest annotated frame as JPEG bytes and
  that callable is passed as `frame_provider`. Lights up the app's live feed.
- [ ] **`ON_BED` vs floor-lying.** The classifier emits `LYING`; distinguishing a
  bed from the floor needs a configured bed region (scene ROI) layered on top.

## App / API

- [ ] **SSE vs WebSocket — confirm with Anshit.** `docs/app-api.md` specs SSE; it's
  behind the `AppBus` seam so swapping to WebSocket costs no fusion change. Decide
  *before* he builds the iOS client.
- [ ] **TLS + real token store.** MVP uses a single shared bearer token over the LAN.
  Add TLS and per-user tokens before any non-LAN exposure (see Networking).
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

- [ ] **MCU serial-protocol parser.** `SerialAlertSink` emits `STATUS <state> <level>`
  / `LCD <l1>|<l2>`; the UNO Q controller `.ino` doesn't parse them yet. Wire the
  buzzer / red LED / 16×2 LCD to reflect those messages.
- [ ] **Assign the hub-alert-wiring owner.** LCD/buzzer/red-LED wiring on the UNO Q
  still has no owner (open in CLAUDE.md).

## Hardware gates (wearable + hub bring-up)

- [x] **Wearable IMU bring-up.** Modulino Movement confirmed on I²C `0x6A` (LSM6DSOX),
  `SDA=GPIO4 / SCL=GPIO5 @ 3.3 V`; `Wire.begin(4,5)` before `Modulino.begin()`.
  FQBN needs `CDCOnBoot=cdc` or `Serial` output is dropped. *(Wearable agent.)*
- [ ] **Wearable battery + power/continuity checks.** *Owner: Ryaan.*
- [ ] **UNO Q camera bring-up** → unblocks `run_hub --camera`. *Gate: hardware agent.*
- [ ] **UNO Q ↔ STM32 serial** → unblocks `run_hub --serial` for real MCU alerts.

## Definition of done (MVP)

Both demo-script scenarios on real hardware: (1) wearable candidate → vision
confirm → local buzzer/LED/LCD alert → app alert in real time; (2) app **Analyze
space** → fresh frame → activity + room summary back to the app.
