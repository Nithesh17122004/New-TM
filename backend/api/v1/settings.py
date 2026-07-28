# -*- coding: utf-8 -*-
"""Public platform settings (fees, support contact)."""

from flask import Blueprint, jsonify, current_app

from services.platform_settings import get_platform_settings

settings_bp = Blueprint("settings", __name__)


def get_db():
    return current_app.extensions.get("mongo_db")


@settings_bp.route("/platform", methods=["GET"])
def get_public_platform_settings():
    """Return fee settings for checkout — no auth required."""
    settings = get_platform_settings(get_db())
    return jsonify({"success": True, "data": settings}), 200


@settings_bp.route("/ice-config", methods=["GET"])
def get_ice_config():
    """
    WebRTC ICE server config for in-app calling — no auth required (these are
    not secret in the way an API key is; TURN credentials are short-lived-ish
    and only useful for relaying media, not for account access).
    Always includes public Google STUN. Adds your own Coturn TURN server if
    TURN_SERVER_URL/USERNAME/CREDENTIAL are set — this is what keeps calling
    working when both parties are behind restrictive NATs (e.g. mobile data).
    """
    import os
    ice_servers = [
        {"urls": ["stun:stun.l.google.com:19302", "stun:stun1.l.google.com:19302"]}
    ]
    turn_url = os.environ.get("TURN_SERVER_URL", "")
    turn_user = os.environ.get("TURN_SERVER_USERNAME", "")
    turn_cred = os.environ.get("TURN_SERVER_CREDENTIAL", "")
    if turn_url and turn_user and turn_cred:
        ice_servers.append({
            "urls": [turn_url],
            "username": turn_user,
            "credential": turn_cred,
        })
    return jsonify({"success": True, "data": {"iceServers": ice_servers}}), 200
