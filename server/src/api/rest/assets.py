"""Asset upload endpoint for REST API."""

import base64
import hashlib
import struct

from aiohttp import web

from ...db.models.asset import Asset
from ...db.models.asset_entry import AssetEntry
from ...storage import get_storage
from .helpers import error, ok, require_role


def _read_image_dimensions(data: bytes) -> tuple[int, int] | None:
    """Read width/height from PNG or JPEG header. Returns (width, height) or None."""
    if data[:8] == b'\x89PNG\r\n\x1a\n' and len(data) >= 24:
        w, h = struct.unpack('>II', data[16:24])
        return w, h
    if data[:2] == b'\xff\xd8':
        i = 2
        while i < len(data) - 1:
            if data[i] != 0xFF:
                break
            marker = data[i + 1]
            if marker == 0xC0 or marker == 0xC2:
                if i + 9 < len(data):
                    h, w = struct.unpack('>HH', data[i + 5:i + 9])
                    return w, h
                break
            if marker in (0xD0, 0xD1, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7, 0xD8, 0xD9, 0x01):
                i += 2
            else:
                if i + 3 < len(data):
                    seg_len = struct.unpack('>H', data[i + 2:i + 4])[0]
                    i += 2 + seg_len
                else:
                    break
    return None


@require_role("dm")
async def upload_asset(request: web.Request) -> web.Response:
    """POST /api/v1/assets — Upload an image asset."""
    api_key = request["api_key"]
    user = api_key.user

    try:
        data = await request.json()
    except Exception:
        return error("Invalid JSON", code="VALIDATION_ERROR", status=400)

    name = data.get("name")
    content_b64 = data.get("content_base64")

    if not name or not content_b64:
        return error("Missing required fields: name, content_base64", code="VALIDATION_ERROR", status=400)

    try:
        file_bytes = base64.b64decode(content_b64)
    except Exception:
        return error("Invalid base64 content", code="VALIDATION_ERROR", status=400)

    if len(file_bytes) == 0:
        return error("Empty file content", code="VALIDATION_ERROR", status=400)

    extension = name.rsplit(".", 1)[-1] if "." in name else None

    hashname = hashlib.sha1(file_bytes).hexdigest()

    storage = get_storage()
    if not await storage.exists(hashname):
        await storage.store(hashname, file_bytes)

    asset, created = Asset.get_or_create(
        file_hash=hashname,
        kind="regular",
        defaults={"extension": extension, "file_size": len(file_bytes)},
    )
    if created:
        await asset.generate_thumbnails()

    root = AssetEntry.get_root_folder(user)

    entry = AssetEntry.create(
        name=name,
        asset=asset,
        owner=user,
        parent=root.id,
    )

    result = {
        "asset_id": asset.id,
        "asset_hash": asset.file_hash,
        "entry_id": entry.id,
    }

    dims = _read_image_dimensions(file_bytes)
    if dims:
        result["width_px"] = dims[0]
        result["height_px"] = dims[1]

    return ok(result, status=201)
