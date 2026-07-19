# Main controller design (vision hub)

The **main controller** is the abstracted fusion brain of the stationary vision
hub (Node B). It runs on the **UNO Q Linux side**, owns the fall-fusion state
machine and the **Analyze space** action, and drives the local alert output and
the phone app. Reference implementation: `hub/caremate_hub/`.

Its defining property is that it talks only to four abstract interfaces, never to
a concrete camera, transport, serial port, or web framework. That keeps the alert
decision in one testable place and lets each owner's real component plug in
without changing fusion logic.

## Where fall detection happens, and why (phased)

Fall detection is a fusion of two independent evidence sources, so it is split
across nodes rather than living in one place:

| Stage | Node | Method | Rationale |
|---|---|---|---|
| **Candidate** — "something might have happened" | ESP32-C6 wearable | Threshold **heuristic**: `impact spike → orientation change → no-motion window` | The only sensor physically on the person. Fires locally even if Wi-Fi drops; works when the person is out of frame or occluded. Sends a tiny event, not an IMU stream. |
| **Confirmation** — "is it really a fall" | UNO Q Linux (camera) | Pose **model** (YOLOv8/YOLO11-pose) + a thin rule: lying + sustained no-motion | The camera is here. Pose is a genuine ML task; the horizontal + still test on top is deterministic. |
| **Decision** — "alert / check / none" | UNO Q main controller | **Deterministic** fusion policy | Combines both sources + recency. A model is evidence, never the alert authority — the same rule CLAUDE.md sets for the VLM. |

Why not put the IMU heuristic on the UNO Q? Streaming raw accelerometer over
Wi-Fi to the hub is worse on power, latency, bandwidth, and privacy, and it fails
the moment Wi-Fi hiccups — exactly what the demo script forbids.

Why a heuristic (not a model) on the wearable for the MVP? A TinyML fall
classifier needs labeled fall data, and CLAUDE.md forbids testing falls on an
older adult. Only synthetic/drop-rig data is available. So we start with a
tunable threshold heuristic and **log the telemetry it sees**; that logged data
is what could later train a model. (Model-selection findings for the vision side
are tracked in the section below.)

## The four interfaces

```
WearableSource  ── ESP32↔UNO Q transport → CandidateFall events (ingest_candidate)
VisionSource    ── YOLOv8 pose stream (ingest_vision) + analyze_space()
AlertSink       ── MCU firmware over serial: buzzer / red LED / LCD
AppBus          ── API layer: publish_status / publish_alert / publish_analysis + inbound actions
```

`pump(now_ms, controller)` is the cooperative-scheduling hook: on each tick every
source drains what it has and pushes into the controller. Single-threaded and
deterministic — no locks, mirroring the firmware loop.

## Fusion state machine

```
                    candidate (≥ min confidence)
        READY ───────────────────────────────▶ AWAITING_VISION
          ▲                                      │
          │                     lying + no-motion │ sustained ≥ no_motion_confirm_ms
   ack /  │                                      ▼
   cancel │                              CONFIRMED_FALL ──▶ ALERTING ──(ack)──▶ READY
          │                                      
          ├───────── upright / on bed ◀──────────┤  (REJECTED → READY)
          │                                      │
          └── window elapsed / camera down ◀─────┘  (UNCERTAIN — check user)
```

- A wearable candidate is immediately surfaced to the app as **possible fall**
  while vision is pending, then updated to confirmed / rejected / uncertain.
- Stale vision (older than `vision_staleness_ms`) counts as **absent**, not as
  "no fall" — a stalled camera routes to uncertain, never to silence.
- Analyze-space output is advisory: it can raise a **check**, but it can never
  produce a confirmed fall on its own.
- `acknowledge()` and `cancel()`/test are recorded separately from confirmation.

Tunable timing/thresholds live in `hub/caremate_hub/config.py` (`FusionConfig`).

## Linux ↔ MCU serial protocol (v1)

The main controller keeps Linux-side vision/networking separate from the MCU's
physical I/O, exchanging explicit newline-terminated messages. `AlertSink` is the
Linux-side driver; `firmware/caremate_controller` is the MCU-side actuator.

