# CareMate wearable (Node A)

Glyph C6 (ESP32-C6) + Modulino Movement, worn/clipped to the person. Runs a
local three-stage fall heuristic and streams `candidate_fall` events to the
stationary UNO Q hub over a persistent TCP socket. It **never** declares a
confirmed fall — vision on the hub confirms.

This README is the source of truth for the **wearable ↔ hub message contract**,
so both this firmware and the hub's real `WearableSource`
(`hub/caremate_hub/`) build against the same shapes.

## Files

| File | Role |
|---|---|
| `caremate_wearable.ino` | Non-blocking main loop: sample → heuristic → link |
| `fall_heuristic.{h,cpp}` | Three-stage detector (impact → orientation → stillness). Pure, host-testable |
| `imu.{h,cpp}` | Modulino Movement (LSM6DSOX) adapter — isolates the vendor library |
| `link.{h,cpp}` | Persistent TCP socket: heartbeat, seq/ack, retransmit, reset |
| `config.h` | All tunable thresholds and link timing (bench starting points) |
| `secrets.h.example` | Copy to `secrets.h` (gitignored); Wi-Fi + hub address |

## The heuristic (why it is a heuristic, not a model)

`impact spike → orientation change → no-motion window`, all three required:

1. **Impact** — acceleration magnitude `SVM = √(ax²+ay²+az²)` exceeds `impact_g`
   (default 2.5 g). Set the IMU range to **±8 g/±16 g** so a real impact is not
   clipped.
2. **Orientation change** — the smoothed gravity direction rotates by
   `orient_change_deg` (default 45°) between just-before-impact and after the
   body settles (vertical → horizontal).
3. **Stillness** — `SVM ≈ 1 g` within `still_band_g`, sustained for
   `no_motion_ms` (default 1.5 s). Biggest false-positive killer.

An optional pre-impact **free-fall dip** (`SVM < freefall_g`) only raises
confidence. A TinyML classifier is deliberately **not** used for the MVP: it
needs labeled fall data we are ethically barred from collecting on an older
adult (CLAUDE.md). Tune the thresholds against a drop-test rig and public
datasets (**SisFall**, MobiFall, UMAFall); the telemetry logged here is what
could train a model later.

## Message contract (newline-delimited JSON, both directions)

Transport: one long-lived TCP connection on the private hotspot. No TLS (closed
trusted network; HTTPS belongs on the hub↔phone link). `seq` is transport
metadata for ack/dedup — the hub uses it to ack and to drop duplicates, then
strips it when building `CandidateFall`. `received_at_ms` is stamped by the hub
on receipt and is intentionally **not** sent by the wearable.

**Wearable → hub**

```json
{"version":1,"event":"boot","source":"wearable","seq":1,"uptime_ms":1234}
{"version":1,"event":"heartbeat","source":"wearable","seq":2,"uptime_ms":2734}
{"version":1,"event":"candidate_fall","source":"wearable","seq":3,"uptime_ms":5011,"confidence":0.82}
```

- `candidate_fall` maps 1:1 to `CandidateFall` in `hub/caremate_hub/events.py`.
- `confidence` is always > `min_candidate_confidence` (0.5) when emitted.
- `heartbeat` (~every 1.5 s) is liveness: if it stops, the hub must show the
  wearable disconnected (FAULT / uncertain), not assume all-clear.
- `boot` signals an uptime reset (reboot) so the hub can clear stale state.

**Hub → wearable**

```json
{"version":1,"event":"ack","seq":3}
{"version":1,"event":"reset"}
```

- `ack` stops retransmission of that `seq` (only `candidate_fall` is retried;
  heartbeats are fire-and-forget).
- `reset` = the caregiver acknowledged the alert in the app; the wearable clears
  its internal latch.

**Reliability:** `candidate_fall` is retransmitted every `candidate_retransmit_ms`
until acked; a fall that fires while offline is buffered in a bounded outbox
(oldest dropped when full) and flushed on reconnect; TCP drops trigger
exponential reconnect backoff. All timing is `millis()`-based — no `delay()` in
the hot path.

## Hardware confirmed on bench

- Glyph C6 (PCB Cupid) GLINK/Qwiic connector: **SDA=GPIO4, SCL=GPIO5, 3V3**
  (not the generic esp32c6 board default of 23/22). `imu.cpp` calls
  `Wire.begin(4, 5)` before `Modulino.begin()` to target these pins.
- Modulino Movement confirmed on I2C at **0x6A** (LSM6DSOX default address)
  via raw bus scan; `movement.begin()` succeeds and streams plausible
  accel/gyro values (SVM ≈ 1.0 g at rest).
- FQBN: `esp32:esp32:esp32c6:CDCOnBoot=cdc` — **`CDCOnBoot=cdc` is required**,
  the default (`CDCOnBoot=default`, i.e. disabled) silently drops all
  `Serial` output on this board's native USB.
- Still open: battery wiring (Ryaan owns the physical build + continuity/
  power checks).

## Build / bench test

**Build** (Arduino CLI; confirm the exact core/FQBN for the Glyph C6 —
ESP32-C6 is provided by the `esp32` core):

```bash
# one-time
cp secrets.h.example secrets.h   # then edit Wi-Fi + hub address
arduino-cli core install esp32:esp32
arduino-cli lib install Modulino

# compile (adjust the FQBN to the confirmed Glyph C6 board id)
arduino-cli compile --fqbn esp32:esp32:esp32c6 firmware/caremate_wearable
```

> Not yet compiled in CI — this is a first cut. The Modulino API was verified
> against the `Arduino_Modulino` source, but confirm on-device.

**Bench test (no person, ever):**

1. **Boot/link** — power on with the hub server (or a `nc -l 9000` listener)
   running; confirm `boot` then periodic `heartbeat` arrive, and that pulling
   Wi-Fi makes the hub see heartbeats stop and the wearable reconnect.
2. **Impact only** (tap the sensor) — SVM spikes but no orientation change/
   stillness → **no** candidate. Confirms false-positive rejection.
3. **Sit-down-hard / drop-on-bed** — should **not** emit (orientation/stillness
   gates). Tune `impact_g`, `still_band_g` if it does.
4. **Drop-rig fall** — impact + horizontal + still → single `candidate_fall`
   with confidence > 0.5; verify the hub acks and retransmission stops.
5. **Offline fall** — trigger a fall with the hub unreachable; on reconnect the
   buffered candidate flushes.
6. **Reset** — send `{"event":"reset"}` from the hub; confirm the log/LED
   reacts.

Capture the `TLM,...` CSV over Serial during 2–4 to tune thresholds against the
drop rig and public datasets.
