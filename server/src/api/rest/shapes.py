"""Generic shape creation, upsert, and query endpoints.

Supports all shape types needed for battle maps: circulartoken, line, polygon, rect.
Walls, doors, and light blockers are created by combining shape types with flags
like vision_obstruction, is_door, etc.
"""

import json
from typing import Any
from uuid import uuid4

from .revision import next_revision, broadcast_revision

from aiohttp import web
from peewee import DoesNotExist

from ...db.db import db
from ...db.models.floor import Floor
from ...db.models.layer import Layer
from ...db.models.location import Location
from ...db.models.player_room import PlayerRoom
from ...db.models.rest_ext.shape_external_id import ShapeExternalId
from ...db.models.shape import Shape
from ...db.utils import get_table
from ...models.role import Role
from ...state.game import game_state
from ...transform.to_api.shape import transform_shape
from ..common.shapes import create_shape
from ..helpers import _send_game
from ..models.shape import ApiCircularTokenShape
from ..models.shape.subtypes import ApiAssetRectShape, ApiLineShape, ApiPolygonShape, ApiRectShape
from ..models.shape.owner import ApiShapeOwner
from .helpers import error, log_event, ok, require_role

SUPPORTED_TYPES = {"assetrect", "circulartoken", "line", "polygon", "rect"}

CORE_DEFAULTS = dict(
    name="",
    name_visible=True,
    fill_colour="rgba(255, 255, 255, 1)",
    stroke_colour="rgba(0, 0, 0, 1)",
    stroke_width=2,
    vision_obstruction=0,
    movement_obstruction=False,
    draw_operator="source-over",
    options="[]",
    badge=1,
    show_badge=False,
    default_edit_access=False,
    default_vision_access=False,
    default_movement_access=False,
    is_invisible=False,
    is_defeated=False,
    is_locked=False,
    angle=0.0,
    variants=None,
    group=None,
    ignore_zoom_size=False,
    is_door=False,
    is_teleport_zone=False,
    custom_data=[],
    character=None,
    odd_hex_orientation=False,
    size_x=1,
    size_y=1,
    show_cells=False,
    cell_fill_colour=None,
    cell_stroke_colour=None,
    cell_stroke_width=None,
    notes=[],
)


def _build_core_kwargs(data: dict, shape_uuid: str, owner_name: str) -> dict:
    """Extract core shape fields from request data, applying defaults."""
    kwargs = {"uuid": shape_uuid, "type_": data["type"]}
    kwargs["x"] = float(data["x"])
    kwargs["y"] = float(data["y"])

    for field, default in CORE_DEFAULTS.items():
        if field in data:
            kwargs[field] = data[field]
        else:
            kwargs[field] = default

    if "options" in data and isinstance(data["options"], dict):
        kwargs["options"] = json.dumps(list(data["options"].items()))

    kwargs["owners"] = [
        ApiShapeOwner(
            shape=shape_uuid,
            user=owner_name,
            edit_access=True,
            movement_access=True,
            vision_access=True,
        )
    ]
    kwargs["trackers"] = []
    kwargs["auras"] = []

    return kwargs


def _get_asset_dimensions(file_hash: str):
    """Read image dimensions from stored asset. Returns (w, h) or None."""
    from .assets import _read_image_dimensions
    from ...storage import get_storage
    storage = get_storage()
    file_bytes = storage.retrieve_sync(file_hash)
    if file_bytes:
        return _read_image_dimensions(file_bytes)
    return None


def _check_aspect_ratio(width: float, height: float, img_dims, strict: bool) -> str | None:
    """Check aspect ratio. Returns warning string or None."""
    if not img_dims or img_dims[0] <= 0 or img_dims[1] <= 0 or height <= 0:
        return None
    img_ratio = img_dims[0] / img_dims[1]
    req_ratio = width / height
    if abs(img_ratio - req_ratio) / img_ratio > 0.01:
        return (
            f"Aspect ratio mismatch: image is {img_dims[0]}x{img_dims[1]} "
            f"({img_ratio:.4f}), requested {int(width)}x{int(height)} "
            f"({req_ratio:.4f}). Difference exceeds 1%."
        )
    return None


