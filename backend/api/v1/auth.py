# -*- coding: utf-8 -*-
"""
Authentication module for Thooku Madurai.
Supports:
  1. Customer  - Google OAuth
  2. Restaurant - Username + Password
  3. Rider      - Username + Password
  4. SuperAdmin - Email + Password
"""

import os
import time
import logging

import bcrypt
import jwt
from flask import Blueprint, current_app, jsonify, request

# ---------------------------------------------------------------------------
# Blueprint & constants
# ---------------------------------------------------------------------------
auth_bp = Blueprint("auth", __name__)
logger = logging.getLogger(__name__)

JWT_SECRET = os.environ.get("JWT_SECRET", "thooku-madurai-secret-key-2026")
JWT_EXPIRY = 86400 * 7  # 7 days


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_db():
    return current_app.extensions.get("mongo_db")

def _make_token(payload: dict) -> str:
    payload["exp"] = int(time.time()) + JWT_EXPIRY
    payload["iat"] = int(time.time())
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


# ---------------------------------------------------------------------------
# Restaurant login
# ---------------------------------------------------------------------------

@auth_bp.route("/restaurant-login", methods=["POST"])
def restaurant_login():
    """
    Body: { "username": "...", "password": "..." }
    Finds restaurant by username in 'restaurants' collection.
    Verifies password with bcrypt.
    Returns JWT with role='restaurant'.
    """
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", "")).strip()

    if not username or not password:
        return jsonify({"success": False, "message": "Username and password are required"}), 400

    db = get_db()
    if db is None:
        return jsonify({"success": False, "message": "Database unavailable"}), 503

    restaurant = db.restaurants.find_one({"username": username})
    if restaurant is None:
        return jsonify({"success": False, "message": "Invalid credentials"}), 401

    password_hash = restaurant.get("password_hash", "")
    try:
        valid = bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except Exception:
        valid = False

    if not valid:
        return jsonify({"success": False, "message": "Invalid credentials"}), 401

    # Optional 2FA: if the client sends a firebase_id_token (OTP already verified
    # client-side), confirm it matches the phone number on file before issuing
    # a session. Not yet mandatory — enforce by requiring this field once every
    # restaurant account has a phone number on file.
    firebase_id_token = str(data.get("firebase_id_token", "")).strip()
    if firebase_id_token:
        decoded = _verify_firebase_id_token(firebase_id_token)
        if decoded is None:
            return jsonify({"success": False, "message": "OTP verification failed or expired"}), 401
        otp_phone = _normalize_phone_10digit(decoded.get("phone_number", ""))
        on_file_phone = _normalize_phone_10digit(restaurant.get("phone", ""))
        if on_file_phone and otp_phone != on_file_phone:
            return jsonify({"success": False, "message": "OTP phone does not match the registered restaurant phone"}), 401

    restaurant_id = str(restaurant["_id"])
    token = _make_token(
        {
            "user_id": restaurant_id,
            "role": "restaurant",
            "name": restaurant.get("name", username),
            "restaurant_id": restaurant_id,
        }
    )

    return jsonify(
        {
            "success": True,
            "message": "Login successful",
            "token": token,
            "user": {
                "id": restaurant_id,
                "name": restaurant.get("name", username),
                "username": username,
                "role": "restaurant",
                "restaurant_id": restaurant_id,
            },
        }
    ), 200


# ---------------------------------------------------------------------------
# Rider login
# ---------------------------------------------------------------------------

