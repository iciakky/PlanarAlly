"""
Fog of War Control Endpoints

DM CLI control over fog reveal/hide using PA's preFogShape system.
"""

import json
import uuid as uuid_lib
from typing import Any

from aiohttp import web

from ...api.common.shapes import create_shape
from ...api.helpers import _send_game
from ...transform.to_api.shape import transform_shape
from ...api.models.shape.subtypes import ApiPolygonShape, ApiRectShape
from ...db.models.layer import Layer
from ...db.models.location import Location
from ...db.models.room import Room
from ...db.models.shape import Shape
from ...state.game import game_state
from .helpers import error, log_event, ok, require_role


@require_role("dm")
async def reveal_fog(request: web.Request) -> web.Response:
    """
    POST /api/v1/scenes/{uuid}/fog/reveal

    Reveal an area of fog by creating a fog control shape.

    Request body (polygon):
    {
        "type": "polygon",
        "vertices": [[x1, y1], [x2, y2], ...],
        "layer_name": "fow"  // optional, default "fow"
    }

    Request body (rect):
    {
        "type": "rect",
        "x": 100,
        "y": 100,
        "width": 200,
        "height": 150,
        "layer_name": "fow"  // optional, default "fow"
    }

    Returns:
    {
        "success": true,
        "data": {
            "shape_id": "uuid"
        }
    }
    """
    api_key = request.get("api_key")
    try:
        scene_uuid = int(request.match_info["uuid"])
    except (ValueError, TypeError):
        return error("Invalid scene UUID", code="VALIDATION_ERROR", status=400)

    try:
        body = await request.json()
    except Exception:
        return error("Invalid JSON body", code="VALIDATION_ERROR", status=400)

    # Validate request
    shape_type = body.get("type")
    if not shape_type or shape_type not in ["polygon", "rect"]:
        return error("Invalid type. Must be 'polygon' or 'rect'", code="VALIDATION_ERROR", status=400)

    layer_name = body.get("layer_name", "fow")
    if layer_name not in ["fow", "fow-players"]:
        return error("Invalid layer_name. Must be 'fow' or 'fow-players'", code="VALIDATION_ERROR", status=400)

    # Get location (scene)
    try:
        location = Location.get_by_id(scene_uuid)
    except Location.DoesNotExist:
        return error("Scene not found", code="NOT_FOUND", status=404)

    # Verify user has access to this location
    room = location.room
    if room.creator.id != api_key.user.id:
        # Check if user is a player in the room
        if not any(rp.player.id == api_key.user.id for rp in room.players):
            return error("Access denied to this scene", code="FORBIDDEN", status=403)

    # Get the FOW layer from the first floor (assuming single floor for now)
    floors = list(location.floors)
    if not floors:
        return error("Scene has no floors", code="VALIDATION_ERROR", status=400)

    floor = floors[0]  # Use first floor

    try:
        layer = Layer.get((Layer.floor == floor) & (Layer.name == layer_name))
    except Layer.DoesNotExist:
        return error(f"Layer '{layer_name}' not found in scene", code="NOT_FOUND", status=404)

    # Generate UUID for the fog shape
    fog_shape_uuid = str(uuid_lib.uuid4())

    # Create shape based on type
    try:
        if shape_type == "polygon":
            # Validate vertices
            vertices = body.get("vertices")
            if not vertices or not isinstance(vertices, list) or len(vertices) < 3:
                return error("Polygon requires at least 3 vertices", code="VALIDATION_ERROR", status=400)

            # Validate vertex format
            for vertex in vertices:
                if not isinstance(vertex, list) or len(vertex) != 2:
                    return error("Each vertex must be [x, y]", code="VALIDATION_ERROR", status=400)

            # Create ApiPolygonShape with all required fields
            api_shape = ApiPolygonShape(
                uuid=fog_shape_uuid,
                type_="polygon",
                x=0,  # Polygon uses absolute vertices
                y=0,
                vertices=json.dumps(vertices),  # Must be JSON string
                line_width=0,
                open_polygon=False,
                name="fog_reveal",
                name_visible=False,
                fill_colour="rgba(0, 0, 0, 0)",
                stroke_colour="rgba(0, 0, 0, 0)",
                stroke_width=0,
                vision_obstruction=0,
                movement_obstruction=False,
                draw_operator="source-over",
                options=json.dumps({"preFogShape": True}),  # JSON string
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
                owners=[],
                trackers=[],
                auras=[],
            )

        elif shape_type == "rect":
            # Validate rect parameters
            x = body.get("x")
            y = body.get("y")
            width = body.get("width")
            height = body.get("height")

            if x is None or y is None or width is None or height is None:
                return error("Rectangle requires x, y, width, height", code="VALIDATION_ERROR", status=400)

            if width <= 0 or height <= 0:
                return error("Width and height must be positive", code="VALIDATION_ERROR", status=400)

            # Create ApiRectShape with all required fields
            api_shape = ApiRectShape(
                uuid=fog_shape_uuid,
                type_="rect",
                x=x,
                y=y,
                width=width,
                height=height,
                name="fog_reveal",
                name_visible=False,
                fill_colour="rgba(0, 0, 0, 0)",
                stroke_colour="rgba(0, 0, 0, 0)",
                stroke_width=0,
                vision_obstruction=0,
                movement_obstruction=False,
                draw_operator="source-over",
                options=json.dumps({"preFogShape": True}),  # JSON string
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
                owners=[],
                trackers=[],
                auras=[],
            )

        # Create the shape in the database
        fog_shape = create_shape(api_shape, layer=layer)

    except Exception as e:
        return error(f"Failed to create fog shape: {str(e)}", code="INTERNAL_ERROR", status=500)

    # Emit Shape.Add to all players in the location
    try:
        for room_player in room.players:
            for psid in game_state.get_sids(player=room_player.player, active_location=location):
                # Transform shape for this player's perspective
                api_shape_data = transform_shape(fog_shape, room_player)

                # Send Shape.Add event
                await _send_game(
                    "Shape.Add",
                    {
                        "shape": api_shape_data,
                        "floor": floor.name,
                        "layer": layer_name,
                        "temporary": False,
                    },
                    room=psid,
                )
    except Exception as e:
        # Shape created but broadcast failed - log warning but don't fail
        print(f"Warning: Failed to broadcast fog reveal: {e}")

    # Log event
    await log_event(
        event_type="fog_revealed",
        payload={
            "shape_id": fog_shape_uuid,
            "type": shape_type,
            "layer": layer_name,
        },
        scene_id=location.id,
    )

    return ok({"shape_id": fog_shape_uuid})


