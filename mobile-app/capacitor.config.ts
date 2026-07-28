import type { CapacitorConfig } from '@capacitor/cli';

// Capacitor wraps your existing frontend/ HTML/JS as-is (server.url points at
// your live site, so you do NOT need to rebuild your UI). The native shell's
// only job is to run two background-wake plugins that JS alone cannot do:
//   - Android: high-priority FCM push -> full-screen incoming-call Activity
//   - iOS: PushKit VoIP push -> CallKit native incoming-call UI
// Both hand off to your existing WebRTC code (tracking.html / rider-dashboard.html)
// once the user answers.
const config: CapacitorConfig = {
  appId: 'in.thookumadurai.app',
  appName: 'Thooku Madurai',
  webDir: '../frontend',
  server: {
    // Point this at your deployed frontend so the wrapped app always loads
    // the live site instead of a bundled copy. Switch to bundling later if
    // you want offline support.
    url: 'https://thookumadurai.in',
    cleartext: false
  },
  android: {
    allowMixedContent: false
  }
};

export default config;
