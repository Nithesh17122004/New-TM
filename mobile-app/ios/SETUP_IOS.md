# iOS setup — CallKit / PushKit incoming-call feature

Requires a Mac with Xcode and an Apple Developer account ($99/yr — this is
unavoidable for any iOS app, wrapper or not, once you want it on real
devices or the App Store).

## 1. Generate the base project
```
npx cap add ios
```
Then copy `CallManager.swift` and `CallPlugin.swift` from this scaffold into
`ios/App/App/` in Xcode (drag into the project navigator so Xcode adds them
to the target — copying the raw files on disk alone isn't enough).

## 2. Enable capabilities in Xcode
Select the App target → **Signing & Capabilities** → **+ Capability**:
- **Push Notifications**
- **Background Modes** → check **Voice over IP**

## 3. Apple Developer portal
1. Create an **App ID** matching your bundle id (`in.thookumadurai.app`).
2. Create a **VoIP Services Certificate** for that App ID (Certificates →
   type: VoIP Services Certificate). Download it, export as `.p12` from
   Keychain Access — your backend needs this to send VoIP pushes.

## 4. AppDelegate wiring
In `AppDelegate.swift`, inside `application(_:didFinishLaunchingWithOptions:)`,
add:
```swift
CallManager.shared.start()
```
(CallPlugin.load() also calls this, so this line is only needed if you want
VoIP registration to start before the WebView loads — usually fine either way.)

## 5. Give the backend your VoIP cert
Send `VoipCert.p12` + its password to wherever you deploy the backend, and
set these env vars (see `backend-patch/`):
```
APNS_VOIP_CERT_PATH=/etc/secrets/VoipCert.p12
APNS_VOIP_CERT_PASSWORD=...
APNS_TOPIC=in.thookumadurai.app.voip
APNS_USE_SANDBOX=true   # false once you submit to the App Store
```

## 6. Test
- Real device required — the iOS Simulator cannot receive push notifications.
- Force-quit the app (swipe up in the app switcher).
- Trigger a call from the other role. You should see the native full-screen
  CallKit incoming-call UI, even over the lock screen, in silent mode.
- Tapping Answer should launch the app and fire `incomingCallAnswered` in JS.

## Known limitation
Apple requires VoIP pushes to be used only for actual calls — using them for
anything else can get your app rejected or your VoIP entitlement revoked.
Keep this path strictly for real "someone is calling" events.