@auth_bp.route("/rider-login", methods=["POST"])
def rider_login():
    """
    Body: { "username": "...", "password": "..." }
    Finds rider by username in 'delivery_partners' collection.
    Verifies password with bcrypt.
    Returns JWT with role='rider'.
    """
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", "")).strip()

    if not username or not password:
        return jsonify({"success": False, "message": "Username and password are required"}), 400

    db = get_db()
    if db is None:
        return jsonify({"success": False, "message": "Database unavailable"}), 503

    rider = db.delivery_partners.find_one({"username": username})
    if rider is None:
        return jsonify({"success": False, "message": "Invalid credentials"}), 401

    password_hash = rider.get("password_hash", "")
    try:
        valid = bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except Exception:
        valid = False

    if not valid:
        return jsonify({"success": False, "message": "Invalid credentials"}), 401

    firebase_id_token = str(data.get("firebase_id_token", "")).strip()
    if firebase_id_token:
        decoded = _verify_firebase_id_token(firebase_id_token)
        if decoded is None:
            return jsonify({"success": False, "message": "OTP verification failed or expired"}), 401
        otp_phone = _normalize_phone_10digit(decoded.get("phone_number", ""))
        on_file_phone = _normalize_phone_10digit(rider.get("phone", ""))
        if on_file_phone and otp_phone != on_file_phone:
            return jsonify({"success": False, "message": "OTP phone does not match the registered rider phone"}), 401

    rider_id = str(rider["_id"])
    rider_phone = str(rider.get("phone", "")).strip()
    token = _make_token(
        {
            "user_id": rider_id,
            "role": "rider",
            "name": rider.get("name", username),
            "rider_id": rider_id,
            "phone": rider_phone,
        }
    )

    return jsonify(
        {
            "success": True,
            "message": "Login successful",
            "token": token,
            "user": {
                "id": rider_id,
                "name": rider.get("name", username),
                "username": username,
                "role": "rider",
                "rider_id": rider_id,
                "phone": rider_phone,
            },
        }
    ), 200


# ---------------------------------------------------------------------------
# SuperAdmin login
# ---------------------------------------------------------------------------

@auth_bp.route("/admin-login", methods=["POST"])
def admin_login():
    """
    Body: { "email": "...", "password": "..." }
    Finds admin by email in 'admins' collection.
    Verifies password with bcrypt.
    Returns JWT with role='superadmin'.
    """
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", "")).strip()

    if not email or not password:
        return jsonify({"success": False, "message": "Email and password are required"}), 400

    db = get_db()
    if db is not None:
        admin = db.admins.find_one({"email": email})
        if admin is not None:
            password_hash = admin.get("password_hash", "")
            try:
                valid = bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
            except Exception:
                valid = False
            if valid:
                firebase_id_token = str(data.get("firebase_id_token", "")).strip()
                if firebase_id_token:
                    decoded = _verify_firebase_id_token(firebase_id_token)
                    if decoded is None:
                        return jsonify({"success": False, "message": "OTP verification failed or expired"}), 401
                    otp_phone = _normalize_phone_10digit(decoded.get("phone_number", ""))
                    on_file_phone = _normalize_phone_10digit(admin.get("phone", ""))
                    if on_file_phone and otp_phone != on_file_phone:
                        return jsonify({"success": False, "message": "OTP phone does not match the registered admin phone"}), 401
                admin_id = str(admin["_id"])
                token = _make_token({
                    "user_id": admin_id, "role": "superadmin",
                    "name": admin.get("name", email), "email": email,
                })
                return jsonify({"success": True, "message": "Login successful", "token": token,
                    "user": {"id": admin_id, "name": admin.get("name", email),
                             "email": email, "role": "superadmin"}}), 200

    # Fallback default admin (when DB unavailable or no admin found)
    if email == "admin@thooku.com" and password == "admin123":
        token = _make_token({
            "user_id": "default_admin", "role": "superadmin",
            "name": "Super Admin", "email": email,
        })
        return jsonify({"success": True, "message": "Login successful (fallback)", "token": token,
            "user": {"id": "default_admin", "name": "Super Admin",
                     "email": email, "role": "superadmin"}}), 200

    return jsonify({"success": False, "message": "Invalid credentials"}), 401


# ── Google Login ──────────────────────────────────────────────────────────────

