# Agent instructions for CareMate

Read `CLAUDE.md` completely before changing or recommending anything; it is the scope, architecture, and ownership source of truth. Read `docs/architecture.md` for cross-node work and `docs/hardware-plan.md` before hardware or GPIO work. Inspect affected source and tests before editing.

If any file conflicts with `CLAUDE.md`, treat `CLAUDE.md` as authoritative, flag the conflict to the user, and fix the stale file in the same change.

## Do not assume

- No motors, mobile chassis, native Android/web clients, cloud infrastructure, or deferred sensors (push buttons, rotary encoder, 7-segment display, Hall sensors/magnets, LDRs, SPDT switch, IR sensor) are in scope until the three MVP features work end to end.
- Do not expand the MVP without explicit approval from the user.

## Route work by owner

See `CLAUDE.md` § Team ownership for the current, authoritative split. As of now:

- Wearable hardware (soldering, wiring, power/continuity checks) → **Ryaan**.
- Wearable firmware/heuristic, ESP32↔UNO Q and camera↔UNO Q control system, YOLOv8 vision, and NL space-analysis → **Aryan**.
- API layer and phone app → **Anshit**.
- Stationary hub's local alert wiring (LCD, buzzer, LED) → unassigned; flag it rather than guessing an owner.

## Keep work inside the MVP

Map every task to one of:

- Wearable candidate-fall detection
- Stationary vision/activity inference and event fusion
- Phone app and its backend API

## Implement safely

1. State which node and owner boundary the change affects.
2. Identify inputs, outputs, message schema, timing assumptions, and failure behavior.
3. Confirm hardware revision, pinout, voltage, and interface before finalizing wiring or pin constants.
4. Keep sensor candidates, vision evidence, model recommendations, confirmed falls, alert delivery, and acknowledgement as distinct events.
5. Preserve degraded behavior when the wearable, camera, network, or inference process is unavailable.
6. Avoid blocking firmware delays and unbounded network waits.
7. Keep secrets and personal media/data out of the repository.

## Verify proportionally

- Firmware: compile for the actual board target and describe the bench setup.
- Fall heuristic: test impact, daily motion, orientation, stillness, and disconnect cases with controlled or synthetic input.
- Vision/model: test on-bed, standing, sitting, lying, walking, room summaries, occlusion, empty frames, low light, image-borne instructions, malformed model output, timeout, and provider outage.
- Fusion: test time-window boundaries, out-of-order and duplicate events, one-node failure, cancellation, and uncertain outcomes.
- API/app: test camera-feed reconnects, foreground/background transitions, stale status, alert deduplication, network loss, and visible delivery state.

Never test a deliberate fall on an older adult.

## Finish the change

Update `CLAUDE.md`, `docs/architecture.md`, or `docs/hardware-plan.md` in the same change whenever hardware assumptions, node responsibilities, event contracts, confirmation behavior, or privacy behavior change.

Report what was implemented, how it was verified, remaining limitations, and the next dependency — never present the prototype as a medical-grade system.
