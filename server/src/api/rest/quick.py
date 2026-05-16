"""
Quick command endpoints for common DM operations.

These endpoints provide convenience shortcuts for frequent actions during gameplay.
All endpoints require DM role and emit socket events to keep UI synchronized.
"""

from aiohttp import web
from typing import Any
from uuid import uuid4
import json

from .helpers import ok, error, require_role, log_event
from ...db.models.shape import Shape
from ...db.models.tracker import Tracker
from ...db.models.rest_ext.token_ext import TokenExt
from ...db.models.rest_ext.combat_ext import CombatExt
from ...db.models.initiative import Initiative
from ...state.game import game_state
from ...api.helpers import _send_game


# Helper function to find HP tracker
def _get_hp_tracker(shape: Shape) -> Tracker | None:
    """Get the HP tracker for a shape, if it exists."""
    for tracker in shape.trackers:
        if tracker.name == "HP":
            return tracker
    return None


@require_role("dm")
async def apply_damage(request: web.Request) -> web.Response:
    """
    POST /api/v1/quick/damage

    Apply damage to a token's HP.

    Request body:
    {
        "token_id": "uuid",
        "amount": 5,
        "note": "Goblin attack" (optional)
    }

    Response:
    {
        "success": true,
        "data": {
            "token_id": "uuid",
            "old_hp": 20,
            "new_hp": 15,
            "damage": 5
        }
    }
    """
    try:
        body = await request.json()
    except Exception:
        return error("Invalid JSON body", code="VALIDATION_ERROR", status=400)

    token_id = body.get("token_id")
    amount = body.get("amount")
    note = body.get("note", "")

    # Validate required fields
    if not token_id:
        return error("Missing required field: token_id", code="VALIDATION_ERROR", status=400)
    if amount is None:
        return error("Missing required field: amount", code="VALIDATION_ERROR", status=400)
    if not isinstance(amount, (int, float)) or amount < 0:
        return error("amount must be a non-negative number", code="VALIDATION_ERROR", status=400)
    amount = int(amount)  # Normalize to int to match IntegerField DB storage

    # Get token
    token = Shape.get_or_none(Shape.uuid == token_id)
    if not token:
        return error(f"Token not found: {token_id}", code="NOT_FOUND", status=404)

    # Ownership check
    api_key = request["api_key"]
    location = token.layer.floor.location
    room = location.room
    if room.creator.id != api_key.user.id:
        if not any(rp.player.id == api_key.user.id for rp in room.players):
            return error("Access denied to this scene", code="FORBIDDEN", status=403)

    # Get HP tracker
    hp_tracker = _get_hp_tracker(token)
    if not hp_tracker:
        return error("Token has no HP tracker", code="VALIDATION_ERROR", status=400)

    # Apply damage
    old_hp = hp_tracker.value
    new_hp = max(0, old_hp - amount)  # Can't go below 0
    hp_tracker.value = new_hp
    hp_tracker.save()

    # Get location for socket emission
    location = token.layer.floor.location

    # Emit tracker update to all players
    for psid in game_state.get_sids(active_location=location):
        await _send_game(
            "Shape.Options.Tracker.Update",
            {
                "uuid": hp_tracker.uuid,
                "shape": token_id,
                "value": new_hp,
                "maxvalue": hp_tracker.maxvalue,
            },
            room=psid,
        )

    # Log event
    await log_event(
        event_type="damage_applied",
        payload={
            "token_id": token_id,
            "token_name": token.name,
            "damage": amount,
            "old_hp": old_hp,
            "new_hp": new_hp,
            "note": note,
        },
        scene_id=location.id,
        actor_id=token_id,
    )

    return ok({
        "token_id": token_id,
        "old_hp": old_hp,
        "new_hp": new_hp,
        "damage": amount,
    })


