/*
 * CareMate controller firmware
 *
 * Minimal, dependency-free starting point. Hardware modules should be added
 * only after their wiring and voltage requirements are documented.
 */

enum class CareMateState {
  STARTING,
  READY,
  POSSIBLE_FALL,
  MANUAL_HELP,
  ALERTING,
  CANCELLED,
  FAULT
};

CareMateState currentState = CareMateState::STARTING;
unsigned long lastHeartbeatMs = 0;
constexpr unsigned long HEARTBEAT_INTERVAL_MS = 1000;

const __FlashStringHelper* stateName(CareMateState state) {
  switch (state) {
    case CareMateState::STARTING:      return F("STARTING");
    case CareMateState::READY:         return F("READY");
    case CareMateState::POSSIBLE_FALL: return F("POSSIBLE_FALL");
    case CareMateState::MANUAL_HELP:   return F("MANUAL_HELP");
    case CareMateState::ALERTING:      return F("ALERTING");
    case CareMateState::CANCELLED:     return F("CANCELLED");
    case CareMateState::FAULT:         return F("FAULT");
    default:                           return F("UNKNOWN");
  }
}

void setState(CareMateState nextState) {
  if (nextState == currentState) return;

  Serial.print(F("STATE "));
  Serial.print(stateName(currentState));
  Serial.print(F(" -> "));
  Serial.println(stateName(nextState));
  currentState = nextState;
}

void setup() {
  Serial.begin(115200);
  delay(250);
  Serial.println(F("CareMate controller starting"));

  // Initialize buttons, display, indicators, and sensors here as modules land.
  setState(CareMateState::READY);
}

void loop() {
  const unsigned long now = millis();

  // Non-blocking timing keeps controls responsive as features are added.
  if (now - lastHeartbeatMs >= HEARTBEAT_INTERVAL_MS) {
    lastHeartbeatMs = now;
    Serial.print(F("HEARTBEAT state="));
    Serial.println(stateName(currentState));
  }

  // Planned loop order:
  // 1. Read and debounce physical controls.
  // 2. Sample sensors.
  // 3. Update the state machine.
  // 4. Refresh local feedback.
  // 5. Exchange messages with the AI/connectivity process.
}
