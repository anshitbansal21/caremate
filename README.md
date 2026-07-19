# CareMate

CareMate is an autonomous companion robot concept for older adults. The device is intended to move with its user, provide simple physical interaction, share opt-in daily activity updates, detect possible falls, and alert trusted family members quickly.

> **Prototype status:** This repository is an early hardware and software starting point. CareMate is not a certified medical device or emergency service. Fall detection and alerts must be tested carefully and must not be the user's only safety system.

## Project goals

- Provide accessible interaction through buttons, an LCD, LEDs, a buzzer, and a rotary encoder.
- Detect possible falls using movement-sensor data.
- Capture camera/microphone input for future on-device AI features.
- Send clear local feedback before sharing an alert.
- Support a future mobile chassis without coupling navigation to safety logic.
- Respect privacy: obtain consent, collect only necessary data, and make sharing visible and controllable.

## Available hardware

- Arduino UNO Q 2GB
- Logitech C270 USB webcam with microphone
- Modulino Movement sensor (shipment-dependent)
- Glyph C6 (ESP32-C6), headers pre-soldered
- 16×2 LCD, 2 push buttons, buzzer, rotary encoder
- 2 Hall sensors and 2 magnets
- 2 blue LEDs, 2 red LEDs, 2 LDRs
- 7-segment display, SPDT switch, IR sensor
- Breadboard, jumper wires, and USB-C data cable
- Possible future chassis with motors and wheels

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

## First prototype milestone

The recommended first demo is intentionally small:

1. A button toggles between **Ready** and **Help requested**.
2. The LCD and LEDs show the current state.
3. The buzzer confirms an alert locally.
4. A simulated fall event starts a cancellation countdown.
5. The second button cancels a false alarm.
6. Only after this flow is reliable should the movement sensor trigger it.

Camera AI, remote notifications, and autonomous driving should be separate later milestones.

## Proposed operating states

```text
STARTING → READY → POSSIBLE_FALL → ALERTING → READY
                    ↘ CANCELLED ───────────↗
READY → MANUAL_HELP → ALERTING
```

Every alert should have a visible/audible indication, a cancellation window when appropriate, an acknowledgement path, and a record of whether delivery succeeded.

## Team decisions still needed

- Exact UNO Q board/core and how its Linux/AI side communicates with its microcontroller side
- Movement sensor model, library, sampling rate, and fall-detection approach
- LCD interface type (parallel or I²C backpack)
- Chassis, motor driver, battery, charging, and emergency-stop design
- Alert transport (phone companion, Wi-Fi service, SMS gateway, etc.)
- Consent, retention, encryption, and access rules for camera/audio/activity data
- Who receives alerts and what happens if nobody acknowledges one

## Ground rules

- Never test falls on an older adult; use recorded/simulated motion and controlled test rigs.
- Do not connect motors directly to a microcontroller pin.
- Verify component voltage and current requirements before wiring.
- Keep credentials and personal data out of Git.
- Require explicit user consent before recording or sharing audio, video, or activity.
- Provide a physical way to mute/disable sensing and clearly show its state.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request. Keep changes small, document hardware assumptions, and include a short bench-test note for firmware changes.

## License

No license has been selected yet. Until the team chooses one, treat this code and documentation as all rights reserved.
