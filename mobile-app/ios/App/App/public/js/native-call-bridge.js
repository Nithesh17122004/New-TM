/**
 * native-call-bridge.js
 *
 * Include this AFTER your existing call logic (the pendingOffer / acceptCall
 * functions already fixed in tracking.html, and the equivalents in
 * index.html and rider-dashboard.html) on every page that can receive calls.
 *
 * It is a no-op in a normal browser tab — Capacitor.isNativePlatform() is
 * false there, so nothing changes for your existing PWA/browser flow.
 * Inside the wrapped native app, it:
 *   1. Registers the device's FCM (Android) or VoIP (iOS) token with the
 *      backend so it can be woken for calls even when fully closed.
 *   2. Listens for the native "the user tapped Answer on the native call
 *      screen" event, fetches the stored SDP offer, and feeds it into your
 *      existing acceptCall() flow — so the actual WebRTC/audio code is
 *      reused unchanged.
 */
(function () {
  if (!window.Capacitor || !window.Capacitor.isNativePlatform || !window.Capacitor.isNativePlatform()) {
    return; // plain browser / PWA — existing Web Push flow already handles this
  }

  var ThookuCalls = window.Capacitor.Plugins && window.Capacitor.Plugins.CallPlugin;
  if (!ThookuCalls) {
    console.warn('CallPlugin not registered — did you add it in MainActivity/AppDelegate?');
    return;
  }

  var API_BASE = (window.API || window.API_BASE || 'https://new-tm-knk1.onrender.com/api/v1');
  var platform = window.Capacitor.getPlatform(); // 'android' | 'ios'

  function getAuth() {
    try { return JSON.parse(localStorage.getItem('tm_auth') || '{}'); }
    catch (e) { return {}; }
  }

  function authHeaders() {
    var token = getAuth().token || '';
    return { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' };
  }

  function registerDeviceToken() {
    if (!getAuth().token) return; // not logged in yet on this page load
    var getToken = platform === 'ios' ? ThookuCalls.getVoipToken : ThookuCalls.getFcmToken;
    if (!getToken) return;
    getToken().then(function (res) {
      if (!res || !res.token) return;
      fetch(API_BASE + '/push/register-device', {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({ token: res.token, platform: platform })
      }).catch(function (e) { console.warn('Device token registration failed', e); });
    }).catch(function (e) {
      // iOS VoIP token may not be ready on first launch — retry once shortly after.
      if (platform === 'ios') setTimeout(registerDeviceToken, 5000);
    });
  }

  // Register on load, and again after login (token/user id may not be
  // available yet on first app open before auth completes).
  registerDeviceToken();
  window.addEventListener('thooku:login', registerDeviceToken);

  ThookuCalls.addListener('incomingCallAnswered', function (data) {
    // data: { callId, orderId, callerName, callerRole }
    fetch(API_BASE + '/push/pending-offer/' + encodeURIComponent(data.callId), {
      headers: authHeaders()
    })
      .then(function (r) { return r.json(); })
      .then(function (res) {
        if (!res || !res.sdp) {
          if (window.showToast) window.showToast('Call already ended', 'warning');
          return;
        }
        if (typeof window.__thookuAcceptNativeCall !== 'function') {
          console.warn('__thookuAcceptNativeCall shim missing on this page \u2014 see www/INTEGRATION.md');
          return;
        }
        // Each page (tracking.html / index.html / rider-dashboard.html) uses
        // its own variable and function names for the same concept, so the
        // per-page shim (defined right before this script tag) normalizes
        // that instead of this file guessing at globals that don't exist.
        window.__thookuAcceptNativeCall(res.sdp, res.orderId || data.orderId, data.callerName);
      })
      .catch(function (e) { console.warn('Could not fetch pending offer', e); });
  });
})();