```
STATUS <state> <level>\n     # e.g. "STATUS alerting confirmed" → buzzer + red LED
LCD <line1>|<line2>\n        # 16 chars per row, '|' separates the two rows
```

`SerialAlertSink` formats these and takes an injected writer, so the scaffold has
no pyserial dependency; wire `lambda s: ser.write(s.encode())` at deploy time. The
MCU firmware's existing state enum (STARTING/READY/POSSIBLE_FALL/ALERTING/…) maps
directly onto these `STATUS` levels — extend the `.ino` to parse this protocol
when the alert wiring owner is assigned.

## Contract with the wearable and the API layer

- **WearableSource** consumes the versioned `candidate_fall` contract from
  `architecture.md`. The ESP32 heuristic + transport (owned separately) plug in
  behind this interface; the hub does not reach into that code.
- **AppBus** carries the `space_analysis` contract and the possible/confirmed/
  rejected/uncertain status stream to the API layer. Keep this aligned with
  Anshit's API as the single handoff.

## Model selection (vision side)

Hardware reality on the UNO Q 2GB — verify before committing the live-feed frame
rate:

- The Linux side is a Qualcomm **Dragonwing QRB2210**: quad Cortex-A53 @ ~2 GHz,
  **Adreno 702 GPU**, a small 6th-gen **Hexagon DSP**, 2 GB LPDDR4, Debian.
- **There is no large AI NPU.** Do not design around one — that is the *Ventuno Q*
  (40 TOPS), a different board. Vision inference here runs on the **A53 CPU
  (NEON, int8)** or is offloaded to the **Adreno GPU**; a Qualcomm QNN/LiteRT GPU
  path exists but is not turnkey for this exact chip on a hackathon timeline.
- Measured reference on the actual board: **~17 FPS** for a nano YOLO *detection*
  model via Arduino **App Lab + Edge Impulse**. Pose is heavier, so expect
  meaningfully less and plan to downscale input.

Recommendation:

- **Committed MVP model:** **YOLOv8n-pose / YOLO11n-pose, int8-quantized** (TFLite
  or NCNN), reduced input (e.g. 416–480), deployed through **App Lab + Edge
  Impulse** — the one inference path already proven on this board. It yields, from
  a single model, **both** the person bounding box **and** 17 keypoints, so the
  live annotated feed shows boxes *and* the four MVP activity labels.
- **Pose (keypoints) is required, not optional, for the MVP.** MVP feature 2 needs
  `standing / sitting / lying / walking`, and **plain bounding-box detection cannot
  separate sitting from standing** (same box shape). So plain-box detection is
  *not* an acceptable MVP path — only a live-feed **frame-rate degrade of last
  resort**, and one that fails the activity-label requirement, so avoid it.
- **Frame rate, not labels, is the tuning knob.** If pose FPS is low, reduce input
  resolution, run detection every Nth frame while tracking between, or GPU/QNN-
  offload — never drop to box-only to buy FPS.
- **Fall rule:** no trained fall classifier is needed. Keypoint orientation +
  a no-motion window is the standard, portable pattern (e.g.
  `andmydignity/fall_detection_yolov8s`, `16dina/fall-detection`).
- **GPU/QNN offload is an optimization, not a dependency** — get it working on CPU
  int8 first.

Wearable side: research confirms the **threshold heuristic is correct for the MVP**
(SVM impact spike → orientation change → no-motion window; high recall, trivially
tunable from drop-test telemetry). SisFall-trained TinyML (int8, ~10 KB) is a
deferred precision upgrade, not MVP scope.

All cited fall-detection repos and the 17 FPS figure are research-grade / a single
measured config — bench-confirm real pose FPS on your 2 GB board with the C270
before locking the live-feed UX to a frame rate.

## Integration status

The repository now contains real `PoseVisionSource`, `WearableServer`, and
`HttpAppBus` implementations as well as their mocks. They are tested separately,
but no production UNO Q runner currently composes all three with the controller.
The annotated-frame provider and MCU-side serial protocol parser also remain
unwired. The headless demo therefore still uses mocks, and the live wearable
runner still uses a bench-only vision stub.