@require_role("dm")
async def hide_fog(request: web.Request) -> web.Response:
    """
    POST /api/v1/scenes/{uuid}/fog/hide

    Hide fog (bring back fog) by removing a fog control shape.

    Request body:
    {
        "shape_id": "uuid"
    }

    Returns:
    {
        "success": true,
        "data": {}
    }
    """
    api_key = request.get("api_key")
    try:
        scene_uuid = int(request.match_info["uuid"])
    except (ValueError, TypeError):
        return error("Invalid scene UUID", code="VALIDATION_ERROR", status=400)

    try:
        body = await request.json()
    except Exception:
        return error("Invalid JSON body", code="VALIDATION_ERROR", status=400)

    # Validate request
    shape_id = body.get("shape_id")
    if not shape_id:
        return error("Missing shape_id", code="VALIDATION_ERROR", status=400)

    # Get location (scene)
    try:
        location = Location.get_by_id(scene_uuid)
    except Location.DoesNotExist:
        return error("Scene not found", code="NOT_FOUND", status=404)

    # Verify user has access to this location
    room = location.room
    if room.creator.id != api_key.user.id:
        if not any(rp.player.id == api_key.user.id for rp in room.players):
            return error("Access denied to this scene", code="FORBIDDEN", status=403)

    # Get the fog control shape
    try:
        fog_shape = Shape.get_by_id(shape_id)
    except Shape.DoesNotExist:
        return error("Fog shape not found", code="NOT_FOUND", status=404)

    # Verify the shape belongs to this scene
    if fog_shape.layer.floor.location.id != location.id:
        return error("Fog shape does not belong to this scene", code="VALIDATION_ERROR", status=400)

    # Verify it's actually a fog control shape
    try:
        options = json.loads(fog_shape.options) if fog_shape.options else {}
    except (json.JSONDecodeError, TypeError):
        options = {}
    if not options.get("preFogShape"):
        return error("Shape is not a fog control shape", code="VALIDATION_ERROR", status=400)

    # Get layer name for broadcast
    layer_name = fog_shape.layer.name
    floor_name = fog_shape.layer.floor.name

    # Delete the shape (cascades to trackers, auras, etc.)
    fog_shape.delete_instance(recursive=True)

    # Emit Shape.Remove to all players
    try:
        for room_player in room.players:
            for psid in game_state.get_sids(player=room_player.player, active_location=location):
                await _send_game(
                    "Shapes.Remove",
                    [shape_id],
                    room=psid,
                )
    except Exception as e:
        print(f"Warning: Failed to broadcast fog hide: {e}")

    # Log event
    await log_event(
        event_type="fog_hidden",
        payload={
            "shape_id": shape_id,
            "layer": layer_name,
        },
        scene_id=location.id,
    )

    return ok({})


