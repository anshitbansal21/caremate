# Hardware plan

This file is a planning worksheet, not a final wiring diagram. Pin assignments remain deliberately uncommitted until the team confirms the UNO Q pinout, logic levels, LCD interface, and sensor variants.

## Proposed control meanings

| Part | Initial role |
|---|---|
| Push button 1 | Manual help request |
| Push button 2 | Cancel/acknowledge |
| Rotary encoder | Navigate options; press to select if supported |
| SPDT switch | Physical privacy/mute control |
| 16×2 LCD | State, countdown, and alert delivery status |
| Blue LEDs | Ready/connected feedback |
| Red LEDs | Possible fall/active alert feedback |
| Buzzer | Local confirmation and alert countdown |
| Movement sensor | Possible-fall input after calibration |
| IR sensor | Future nearby obstacle input |
| Hall sensors + magnets | Future wheel/door/attachment state sensing |
| LDRs | Ambient-light input for display brightness |
| 7-segment display | Optional countdown or prototype diagnostics |

## Pin assignment worksheet

| Module | Signal | Board pin | Voltage | Notes |
|---|---|---:|---:|---|
| Help button | Digital input | TBD | TBD | Prefer internal pull-up if supported |
| Cancel button | Digital input | TBD | TBD | Debounce in software |
| Buzzer | Digital/PWM output | TBD | TBD | Check current; use driver if required |
| LCD | TBD | TBD | TBD | Confirm parallel vs I²C backpack |
| Movement sensor | TBD | TBD | TBD | Confirm exact model/library |
| Status LEDs | Digital output | TBD | TBD | Add suitable series resistors |
| Privacy switch | Digital input | TBD | TBD | State must be visible to user |

## Before powering hardware

1. Confirm board and module logic voltage.
2. Create a real schematic, including grounds and current-limiting resistors.
3. Check the total current budget; power motors from a suitable separate supply.
4. Test continuity and polarity.
5. Begin with a current-limited bench supply where possible.

## Chassis additions likely required

A wheeled chassis normally also needs geared motors, encoders, a compatible motor driver, battery protection/charging, voltage regulation, fusing, a physical power switch, and an emergency stop. These are not listed in the current kit and should be selected as a system.
