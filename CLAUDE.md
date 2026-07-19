# CareMate project instructions

## Product boundary

Build CareMate as a **stationary elderly-safety prototype**. No motors or mobile chassis are confirmed. Do not introduce navigation, motor control, or unconfirmed hardware into the MVP.

CareMate is a prototype, not a certified medical device or guaranteed emergency service. Never describe fall detection as infallible. Prefer “possible fall detected” until fusion logic confirms the event.

## Confirmed kit

- Arduino UNO Q 2GB
- Logitech C270 webcam with microphone
- Modulino Movement sensor
- Breadboard and jumper wires
- 16×2 LCD
- 2 push buttons, buzzer, and rotary encoder
- 2 Hall sensors and 2 magnets
- 2 blue 5 mm LEDs and 2 red 5 mm LEDs
- 2 LDRs, 7-segment display, SPDT switch, and IR sensor
- Glyph C6 (ESP32-C6), headers pre-soldered

Do not assume unlisted components exist. In particular, no motors are confirmed. Require one current-limiting resistor per LED; use 330 Ω as the default for initial tests unless measured requirements justify another value.

## MVP: exactly three features

1. **Live fall detection:** sensor-confirmed plus vision-confirmed, followed by a local alert.
2. **Live annotated feed:** label visible activity in real time, initially standing, sitting, lying, or walking.
3. **Mobile-responsive app:** show current status and a real-time fall alert.

Treat every other feature as deferred until these three work end to end.

## Architecture

### Node A: wearable sensor node

Use the Glyph C6 plus Modulino Movement sensor. The node must be worn or clipped to the person; do not mount it on the stationary camera/hub.

Implement a local heuristic based on:

```text
impact spike → orientation change → no-motion window
```

Send timestamped candidate-fall events over Wi-Fi. Make thresholds configurable and log enough synthetic/non-personal telemetry to tune them. Do not call a candidate event a confirmed fall.

### Node B: stationary vision hub

Use the UNO Q plus C270 webcam. Run pose/activity inference on the UNO Q Linux side, annotate the live feed, and evaluate candidate falls from Node A. Confirm using evidence such as a horizontal pose plus sustained lack of motion.

Drive the local buzzer, red LED, and LCD from the hub. Keep microcontroller-facing physical I/O separate from Linux-side vision/network processing and define explicit messages between them.

### Software layer

Run a small server, preferably on the UNO Q Linux side for the MVP. It receives sensor and vision events and exposes a live annotated feed, current status, and real-time fall alert through a mobile-responsive web app. Calling it “the app” is acceptable; do not build native clients unless explicitly requested.

## Event fusion

Keep these states distinct:

```text
sensor candidate → awaiting vision → confirmed fall → locally alerting
                                  ↘ rejected/uncertain
```

- Correlate timestamped events within a configurable window.
- Define behavior when either node is offline or vision is occluded.
- Prefer “uncertain—check user” over silently discarding credible sensor events.
- Provide a cancellation/test mechanism before involving real recipients.
- Record alert delivery and acknowledgement separately from fall confirmation.

## Deferred hardware

Do not wire or implement the push buttons, rotary encoder, 7-segment display, Hall sensors/magnets, LDRs, SPDT switch, or IR sensor until the three MVP features work end to end.

## Team boundaries

- **Person 1 — Sensor node:** Glyph C6/Modulino wiring, wearable fall heuristic, and Wi-Fi candidate-event transmission.
- **Person 2 — Vision node:** C270/UNO Q inference, annotations, fusion logic, and buzzer/LED/LCD outputs.
- **Person 3 — App/backend:** event server, live-feed relay, status API, responsive interface, and real-time alert UI.

Assign by strength: embedded/C++ to Person 1, CV/ML to Person 2, and web/backend to Person 3. Keep message schemas documented so work can proceed independently.

## Engineering rules

- Confirm exact pinouts, logic voltages, sensor revision, and LCD interface before wiring.
- Never connect an LED without a series resistor or drive a high-current load from GPIO.
- Use non-blocking timing in microcontroller firmware.
- Keep credentials, recordings, and personal data out of Git.
- Use synthetic or consenting-team-member data; never test falls on an older adult.
- Make camera/microphone operation visible and obtain consent before capture or sharing.
- Prefer on-device inference and minimize transmitted or stored media and telemetry.
- Add a bench-test note for firmware changes and failure-path tests for alert changes.
- Do not expand the MVP without explicit approval.

## Source-of-truth files

- `README.md`: teammate onboarding and repository overview
- `docs/architecture.md`: system boundaries and message flow
- `docs/hardware-plan.md`: hardware roles and pin-planning worksheet
- `firmware/caremate_controller/`: UNO Q controller firmware
- `skills/caremate-project/SKILL.md`: portable Codex workflow

Update relevant documentation in the same change when implementation decisions change.