@require_role("dm", "player")
async def get_fog_state(request: web.Request) -> web.Response:
    """
    GET /api/v1/scenes/{uuid}/fog

    Get current fog state (list all fog control shapes).

    Query params:
    - layer_name: Filter by layer (default: all FOW layers)

    Returns:
    {
        "success": true,
        "data": {
            "fog_shapes": [
                {
                    "shape_id": "uuid",
                    "type": "polygon" | "rect",
                    "layer": "fow" | "fow-players",
                    "data": {
                        // Polygon: {"vertices": [[x, y], ...]}
                        // Rect: {"x": 100, "y": 100, "width": 200, "height": 150}
                    }
                },
                ...
            ]
        }
    }
    """
    api_key = request.get("api_key")
    try:
        scene_uuid = int(request.match_info["uuid"])
    except (ValueError, TypeError):
        return error("Invalid scene UUID", code="VALIDATION_ERROR", status=400)

    # Query params
    layer_name_filter = request.query.get("layer_name")
    if layer_name_filter and layer_name_filter not in ["fow", "fow-players"]:
        return error("Invalid layer_name. Must be 'fow' or 'fow-players'", code="VALIDATION_ERROR", status=400)

    # Get location (scene)
    try:
        location = Location.get_by_id(scene_uuid)
    except Location.DoesNotExist:
        return error("Scene not found", code="NOT_FOUND", status=404)

    # Verify user has access to this location
    room = location.room
    if room.creator.id != api_key.user.id:
        if not any(rp.player.id == api_key.user.id for rp in room.players):
            return error("Access denied to this scene", code="FORBIDDEN", status=403)

    # Query all fog control shapes in this location
    fog_shapes = []

    for floor in location.floors:
        for layer in floor.layers:
            # Filter by layer name if specified
            if layer_name_filter and layer.name != layer_name_filter:
                continue

            # Only check FOW layers
            if layer.name not in ["fow", "fow-players"]:
                continue

            # Get all shapes on this layer
            for shape in layer.shapes:
                # Check if it's a fog control shape (options stored as JSON string)
                try:
                    options = json.loads(shape.options) if shape.options else {}
                except (json.JSONDecodeError, TypeError):
                    options = {}
                if options.get("preFogShape"):
                    # Serialize shape data based on type
                    shape_data: dict[str, Any] = {}

                    if shape.type_ == "polygon":
                        # Get polygon vertices
                        from ...db.models.polygon import Polygon
                        polygon = Polygon.get_or_none(shape=shape)
                        if polygon:
                            shape_data = {
                                "vertices": polygon.vertices  # Already a list
                            }

                    elif shape.type_ == "rect":
                        # Get rect dimensions
                        from ...db.models.rect import Rect
                        rect = Rect.get_or_none(shape=shape)
                        if rect:
                            shape_data = {
                                "x": shape.x,
                                "y": shape.y,
                                "width": rect.width,
                                "height": rect.height,
                            }

                    fog_shapes.append({
                        "shape_id": shape.uuid,
                        "type": shape.type_,
                        "layer": layer.name,
                        "floor": floor.name,
                        "data": shape_data,
                    })

    return ok({"fog_shapes": fog_shapes})
