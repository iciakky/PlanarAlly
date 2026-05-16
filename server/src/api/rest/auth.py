"""
API Key Management Endpoints

Implements:
- POST /api/v1/auth/keys - Generate new API key
- GET /api/v1/auth/keys - List active API keys
- DELETE /api/v1/auth/keys/{id} - Revoke API key
"""

import secrets
import uuid
from datetime import datetime, timezone
from aiohttp import web

from ...db.models.rest_ext.api_key import ApiKey
from ...db.models.user import User
from .helpers import ok, error, require_role, serialize_datetime


async def create_api_key(request: web.Request) -> web.Response:
    """
    POST /api/v1/auth/keys

    Generate a new API key for a PA user.

    Body:
        {
            "username": "testdm",      // PA username
            "password": "test123",     // PA password (optional, for credential auth)
            "role": "dm"               // "dm" or "player"
        }

    Returns:
        {
            "key": "dm-xxxxxxxxxxxxxxxx",
            "user_id": "uuid",
            "role": "dm",
            "created_at": "2026-02-10T12:00:00Z"
        }

    Authentication modes (in order):
        1. Credential-based: If username+password provided, verify credentials
        2. Bootstrap: If no API keys exist, allow first key creation without auth
        3. API key auth: Otherwise, require existing DM API key
    """
    try:
        data = await request.json()
    except Exception:
        return error("Invalid JSON", code="VALIDATION_ERROR", status=400)

    # Accept both "user" and "username" for backwards compatibility
    username = data.get("username") or data.get("user")
    password = data.get("password")
    role = data.get("role", "dm").lower()

    if not username:
        return error("Missing required field: username", code="VALIDATION_ERROR", status=400)

    if role not in ("dm", "player"):
        return error("Invalid role. Must be 'dm' or 'player'", code="VALIDATION_ERROR", status=400)

    # Find PA user
    try:
        user = User.get(User.name == username)
    except User.DoesNotExist:
        return error(f"User not found: {username}", code="NOT_FOUND", status=404)

    # Authentication logic (in priority order)
    authenticated = False

    # Mode 1: Credential-based authentication
    if password:
        if user.check_password(password):
            authenticated = True
        else:
            return error("Invalid password", code="UNAUTHORIZED", status=401)

    # Mode 2: Bootstrap scenario (first key creation)
    if not authenticated:
        existing_keys = list(ApiKey.select().limit(1))
        is_bootstrap = len(existing_keys) == 0
        if is_bootstrap:
            authenticated = True

    # Mode 3: Existing API key authentication
    if not authenticated:
        api_key = request.get("api_key")
        if not api_key or api_key.role != "dm":
            return error("Only DM keys can create new API keys", code="FORBIDDEN", status=403)
        authenticated = True

    # At this point, one of the auth modes succeeded

    # Generate API key
    # Format: "{role}-{16_random_hex_chars}"
    random_hex = secrets.token_hex(16)  # 32 characters
    key_value = f"{role}-{random_hex}"

    # Create ApiKey record
    new_key = ApiKey.create(
        uuid=str(uuid.uuid4()),
        user=user,
        role=role,
        key=key_value,
        created_at=datetime.now(timezone.utc)
    )

    return ok({
        "id": new_key.uuid,
        "key": new_key.key,
        "user_id": str(user.id),
        "username": user.name,
        "role": new_key.role,
        "created_at": serialize_datetime(new_key.created_at)
    }, status=201)


@require_role("dm")
async def list_api_keys(request: web.Request) -> web.Response:
    """
    GET /api/v1/auth/keys

    List all active API keys (DM only).

    Returns:
        {
            "keys": [
                {
                    "id": "uuid",
                    "user_id": "uuid",
                    "username": "admin",
                    "role": "dm",
                    "created_at": "2026-02-10T12:00:00Z"
                },
                ...
            ]
        }

    Note: Does NOT return the actual key value for security.
    """
    keys = ApiKey.select().order_by(ApiKey.created_at.desc())

    result = []
    for key in keys:
        result.append({
            "id": key.uuid,
            "user_id": str(key.user.id),
            "username": key.user.name,
            "role": key.role,
            "created_at": serialize_datetime(key.created_at)
        })

    return ok({"keys": result})


@require_role("dm")
async def revoke_api_key(request: web.Request) -> web.Response:
    """
    DELETE /api/v1/auth/keys/{id}

    Revoke an API key (DM only).

    Returns:
        {
            "message": "API key revoked",
            "id": "uuid"
        }
    """
    key_id = request.match_info.get("id")

    if not key_id:
        return error("Missing key ID", code="VALIDATION_ERROR", status=400)

    # Find and delete the key
    try:
        api_key = ApiKey.get(ApiKey.uuid == key_id)
        api_key.delete_instance()

        return ok({
            "message": "API key revoked",
            "id": key_id
        })
    except ApiKey.DoesNotExist:
        return error(f"API key not found: {key_id}", code="NOT_FOUND", status=404)