def _build_api_shape(data: dict, shape_uuid: str, owner_name: str):
    """Build the appropriate ApiShape subtype from request data."""
    shape_type = data["type"]
    core = _build_core_kwargs(data, shape_uuid, owner_name)

    if shape_type == "assetrect":
        asset_id = data.get("assetId")
        asset_hash = data.get("assetHash")
        if asset_id is None or asset_hash is None:
            return None, "Missing required fields for assetrect: assetId, assetHash"
        from ...db.models.asset import Asset
        asset = Asset.get_or_none(Asset.id == asset_id)
        if asset is None or asset.file_hash != asset_hash:
            return None, "Asset not found or assetHash does not match assetId"

        width = data.get("width")
        height = data.get("height")

        img_dims = _get_asset_dimensions(asset.file_hash)

        if width is None or height is None:
            if img_dims:
                width = width if width is not None else img_dims[0]
                height = height if height is not None else img_dims[1]
            else:
                return None, "Missing width/height and could not detect from asset image"

        aspect_warning = _check_aspect_ratio(
            float(width), float(height), img_dims, data.get("strict_aspect_ratio", False),
        )
        if isinstance(aspect_warning, str) and data.get("strict_aspect_ratio"):
            return None, aspect_warning

        shape = ApiAssetRectShape(
            **core,
            width=float(width),
            height=float(height),
            assetId=int(asset_id),
            assetHash=str(asset_hash),
        )
        shape._aspect_ratio_warning = aspect_warning if isinstance(aspect_warning, str) else None
        return shape, None

    elif shape_type == "circulartoken":
        radius = data.get("radius")
        if radius is None:
            return None, "Missing required field for circulartoken: radius"
        return ApiCircularTokenShape(
            **core,
            radius=float(radius),
            viewing_angle=data.get("viewing_angle"),
            text=data.get("text", core.get("name", "")[:2].upper() or "??"),
            font=data.get("font", "serif"),
        ), None

    elif shape_type == "line":
        x2 = data.get("x2")
        y2 = data.get("y2")
        if x2 is None or y2 is None:
            return None, "Missing required fields for line: x2, y2"
        return ApiLineShape(
            **core,
            x2=float(x2),
            y2=float(y2),
            line_width=data.get("line_width", 2),
        ), None

    elif shape_type == "polygon":
        vertices = data.get("vertices")
        if vertices is None:
            return None, "Missing required field for polygon: vertices"
        if isinstance(vertices, list):
            vertices = json.dumps(vertices)
        return ApiPolygonShape(
            **core,
            vertices=vertices,
            line_width=data.get("line_width", 0),
            open_polygon=data.get("open_polygon", False),
        ), None

    elif shape_type == "rect":
        width = data.get("width")
        height = data.get("height")
        if width is None or height is None:
            return None, "Missing required fields for rect: width, height"
        return ApiRectShape(
            **core,
            width=float(width),
            height=float(height),
        ), None

    return None, f"Unsupported shape type: {shape_type}"


def _get_layer(location: Location, layer_name: str, floor_name: str | None = None) -> Layer | None:
    """Find a layer by name, optionally on a specific floor."""
    if floor_name:
        floor = location.floors.where(Floor.name == floor_name).first()
        if not floor:
            return None
        return floor.layers.where(Layer.name == layer_name).first()

    for floor in location.floors:
        layer = floor.layers.where(Layer.name == layer_name).first()
        if layer:
            return layer
    return None


