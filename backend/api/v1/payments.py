# ============================================================
# THOOKU MADURAI — API: Payments (Razorpay)
# /api/v1/payments
# ============================================================

import hmac
import hashlib
import os
import uuid
import logging

import jwt
import requests as req
from flask import Blueprint, request, jsonify, current_app
from functools import wraps

payments_bp = Blueprint("payments", __name__)
logger = logging.getLogger(__name__)

# Reuse the app-level require_auth from app.py (imported at blueprint registration)
from services.jwt_config import JWT_SECRET  # fails fast if unset — see that module
RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "")
RAZORPAY_WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "")
FLASK_ENV = os.environ.get("FLASK_ENV", "development").lower()

RAZORPAY_API = "https://api.razorpay.com/v1/"
PAYMENT_MOCK_MODE = os.environ.get("PAYMENT_MOCK_MODE", "").lower() in ("1", "true", "yes")


def _use_mock_mode() -> bool:
    """Mock payments unless explicitly configured for real mode.

    - PAYMENT_MOCK_MODE=1/true/yes  -> always mock
    - PAYMENT_MOCK_MODE=0/false/no  -> always real (fails loudly if keys missing)
    - unset                          -> mock only while no real Razorpay
                                        credentials are configured, so enabling
                                        real payments is automatic once the
                                        keys are set.
    """
    env_mode = os.environ.get("PAYMENT_MOCK_MODE", "").lower()
    if env_mode in ("1", "true", "yes"):
        return True
    if env_mode in ("0", "false", "no"):
        return False
    return not (RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET)


def get_db():
    return current_app.extensions.get("mongo_db")


