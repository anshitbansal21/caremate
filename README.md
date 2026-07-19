# CareMate

CareMate is a stationary elderly-safety prototype with a wearable motion sensor, a camera-based vision hub, and a native iOS app. It detects possible falls, confirms them using sensor and vision evidence, provides a local alert, and shows the camera feed, status, and alerts in the app.

> **Prototype status:** This repository is an early hardware and software starting point. CareMate is not a certified medical device or emergency service. Fall detection and alerts must be tested carefully and must not be the user's only safety system.

## Project goals

- Detect a candidate fall on the Glyph C6 wearable using the Modulino Movement sensor.
- Use the stationary UNO Q and C270 webcam to annotate activity, report person/room status, and help confirm or reject candidate falls.
- Provide clear local feedback through the LCD, red LED, and buzzer.
- Show the live annotated camera feed, current status, and real-time fall alert in a native iOS app, with **Analyze space**, test, cancel, and acknowledgement interactions.
- Respect privacy: obtain consent, collect only necessary data, and make sharing visible and controllable.

## Available hardware

- Arduino UNO Q 2GB
- Logitech C270 USB webcam with microphone
- Modulino Movement sensor
- Glyph C6 (ESP32-C6), headers pre-soldered
- 16×2 LCD, 2 push buttons, buzzer, rotary encoder
- 2 Hall sensors and 2 magnets
- 2 blue LEDs, 2 red LEDs, 2 LDRs
- 7-segment display, SPDT switch, IR sensor
- Breadboard and jumper wires

No motors or mobile chassis are confirmed. Each LED requires a current-limiting resistor; use 330 Ω for initial tests unless measurements justify another value, and confirm that resistors are available before wiring.

## Repository layout

```text
caremate/
├── firmware/
│   └── caremate_controller/     # Arduino controller firmware
├── docs/
│   ├── architecture.md          # Proposed system boundaries and data flow
│   └── hardware-plan.md         # Initial controls and pin-planning worksheet
├── .gitignore
├── CONTRIBUTING.md
└── README.md
```

## Quick start

### 1. Install tools

Install the latest Arduino IDE or Arduino CLI, then install the board package recommended for the Arduino UNO Q. Confirm the exact board target and core version as a team before committing lock/configuration files.

### 2. Open the starter firmware

Open:

```text
firmware/caremate_controller/caremate_controller.ino
```

Select the board and serial port, compile, and upload. The starter sketch requires no external libraries and prints a heartbeat at `115200` baud.

### 3. Test safely

Start with only the board connected. Add one component at a time and document its voltage, ground, and pin assignment in `docs/hardware-plan.md` before wiring it.

## MVP: exactly three features

1. Live fall detection using a wearable sensor candidate plus vision confirmation, followed by a local alert.
2. A live annotated feed labeling on-bed, standing, sitting, lying, or walking, plus an on-demand person/room summary from the current camera view.
3. A native iOS app connected to the base-station camera feed, showing current status and real-time fall alerts, and allowing the user to request **Analyze space**.

Push buttons, the rotary encoder, Hall sensors/magnets, LDRs, 7-segment display, SPDT switch, and IR sensor are deferred until these features work end to end.

## Proposed operating states

```text
sensor candidate → awaiting vision → confirmed fall → locally alerting
                                  ↘ rejected/uncertain
```

Every alert should have a visible/audible indication, a cancellation window when appropriate, an acknowledgement path, and a record of whether delivery succeeded.

## Team ownership

| Person | Ownership |
|---|---|
| Aryan | Wearable fall-detection device, Glyph C6/Modulino firmware, and candidate-event delivery to the base station/app flow |
| Anshit | Base station, image detection, OpenAI-compatible summaries, fusion/backend, camera feed, app alerts, and native iOS app |
| Ryaan | Hardware connections, wiring review, soldering, continuity and power checks, and bench assembly |

Aryan's device reports a **possible fall** to Anshit's server and iOS UI; the base station then updates it after vision fusion. Ryaan reviews physical interfaces before soldering or first power-up.

## Team decisions still needed

- Exact UNO Q board/core and how its Linux/AI side communicates with its microcontroller side
- Movement sensor model, library, sampling rate, and fall-detection approach
- LCD interface type (parallel or I²C backpack)
- Wearable-to-hub and hub-controller message schemas
- Alert transport and iOS camera-feed/API protocol
- Multimodal model/provider selection after testing capability, latency, cost, privacy, and retention
- Consent, retention, encryption, and access rules for camera/audio/activity data
- Who receives alerts and what happens if nobody acknowledges one

## Ground rules

- Never test falls on an older adult; use recorded/simulated motion and controlled test rigs.
- Do not connect motors directly to a microcontroller pin.
- Verify component voltage and current requirements before wiring.
- Keep credentials and personal data out of Git.
- Require explicit user consent before recording or sharing audio, video, or activity.
- Make camera/microphone operation visible and provide an approved test/cancellation mechanism before involving real recipients.
- Treat model output as advisory evidence; a single LLM response must not silently trigger or suppress a safety alert.
- Send only consented, request-scoped frames to an off-device model; exclude audio and continuous video, avoid storing frames by default, and keep API keys on the server.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request. Keep changes small, document hardware assumptions, and include a short bench-test note for firmware changes.

## License

No license has been selected yet. Until the team chooses one, treat this code and documentation as all rights reserved.