@auth_bp.route("/google", methods=["POST"])
def google_login():
    data = request.get_json(silent=True) or {}
    id_token = data.get("credential", "")

    if not id_token:
        return jsonify({"success": False, "message": "Missing credential"}), 400

    try:
        from google.oauth2 import id_token as google_id_token
        from google.auth.transport import requests as google_requests

        GOOGLE_CLIENT_ID = data.get("client_id", "849711418902-7reguj59f9au1c48ko8boh3eaprp0rng.apps.googleusercontent.com")
        info = google_id_token.verify_oauth2_token(id_token, google_requests.Request(), GOOGLE_CLIENT_ID)

        email = info.get("email", "")
        name = info.get("name", email.split("@")[0] if email else "User")
        google_id = info.get("sub", "")

        if not email:
            return jsonify({"success": False, "message": "Email not available from Google"}), 400

        db = get_db()
        user = None
        if db is not None:
            user = db.customers.find_one({"google_id": google_id}) or db.customers.find_one({"email": email})

        if not user:
            user_doc = {
                "google_id": google_id,
                "email": email,
                "name": name,
                "phone": data.get("phone", ""),
                "role": "customer",
                "created_at": int(time.time()),
            }
            if db is not None:
                db.customers.insert_one(user_doc)
            user = user_doc

        token = _make_token({
            "id": str(user.get("_id", "")),
            "google_id": google_id,
            "email": email,
            "phone": user.get("phone", ""),
            "name": name,
            "role": "customer",
        })

        return jsonify({
            "success": True,
            "message": "Google login successful",
            "data": {
                "token": token,
                "user": {
                    "name": name,
                    "email": email,
                    "phone": user.get("phone", ""),
                    "role": "customer",
                },
            },
    }), 200
    except Exception as e:
        logger.warning(f"Google login failed: {e}")
        return jsonify({"success": False, "message": "Google login failed"}), 401


@auth_bp.route("/google-firebase", methods=["POST"])
def google_firebase_login():
    data = request.get_json(silent=True) or {}
    id_token = str(data.get("id_token", "")).strip()
    if not id_token:
        return jsonify({"success": False, "message": "Missing id_token"}), 400

    decoded = _verify_firebase_id_token(id_token)
    if decoded is None:
        return jsonify({"success": False, "message": "Invalid token"}), 401

    email = decoded.get("email", "")
    name = decoded.get("name", email.split("@")[0] if email else "User")
    firebase_uid = decoded.get("uid", "")
    provider = decoded.get("firebase", {}).get("sign_in_provider", "google.com")

    if not email:
        return jsonify({"success": False, "message": "Email not available"}), 400

    db = get_db()
    user = None
    if db is not None:
        user = db.customers.find_one({"email": email}) or db.customers.find_one({"firebase_uid": firebase_uid})

    if not user:
        user_doc = {
            "firebase_uid": firebase_uid,
            "email": email,
            "name": name,
            "phone": "",
            "role": "customer",
            "provider": provider,
            "created_at": int(time.time()),
        }
        if db is not None:
            result = db.customers.insert_one(user_doc)
            user_doc["_id"] = result.inserted_id
        user = user_doc

    token = _make_token({
        "id": str(user.get("_id", "")),
        "email": email,
        "firebase_uid": firebase_uid,
        "name": user.get("name", name),
        "role": "customer",
    })

    return jsonify({
        "success": True,
        "message": "Login successful",
        "data": {
            "token": token,
            "user": {
                "name": user.get("name", name),
                "email": email,
                "phone": user.get("phone", ""),
                "role": "customer",
            },
        },
    }), 200


@auth_bp.route("/save-phone", methods=["POST"])
def save_phone():
    auth_hdr = request.headers.get("Authorization", "")
    if not auth_hdr.startswith("Bearer "):
        return jsonify({"success": False, "message": "Unauthorized"}), 401
    try:
        payload = jwt.decode(auth_hdr.split(" ", 1)[1], JWT_SECRET, algorithms=["HS256"])
    except Exception:
        return jsonify({"success": False, "message": "Invalid token"}), 401
    data = request.get_json(silent=True) or {}
    phone = str(data.get("phone", "")).strip()
    if not phone or not phone.isdigit() or len(phone) != 10:
        return jsonify({"success": False, "message": "Valid 10-digit phone number required"}), 400
    db = get_db()
    if db is None:
        return jsonify({"success": False, "message": "Database unavailable"}), 503
    email = payload.get("email", "")
    google_id = payload.get("google_id", "")
    if email:
        db.customers.update_one({"email": email}, {"$set": {"phone": phone}})
    elif google_id:
        db.customers.update_one({"google_id": google_id}, {"$set": {"phone": phone}})
    return jsonify({"success": True, "message": "Phone saved", "data": {"phone": phone}}), 200


