# CareMate vision-hub main controller

The abstracted **main controller** for the stationary vision hub (Node B), meant
to run on the **UNO Q Linux side**. It owns the fall-fusion state machine and the
**Analyze space** action, and it talks only through four interfaces so every real
component (wearable transport, camera inference, MCU alert output, phone API) can
be swapped or mocked without touching the fusion logic.

> Scope note: this is Aryan's control-system layer. It does **not** implement the
> ESP32↔UNO Q transport (owned via `WearableSource`), the YOLOv8 model (owned via
> `VisionSource`), the API server (owned via `AppBus`), or the MCU firmware (owned
> via `AlertSink` + `firmware/caremate_controller`). It defines the seams between them.

## Run it (no hardware needed)

```bash
cd hub
python3 -m caremate_hub      # runs both demo-script scenarios in simulated time
python3 tests/test_fusion.py # runs the fusion happy/failure-path tests
```

Pure standard library — no pip install, no camera, no Wi-Fi.

## The four seams

| Interface | Real implementation | Mock |
|---|---|---|
| `WearableSource` | ESP32↔UNO Q transport carrying `candidate_fall` events | `MockWearable` (scripted) |
| `VisionSource` | On-device YOLOv8 pose + NL/VLM Analyze-space | `MockVision` (scripted stream) |
| `AlertSink` | MCU firmware over serial (buzzer / red LED / LCD) | `MockAlertSink` (prints); `SerialAlertSink` (real protocol, injected writer) |
| `AppBus` | Anshit's API layer → iOS app | `MockAppBus` (scripted actions) |

`MainController` depends on the abstractions above and on `Clock` (injectable, so
tests and the demo run in deterministic simulated time — mirrors the firmware's
non-blocking `millis()` timing).

## Fall detection is phased (where each piece runs)

| Stage | Runs on | Heuristic or model |
|---|---|---|
| **Candidate** (`impact → orientation → no-motion`) | ESP32-C6 wearable | Heuristic |
| **Confirmation** (lying + sustained no-motion) | UNO Q Linux (vision) | Model (pose) + rule |
| **Decision** (alert / check / none) | UNO Q main controller (this package) | Deterministic fusion — never a model |

A wearable candidate is never a confirmed fall. A model is evidence, never the
alert authority. Missing/stale/occluded evidence yields **uncertain — check user**,
never silence. See `docs/main-controller.md` for the full rationale and the
Linux↔MCU serial protocol.
