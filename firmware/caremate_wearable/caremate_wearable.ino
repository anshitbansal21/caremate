/*
 * CareMate wearable — Node A (Glyph C6 / ESP32-C6 + Modulino Movement).
 *
 * Worn/clipped to the person. Runs a local three-stage fall heuristic on the
 * IMU and sends timestamped candidate_fall events to the stationary UNO Q hub
 * over a persistent TCP socket. It NEVER declares a confirmed fall — vision on
 * the hub confirms (see CLAUDE.md, docs/architecture.md).
 *
 * Loop is fully non-blocking (millis-scheduled): sample IMU -> heuristic ->
 * link. Wi-Fi/TCP drops are handled by the link with backoff, and a fall that
 * fires while offline is buffered and flushed on reconnect.
 *
 * Set TELEMETRY to 1 to stream tuning data over Serial (see README bench note).
 */

#include <Arduino.h>

#include "config.h"
#include "fall_heuristic.h"
#include "imu.h"
#include "link.h"
#include "secrets.h"

#define TELEMETRY 1

static HeuristicConfig gHeuristicCfg;
static LinkConfig gLinkCfg;
static FallHeuristic gHeuristic;
static HubLink gLink;

static unsigned long gLastSampleMs = 0;
static bool gImuOk = false;

#if TELEMETRY
static unsigned long gLastTelemetryMs = 0;
static const unsigned long TELEMETRY_INTERVAL_MS = 200;
#endif

// Hub -> wearable "reset": the caregiver acknowledged the alert in the app.
// The wearable has no local output in the confirmed kit, so this just clears
// internal latching and blinks the onboard LED if one exists.
static void onHubReset() {
  Serial.println(F("RESET from hub (caregiver acknowledged)"));
#ifdef LED_BUILTIN
  for (int i = 0; i < 3; ++i) {
    digitalWrite(LED_BUILTIN, HIGH); delay(40);
    digitalWrite(LED_BUILTIN, LOW);  delay(40);
  }
#endif
}

void setup() {
  Serial.begin(115200);
  delay(250);
  Serial.println(F("CareMate wearable starting"));

#ifdef LED_BUILTIN
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, LOW);
#endif

  gImuOk = imuBegin();
  if (!gImuOk) {
    // Surface the fault; the hub will also see missing candidates/heartbeats.
    Serial.println(F("FAULT: Modulino Movement not detected on I2C/Qwiic"));
  }

  gHeuristic.begin(gHeuristicCfg);
  gLink.begin(gLinkCfg, WIFI_SSID, WIFI_PASSWORD, HUB_HOST, HUB_PORT, onHubReset);

  Serial.println(F("Wearable ready: sampling IMU, connecting to hub"));
}

void loop() {
  const unsigned long now = millis();

  // 1) Keep the hub link alive (Wi-Fi/TCP, heartbeat, retransmit, inbound).
  gLink.loop(now);

  // 2) Sample the IMU at a fixed rate and run the heuristic.
  if (gImuOk && (now - gLastSampleMs >= SAMPLE_INTERVAL_MS)) {
    gLastSampleMs = now;

    ImuSample s;
    if (imuRead(s)) {
      FallResult r = gHeuristic.update(now, s.ax, s.ay, s.az, s.gx, s.gy, s.gz);
      if (r.detected) {
        Serial.print(F("CANDIDATE_FALL confidence="));
        Serial.println(r.confidence, 2);
        gLink.sendCandidate(now, r.confidence);
      }

#if TELEMETRY
      if (now - gLastTelemetryMs >= TELEMETRY_INTERVAL_MS) {
        gLastTelemetryMs = now;
        // CSV: t_ms,svm,stage,peak_g,link. Log this against the drop rig and
        // public datasets to tune thresholds (never against a real elder fall).
        Serial.print(F("TLM,"));
        Serial.print(now);              Serial.print(',');
        Serial.print(gHeuristic.lastSvm(), 3); Serial.print(',');
        Serial.print((int)gHeuristic.stage()); Serial.print(',');
        Serial.print(gHeuristic.peakG(), 2);   Serial.print(',');
        Serial.println(gLink.connected() ? 1 : 0);
      }
#endif
    }
  }
}
