# Hardware plan

This file is a planning worksheet, not a final wiring diagram. Pin assignments remain deliberately uncommitted until the team confirms board pinouts, logic levels, the LCD interface, and sensor revisions.

## Confirmed kit

| Vertical | Confirmed components | MVP role |
|---|---|---|
| Wearable | Glyph C6 (ESP32-C6), Modulino Movement sensor | Produce timestamped candidate-fall events from configurable IMU heuristics |
| Stationary vision hub | Arduino UNO Q 2GB, Logitech C270 webcam with microphone | Annotate activity, fuse sensor and vision evidence, and host the preferred local server |
| Local alert output | 16×2 LCD, buzzer, red 5 mm LED | Show status and provide visible/audible fall alerts |
| Prototyping | Breadboard and jumper wires | Bench wiring after interfaces and voltage levels are confirmed |

The remaining confirmed kit is 2 push buttons, a rotary encoder, 2 Hall sensors, 2 magnets, 2 blue 5 mm LEDs, a second red 5 mm LED, 2 LDRs, a 7-segment display, an SPDT switch, and an IR sensor. Do not wire or implement these deferred parts until the three MVP features work end to end.

No motors or mobile chassis are confirmed. The client is a native iOS app and requires an iPhone for app testing; no additional CareMate hardware is implied.

Ryaan owns the wearable's physical build — soldering the battery and wiring the Modulino sensor — plus continuity and power-safety checks before first power-up. Aryan owns the wearable firmware/heuristic and all UNO Q-side software (control system, vision, NL analysis). Anshit owns the API layer and native iOS app. The stationary hub's local alert wiring (LCD, buzzer, LED) is not yet assigned.

## Pin assignment worksheet

| Module | Signal | Board pin | Voltage | Notes |
|---|---|---:|---:|---|
| Buzzer | Digital/PWM output | TBD | TBD | Check current; use driver if required |
| LCD | TBD | TBD | TBD | Confirm parallel vs I²C backpack |
| Red alert LED | Digital output | TBD | TBD | Require a series resistor; default to 330 Ω for initial tests |
| C270 webcam | USB | USB | TBD | Connect to the UNO Q Linux side; confirm camera and microphone permissions |
| Modulino Movement sensor | I2C (SDA/SCL) | GPIO4 (SDA) / GPIO5 (SCL) | 3.3 V | Glyph C6 (PCB Cupid) GLINK/Qwiic connector; confirmed via bench I2C scan (device at 0x6A, LSM6DSOX default address). Not the generic esp32c6 board default (23/22) — `Wire.begin(4, 5)` must run before `Modulino.begin()`. |

## Before powering hardware

1. Confirm board and module logic voltage.
2. Create a real schematic, including grounds and current-limiting resistors.
3. Check the total current budget; use a driver if the buzzer exceeds a GPIO's safe current.
4. Test continuity and polarity.
5. Begin with a current-limited bench supply where possible.
