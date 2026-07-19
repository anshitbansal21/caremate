/*
 * CareMate wearable — IMU adapter.
 *
 * Isolates the Modulino Movement (LSM6DSOX, 6-axis accel + gyro over I2C/Qwiic)
 * behind a tiny interface so the rest of the firmware never touches the vendor
 * library. If the library API or sensor revision changes, only imu.cpp changes.
 *
 * Units: acceleration in g, angular rate in dps (degrees/second).
 */

#ifndef CAREMATE_WEARABLE_IMU_H
#define CAREMATE_WEARABLE_IMU_H

struct ImuSample {
  float ax, ay, az;  // acceleration, g
  float gx, gy, gz;  // angular rate, dps
};

// Initialize the I2C bus and the Modulino Movement sensor. Returns false if the
// sensor is not found (caller should surface a FAULT rather than run blind).
bool imuBegin();

// Read the latest sample. Returns true when fresh data was written to `out`.
bool imuRead(ImuSample& out);

#endif  // CAREMATE_WEARABLE_IMU_H
