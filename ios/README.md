# CareMate iOS app

Open `CareMate.xcodeproj` in Xcode and run the `CareMate` scheme on an iPhone or
iOS simulator. The target is iOS 17 or newer.

Enter the hub URL and the bearer token configured for Aryan's `HttpAppBus`. The
app saves the URL in device preferences and stores the token in the device-only
iOS Keychain after Connect is tapped. `http://` is supported for an isolated
local demo network; use `https://` on shared networks.
All native requests include ngrok's free-tier interstitial-bypass header, which
is harmless on the direct hotspot connection. Normal Live View prefers the
authenticated `/feed` MJPEG stream on the LAN and automatically falls back to
`/frame` polling if MJPEG cannot deliver frames. **Load one frame** also fetches
one bounded JPEG from `/frame`.

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
unsupported devices use a deterministic paragraph. Start the hub with
`--feed-camera` for the current unannotated C270 feed; pose annotations are still
pending. This is a prototype, not a medical device or guaranteed emergency service.
