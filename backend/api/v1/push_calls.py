# -*- coding: utf-8 -*-
"""
Native call-wake pushes for the Capacitor-wrapped app.

This is additive to your existing backend/api/v1/push_notifications.py
(which handles browser Web Push for the PWA). Native app installs register
here instead, and get woken via FCM (Android) or APNs VoIP (iOS) — both of
which can start the app from fully-killed state, unlike browser Web Push.

Setup:
  pip install firebase-admin PyAPNs2
  env vars:
    FIREBASE_SERVICE_ACCOUNT_PATH=/etc/secrets/firebase-service-account.json
    APNS_VOIP_CERT_PATH=/etc/secrets/VoipCert.pem   # convert .p12 -> .pem, see note below
    APNS_TOPIC=in.thookumadurai.app.voip
    APNS_USE_SANDBOX=true

Register this blueprint in app.py:
    from api.v1.push_calls import push_calls_bp
    app.register_blueprint(push_calls_bp, url_prefix='/api/v1/push')
"""
import os
import logging
from functools import wraps
from flask import Blueprint, request, jsonify, current_app
import jwt

push_calls_bp = Blueprint('push_calls', __name__)
logger = logging.getLogger(__name__)

_firebase_app = None
_apns_client = None


def _get_db():
    return current_app.extensions.get('mongo_db')


def _auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        try:
            request.user = jwt.decode(token, os.environ.get('JWT_SECRET', 'thooku-madurai-secret-key-2026'), algorithms=['HS256'])
        except Exception:
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return wrapper


def _firebase():
    """
    Reuse the Firebase Admin app if auth.py's phone-OTP code (or this
    module, whichever runs first) already initialized it — calling
    firebase_admin.initialize_app() a second time in the same process
    raises "The default Firebase app already exists".
    """
    global _firebase_app
    if _firebase_app is not None:
        return _firebase_app
    try:
        import firebase_admin
        try:
            _firebase_app = firebase_admin.get_app()
            return _firebase_app
        except ValueError:
            pass  # no default app yet — fall through and create one

        from firebase_admin import credentials
        path = os.environ.get('FIREBASE_SERVICE_ACCOUNT_PATH')
        if not path or not os.path.exists(path):
            logger.warning('FIREBASE_SERVICE_ACCOUNT_PATH not set/found — Android call wake disabled')
            return None
        cred = credentials.Certificate(path)
        _firebase_app = firebase_admin.initialize_app(cred)
        return _firebase_app
    except Exception as e:
        logger.warning(f'Firebase init failed: {e}')
        return None


def _apns():
    """Lazily initialize an APNs VoIP client (iOS)."""
    global _apns_client
    if _apns_client is not None:
        return _apns_client
    try:
        from apns2.client import APNsClient
        cert_path = os.environ.get('APNS_VOIP_CERT_PATH')
        if not cert_path or not os.path.exists(cert_path):
            logger.warning('APNS_VOIP_CERT_PATH not set/found — iOS call wake disabled')
            return None
        use_sandbox = os.environ.get('APNS_USE_SANDBOX', 'true').lower() == 'true'
        _apns_client = APNsClient(cert_path, use_sandbox=use_sandbox)
        return _apns_client
    except Exception as e:
        logger.warning(f'APNs init failed: {e}')
        return None


@push_calls_bp.route('/register-device', methods=['POST'])
@_auth
def register_device():
    """
    Body: { "token": "...", "platform": "android"|"ios", "role": "customer"|"rider" }
    Called once from JS after ThookuCalls.getFcmToken() / getVoipToken().
    """
    data = request.get_json(silent=True) or {}
    token = data.get('token')
    platform = data.get('platform')
    if not token or platform not in ('android', 'ios'):
        return jsonify({'success': False, 'error': 'token and platform (android|ios) required'}), 400

    user_id = (request.user.get('id') or request.user.get('user_id')
               or request.user.get('phone') or request.user.get('google_id'))
    role = data.get('role', request.user.get('role', 'customer'))

    db = _get_db()
    if db is None:
        return jsonify({'success': False, 'error': 'Database unavailable'}), 503

    db.device_tokens.update_one(
        {'user_id': user_id, 'platform': platform},
        {'$set': {'token': token, 'role': role, 'user_id': user_id, 'platform': platform}},
        upsert=True
    )
    return jsonify({'success': True}), 200


