# -*- coding: utf-8 -*-
"""Public platform settings (fees, support contact)."""

import base64
import json
import os
import urllib.request

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
    Always includes public Google STUN. TURN servers are added from:
      1) Your own Coturn VPS via TURN_SERVER_URL/USERNAME/CREDENTIAL, or
      2) Xirsys free via XIRSYS_IDENT/XIRSYS_SECRET/XIRSYS_CHANNEL (fresh
         credentials are fetched from their REST API on every request —
         Xirsys credentials expire, so never hardcode them).
    """
    ice_servers = [
        {"urls": ["stun:stun.l.google.com:19302", "stun:stun1.l.google.com:19302"]}
    ]

    turn_url = os.environ.get("TURN_SERVER_URL", "")
    turn_user = os.environ.get("TURN_SERVER_USERNAME", "")
    turn_cred = os.environ.get("TURN_SERVER_CREDENTIAL", "")
    # Skip placeholder/default TURN values — dead servers only slow down
    # ICE and can prevent a working P2P audio path.
    placeholder = ("your-server", "your_coturn", "localhost", "example.com")
    if (turn_url and turn_user and turn_cred
            and not any(p in turn_url.lower() for p in placeholder)
            and "your_coturn" not in turn_user and "your_coturn" not in turn_cred):
        ice_servers.append({
            "urls": [turn_url],
            "username": turn_user,
            "credential": turn_cred,
        })

    xirsys_ident = os.environ.get("XIRSYS_IDENT", "")
    xirsys_secret = os.environ.get("XIRSYS_SECRET", "")
    xirsys_channel = os.environ.get("XIRSYS_CHANNEL", "")
    if xirsys_ident and xirsys_secret and xirsys_channel:
        try:
            auth = base64.b64encode(f"{xirsys_ident}:{xirsys_secret}".encode()).decode()
            req = urllib.request.Request(
                f"https://global.xirsys.net/_turn/{xirsys_channel}",
                data=b'{"format": "urls"}',
                headers={
                    "Authorization": f"Basic {auth}",
                    "Content-Type": "application/json",
                },
                method="PUT",
            )
            # Hardcoded HTTPS-only Xirsys endpoint with timeout — no
            # file:// or custom scheme is ever used here.
            with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310
                data = json.loads(resp.read().decode())
            servers = data.get("v", {}).get("iceServers") if data.get("s") == "ok" else None
            if isinstance(servers, dict):
                servers = [servers]
            for server in servers or []:
                ice_servers.append({
                    "urls": server["urls"],
                    "username": server.get("username"),
                    "credential": server.get("credential"),
                })
        except Exception:
            # TURN unreachable — keep STUN so normal NAT calls still work
            pass

    return jsonify({"success": True, "data": {"iceServers": ice_servers}}), 200