@require_role("dm")
async def apply_heal(request: web.Request) -> web.Response:
    """
    POST /api/v1/quick/heal

    Heal a token's HP.

    Request body:
    {
        "token_id": "uuid",
        "amount": 3,
        "note": "Potion of healing" (optional)
    }

    Response:
    {
        "success": true,
        "data": {
            "token_id": "uuid",
            "old_hp": 15,
            "new_hp": 18,
            "healed": 3
        }
    }
    """
    try:
        body = await request.json()
    except Exception:
        return error("Invalid JSON body", code="VALIDATION_ERROR", status=400)

    token_id = body.get("token_id")
    amount = body.get("amount")
    note = body.get("note", "")

    # Validate required fields
    if not token_id:
        return error("Missing required field: token_id", code="VALIDATION_ERROR", status=400)
    if amount is None:
        return error("Missing required field: amount", code="VALIDATION_ERROR", status=400)
    if not isinstance(amount, (int, float)) or amount < 0:
        return error("amount must be a non-negative number", code="VALIDATION_ERROR", status=400)
    amount = int(amount)  # Normalize to int to match IntegerField DB storage

    # Get token
    token = Shape.get_or_none(Shape.uuid == token_id)
    if not token:
        return error(f"Token not found: {token_id}", code="NOT_FOUND", status=404)

    # Ownership check
    api_key = request["api_key"]
    location = token.layer.floor.location
    room = location.room
    if room.creator.id != api_key.user.id:
        if not any(rp.player.id == api_key.user.id for rp in room.players):
            return error("Access denied to this scene", code="FORBIDDEN", status=403)

    # Get HP tracker
    hp_tracker = _get_hp_tracker(token)
    if not hp_tracker:
        return error("Token has no HP tracker", code="VALIDATION_ERROR", status=400)

    # Apply healing (cap at max HP)
    old_hp = hp_tracker.value
    new_hp = min(hp_tracker.maxvalue, old_hp + amount)
    actual_healed = new_hp - old_hp
    hp_tracker.value = new_hp
    hp_tracker.save()

    # Get location for socket emission
    location = token.layer.floor.location

    # Emit tracker update to all players
    for psid in game_state.get_sids(active_location=location):
        await _send_game(
            "Shape.Options.Tracker.Update",
            {
                "uuid": hp_tracker.uuid,
                "shape": token_id,
                "value": new_hp,
                "maxvalue": hp_tracker.maxvalue,
            },
            room=psid,
        )

    # Log event
    await log_event(
        event_type="heal_applied",
        payload={
            "token_id": token_id,
            "token_name": token.name,
            "amount": amount,
            "actual_healed": actual_healed,
            "old_hp": old_hp,
            "new_hp": new_hp,
            "note": note,
        },
        scene_id=location.id,
        actor_id=token_id,
    )

    return ok({
        "token_id": token_id,
        "old_hp": old_hp,
        "new_hp": new_hp,
        "healed": actual_healed,
    })