def send_call_wake_push(user_id, call_id, order_id, caller_name, caller_role):
    """
    Call this as a fallback whenever you'd otherwise rely on the socket
    room being connected — e.g. from tracking.py's on_call_offer, or from
    push_notifications.py's call_rider()/call_customer(), right after (or
    instead of) the WebPush send. Wakes native app installs even if fully
    closed; browser/PWA installs still get the existing WebPush path.
    """
    db = _get_db()
    if db is None:
        return
    devices = list(db.device_tokens.find({'user_id': user_id}))
    for d in devices:
        if d['platform'] == 'android':
            _send_fcm(d['token'], call_id, order_id, caller_name, caller_role)
        elif d['platform'] == 'ios':
            _send_apns_voip(d['token'], call_id, order_id, caller_name, caller_role)


def _send_fcm(token, call_id, order_id, caller_name, caller_role):
    app = _firebase()
    if not app:
        return
    try:
        from firebase_admin import messaging
        message = messaging.Message(
            token=token,
            # DATA-only message (no "notification" key) delivered at high
            # priority — this is what wakes a killed app on Android.
            data={
                'type': 'incoming_call',
                'callId': call_id,
                'orderId': order_id,
                'callerName': caller_name,
                'callerRole': caller_role,
            },
            android=messaging.AndroidConfig(priority='high'),
        )
        messaging.send(message, app=app)
    except Exception as e:
        logger.warning(f'FCM send failed: {e}')


def _send_apns_voip(token, call_id, order_id, caller_name, caller_role):
    client = _apns()
    if not client:
        return
    try:
        from apns2.payload import Payload
        payload = Payload(custom={
            'callId': call_id,
            'orderId': order_id,
            'callerName': caller_name,
            'callerRole': caller_role,
        })
        topic = os.environ.get('APNS_TOPIC', 'in.thookumadurai.app.voip')
        client.send_notification(token, payload, topic=topic)
    except Exception as e:
        logger.warning(f'APNs VoIP send failed: {e}')


def send_delivery_offer_push(user_id, order_id, restaurant_name, total, distance_km, far_delivery=False):
    """
    Wake the rider's native app (FCM/APNs) with a delivery-offer notification
    so they can accept or reject, even when the app is in background/killed.
    Browser PWA riders get the equivalent WebPush from
    push_notifications.notify_rider_delivery_offer().
    """
    db = _get_db()
    if db is None:
        return
    devices = list(db.device_tokens.find({'user_id': user_id}))
    if not devices:
        return
    for d in devices:
        if d['platform'] == 'android':
            app = _firebase()
            if not app:
                continue
            try:
                from firebase_admin import messaging
                message = messaging.Message(
                    token=d['token'],
                    data={
                        'type': 'delivery_offer',
                        'orderId': str(order_id),
                        'restaurantName': restaurant_name or '',
                        'total': str(total or ''),
                        'distanceKm': str(round(distance_km, 2) if distance_km else ''),
                        'farDelivery': '1' if far_delivery else '0',
                    },
                    android=messaging.AndroidConfig(priority='high'),
                )
                messaging.send(message, app=app)
            except Exception as e:
                logger.warning(f'FCM delivery-offer send failed: {e}')
        elif d['platform'] == 'ios':
            client = _apns()
            if not client:
                continue
            try:
                from apns2.payload import Payload
                payload = Payload(custom={
                    'type': 'delivery_offer',
                    'orderId': str(order_id),
                    'restaurantName': restaurant_name or '',
                    'total': str(total or ''),
                    'distanceKm': str(round(distance_km, 2) if distance_km else ''),
                    'farDelivery': '1' if far_delivery else '0',
                })
                topic = os.environ.get('APNS_TOPIC', 'in.thookumadurai.app.voip')
                client.send_notification(d['token'], payload, topic=topic)
            except Exception as e:
                logger.warning(f'APNs delivery-offer send failed: {e}')
