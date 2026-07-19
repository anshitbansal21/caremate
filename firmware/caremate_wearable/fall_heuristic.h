/*
 * CareMate wearable — fall heuristic.
 *
 * A tunable, deterministic three-stage detector. NOT a machine-learning model:
 * a TinyML classifier would need labeled fall data we are ethically barred from
 * collecting on an older adult (CLAUDE.md). A threshold heuristic is the only
 * defensible MVP path; the telemetry it logs is what could train a model later.
 *
 *   Stage 1  impact       SVM spike above impact_g
 *   Stage 2  orientation  smoothed gravity direction rotates (vertical->horizontal)
 *   Stage 3  stillness    SVM ~ 1 g, low variance, sustained for no_motion_ms
 *
 * Only when all three pass does it report a candidate. This produces a
 * candidate_fall event for the hub — never a confirmed fall (vision confirms).
 *
 * Pure and self-contained (no Arduino headers): time is passed in as now_ms so
 * the same logic can be replayed against dataset samples on a host for tuning.
 */

#ifndef CAREMATE_WEARABLE_FALL_HEURISTIC_H
#define CAREMATE_WEARABLE_FALL_HEURISTIC_H

#include <stdint.h>

#include "config.h"

struct FallResult {
  bool detected = false;   // true for exactly one update() when a candidate fires
  float confidence = 0.0f; // 0..1, always > min_confidence when detected
};

// For telemetry / tuning: which stage the detector is currently in.
enum class FallStage : uint8_t { IDLE, POST_IMPACT };

class FallHeuristic {
 public:
  void begin(const HeuristicConfig& cfg);

  // Feed one IMU sample. `now_ms` is a monotonic millisecond clock.
  FallResult update(uint32_t now_ms,
                    float ax, float ay, float az,
                    float gx, float gy, float gz);

  // Telemetry accessors (const, cheap) for the tuning log.
  FallStage stage() const { return stage_; }
  float lastSvm() const { return last_svm_; }
  float peakG() const { return peak_g_; }

 private:
  HeuristicConfig cfg_;

  FallStage stage_ = FallStage::IDLE;

  // Low-pass gravity-direction estimate (recovers body orientation).
  float grav_[3] = {0.0f, 0.0f, 1.0f};
  bool grav_init_ = false;

  // Short ring of recent SVM for the pre-impact free-fall lookback.
  static const int kRing = 64;  // ~640 ms at 100 Hz
  float svm_ring_[kRing] = {0};
  uint32_t t_ring_[kRing] = {0};
  int ring_head_ = 0;

  // Latched at impact.
  float pre_impact_grav_[3] = {0.0f, 0.0f, 1.0f};
  uint32_t impact_ms_ = 0;
  float peak_g_ = 0.0f;
  bool freefall_seen_ = false;

  // Stillness tracking during POST_IMPACT.
  uint32_t still_start_ms_ = 0;  // 0 = not currently still

  float last_svm_ = 1.0f;

  void pushRing(uint32_t now_ms, float svm);
  bool sawFreefallBefore(uint32_t impact_ms) const;
  float orientationChangeDeg() const;
  float computeConfidence(float orient_deg) const;
  void reset();
};

#endif  // CAREMATE_WEARABLE_FALL_HEURISTIC_H