# ---------------------------------------------------------------------------
# Firebase Phone Auth (OTP) — primary login for customers, optional 2FA layer
# for restaurant/rider/admin logins.
#
# Setup: put your Firebase service account JSON somewhere on the server and
# set FIREBASE_SERVICE_ACCOUNT_PATH to its path (never commit this file).
# The frontend does the actual OTP send/verify via the Firebase JS SDK and
# only ever sends us the resulting Firebase ID token — we never see the OTP
# itself, and never touch a third-party SMS gateway.
# ---------------------------------------------------------------------------

_firebase_app = None


def _get_firebase_app():
    """Lazily initialize the Firebase Admin SDK app (singleton)."""
    global _firebase_app
    if _firebase_app is not None:
        return _firebase_app
    try:
        import firebase_admin
        from firebase_admin import credentials

        service_account_path = os.environ.get("FIREBASE_SERVICE_ACCOUNT_PATH", "")
        service_account_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON", "")

        if service_account_path and os.path.exists(service_account_path):
            cred = credentials.Certificate(service_account_path)
        elif service_account_json:
            import json as _json
            cred = credentials.Certificate(_json.loads(service_account_json))
        else:
            logger.warning("Firebase service account not configured (set FIREBASE_SERVICE_ACCOUNT_PATH)")
            return None

        _firebase_app = firebase_admin.initialize_app(cred)
        return _firebase_app
    except Exception as exc:
        logger.error("Firebase Admin SDK init failed: %s", exc)
        return None


def _verify_firebase_id_token(id_token: str):
    """
    Verify a Firebase ID token from the client's Firebase Phone Auth sign-in.
    Returns the decoded token dict (contains 'phone_number') on success, or
    None on any failure. Never raises — callers should treat None as "reject".
    """
    app = _get_firebase_app()
    if app is None:
        return None
    try:
        from firebase_admin import auth as firebase_auth
        return firebase_auth.verify_id_token(id_token, app=app)
    except Exception as exc:
        logger.warning("Firebase ID token verification failed: %s", exc)
        return None


def _normalize_phone_10digit(raw: str) -> str:
    """Firebase phone_number is E.164 (e.g. +919876543210) — normalize to bare 10-digit for DB lookups."""
    digits = "".join(ch for ch in str(raw) if ch.isdigit())
    return digits[-10:] if len(digits) >= 10 else digits


@auth_bp.route("/firebase-verify", methods=["POST"])
def firebase_verify():
    """
    Body: { "id_token": "<Firebase ID token from client-side Phone Auth>" }
    Verifies the token server-side, then finds-or-creates a customer by phone
    and returns our own JWT — same session model as every other login route.
    This REPLACES Google OAuth as the customer login method.
    """
    data = request.get_json(silent=True) or {}
    id_token = str(data.get("id_token", "")).strip()
    if not id_token:
        return jsonify({"success": False, "message": "Missing id_token"}), 400

    decoded = _verify_firebase_id_token(id_token)
    if decoded is None:
        return jsonify({"success": False, "message": "Invalid or expired OTP session — please verify again"}), 401

    firebase_uid = decoded.get("uid", "")
    phone_e164 = decoded.get("phone_number", "")
    phone = _normalize_phone_10digit(phone_e164)
    if not phone or len(phone) != 10:
        return jsonify({"success": False, "message": "No verified phone number on this session"}), 400

    db = get_db()
    user = None
    if db is not None:
        user = db.customers.find_one({"phone": phone}) or db.customers.find_one({"firebase_uid": firebase_uid})

    name = data.get("name", "")
    if not user:
        user_doc = {
            "firebase_uid": firebase_uid,
            "phone": phone,
            "name": name or f"Customer {phone[-4:]}",
            "role": "customer",
            "created_at": int(time.time()),
        }
        if db is not None:
            result = db.customers.insert_one(user_doc)
            user_doc["_id"] = result.inserted_id
        user = user_doc
    elif db is not None and not user.get("firebase_uid"):
        db.customers.update_one({"_id": user["_id"]}, {"$set": {"firebase_uid": firebase_uid}})

    token = _make_token({
        "id": str(user.get("_id", "")),
        "phone": phone,
        "firebase_uid": firebase_uid,
        "name": user.get("name", name),
        "role": "customer",
    })

    return jsonify({
        "success": True,
        "message": "Login successful",
        "data": {
            "token": token,
            "user": {
                "name": user.get("name", name),
                "phone": phone,
                "role": "customer",
            },
        },
    }), 200