@require_role("dm")
async def create_shape_endpoint(request: web.Request) -> web.Response:
    """POST /api/v1/scenes/{scene_id}/shapes — Create a shape."""
    api_key = request["api_key"]

    try:
        scene_id = int(request.match_info["scene_id"])
    except (ValueError, TypeError):
        return error("Invalid scene ID", code="VALIDATION_ERROR", status=400)

    try:
        data = await request.json()
    except Exception:
        return error("Invalid JSON", code="VALIDATION_ERROR", status=400)

    shape_type = data.get("type")
    if shape_type not in SUPPORTED_TYPES:
        return error(
            f"Invalid shape type: {shape_type}. Supported: {', '.join(sorted(SUPPORTED_TYPES))}",
            code="VALIDATION_ERROR", status=400,
        )

    if "x" not in data or "y" not in data:
        return error("Missing required fields: x, y", code="VALIDATION_ERROR", status=400)

    try:
        location = Location.get_by_id(scene_id)
    except DoesNotExist:
        return error("Scene not found", code="NOT_FOUND", status=404)

    room = location.room
    if room.creator.id != api_key.user.id:
        pr = PlayerRoom.get_or_none(room=room, player=api_key.user)
        if not pr or pr.role != Role.DM:
            return error("Only DM can create shapes", code="FORBIDDEN", status=403)

    layer_name = data.get("layer", "tokens")
    floor_name = data.get("floor")
    layer = _get_layer(location, layer_name, floor_name)
    if not layer:
        return error(f"Layer not found: {layer_name}", code="NOT_FOUND", status=404)

    external_id = data.get("external_id")
    if external_id:
        existing = ShapeExternalId.get_or_none(
            ShapeExternalId.location == location,
            ShapeExternalId.external_id == external_id,
        )
        if existing:
            return error(
                f"external_id already exists in this scene: {external_id}",
                code="CONFLICT", status=409,
            )

    shape_uuid = str(uuid4())
    api_shape, err = _build_api_shape(data, shape_uuid, api_key.user.name)
    if err:
        return error(err, code="VALIDATION_ERROR", status=400)

    with db.atomic():
        shape = create_shape(api_shape, layer=layer)
        if not shape:
            return error("Failed to create shape", code="INTERNAL_ERROR", status=500)

        if external_id:
            ShapeExternalId.create(shape=shape, location=location, external_id=external_id)

    for room_player in room.players:
        is_dm = room_player.role == Role.DM
        for psid in game_state.get_sids(player=room_player.player, active_location=location):
            if not is_dm and not layer.player_visible:
                continue
            api_shape_data = transform_shape(shape, room_player)
            await _send_game(
                "Shape.Add",
                {"shape": api_shape_data, "floor": layer.floor.name, "layer": layer_name, "temporary": False},
                room=psid,
            )

    await log_event(
        event_type="shape_created",
        payload={"shape_id": shape_uuid, "type": shape_type, "external_id": external_id, "layer": layer_name},
        scene_id=location.id,
    )

    rev = next_revision()
    await broadcast_revision(rev, location.get_path())

    result = {
        "uuid": shape_uuid,
        "external_id": external_id,
        "type": shape_type,
        "revision": rev,
    }
    if hasattr(api_shape, '_aspect_ratio_warning') and api_shape._aspect_ratio_warning:
        result["aspect_ratio_warning"] = api_shape._aspect_ratio_warning

    return ok(result, status=201)


