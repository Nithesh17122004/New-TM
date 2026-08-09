# -*- coding: utf-8 -*-
"""
Call recording upload + storage.

WebRTC calls are peer-to-peer, so the backend never sees the live audio —
the customer/rider app records both sides locally (mixed via Web Audio,
low bitrate since this is voice-only) and uploads the finished file here
once the call ends.

Storage: uploads to Cloudflare R2 (S3-compatible, cheap, generous free
tier) if R2_* env vars are configured. Falls back to local disk if not
configured — but note local disk on most hosts (e.g. Render's free/starter
tiers) is EPHEMERAL and wiped on every redeploy, so R2 (or another
persistent object store) should be configured before relying on this for
anything you actually need to keep.

IMPORTANT: recording a call without informing both parties has real legal
implications. The frontend already shows a "this call may be recorded"
notice during every call — do not remove that if you keep this feature.
"""
import os
import time
import uuid

from flask import Blueprint, jsonify, request

from api.v1.tracking import _require_auth  # reuse the existing JWT auth decorator

call_recordings_bp = Blueprint("call_recordings", __name__)

MAX_RECORDING_BYTES = 20 * 1024 * 1024  # 20MB safety cap per recording
LOCAL_STORAGE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "call_recordings_local")


def _r2_client():
    """Returns a configured boto3 S3-compatible client for Cloudflare R2,
    or None if R2 isn't configured (falls back to local disk)."""
    account_id = os.environ.get("R2_ACCOUNT_ID", "")
    access_key = os.environ.get("R2_ACCESS_KEY_ID", "")
    secret_key = os.environ.get("R2_SECRET_ACCESS_KEY", "")
    if not (account_id and access_key and secret_key):
        return None
    try:
        import boto3
        return boto3.client(
            "s3",
            endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="auto",
        )
    except ImportError:
        return None


@call_recordings_bp.route("/recording", methods=["POST"])
@_require_auth
def upload_call_recording():
    from flask import current_app
    db = current_app.extensions.get("mongo_db")
    if db is None:
        return jsonify({"success": False, "message": "Database unavailable"}), 503

    order_id = request.form.get("order_id", "").strip()
    role = request.form.get("role", "").strip()
    audio_file = request.files.get("audio")

    if not order_id or role not in ("customer", "rider") or audio_file is None:
        return jsonify({"success": False, "message": "order_id, role, and audio file are required"}), 400

    raw = audio_file.read()
    if not raw:
        return jsonify({"success": False, "message": "Empty recording"}), 400
    if len(raw) > MAX_RECORDING_BYTES:
        return jsonify({"success": False, "message": "Recording too large"}), 413

    filename = f"{order_id}_{role}_{int(time.time())}_{uuid.uuid4().hex[:8]}.webm"
    bucket = os.environ.get("R2_BUCKET", "call-recordings")
    storage_backend = "local"
    storage_ref = ""

    client = _r2_client()
    if client is not None:
        try:
            client.put_object(Bucket=bucket, Key=filename, Body=raw, ContentType="audio/webm")
            storage_backend = "r2"
            storage_ref = f"{bucket}/{filename}"
        except Exception as e:
            import logging
            logging.warning(f"R2 upload failed, falling back to local disk: {e}")

    if storage_backend == "local":
        os.makedirs(LOCAL_STORAGE_DIR, exist_ok=True)
        path = os.path.join(LOCAL_STORAGE_DIR, filename)
        with open(path, "wb") as f:
            f.write(raw)
        storage_ref = path

    db.call_recordings.insert_one({
        "order_id": order_id,
        "role": role,
        "uploaded_by": str(request.user.get("user_id", "")),
        "filename": filename,
        "storage_backend": storage_backend,
        "storage_ref": storage_ref,
        "size_bytes": len(raw),
        "created_at": time.time(),
    })

    return jsonify({"success": True, "data": {"filename": filename, "storage_backend": storage_backend}}), 201


@call_recordings_bp.route("/recording/<order_id>", methods=["GET"])
@_require_auth
def list_call_recordings(order_id):
    """List recordings for an order (admin/support use — e.g. dispute review)."""
    from flask import current_app
    db = current_app.extensions.get("mongo_db")
    if db is None:
        return jsonify({"success": False, "message": "Database unavailable"}), 503

    docs = list(db.call_recordings.find({"order_id": order_id}, {"storage_ref": 0}))
    for d in docs:
        d["_id"] = str(d["_id"])
    return jsonify({"success": True, "data": docs}), 200