@require_role("dm")
async def move_token(request: web.Request) -> web.Response:
    """
    POST /api/v1/quick/move

    Move a token to new coordinates.

    Request body:
    {
        "token_id": "uuid",
        "x": 500,
        "y": 600,
        "note": "Moved to flank" (optional)
    }

    Response:
    {
        "success": true,
        "data": {
            "token_id": "uuid",
            "old_position": {"x": 400, "y": 500},
            "new_position": {"x": 500, "y": 600}
        }
    }
    """
    try:
        body = await request.json()
    except Exception:
        return error("Invalid JSON body", code="VALIDATION_ERROR", status=400)

    token_id = body.get("token_id")
    x = body.get("x")
    y = body.get("y")
    note = body.get("note", "")

    # Validate required fields
    if not token_id:
        return error("Missing required field: token_id", code="VALIDATION_ERROR", status=400)
    if x is None:
        return error("Missing required field: x", code="VALIDATION_ERROR", status=400)
    if y is None:
        return error("Missing required field: y", code="VALIDATION_ERROR", status=400)
    if not isinstance(x, (int, float)):
        return error("x must be a number", code="VALIDATION_ERROR", status=400)
    if not isinstance(y, (int, float)):
        return error("y must be a number", code="VALIDATION_ERROR", status=400)

    # Get token
    token = Shape.get_or_none(Shape.uuid == token_id)
    if not token:
        return error(f"Token not found: {token_id}", code="NOT_FOUND", status=404)

    # Ownership check
    api_key = request["api_key"]
    location = token.layer.floor.location
    room = location.room
    if room.creator.id != api_key.user.id:
        if not any(rp.player.id == api_key.user.id for rp in room.players):
            return error("Access denied to this scene", code="FORBIDDEN", status=403)

    # Save old position
    old_x = token.x
    old_y = token.y

    # Update position
    token.x = x
    token.y = y
    token.save()

    # Get location for socket emission
    location = token.layer.floor.location

    # Emit position update to all players
    for psid in game_state.get_sids(active_location=location):
        await _send_game(
            "Shapes.Position.Update",
            [{"uuid": token_id, "position": {"x": x, "y": y}}],
            room=psid,
        )

    # Log event
    await log_event(
        event_type="token_moved",
        payload={
            "token_id": token_id,
            "token_name": token.name,
            "old_position": {"x": old_x, "y": old_y},
            "new_position": {"x": x, "y": y},
            "note": note,
        },
        scene_id=location.id,
        actor_id=token_id,
    )

    return ok({
        "token_id": token_id,
        "old_position": {"x": old_x, "y": old_y},
        "new_position": {"x": x, "y": y},
    })


@require_role("dm")
async def update_condition(request: web.Request) -> web.Response:
    """
    POST /api/v1/quick/condition

    Add or remove a condition from a token.

    Request body:
    {
        "token_id": "uuid",
        "condition": "poisoned",
        "action": "add" | "remove",
        "note": "Failed save vs poison" (optional)
    }

    Response:
    {
        "success": true,
        "data": {
            "token_id": "uuid",
            "condition": "poisoned",
            "action": "add",
            "conditions": ["poisoned", "blinded"]
        }
    }
    """
    try:
        body = await request.json()
    except Exception:
        return error("Invalid JSON body", code="VALIDATION_ERROR", status=400)

    token_id = body.get("token_id")
    condition = body.get("condition")
    action = body.get("action")
    note = body.get("note", "")

    # Validate required fields
    if not token_id:
        return error("Missing required field: token_id", code="VALIDATION_ERROR", status=400)
    if not condition:
        return error("Missing required field: condition", code="VALIDATION_ERROR", status=400)
    if action not in ["add", "remove"]:
        return error("action must be 'add' or 'remove'", code="VALIDATION_ERROR", status=400)

    # Get token
    token = Shape.get_or_none(Shape.uuid == token_id)
    if not token:
        return error(f"Token not found: {token_id}", code="NOT_FOUND", status=404)

    # Ownership check
    api_key = request["api_key"]
    location = token.layer.floor.location
    room = location.room
    if room.creator.id != api_key.user.id:
        if not any(rp.player.id == api_key.user.id for rp in room.players):
            return error("Access denied to this scene", code="FORBIDDEN", status=403)

    # Get or create TokenExt
    token_ext = TokenExt.get_or_none(TokenExt.shape == token)
    if not token_ext:
        token_ext = TokenExt.create(
            uuid=str(uuid4()),
            shape=token,
            faction="neutral",
            conditions=json.dumps([]),
            custom=json.dumps({}),
        )

    # Get current conditions
    conditions = token_ext.get_conditions()

    # Update conditions
    if action == "add":
        if condition not in conditions:
            conditions.append(condition)
    else:  # remove
        if condition in conditions:
            conditions.remove(condition)

    # Save updated conditions
    token_ext.set_conditions(conditions)
    token_ext.save()

    # Get location for socket emission
    location = token.layer.floor.location

    # Note: Conditions are stored in TokenExt (REST extension), not in PA's shape system.
    # There is no native socket event for condition changes — CLI clients monitor via SSE.

    # Log event
    event_type = "condition_added" if action == "add" else "condition_removed"
    await log_event(
        event_type=event_type,
        payload={
            "token_id": token_id,
            "token_name": token.name,
            "condition": condition,
            "conditions": conditions,
            "note": note,
        },
        scene_id=location.id,
        actor_id=token_id,
    )

    return ok({
        "token_id": token_id,
        "condition": condition,
        "action": action,
        "conditions": conditions,
    })


