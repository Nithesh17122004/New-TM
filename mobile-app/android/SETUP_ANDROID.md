# Android setup — incoming-call wake feature

These steps assume you've already run `npx cap add android` once (that
generates the base project this folder's files get copied into).

## 1. Copy files
Copy everything under `android/app/src/main/java/com/thookumadurai/app/`
and `android/app/src/main/res/layout/` from this scaffold into the matching
paths in your generated `android/` project (same package name).

## 2. Add Firebase
1. Create a Firebase project (free tier is fine) at console.firebase.google.com.
2. Add an Android app with package name `in.thookumadurai.app` (or whatever
   you set as `appId` in `capacitor.config.ts`).
3. Download `google-services.json` and place it in `android/app/`.
4. In `android/build.gradle` (project level), add to `dependencies`:
   ```gradle
   classpath 'com.google.gms:google-services:4.4.2'
   ```
5. In `android/app/build.gradle`:
   ```gradle
   apply plugin: 'com.google.gms.google-services'

   dependencies {
     implementation platform('com.google.firebase:firebase-bom:33.1.0')
     implementation 'com.google.firebase:firebase-messaging'
     implementation 'androidx.appcompat:appcompat:1.7.0'
   }
   ```

## 3. AndroidManifest.xml additions
Inside `<application>`, add:
```xml
<service
    android:name=".CallFirebaseMessagingService"
    android:exported="false">
    <intent-filter>
        <action android:name="com.google.firebase.MESSAGING_EVENT" />
    </intent-filter>
</service>

<activity
    android:name=".IncomingCallActivity"
    android:exported="false"
    android:showOnLockScreen="true"
    android:launchMode="singleTop"
    android:theme="@style/Theme.AppCompat.NoActionBar" />
```

Above `<application>`, add permissions:
```xml
<uses-permission android:name="android.permission.VIBRATE" />
<uses-permission android:name="android.permission.USE_FULL_SCREEN_INTENT" />
<uses-permission android:name="android.permission.POST_NOTIFICATIONS" />
```

## 4. Runtime permissions (read this — affects whether it actually works)
- **Android 13+ (API 33+):** `POST_NOTIFICATIONS` must be granted at *runtime*,
  not just declared in the manifest. `MainActivity.kt` already requests this
  on first launch. If the user denies it, no incoming-call notification (and
  therefore no full-screen call UI) will ever show — silently, no crash.
- **Android 14+ (API 34+):** Google tightened `USE_FULL_SCREEN_INTENT` so it's
  auto-granted only to apps Play Protect classifies as calling/alarm apps.
  New apps may need the user to manually enable it: **Settings → Apps →
  Thooku Madurai → Alarms & reminders / Full screen notifications**. Until
  granted, the call still arrives as a normal heads-up notification (tappable,
  just not auto-popping over the lock screen) — so it degrades gracefully
  rather than failing outright.

## 5. Battery optimization (important — read this)
Some Android OEMs (Xiaomi/MIUI, Vivo, Oppo, Huawei) kill background apps
aggressively regardless of FCM priority. Add an onboarding step in your app
asking the rider/customer to disable battery optimization for the app
(Settings → Apps → Thooku Madurai → Battery → Unrestricted). Without this,
the high-priority push may still arrive late or not at all on those devices.
There is no fully reliable code-only workaround for this — it's an OS/OEM
restriction, not a bug in your app.

## 6. Test
- Force-stop the app (Settings → Apps → Force Stop) to simulate "closed".
- Trigger a call from the other role's dashboard.
- Confirm the full-screen incoming-call activity appears, even over the
  lock screen, and that tapping Answer opens the app and fires the
  `incomingCallAnswered` JS event (see `www/js/native-call-bridge.js`).
