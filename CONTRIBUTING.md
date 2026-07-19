# Contributing to CareMate

## Workflow

1. Create a short branch such as `feature/lcd-status` or `docs/pin-map`.
2. Keep each pull request focused on one behavior or hardware module.
3. Explain the hardware used, board/core version, wiring, and test result.
4. Ask for review before merging changes that affect alerts, privacy, power, or motors.

## Commit style

Use concise, action-oriented messages:

- `add button debounce logic`
- `document movement sensor wiring`
- `fix alert cancellation timeout`

## Definition of done

- The project compiles for the agreed board target.
- New pins and dependencies are documented.
- Serial logs do not expose private data or credentials.
- Safety-relevant failure cases have been considered.
- A bench test or simulation result is included in the pull request.

## Secrets and personal data

Never commit Wi-Fi passwords, API keys, phone numbers, recordings, user profiles, or real health/activity data. Use ignored local configuration files and synthetic test data.
