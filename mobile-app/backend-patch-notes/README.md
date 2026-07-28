# Backend patch — native call-wake pushes

## 1. Install
Add to `backend/requirements.txt`:
```
firebase-admin>=6.5.0
PyAPNs2>=0.7.2
```
Then `pip install -r requirements.txt` (locally: `pip install -r requirements.txt --break-system-packages` if using a system Python).

## 2. Copy the file
Copy `push_calls.py` into `backend/api/v1/push_calls.py`.

## 3. Register the blueprint
In `backend/app.py`, alongside your existing blueprint registrations:
```python
from api.v1.push_calls import push_calls_bp
app.register_blueprint(push_calls_bp, url_prefix='/api/v1/push')
```

## 4. Env vars (add to your real .env, not .env.example)
```
FIREBASE_SERVICE_ACCOUNT_PATH=/etc/secrets/firebase-service-account.json
APNS_VOIP_CERT_PATH=/etc/secrets/VoipCert.pem
APNS_TOPIC=in.thookumadurai.app.voip
APNS_USE_SANDBOX=true
```
Converting the `.p12` you exported from Keychain Access to the `.pem`
PyAPNs2 expects:
```
openssl pkcs12 -in VoipCert.p12 -out VoipCert.pem -nodes -clcerts
```

## 5. Wire it into the existing call flow
In `backend/api/v1/tracking.py`, inside `on_call_offer()`, after the existing
`socketio.emit('call_offer', ...)` relay calls, add a native-wake fallback:

```python
from api.v1.push_calls import send_call_wake_push

@socketio.on('call_offer')
def on_call_offer(data):
    oid = data.get('order_id', '')
    if oid:
        socketio.emit('call_offer', data, room=f'order_{oid}', include_self=False)
    db = current_app.extensions.get("mongo_db")
    callee_user_id = None
    if db is not None and oid:
        order = db.orders.find_one({'_id': oid})
        if order and order.get('rider_id'):
            socketio.emit('call_offer', data, room=f'rider_{order["rider_id"]}', include_self=False)
            callee_user_id = order['rider_id'] if data.get('caller_role') == 'customer' else order.get('customer_phone')
    # ... existing store_sdp_offer(...) call stays as-is ...
    if callee_user_id:
        send_call_wake_push(
            user_id=callee_user_id,
            call_id=data.get('callId') or (oid + '_wake'),
            order_id=oid,
            caller_name=data.get('caller_name', 'Caller'),
            caller_role=data.get('caller_role', 'customer'),
        )
```

This keeps your existing Socket.IO relay (works when both sides have the
page open) and the existing Web Push path (works for PWA installs) exactly
as they are — it just adds a third path that also fires for native app
installs, which is the only one that reliably wakes a fully-closed app.

## 6. Mongo index (optional but recommended)
```python
db.device_tokens.create_index([('user_id', 1), ('platform', 1)], unique=True)
```
