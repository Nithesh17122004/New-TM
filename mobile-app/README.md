# Thooku Madurai — Native Call-Wake Wrapper

Solves: *"customer places order, closes the app, rider arrives and calls —
the call needs to actually ring."* Plain WebRTC-in-a-browser-tab can't do
this; it needs OS-level wake mechanisms, which is what this adds — at zero
per-call cost (unlike Exotel/Twilio masked calling).

## What this is
Your existing frontend (`frontend/*.html`) is wrapped, unmodified in
behavior, using [Capacitor](https://capacitorjs.com) — a thin native shell
around a WebView. Two small native plugins add the one thing pure web code
cannot do: wake the app from fully-closed state when a call comes in.

- **Android** → Firebase Cloud Messaging (high-priority data push) → a
  full-screen native incoming-call Activity, even over the lock screen.
- **iOS** → PushKit (VoIP push) → Apple's CallKit, the same system UI
  WhatsApp/Signal use for calls.

Once answered, both hand off to your **existing, already-working WebRTC
code** (same `acceptCall()` / `answerIncomingCall()` / `answerCall()` logic
you already have) — nothing about the actual audio/call connection changes.

## Cost
- Firebase: free tier is enough (FCM has no per-message charge).
- Apple Developer Program: $99/year — **required for any iOS app**,
  wrapper or not; not specific to this feature.
- Google Play: $25 one-time — also just the standard cost of shipping an
  Android app at all.
- No telephony/per-minute charges (unlike the Exotel path we discussed and
  ruled out).

## What you still need that I can't provide from here
- **A Mac + Xcode** for the iOS half — cannot be built or tested from a
  browser/Linux box, that's an Apple platform restriction, not a tooling gap.
- **Android Studio** (or at least the Android SDK/CLI) to build the APK.
- **A physical Android device** to properly test background-wake behavior
  (emulators don't reflect real OEM battery-optimization behavior).
- **A physical iPhone** — the iOS Simulator cannot receive push notifications
  at all, so CallKit/PushKit is untestable there.
- Your own Firebase project and Apple Developer account (both tied to your
  identity/payment method — I can't create these for you).

## Setup order
1. `npm install` in this folder, then `npx cap add android` and
   `npx cap add ios` to generate the platform projects.
2. Follow `android/SETUP_ANDROID.md` — copy the plugin files in, add
   Firebase, edit AndroidManifest.xml.
3. Follow `ios/SETUP_IOS.md` — copy the plugin files in via Xcode, enable
   capabilities, create the VoIP push certificate.
4. Follow `backend-patch/README.md` — adds one new blueprint
   (`push_calls.py`) to your Flask backend for device-token registration and
   sending the wake pushes. Doesn't touch your existing Web Push (browser
   PWA) code path at all — it's additive.
5. Follow `www/INTEGRATION.md` — already applied for you in this bundle's
   `www/*.html` (script tags + per-page shims are in place); this doc just
   explains what was changed and why, in case you need to reapply it to a
   newer copy of your frontend later.

## File map
```
capacitor.config.ts              — points the wrapper at your live site
package.json                     — Capacitor deps
android/.../CallFirebaseMessagingService.kt   — receives the FCM wake push
android/.../IncomingCallActivity.kt           — full-screen native call UI
android/.../CallPlugin.kt + MainActivity.kt   — JS <-> native bridge
android/SETUP_ANDROID.md         — manual Firebase/manifest steps
ios/App/App/CallManager.swift    — PushKit + CallKit
ios/App/App/CallPlugin.swift     — JS <-> native bridge
ios/SETUP_IOS.md                 — manual Xcode/Apple Developer steps
backend-patch/push_calls.py      — device token registration + FCM/APNs sending
backend-patch/README.md          — how to wire it into tracking.py
www/*.html                       — your frontend, with the tracking.html
                                    pendingOffer bug already fixed, plus the
                                    bridge script + per-page shims added
www/js/native-call-bridge.js     — the actual JS glue
www/INTEGRATION.md               — explains the edits made to the html files
```

## Realistic expectation
This gets you WhatsApp/Uber-grade "rings even when closed" behavior on
Android reliably, and on iOS reliably **once built and signed properly**.
The one soft spot that's an OS/OEM limitation, not something fixable in
code: aggressive battery managers on some Android phones (Xiaomi, Vivo,
Oppo) can still delay or drop the wake push unless the user grants
"unrestricted battery" for the app — worth a one-time onboarding prompt.
