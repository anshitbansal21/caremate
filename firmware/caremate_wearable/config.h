/*
 * CareMate wearable — tunable configuration.
 *
 * Node A (Glyph C6 / ESP32-C6 + Modulino Movement). Every threshold here is a
 * BENCH STARTING POINT, not a validated value. Tune against synthetic motion,
 * a drop-test rig, and public datasets (SisFall / MobiFall / UMAFall) — never
 * against a fall performed by an older adult (see CLAUDE.md).
 *
 * Network credentials and the hub address live in secrets.h (gitignored), not
 * here. Copy secrets.h.example -> secrets.h and fill it in.
 */

#ifndef CAREMATE_WEARABLE_CONFIG_H
#define CAREMATE_WEARABLE_CONFIG_H

// ---------------------------------------------------------------------------
// Sampling
// ---------------------------------------------------------------------------
// 100 Hz. Impacts last only tens of ms, so do not sample slower than ~50 Hz.
static const unsigned long SAMPLE_INTERVAL_MS = 10;

// ---------------------------------------------------------------------------
// Fall heuristic thresholds  (stage order: impact -> orientation -> stillness)
// ---------------------------------------------------------------------------
struct HeuristicConfig {
  // Stage 1 — impact. Acceleration magnitude (SVM) spike, in g. Lowered to 2.0
  // from a bench drop-rig session where a genuine drop onto a semi-soft surface
  // landed at only ~2.1 g. Stages 2+3 (orientation change + sustained stillness)
  // still gate out false positives, so this stays safe. Set the sensor range to
  // +/-8 g or +/-16 g so the spike is NOT clipped (a clipped impact is missed).
  float impact_g = 2.0f;

  // Optional pre-impact free-fall dip, in g. During free fall SVM approaches 0.
  // Seeing a dip below this shortly before the impact raises confidence; it is
  // a bonus, not a requirement (the dip is short and noisy).
  float freefall_g = 0.6f;
  unsigned long freefall_lookback_ms = 400;

  // Stage 2 — orientation change, in degrees, between the smoothed gravity
  // direction just before impact and after the body settles. A real fall goes
  // vertical -> horizontal. Literature finds 20-60 deg separates falls well.
  float orient_change_deg = 45.0f;

  // Stage 3 — post-impact stillness. The person lies still: SVM stays within
  // +/- still_band_g of 1 g for at least no_motion_ms. This is the biggest
  // false-positive killer (rejects "sat down hard", "dropped the device").
  float still_band_g = 0.25f;
  unsigned long no_motion_ms = 1500;

  // Give up waiting for stillness after this long past the impact (person got
  // up / it was normal vigorous activity) -> reject, back to idle.
  unsigned long post_impact_window_ms = 3000;

  // Low-pass factor for the gravity-direction estimate (0..1, higher = smoother
  // / slower). Used to recover body orientation from raw acceleration.
  float gravity_lp_alpha = 0.9f;

  // Candidates below this confidence are ignored by the hub's fusion layer
  // (FusionConfig.min_candidate_confidence). Emitted candidates are always
  // above it by construction; kept here for reference/telemetry.
  float min_confidence = 0.5f;
};

// ---------------------------------------------------------------------------
// Transport / link (persistent TCP socket to the UNO Q hub)
// ---------------------------------------------------------------------------
struct LinkConfig {
  // Liveness heartbeat. The hub declares the wearable disconnected (FAULT /
  // uncertain) after it stops seeing these — a silently dead wearable is the
  // dangerous case, so keep this frequent.
  unsigned long heartbeat_ms = 1500;

  // Reconnect backoff bounds for Wi-Fi / TCP (non-blocking).
  unsigned long reconnect_min_ms = 500;
  unsigned long reconnect_max_ms = 8000;

  // Retransmit an unacked candidate_fall this often until the hub acks it.
  unsigned long candidate_retransmit_ms = 750;

  // Bounded outbox: if a fall fires while disconnected, buffer up to this many
  // candidates and flush on reconnect. Oldest is dropped when full.
  static const int outbox_capacity = 8;

  // TCP read/connect are non-blocking; this only bounds a single connect poll.
  unsigned long connect_timeout_ms = 4000;
};

#endif  // CAREMATE_WEARABLE_CONFIG_H
