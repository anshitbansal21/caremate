---
name: caremate-project
description: Build and maintain the CareMate stationary elderly-safety prototype across its Glyph C6 wearable sensor, UNO Q vision hub, fall-event fusion, local alerts, and mobile-responsive web app. Use for CareMate architecture, planning, embedded firmware, sensor heuristics, computer vision, backend/API, live-feed UI, hardware wiring, integration, safety, privacy, testing, or documentation tasks in this repository.
---

# CareMate project workflow

## Establish context

1. Read `../../CLAUDE.md` completely before changing or recommending anything.
2. Read `../../docs/architecture.md` for cross-node work.
3. Read `../../docs/hardware-plan.md` before hardware or GPIO work.
4. Inspect affected source and tests before editing.

Treat `CLAUDE.md` as authoritative if older documents conflict with it. Flag the conflict and update stale documentation in the same change.

## Keep work inside the MVP

Map every task to one of these tracks:

- Wearable candidate-fall detection
- Stationary vision/activity inference and event fusion
- Status/feed/alert web application

Reject silent scope expansion. Do not add motors, navigation, native mobile clients, medicine reminders, or deferred controls unless the user explicitly changes scope.

## Implement safely

1. State which node and owner boundary the change affects.
2. Identify inputs, outputs, message schema, timing assumptions, and failure behavior.
3. Confirm hardware revision, pinout, voltage, and interface before finalizing wiring or pin constants.
4. Keep sensor candidates, vision evidence, confirmed falls, alert delivery, and acknowledgement as distinct events.
5. Preserve useful degraded behavior when the wearable, camera, network, or inference process is unavailable.
6. Avoid blocking firmware delays and unbounded network waits.
7. Keep secrets and personal media/data out of the repository.

## Verify proportionally

- Firmware: compile for the actual board target and describe the bench setup.
- Fall heuristic: test impact, daily motion, orientation, stillness, and disconnect cases with controlled or synthetic input.
- Vision: test standing, sitting, lying, walking, occlusion, empty frame, and low light; report limitations.
- Fusion: test time-window boundaries, out-of-order and duplicate events, one-node failure, cancellation, and uncertain outcomes.
- Backend/UI: test reconnects, stale status, alert deduplication, responsive layout, and visible delivery state.

Never test a deliberate fall on an older adult.

## Finish the change

Update project documentation whenever a change affects hardware or pin assumptions, node responsibilities, event contracts, confirmation behavior, alert semantics, or privacy behavior.

Report what was implemented, how it was verified, remaining limitations, and the next dependency without presenting the prototype as a medical-grade system.