@require_role("dm")
async def upsert_shape_by_external_id(request: web.Request) -> web.Response:
    """PUT /api/v1/scenes/{scene_id}/shapes/by-external-id/{external_id} — Upsert a shape."""
    api_key = request["api_key"]

    try:
        scene_id = int(request.match_info["scene_id"])
    except (ValueError, TypeError):
        return error("Invalid scene ID", code="VALIDATION_ERROR", status=400)

    external_id = request.match_info["external_id"]

    try:
        data = await request.json()
    except Exception:
        return error("Invalid JSON", code="VALIDATION_ERROR", status=400)

    shape_type = data.get("type")
    if shape_type not in SUPPORTED_TYPES:
        return error(
            f"Invalid shape type: {shape_type}. Supported: {', '.join(sorted(SUPPORTED_TYPES))}",
            code="VALIDATION_ERROR", status=400,
        )

    try:
        location = Location.get_by_id(scene_id)
    except DoesNotExist:
        return error("Scene not found", code="NOT_FOUND", status=404)

    room = location.room
    if room.creator.id != api_key.user.id:
        pr = PlayerRoom.get_or_none(room=room, player=api_key.user)
        if not pr or pr.role != Role.DM:
            return error("Only DM can manage shapes", code="FORBIDDEN", status=403)

    existing_mapping = ShapeExternalId.get_or_none(
        ShapeExternalId.location == location,
        ShapeExternalId.external_id == external_id,
    )

    if existing_mapping:
        existing_shape = existing_mapping.shape
        if existing_shape.type_ != shape_type and not data.get("replace"):
            return error(
                f"Type mismatch: existing shape is '{existing_shape.type_}', request is '{shape_type}'. "
                f"Pass \"replace\": true to force replace.",
                code="TYPE_MISMATCH", status=409,
            )

        with db.atomic():
            if "x" in data:
                existing_shape.x = float(data["x"])
            if "y" in data:
                existing_shape.y = float(data["y"])
            if "name" in data:
                existing_shape.name = data["name"]
            if "vision_obstruction" in data:
                existing_shape.vision_obstruction = data["vision_obstruction"]
            if "movement_obstruction" in data:
                existing_shape.movement_obstruction = data["movement_obstruction"]
            if "is_door" in data:
                existing_shape.is_door = data["is_door"]
            if "is_locked" in data:
                existing_shape.is_locked = data["is_locked"]
            if "is_invisible" in data:
                existing_shape.is_invisible = data["is_invisible"]
            if "fill_colour" in data:
                existing_shape.fill_colour = data["fill_colour"]
            if "stroke_colour" in data:
                existing_shape.stroke_colour = data["stroke_colour"]
            if "stroke_width" in data:
                existing_shape.stroke_width = data["stroke_width"]
            if "name_visible" in data:
                existing_shape.name_visible = data["name_visible"]
            if "default_vision_access" in data:
                existing_shape.default_vision_access = data["default_vision_access"]
            if "default_edit_access" in data:
                existing_shape.default_edit_access = data["default_edit_access"]
            if "default_movement_access" in data:
                existing_shape.default_movement_access = data["default_movement_access"]
            existing_shape.save()

            upsert_aspect_warning = None
            subtype_table = get_table(existing_shape.type_)
            if subtype_table is not None:
                sub = subtype_table.get_or_none(subtype_table.shape == existing_shape)
                if sub is not None:
                    sub_changed = False
                    if hasattr(sub, "width") and "width" in data:
                        sub.width = float(data["width"])
                        sub_changed = True
                    if hasattr(sub, "height") and "height" in data:
                        sub.height = float(data["height"])
                        sub_changed = True
                    new_asset = None
                    if hasattr(sub, "asset_id") and "assetId" in data:
                        from ...db.models.asset import Asset
                        new_asset = Asset.get_or_none(Asset.id == int(data["assetId"]))
                        if new_asset is None or (
                            "assetHash" in data and new_asset.file_hash != data["assetHash"]
                        ):
                            return error("Asset not found or assetHash does not match assetId",
                                         code="VALIDATION_ERROR", status=400)
                        sub.asset_id = new_asset.id
                        sub_changed = True
                        if "width" not in data or "height" not in data:
                            file_hash = new_asset.file_hash
                            img_dims = _get_asset_dimensions(file_hash)
                            if img_dims:
                                if "width" not in data:
                                    sub.width = float(img_dims[0])
                                if "height" not in data:
                                    sub.height = float(img_dims[1])
                                sub_changed = True
                    if hasattr(sub, "line_width") and "line_width" in data:
                        sub.line_width = data["line_width"]
                        sub_changed = True
                    if sub_changed:
                        sub.save()

                    if hasattr(sub, "asset_id") and ("width" in data or "height" in data):
                        w = float(data.get("width", sub.width))
                        h = float(data.get("height", sub.height))
                        file_hash = new_asset.file_hash if "assetId" in data else sub.asset.file_hash
                        img_dims = _get_asset_dimensions(file_hash)
                        aspect_warning = _check_aspect_ratio(w, h, img_dims, data.get("strict_aspect_ratio", False))
                        if aspect_warning and data.get("strict_aspect_ratio"):
                            return error(aspect_warning, code="VALIDATION_ERROR", status=400)
                        upsert_aspect_warning = aspect_warning

        location = existing_mapping.location
        for room_player in room.players:
            for psid in game_state.get_sids(player=room_player.player, active_location=location):
                api_shape_data = transform_shape(existing_shape, room_player)
                await _send_game(
                    "Shape.Set",
                    {"shape": api_shape_data, "floor": existing_shape.layer.floor.name,
                     "layer": existing_shape.layer.name, "temporary": False},
                    room=psid,
                )

        rev = next_revision()
        await broadcast_revision(rev, existing_mapping.location.get_path())

        result = {
            "uuid": existing_shape.uuid,
            "external_id": external_id,
            "type": existing_shape.type_,
            "action": "updated",
            "revision": rev,
        }
        if upsert_aspect_warning:
            result["aspect_ratio_warning"] = upsert_aspect_warning

        return ok(result)

    else:
        if "x" not in data or "y" not in data:
            return error("Missing required fields for create: x, y", code="VALIDATION_ERROR", status=400)

        layer_name = data.get("layer", "tokens")
        floor_name = data.get("floor")
        layer = _get_layer(location, layer_name, floor_name)
        if not layer:
            return error(f"Layer not found: {layer_name}", code="NOT_FOUND", status=404)

        shape_uuid = str(uuid4())
        api_shape, err = _build_api_shape(data, shape_uuid, api_key.user.name)
        if err:
            return error(err, code="VALIDATION_ERROR", status=400)

        with db.atomic():
            shape = create_shape(api_shape, layer=layer)
            if not shape:
                return error("Failed to create shape", code="INTERNAL_ERROR", status=500)
            ShapeExternalId.create(shape=shape, location=location, external_id=external_id)

        for room_player in room.players:
            is_dm = room_player.role == Role.DM
            for psid in game_state.get_sids(player=room_player.player, active_location=location):
                if not is_dm and not layer.player_visible:
                    continue
                api_shape_data = transform_shape(shape, room_player)
                await _send_game(
                    "Shape.Add",
                    {"shape": api_shape_data, "floor": layer.floor.name, "layer": layer_name, "temporary": False},
                    room=psid,
                )

        rev = next_revision()
        await broadcast_revision(rev, location.get_path())

        result = {
            "uuid": shape_uuid,
            "external_id": external_id,
            "type": shape_type,
            "action": "created",
            "revision": rev,
        }
        if hasattr(api_shape, '_aspect_ratio_warning') and api_shape._aspect_ratio_warning:
            result["aspect_ratio_warning"] = api_shape._aspect_ratio_warning

        return ok(result, status=201)


