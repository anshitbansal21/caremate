# CareMate iOS app

Open `CareMate.xcodeproj` in Xcode and run the `CareMate` scheme on an iPhone or
iOS simulator. The target is iOS 17 or newer.

Enter the hub URL and the bearer token configured for Aryan's `HttpAppBus`. The
app intentionally does not persist the token. `http://` is supported
for an isolated local demo network; use `https://` on shared networks.

Run the contract tests with:

```sh
swift test
```

The app subscribes to `/events` over SSE, sends Analyze/acknowledge/cancel REST
actions, and reads annotated JPEGs from the `/feed` MJPEG stream. The current
activity card reflects the latest request-scoped **Analyze space** result. On
iOS 26 with Apple Intelligence available, the app uses Apple's on-device
Foundation Models framework to turn the returned structured fields into a
concise presentation paragraph. It does not send the image to the phone model,
and generated prose never changes fall confirmation or alerts. iOS 17–25 and
unsupported devices use a deterministic paragraph. Feed unavailability is
expected until Aryan wires its annotated-frame provider. This is a prototype,
not a medical device or guaranteed emergency service.
