# Frontend integration

Your existing `pendingOffer` / `acceptCall()` / `callOrderId` /
`callTargetName` in `tracking.html`, `index.html`, and `rider-dashboard.html`
are already declared as top-level `var`/`function` inside plain (non-module,
non-IIFE) `<script>` tags — which in a browser means they're already
properties of `window` (`window.pendingOffer`, `window.acceptCall`, etc.)
with no changes needed to those files' logic. The bridge script relies on
exactly that.

## What to add to each of tracking.html / index.html / rider-dashboard.html

Just before `</body>`, add the Capacitor runtime and the bridge script,
**after** all your existing call-handling `<script>` blocks so
`window.acceptCall` etc. already exist when the bridge registers its
listener:

```html
<script src="https://unpkg.com/@capacitor/core@6/dist/capacitor.js"></script>
<script src="js/native-call-bridge.js"></script>
```

(When you run `npx cap sync`, Capacitor also injects its own
`capacitor.js` automatically into `www/` — if that's already present via the
build, you can drop the unpkg `<script>` tag above and just keep
`native-call-bridge.js`.)

## Login event
The bridge re-registers the device token after login (in case the user
wasn't authenticated yet on first app launch). Fire this from wherever your
existing login success handlers are (e.g. after storing the JWT in `auth`):

```js
window.dispatchEvent(new Event('thooku:login'));
```

## Nothing else changes
The actual WebRTC connection, ICE handling, mute/end-call UI, ringtone, etc.
are all your existing code, untouched — the native layer's only job is
getting `acceptCall()` invoked with the right `pendingOffer` even when the
page wasn't open a few seconds ago.