@require_role("dm", "player")
async def query_shape_by_external_id(request: web.Request) -> web.Response:
    """GET /api/v1/scenes/{scene_id}/shapes?external_id=... — Query shape by external ID."""
    api_key = request["api_key"]

    try:
        scene_id = int(request.match_info["scene_id"])
    except (ValueError, TypeError):
        return error("Invalid scene ID", code="VALIDATION_ERROR", status=400)

    external_id = request.query.get("external_id")
    if not external_id:
        return error("Missing query parameter: external_id", code="VALIDATION_ERROR", status=400)

    try:
        location = Location.get_by_id(scene_id)
    except DoesNotExist:
        return error("Scene not found", code="NOT_FOUND", status=404)

    room = location.room
    if room.creator.id != api_key.user.id:
        pr = PlayerRoom.get_or_none(room=room, player=api_key.user)
        if not pr:
            return error("Access denied to this scene", code="FORBIDDEN", status=403)

    mapping = ShapeExternalId.get_or_none(
        ShapeExternalId.location == location,
        ShapeExternalId.external_id == external_id,
    )
    if not mapping:
        return error(f"Shape not found: {external_id}", code="NOT_FOUND", status=404)

    shape = mapping.shape
    result = {
        "uuid": shape.uuid,
        "external_id": external_id,
        "type": shape.type_,
        "name": shape.name,
        "x": shape.x,
        "y": shape.y,
        "is_locked": shape.is_locked,
        "default_vision_access": shape.default_vision_access,
        "default_edit_access": shape.default_edit_access,
        "default_movement_access": shape.default_movement_access,
        "layer": shape.layer.name,
        "floor": shape.layer.floor.name,
    }

    subtype_table = get_table(shape.type_)
    if subtype_table is not None:
        sub = subtype_table.get_or_none(subtype_table.shape == shape)
        if sub is not None:
            if hasattr(sub, "width"):
                result["width"] = sub.width
            if hasattr(sub, "height"):
                result["height"] = sub.height
            if hasattr(sub, "asset_id"):
                result["assetId"] = sub.asset_id
                result["assetHash"] = sub.asset.file_hash
            if hasattr(sub, "radius"):
                result["radius"] = sub.radius
            if hasattr(sub, "line_width"):
                result["line_width"] = sub.line_width

    return ok(result)
