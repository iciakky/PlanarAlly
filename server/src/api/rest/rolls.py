"""
REST API endpoints for dice rolling system.

Supports:
- Execute rolls with full dice notation (via DiceParser)
- Roll history with filtering
- Secret rolls (DM only)
- Integration with combat and actions
"""

import json
import uuid
from datetime import datetime
from typing import Any

from aiohttp import web

from ...db.db import db
from ...db.models.rest_ext.roll_log import RollLog
from ...db.models.location import Location
from ...db.models.rest_ext.combat_ext import CombatExt
from ...db.models.rest_ext.action_declaration import ActionDeclaration
from ...db.models.shape import Shape
from .helpers import ok, error, require_role, log_event, serialize_datetime
from .dice import parse_and_roll, DiceParseError


@require_role("dm", "player")
async def create_roll(request: web.Request) -> web.Response:
    """
    POST /api/v1/rolls - Execute a dice roll

    Request body:
    {
        "notation": "1d20+5",
        "advantage": false,  // optional, converts to 2d20kh1
        "disadvantage": false,  // optional, converts to 2d20kl1
        "modifiers": [2, -1],  // optional, additional modifiers beyond notation
        "scene_id": 123,  // optional, for event logging only (not stored on roll)
        "actor_id": "uuid",  // optional, token that rolled
        "combat_id": "uuid",  // optional, combat context
        "action_id": "uuid",  // optional, action context
        "secret": false,  // optional, DM-only roll (default: false)
        "note": "Attack roll"  // optional, for event logging only (not stored on roll)
    }

    Response:
    {
        "success": true,
        "data": {
            "uuid": "roll-uuid",
            "notation": "1d20+5",
            "result": {...},  // Full parse_and_roll result
            "total": 23,
            "secret": false,
            "actor_id": "uuid",
            "combat_id": "uuid",
            "action_id": "uuid",
            "rolled_at": "2024-01-01T12:00:00Z"
        }
    }
    """
    api_key = request.get("api_key")
    if not api_key:
        return error("Unauthorized", code="UNAUTHORIZED", status=401)

    try:
        body = await request.json()
    except Exception:
        return error("Invalid JSON body", code="VALIDATION_ERROR", status=400)

    notation = body.get("notation", "").strip()
    if not notation:
        return error("Missing required field: notation", code="VALIDATION_ERROR", status=400)

    advantage = body.get("advantage", False)
    disadvantage = body.get("disadvantage", False)
    additional_modifiers = body.get("modifiers", [])
    scene_id = body.get("scene_id")
    actor_id = body.get("actor_id")
    combat_id = body.get("combat_id")
    action_id = body.get("action_id")
    secret = body.get("secret", False)
    note = body.get("note", "")

    # Validate advantage/disadvantage mutual exclusivity
    if advantage and disadvantage:
        return error("Cannot have both advantage and disadvantage", code="VALIDATION_ERROR", status=400)

    # Validate secret rolls (only DM can make secret rolls)
    if secret and api_key.role != "dm":
        return error("Only DM can make secret rolls", code="FORBIDDEN", status=403)

    # Validate scene exists if provided
    if scene_id:
        location = Location.get_or_none(Location.id == scene_id)
        if not location:
            return error(f"Scene {scene_id} not found", code="NOT_FOUND", status=404)

    # Validate actor exists if provided (and store for later use)
    roller = None
    if actor_id:
        roller = Shape.get_or_none(Shape.uuid == actor_id)
        if not roller:
            return error(f"Actor {actor_id} not found", code="NOT_FOUND", status=404)

    # Validate combat exists if provided (and store for later use)
    combat = None
    if combat_id:
        combat = CombatExt.get_or_none(CombatExt.uuid == combat_id)
        if not combat:
            return error(f"Combat {combat_id} not found", code="NOT_FOUND", status=404)

    # Validate action exists if provided (and store for later use)
    action = None
    if action_id:
        action = ActionDeclaration.get_or_none(ActionDeclaration.uuid == action_id)
        if not action:
            return error(f"Action {action_id} not found", code="NOT_FOUND", status=404)

    # Transform notation for advantage/disadvantage
    if advantage:
        # Replace first d20 with 2d20kh1
        if "d20" in notation:
            notation = notation.replace("d20", "2d20kh1", 1)
        else:
            # If no d20, prepend advantage notation
            notation = f"2d20kh1+{notation}" if notation else "2d20kh1"
    elif disadvantage:
        # Replace first d20 with 2d20kl1
        if "d20" in notation:
            notation = notation.replace("d20", "2d20kl1", 1)
        else:
            # If no d20, prepend disadvantage notation
            notation = f"2d20kl1+{notation}" if notation else "2d20kl1"

    # Add additional modifiers to notation
    for modifier in additional_modifiers:
        if modifier >= 0:
            notation += f"+{modifier}"
        else:
            notation += f"{modifier}"

    # Parse and execute roll
    try:
        result = parse_and_roll(notation)
    except DiceParseError as e:
        return error(f"Invalid dice notation: {str(e)}", code="VALIDATION_ERROR", status=400)

    # Store roll in database
    roll_log = RollLog.create(
        uuid=str(uuid.uuid4()),
        dice_notation=notation,
        result=json.dumps(result),
        total=result["total"],
        roller=roller,
        combat=combat,
        action=action,
        secret=secret,
        rolled_at=datetime.utcnow(),
    )

    # Log event (only non-secret rolls get logged)
    if not secret:
        await log_event(
            event_type="roll_created",
            payload={
                "roll_id": roll_log.uuid,
                "notation": notation,
                "total": result["total"],
                "note": note,
            },
            scene_id=scene_id,
            actor_id=actor_id,
        )

    return ok({
        "uuid": roll_log.uuid,
        "notation": notation,
        "result": result,
        "total": result["total"],
        "secret": secret,
        "actor_id": actor_id,
        "combat_id": combat_id,
        "action_id": action_id,
        "rolled_at": serialize_datetime(roll_log.rolled_at),
    }, status=201)