@require_role("dm")
async def kill_token(request: web.Request) -> web.Response:
    """
    POST /api/v1/quick/kill

    Mark a token as dead (set HP to 0, remove from combat).

    Request body:
    {
        "token_id": "uuid",
        "note": "Killed by fireball" (optional)
    }

    Response:
    {
        "success": true,
        "data": {
            "token_id": "uuid",
            "old_hp": 15,
            "removed_from_combat": true
        }
    }
    """
    try:
        body = await request.json()
    except Exception:
        return error("Invalid JSON body", code="VALIDATION_ERROR", status=400)

    token_id = body.get("token_id")
    note = body.get("note", "")

    # Validate required fields
    if not token_id:
        return error("Missing required field: token_id", code="VALIDATION_ERROR", status=400)

    # Get token
    token = Shape.get_or_none(Shape.uuid == token_id)
    if not token:
        return error(f"Token not found: {token_id}", code="NOT_FOUND", status=404)

    # Ownership check
    api_key = request["api_key"]
    location = token.layer.floor.location
    room = location.room
    if room.creator.id != api_key.user.id:
        if not any(rp.player.id == api_key.user.id for rp in room.players):
            return error("Access denied to this scene", code="FORBIDDEN", status=403)

    # Get HP tracker
    hp_tracker = _get_hp_tracker(token)
    if not hp_tracker:
        return error("Token has no HP tracker", code="VALIDATION_ERROR", status=400)

    # Save old HP
    old_hp = hp_tracker.value

    # Set HP to 0
    hp_tracker.value = 0
    hp_tracker.save()

    # Get location for socket emission
    location = token.layer.floor.location

    # Emit HP update to all players
    for psid in game_state.get_sids(active_location=location):
        await _send_game(
            "Shape.Options.Tracker.Update",
            {
                "uuid": hp_tracker.uuid,
                "shape": token_id,
                "value": 0,
                "maxvalue": hp_tracker.maxvalue,
            },
            room=psid,
        )

    # Remove from active combat if present
    removed_from_combat = False
    initiative = Initiative.get_or_none(Initiative.location == location)
    if initiative and initiative.is_active:
        # Parse initiative data
        combatants = json.loads(initiative.data)

        # Find and remove this token from combatants
        original_count = len(combatants)
        combatants = [c for c in combatants if c.get("shape") != token_id]

        if len(combatants) < original_count:
            removed_from_combat = True

            # Adjust turn index if needed
            if initiative.turn >= len(combatants) and len(combatants) > 0:
                initiative.turn = len(combatants) - 1

            # Save updated initiative
            initiative.data = json.dumps(combatants)
            initiative.save()

            # Emit initiative update to all players
            from ...api.socket.initiative import send_initiative
            from ...db.models.user import User
            from ...models.role import Role
            from ...db.models.player_room import PlayerRoom

            # Find a player room for broadcasting
            room = location.room
            for room_player in room.players:
                if room_player.role == Role.DM:
                    # Create a minimal PlayerRoom-like object for send_initiative
                    class PR:
                        def __init__(self, location, player):
                            self.active_location = location
                            self.player = player

                    pr = PR(location, room_player.player)
                    await send_initiative(initiative.as_pydantic(), pr)
                    break

    # Log event
    await log_event(
        event_type="token_killed",
        payload={
            "token_id": token_id,
            "token_name": token.name,
            "old_hp": old_hp,
            "removed_from_combat": removed_from_combat,
            "note": note,
        },
        scene_id=location.id,
        actor_id=token_id,
    )

    return ok({
        "token_id": token_id,
        "old_hp": old_hp,
        "removed_from_combat": removed_from_combat,
    })