def require_auth_decorator(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
        if not token:
            return jsonify({"success": False, "error": "No token"}), 401
        try:
            request.user = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            return jsonify({"success": False, "error": "Token expired"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"success": False, "error": "Invalid token"}), 401
        return f(*args, **kwargs)
    return decorated


def _update_order_payment(db, order_id: str, payment_status: str, payment_id: str = ""):
    if db is None or not order_id:
        return
    update = {"payment_status": payment_status}
    if payment_id:
        # "instamojo_payment_id" is kept as a legacy mirror so orders created
        # before the Razorpay switch and older app builds still work.
        update["razorpay_payment_id"] = payment_id
        update["instamojo_payment_id"] = payment_id
    db.orders.update_one({"_id": order_id}, {"$set": update})


# ── Razorpay Helpers ─────────────────────────────────────────────────────────

def _razorpay_auth():
    return (RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET)


def _create_razorpay_order(order_id: str, amount: float) -> dict | None:
    """Create a Razorpay order (amount in paise). Returns the order dict."""
    try:
        resp = req.post(
            f"{RAZORPAY_API}orders",
            auth=_razorpay_auth(),
            data={
                "amount": f"{round(float(amount) * 100)}",
                "currency": "INR",
                "receipt": order_id,
                "payment_capture": 1,
            },
            timeout=15,
        )
        data = resp.json()
        if resp.status_code == 200 and data.get("id"):
            return data
        logger.warning("Razorpay order create failed: %s", data.get("error", resp.text[:200]))
        return None
    except Exception as e:
        logger.error("Razorpay order request error: %s", e)
        return None


def _verify_razorpay_signature(order_id: str, payment_id: str, signature: str) -> bool:
    """Standard Razorpay signature check: HMAC-SHA256 of
    '<order_id>|<payment_id>' with the key secret."""
    if not signature:
        return False
    mac = hmac.new(
        RAZORPAY_KEY_SECRET.encode(),
        f"{order_id}|{payment_id}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(mac, signature)


def _verify_razorpay_webhook(raw_body: bytes, signature: str) -> bool:
    """Razorpay webhook signature: HMAC-SHA256 of the raw request body with
    the webhook secret."""
    if not signature or not RAZORPAY_WEBHOOK_SECRET:
        return False
    mac = hmac.new(
        RAZORPAY_WEBHOOK_SECRET.encode(),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(mac, signature)


# ── Endpoints ────────────────────────────────────────────────────────────────

@payments_bp.route("/create-order", methods=["POST"])
@require_auth_decorator
def create_payment_order():
    """Create a Razorpay order for the order.

    Follows _use_mock_mode(): a mock payment is returned only while no real
    Razorpay credentials are configured (or PAYMENT_MOCK_MODE forces mock).
    Once RAZORPAY_KEY_ID + RAZORPAY_KEY_SECRET are set, this creates a real
    Razorpay order and returns the order id + the public key id for the
    frontend Razorpay Checkout.

    The amount is taken from the order document (never trusted from the
    client body), so a customer cannot pay less than the billed total.
    """
    body = request.get_json(silent=True) or {}
    order_id = body.get("order_id", "")
    if not order_id:
        return jsonify({"success": False, "error": "order_id required"}), 400

    db = get_db()
    order = None
    if db is not None:
        order = db.orders.find_one({"_id": order_id})
        if order is None:
            return jsonify({"success": False, "error": "Order not found"}), 404

    try:
        amount = float(order["total"]) if order else float(body.get("amount", 0) or 0)
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "Invalid amount"}), 400
    if amount <= 0:
        return jsonify({"success": False, "error": "Invalid amount"}), 400

    if _use_mock_mode():
        return jsonify({
            "success": True,
            "data": {
                "payment_request_id": f"mock_pr_{uuid.uuid4().hex[:12]}",
                "longurl": "",
                "shorturl": "",
                "amount": amount,
                "order_id": order_id,
                "mock_mode": True,
            },
        }), 200

    rzp_order = _create_razorpay_order(order_id, amount)
    if rzp_order is None:
        return jsonify({
            "success": False,
            "error": "Razorpay order creation failed - check RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET",
        }), 502

    # Persist the mapping (Razorpay order id -> our order) so the webhook can
    # resolve payment events back to this order.
    if db is not None:
        db.orders.update_one(
            {"_id": order_id},
            {"$set": {"razorpay_order_id": rzp_order.get("id")}},
        )

    return jsonify({
        "success": True,
        "data": {
            "payment_request_id": rzp_order.get("id"),
            "razorpay_order_id": rzp_order.get("id"),
            "razorpay_key_id": RAZORPAY_KEY_ID,
            "amount": amount,
            "amount_paise": rzp_order.get("amount", round(amount * 100)),
            "currency": rzp_order.get("currency", "INR"),
            "order_id": order_id,
            "mock_mode": False,
        },
    }), 200


@payments_bp.route("/verify", methods=["POST"])
@require_auth_decorator
def verify_payment():
    """Verify payment after Razorpay Checkout success or mock completion."""
    data = request.get_json(silent=True) or {}
    order_id = data.get("order_id", "")
    payment_request_id = data.get("payment_request_id", "")
    payment_id = data.get("payment_id", "")
    status = data.get("status", "paid")

    if not order_id:
        return jsonify({"success": False, "error": "order_id required"}), 400

    db = get_db()
    if db is not None and db.orders.find_one({"_id": order_id}) is None:
        return jsonify({"success": False, "error": "Order not found"}), 404

    is_mock = (payment_request_id or "").startswith("mock_") or data.get("mock_mode")

    if is_mock:
        _update_order_payment(db, order_id, "paid", payment_id or f"pay_mock_{uuid.uuid4().hex[:12]}")
        return jsonify({
            "success": True,
            "message": "Payment verified (mock)",
            "data": {"order_id": order_id, "status": "paid"},
        }), 200

    # Real Razorpay Checkout: verify the payment signature returned by the SDK.
    rzp_order_id = data.get("razorpay_order_id", "")
    rzp_payment_id = data.get("razorpay_payment_id", "")
    rzp_signature = data.get("razorpay_signature", "")

    if not rzp_order_id or not rzp_payment_id or not rzp_signature:
        return jsonify({"success": False, "error": "razorpay_order_id / razorpay_payment_id / razorpay_signature required"}), 400

    if not _verify_razorpay_signature(rzp_order_id, rzp_payment_id, rzp_signature):
        logger.warning("Razorpay signature verification failed for order %s", order_id)
        return jsonify({"success": False, "error": "Payment signature verification failed"}), 400

    _update_order_payment(db, order_id, "paid", rzp_payment_id)
    return jsonify({
        "success": True,
        "message": "Payment verified!",
        "data": {"order_id": order_id, "status": "paid", "payment_id": rzp_payment_id},
    }), 200


def _process_payment_webhook(raw_body: bytes, signature: str, data: dict, db) -> tuple:
    """Validate + apply a Razorpay webhook. Returns (http_status, body).

    Guards applied in order:
      1. Razorpay HMAC-SHA256 signature (webhook secret, over the raw body)
      2. unknown order -> 400, never paid
      3. duplicate webhook / already-paid order -> idempotent 200
      4. paid amount must match the order total -> 400 otherwise
    """
    if not _verify_razorpay_webhook(raw_body, signature):
        logger.warning("Webhook signature verification failed")
        return 400, {"status": "error", "message": "Invalid signature"}

    event = data.get("event", "")
    entity = (data.get("payload") or {}).get("payment") or {}
    payment = entity.get("entity") or {}

    payment_id = payment.get("id", "")
    order_id = payment.get("order_id", "")
    amount_paise = payment.get("amount", 0)
    payment_status = payment.get("status", "")

    # payment.authorized / payment.captured = money moved.
    is_credit = event in ("payment.captured", "payment.authorized") and payment_status in ("captured", "authorized")

    if not is_credit or not order_id:
        if order_id:
            # Order id may be a Razorpay order id — only mark the app order
            # failed when we can resolve it.
            resolved = db.orders.find_one({"_id": order_id}) if db else None
            if resolved is None:
                resolved = db.orders.find_one({"razorpay_order_id": order_id}) if db else None
            if resolved is not None:
                _update_order_payment(db, resolved["_id"], "failed")
        return 200, {"status": "ok"}

    if db is None:
        # Nothing to verify against — acknowledge so Razorpay stops retrying.
        return 200, {"status": "ok"}

    # The payment entity's "order_id" is the RAZORPAY order id — resolve it
    # back to our order via the mapping stored at create-order time.
    order = db.orders.find_one({"_id": order_id})
    if order is None:
        order = db.orders.find_one({"razorpay_order_id": order_id})
    if order is None:
        logger.warning("Webhook for unknown order %s", order_id)
        return 400, {"status": "error", "message": "Unknown order"}

    # Duplicate / already processed — idempotent, never double-process.
    if order.get("payment_status") in ("paid", "completed"):
        return 200, {"status": "ok"}

    try:
        paid_paise = float(amount_paise or 0)
        order_paise = round(float(order.get("total", 0) or 0) * 100)
    except (TypeError, ValueError):
        paid_paise = order_paise = 0.0
    if abs(paid_paise - order_paise) > 0.01:
        logger.error(
            "Webhook amount mismatch for order %s (paid %.2f paise, expected %d paise)",
            order_id, paid_paise, order_paise,
        )
        return 400, {"status": "error", "message": "Amount mismatch"}

    _update_order_payment(db, order["_id"], "paid", payment_id)
    logger.info("Payment webhook: order %s paid (payment %s)", order["_id"], payment_id)
    return 200, {"status": "ok"}


@payments_bp.route("/webhook", methods=["POST"])
def payment_webhook():
    """Handle Razorpay webhook callback (signature-verified, raw body)."""
    raw_body = request.get_data()
    signature = request.headers.get("X-Razorpay-Signature", "")
    data = request.get_json(silent=True) or {}
    code, body = _process_payment_webhook(raw_body, signature, data, get_db())
    return jsonify(body), code


@payments_bp.route("/refund", methods=["POST"])
@require_auth_decorator
def initiate_refund():
    """Initiate a refund via Razorpay or mock."""
    data = request.get_json(silent=True) or {}
    payment_id = data.get("payment_id", data.get("razorpay_payment_id", data.get("instamojo_payment_id", "")))
    amount = data.get("amount", 0)
    reason = data.get("reason", "order_cancelled_no_rider")
    order_id = data.get("order_id", "")

    if not payment_id and not order_id:
        return jsonify({"success": False, "error": "payment_id or order_id required"}), 400

    # Auto-find payment_id from order
    if not payment_id and order_id:
        db = get_db()
        if db is not None:
            order = db.orders.find_one({"_id": order_id}, {"razorpay_payment_id": 1, "instamojo_payment_id": 1})
            if order:
                payment_id = order.get("razorpay_payment_id") or order.get("instamojo_payment_id", "")

    is_mock = (payment_id or "").startswith("pay_mock") or _use_mock_mode()

    if is_mock or not payment_id:
        refund_id = f"refund_mock_{uuid.uuid4().hex[:12]}"
        return jsonify({
            "success": True,
            "message": "Refund initiated (mock)",
            "data": {"refund_id": refund_id, "amount": amount, "status": "processed"},
        }), 200

    try:
        payload = {"notes[reason]": reason}
        if amount:
            payload["amount"] = f"{round(float(amount) * 100)}"
        resp = req.post(
            f"{RAZORPAY_API}payments/{payment_id}/refund",
            auth=_razorpay_auth(),
            data=payload,
            timeout=15,
        )
        ref_data = resp.json()
        if resp.status_code == 200:
            refund_id = ref_data.get("id", f"ref_{uuid.uuid4().hex[:12]}")
            return jsonify({
                "success": True,
                "message": "Refund initiated",
                "data": {"refund_id": refund_id, "amount": amount, "status": "processing"},
            }), 200
        return jsonify({"success": False, "error": ref_data.get("error", {}).get("description", "Refund failed")}), 500
    except Exception as e:
        logger.error("Refund error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@payments_bp.route("/history", methods=["GET"])
@require_auth_decorator
def payment_history():
    phone = request.user.get("phone", "")
    db = get_db()
    if db is None or not phone:
        return jsonify({"success": True, "data": []}), 200

    orders = list(
        db.orders.find(
            {"customer_phone": phone, "payment_status": {"$in": ["paid", "completed"]}},
            {"_id": 1, "total": 1, "payment_method": 1, "payment_status": 1, "created_at": 1},
        ).sort("created_at", -1).limit(20)
    )
    transactions = [
        {
            "id": o["_id"],
            "order_id": o["_id"],
            "amount": o.get("total", 0),
            "method": o.get("payment_method", "UPI"),
            "status": o.get("payment_status", "paid"),
            "date": o.get("created_at"),
        }
        for o in orders
    ]
    return jsonify({"success": True, "data": transactions}), 200
