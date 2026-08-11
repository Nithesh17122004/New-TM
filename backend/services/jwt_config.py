# -*- coding: utf-8 -*-
"""
Single source of truth for JWT_SECRET.

Previously, ~10 files each independently did:
    JWT_SECRET = os.environ.get("JWT_SECRET", "thooku-madurai-secret-key-2026")

That hardcoded fallback string is public (it's been in this codebase's
history), so if the JWT_SECRET environment variable is ever unset on your
server, every file would silently fall back to a secret anyone could guess
from the source code — letting them forge valid login tokens for any user,
including admin.

This module fixes that by failing loudly and immediately at startup if
JWT_SECRET isn't set, instead of silently running with a compromised secret.
Every file that needs the JWT secret should import it from here:

    from services.jwt_config import JWT_SECRET
"""
import os

JWT_SECRET = os.environ.get("JWT_SECRET", "")

if not JWT_SECRET:
    raise RuntimeError(
        "JWT_SECRET environment variable is not set. Refusing to start with "
        "a guessable default secret — set JWT_SECRET in your environment "
        "(e.g. Render dashboard -> Environment) before deploying. "
        "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
    )
