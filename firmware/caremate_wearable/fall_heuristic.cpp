/*
 * CareMate wearable — fall heuristic implementation.
 * See fall_heuristic.h for the three-stage design.
 */

#include "fall_heuristic.h"

#include <math.h>

namespace {
constexpr float kRadToDeg = 57.2957795f;

float magnitude3(float x, float y, float z) {
  return sqrtf(x * x + y * y + z * z);
}
}  // namespace

void FallHeuristic::begin(const HeuristicConfig& cfg) {
  cfg_ = cfg;
  reset();
  grav_[0] = 0.0f; grav_[1] = 0.0f; grav_[2] = 1.0f;
  grav_init_ = false;
}

void FallHeuristic::reset() {
  stage_ = FallStage::IDLE;
  impact_ms_ = 0;
  peak_g_ = 0.0f;
  freefall_seen_ = false;
  still_start_ms_ = 0;
}

void FallHeuristic::pushRing(uint32_t now_ms, float svm) {
  ring_head_ = (ring_head_ + 1) % kRing;
  svm_ring_[ring_head_] = svm;
  t_ring_[ring_head_] = now_ms;
}

bool FallHeuristic::sawFreefallBefore(uint32_t impact_ms) const {
  // Look back over the ring for an SVM dip below freefall_g in the window
  // immediately preceding the impact.
  for (int i = 0; i < kRing; ++i) {
    uint32_t t = t_ring_[i];
    if (t == 0 || t > impact_ms) continue;
    if (impact_ms - t > cfg_.freefall_lookback_ms) continue;
    if (svm_ring_[i] < cfg_.freefall_g) return true;
  }
  return false;
}

float FallHeuristic::orientationChangeDeg() const {
  // Angle between the pre-impact and current smoothed gravity directions.
  const float* a = pre_impact_grav_;
  const float* b = grav_;
  float na = magnitude3(a[0], a[1], a[2]);
  float nb = magnitude3(b[0], b[1], b[2]);
  if (na < 1e-4f || nb < 1e-4f) return 0.0f;
  float dot = (a[0] * b[0] + a[1] * b[1] + a[2] * b[2]) / (na * nb);
  if (dot > 1.0f) dot = 1.0f;
  if (dot < -1.0f) dot = -1.0f;
  return acosf(dot) * kRadToDeg;
}

float FallHeuristic::computeConfidence(float orient_deg) const {
  // All three gates already passed when this is called, so start above the
  // hub's min_candidate_confidence and scale up with severity.
  float impact_score = (peak_g_ - cfg_.impact_g) / 3.0f;      // +3 g over -> 1.0
  if (impact_score < 0.0f) impact_score = 0.0f;
  if (impact_score > 1.0f) impact_score = 1.0f;

  float orient_score = (orient_deg - cfg_.orient_change_deg) / 45.0f;
  if (orient_score < 0.0f) orient_score = 0.0f;
  if (orient_score > 1.0f) orient_score = 1.0f;

  float conf = 0.55f + 0.25f * impact_score + 0.20f * orient_score;
  if (freefall_seen_) conf += 0.10f;
  if (conf > 1.0f) conf = 1.0f;
  return conf;
}

FallResult FallHeuristic::update(uint32_t now_ms,
                                float ax, float ay, float az,
                                float gx, float gy, float gz) {
  (void)gx; (void)gy; (void)gz;  // gyro reserved for future corroboration

  FallResult result;

  const float svm = magnitude3(ax, ay, az);
  last_svm_ = svm;
  pushRing(now_ms, svm);

  // Low-pass the raw acceleration into a gravity-direction estimate. During the
  // violent part of a fall this is corrupted, but it re-settles once the body
  // is still — which is exactly when we read it (after the stillness window).
  if (!grav_init_) {
    grav_[0] = ax; grav_[1] = ay; grav_[2] = az;
    grav_init_ = true;
  } else {
    const float a = cfg_.gravity_lp_alpha;
    grav_[0] = a * grav_[0] + (1.0f - a) * ax;
    grav_[1] = a * grav_[1] + (1.0f - a) * ay;
    grav_[2] = a * grav_[2] + (1.0f - a) * az;
  }

  switch (stage_) {
    case FallStage::IDLE: {
      // Stage 1 — impact.
      if (svm > cfg_.impact_g) {
        pre_impact_grav_[0] = grav_[0];
        pre_impact_grav_[1] = grav_[1];
        pre_impact_grav_[2] = grav_[2];
        impact_ms_ = now_ms;
        peak_g_ = svm;
        freefall_seen_ = sawFreefallBefore(now_ms);
        still_start_ms_ = 0;
        stage_ = FallStage::POST_IMPACT;
      }
      break;
    }

    case FallStage::POST_IMPACT: {
      if (svm > peak_g_) peak_g_ = svm;

      // Stage 3 — sustained stillness (tracked continuously in this window).
      const bool still = fabsf(svm - 1.0f) < cfg_.still_band_g;
      if (still) {
        if (still_start_ms_ == 0) still_start_ms_ = now_ms;
      } else {
        still_start_ms_ = 0;  // motion resumed -> restart the stillness timer
      }

      const bool still_long_enough =
          still_start_ms_ != 0 &&
          (now_ms - still_start_ms_) >= cfg_.no_motion_ms;

      if (still_long_enough) {
        // Stage 2 — orientation change, evaluated now that the body has settled.
        const float orient_deg = orientationChangeDeg();
        if (orient_deg >= cfg_.orient_change_deg) {
          result.detected = true;
          result.confidence = computeConfidence(orient_deg);
        }
        // Whether confirmed or rejected (settled but no orientation change,
        // e.g. sat down and froze), the event is resolved -> back to idle.
        reset();
        break;
      }

      // Gave up waiting for stillness: normal vigorous activity, or they got
      // back up. Reject and re-arm.
      if ((now_ms - impact_ms_) >= cfg_.post_impact_window_ms) {
        reset();
      }
      break;
    }
  }

  return result;
}
