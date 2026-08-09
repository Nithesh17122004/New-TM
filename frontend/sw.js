// Thooku Madurai — Service Worker for Web Push
const API_BASE = 'https://new-tm-knk1.onrender.com';
const API_BASE_SOCKET = 'https://new-tm-knk1.onrender.com';

function isCustomer() { return !self.location.pathname.startsWith('/rider-dashboard'); }

self.addEventListener('push', function (event) {
  if (!event.data) return;
  let data;
  try {
    data = event.data.json();
  } catch (e) { return; }

  // New delivery offer (rider dashboard) — accept/reject happens in the app
  if (data.type === 'delivery_offer') {
    const tag = 'thooku-offer-' + data.order_id;
    const dist = data.distance_km ? ' · ' + data.distance_km + ' km away' : '';
    const far = data.far_offer ? ' · Farther than usual (no nearer rider available)' : '';
    event.waitUntil((async () => {
      const clients = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
      for (const c of clients) {
        if (c.url.includes('rider-dashboard')) {
          c.focus();
          c.postMessage({ type: 'THOOKU_DELIVERY_OFFER', ...data });
          return;
        }
      }
      self.registration.showNotification('New delivery offer 🛵', {
        body: 'Pick up from ' + (data.restaurant_name || 'Restaurant') + dist + far + '. Open the app to accept or reject.',
        icon: '/icon-192.png',
        badge: '/icon-72.png',
        tag: tag,
        data: { type: 'delivery_offer', ...data },
        requireInteraction: true,
        vibrate: [0, 300, 150, 300]
      });
    })());
    return;
  }

  if (!data.callId) return;
  const tag = 'thooku-call-' + data.callId;
  const key = 'thooku_pending_call_' + data.callId;
  event.waitUntil((async () => {
    const clients = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    // If any matching client is already focused, tell it instead of showing notification
    for (const c of clients) {
      const url = c.url || '';
      if (isCustomer() && !url.includes('rider-dashboard')) {
        c.postMessage({ type: 'THOOKU_INCOMING_CALL', ...data });
        return;
      }
      if (!isCustomer() && url.includes('rider-dashboard')) {
        c.postMessage({ type: 'THOOKU_INCOMING_CALL', ...data });
        return;
      }
    }
    self.__thooku_pending = self.__thooku_pending || {};
    self.__thooku_pending[key] = data;
    self.registration.showNotification('Thooku Madurai', {
      body: data.callerName ? data.callerName + ' is calling...' : 'Incoming call...',
      icon: '/icon-192.png',
      badge: '/icon-72.png',
      tag: tag,
      data: data,
      requireInteraction: true,
      vibrate: [200, 100, 200, 100, 400],
      actions: [{ action: 'answer', title: 'Answer' }, { action: 'decline', title: 'Decline' }]
    });
  })());
});

self.addEventListener('notificationclick', function (event) {
  event.notification.close();
  const data = event.notification.data;
  if (!data) return;
  if (data.type === 'delivery_offer') {
    event.waitUntil((async () => {
      const clients = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
      for (const c of clients) {
        if (c.url.includes('rider-dashboard')) { c.focus(); return; }
      }
      await self.clients.openWindow('/rider-dashboard');
      // The dashboard fetches /riders/pending-offer on load and shows
      // the accept/reject card for this offer.
    })());
    return;
  }
  if (!data.callId) return;
  if (event.action === 'decline') {
    fetch(API_BASE + '/api/v1/push/call-declined', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ callId: data.callId, orderId: data.orderId })
    }).catch(() => {});
    return;
  }
  // answer — open/focus the right page
  const targetUrl = data.callerRole === 'rider' ? '/' : '/rider-dashboard';
  event.waitUntil((async () => {
    const clients = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const c of clients) {
      const url = c.url || '';
      if (data.callerRole === 'rider' && !url.includes('rider-dashboard')) {
        c.focus();
        c.postMessage({ type: 'THOOKU_INCOMING_CALL', ...data });
        return;
      }
      if (data.callerRole !== 'rider' && url.includes('rider-dashboard')) {
        c.focus();
        c.postMessage({ type: 'THOOKU_INCOMING_CALL', ...data });
        return;
      }
    }
    const win = await self.clients.openWindow(targetUrl);
    // The opened page will call /api/v1/push/page-ready to get the SDP
  })());
});

self.addEventListener('message', function (event) {
  if (event.data && event.data.type === 'THOOKU_MARK_HANDLED') {
    const key = 'thooku_pending_call_' + event.data.callId;
    if (self.__thooku_pending) delete self.__thooku_pending[key];
  }
});