@require_role("dm", "player")
async def get_roll(request: web.Request) -> web.Response:
    """
    GET /api/v1/rolls/{uuid} - Get a single roll result

    Response:
    {
        "success": true,
        "data": {
            "uuid": "roll-uuid",
            "notation": "1d20+5",
            "result": {...},
            "total": 23,
            "secret": false,
            "actor_id": "uuid",
            "combat_id": "uuid",
            "action_id": "uuid",
            "rolled_at": "2024-01-01T12:00:00Z"
        }
    }
    """
    api_key = request.get("api_key")
    if not api_key:
        return error("Unauthorized", code="UNAUTHORIZED", status=401)

    roll_uuid = request.match_info.get("uuid")
    if not roll_uuid:
        return error("Missing roll UUID", code="VALIDATION_ERROR", status=400)

    roll = RollLog.get_or_none(RollLog.uuid == roll_uuid)
    if not roll:
        return error(f"Roll {roll_uuid} not found", code="NOT_FOUND", status=404)

    # Players cannot see secret rolls
    if roll.secret and api_key.role != "dm":
        return error("Roll not found", code="NOT_FOUND", status=404)

    return ok({
        "uuid": roll.uuid,
        "notation": roll.dice_notation,
        "result": roll.get_result(),
        "total": roll.total,
        "secret": roll.secret,
        "actor_id": roll.roller.uuid if roll.roller else None,
        "combat_id": roll.combat.uuid if roll.combat else None,
        "action_id": roll.action.uuid if roll.action else None,
        "rolled_at": serialize_datetime(roll.rolled_at),
    })


@require_role("dm", "player")
async def list_rolls(request: web.Request) -> web.Response:
    """
    GET /api/v1/rolls - Query roll history

    Query parameters:
    - actor_id: Filter by actor (token UUID)
    - combat_id: Filter by combat (combat UUID)
    - action_id: Filter by action (action UUID)
    - limit: Max results (default: 50, max: 200)
    - offset: Pagination offset (default: 0)
    - include_secret: Include secret rolls (DM only, default: false)

    Response:
    {
        "success": true,
        "data": {
            "rolls": [
                {
                    "uuid": "roll-uuid",
                    "notation": "1d20+5",
                    "total": 23,
                    "secret": false,
                    "actor_id": "uuid",
                    "combat_id": "uuid",
                    "action_id": "uuid",
                    "rolled_at": "2024-01-01T12:00:00Z"
                },
                ...
            ],
            "total_count": 100,
            "limit": 50,
            "offset": 0,
            "has_more": true
        }
    }
    """
    api_key = request.get("api_key")
    if not api_key:
        return error("Unauthorized", code="UNAUTHORIZED", status=401)

    # Parse query parameters
    actor_id = request.rel_url.query.get("actor_id")
    combat_id = request.rel_url.query.get("combat_id")
    action_id = request.rel_url.query.get("action_id")
    include_secret = request.rel_url.query.get("include_secret", "false").lower() == "true"

    try:
        limit = min(int(request.rel_url.query.get("limit", "50")), 200)
        offset = int(request.rel_url.query.get("offset", "0"))
    except ValueError:
        return error("Invalid limit or offset", code="VALIDATION_ERROR", status=400)

    # Build query
    query = RollLog.select()

    # Filter by actor (roller FK)
    if actor_id:
        actor = Shape.get_or_none(Shape.uuid == actor_id)
        if actor is None:
            return ok({"rolls": [], "total_count": 0, "limit": limit, "offset": offset, "has_more": False})
        query = query.where(RollLog.roller == actor)

    # Filter by combat (combat FK)
    if combat_id:
        combat = CombatExt.get_or_none(CombatExt.uuid == combat_id)
        if combat is None:
            return ok({"rolls": [], "total_count": 0, "limit": limit, "offset": offset, "has_more": False})
        query = query.where(RollLog.combat == combat)

    # Filter by action (action FK)
    if action_id:
        action = ActionDeclaration.get_or_none(ActionDeclaration.uuid == action_id)
        if action is None:
            return ok({"rolls": [], "total_count": 0, "limit": limit, "offset": offset, "has_more": False})
        query = query.where(RollLog.action == action)

    # Players cannot see secret rolls unless DM explicitly includes them
    if not include_secret or api_key.role != "dm":
        query = query.where(RollLog.secret == False)

    # Order by rolled_at descending (newest first)
    query = query.order_by(RollLog.rolled_at.desc())

    # Get total count
    total_count = query.count()

    # Apply pagination
    rolls = list(query.limit(limit).offset(offset))

    return ok({
        "rolls": [
            {
                "uuid": roll.uuid,
                "notation": roll.dice_notation,
                "total": roll.total,
                "secret": roll.secret,
                "actor_id": roll.roller.uuid if roll.roller else None,
                "combat_id": roll.combat.uuid if roll.combat else None,
                "action_id": roll.action.uuid if roll.action else None,
                "rolled_at": serialize_datetime(roll.rolled_at),
            }
            for roll in rolls
        ],
        "total_count": total_count,
        "limit": limit,
        "offset": offset,
        "has_more": (offset + len(rolls)) < total_count,
    })
