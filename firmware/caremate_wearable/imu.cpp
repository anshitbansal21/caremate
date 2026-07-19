/*
 * CareMate wearable — IMU adapter (Modulino Movement / LSM6DSOX).
 *
 * Verified against the Arduino_Modulino library public API:
 *   ModulinoMovement: begin(), update(), available(),
 *                     getX()/getY()/getZ()      -> acceleration (g)
 *                     getRoll()/getPitch()/getYaw() -> gyroscope (dps)
 *
 * Bench-confirm before relying on it: the Modulino is on the Qwiic/I2C bus, so
 * confirm the Glyph C6's I2C (SDA/SCL) pins and 3V3 wiring, and that
 * `Modulino.begin()` targets the correct Wire instance for this board.
 */

#include "imu.h"

#include <Modulino.h>

static ModulinoMovement movement;
static bool ready = false;

bool imuBegin() {
  Modulino.begin();          // starts the Qwiic/I2C bus
  ready = movement.begin();  // false if the sensor is not detected
  return ready;
}

bool imuRead(ImuSample& out) {
  if (!ready) return false;

  // update() latches the newest accel + gyro readings from the LSM6DSOX.
  movement.update();

  out.ax = movement.getX();
  out.ay = movement.getY();
  out.az = movement.getZ();
  out.gx = movement.getRoll();
  out.gy = movement.getPitch();
  out.gz = movement.getYaw();
  return true;
}
