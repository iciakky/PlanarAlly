"""
Combat Tracker REST API handlers.

Integrates with PA's Initiative system to provide combat management via REST API.
"""

import json
from typing import Any
from uuid import uuid4

from aiohttp import web
from peewee import DoesNotExist

from ...db.db import db
from ...db.models.initiative import Initiative
from ...db.models.location import Location
from ...db.models.rest_ext.combat_ext import CombatExt
from ...db.models.shape import Shape
from ...state.game import game_state
from ..helpers import _send_game
from ..models.initiative import (
    ApiInitiative,
    InitiativeDirection,
    InitiativeRoundUpdate,
    InitiativeTurnUpdate,
)
from .helpers import error, log_event, ok, require_role

EFFECT_TIMING_TURN_END = 0
EFFECT_TIMING_TURN_START = 1


def _update_effects(entry: dict[str, Any], timing: int | None = None) -> None:
    """Process initiative effects on a combatant entry, matching upstream logic.

    Decrements turn counters and removes expired effects. When timing is specified,
    only effects with matching updateTiming are processed.
    """
    effect_list = entry.get("effects", [])
    starting_len = len(effect_list)
    for i, effect in enumerate(effect_list[::-1]):
        if timing is not None and effect.get("updateTiming", EFFECT_TIMING_TURN_END) != timing:
            continue
        effect_turns = effect.get("turns")
        if effect_turns is None:
            continue
        try:
            turns = int(effect_turns)
            if turns <= 0:
                effect_list.pop(starting_len - 1 - i)
            else:
                effect["turns"] = str(turns - 1)
        except ValueError:
            pass


def _process_effects_on_advance(
    initiative_data: list[dict[str, Any]], exiting_turn: int, entering_turn: int
) -> None:
    """Process effects when advancing turn: TurnEnd on exiting, TurnStart on entering."""
    total = len(initiative_data)
    if 0 <= exiting_turn < total:
        _update_effects(initiative_data[exiting_turn], EFFECT_TIMING_TURN_END)
    if 0 <= entering_turn < total:
        _update_effects(initiative_data[entering_turn], EFFECT_TIMING_TURN_START)


def sort_combatants(combatants: list[dict[str, Any]], sort_mode: int) -> list[dict[str, Any]]:
    """
    Sort combatants based on sort mode.

    Args:
        combatants: List of combatant dicts with 'initiative' field
        sort_mode: 0 = desc (highest first), 1 = asc, 2 = manual (no sort)

    Returns:
        Sorted list of combatants
    """
    if sort_mode == 2:
        return combatants
    return sorted(combatants, key=lambda x: x.get("initiative", 0) or 0, reverse=sort_mode == 0)


async def broadcast_initiative(location: Location):
    """
    Broadcast initiative state to all connected clients in location.

    Args:
        location: Location to broadcast to
    """
    initiative = Initiative.get_or_none(location=location)
    if initiative is None:
        return

    # Get all connected player sessions for this location
    # NOTE: We can't easily get PlayerRoom without sid, so we emit to room path
    # PA's socket handlers will distribute to appropriate clients
    await _send_game(
        "Initiative.Set",
        initiative.as_pydantic(),
        room=location.get_path(),
    )


@require_role("dm")
async def start_combat(request: web.Request) -> web.Response:
    """
    POST /api/v1/scenes/{uuid}/combats

    Start a new combat encounter in the scene.

    Request Body:
    {
        "combatants": [
            {
                "actor_id": "shape-uuid",
                "initiative": 15,
                "is_visible": true
            },
            ...
        ],
        "auto_sort": true  # Optional, default true
    }

    Response:
    {
        "success": true,
        "data": {
            "uuid": "combat-uuid",
            "scene_id": 123,
            "round": 0,
            "turn": 0,
            "combatants": [...],
            "is_active": true
        }
    }
    """
    api_key = request["api_key"]
    scene_uuid = request.match_info["uuid"]

    try:
        data = await request.json()
    except Exception:
        return error("Invalid JSON body", code="VALIDATION_ERROR", status=400)

    combatants_data = data.get("combatants", [])
    auto_sort = data.get("auto_sort", True)

    if not combatants_data:
        return error("At least one combatant required", code="VALIDATION_ERROR", status=400)

    # Validate location exists
    try:
        scene_uuid_int = int(scene_uuid)
    except (ValueError, TypeError):
        return error("Invalid scene UUID", code="VALIDATION_ERROR", status=400)
    try:
        location = Location.get_by_id(scene_uuid_int)
    except DoesNotExist:
        return error("Scene not found", code="NOT_FOUND", status=404)

    # Verify user has access to this scene
    room = location.room
    if room.creator.id != api_key.user.id:
        if not any(rp.player.id == api_key.user.id for rp in room.players):
            return error("Access denied to this scene", code="FORBIDDEN", status=403)

    # Check if combat already active
    existing_combat = CombatExt.get_or_none(CombatExt.location == location, CombatExt.active == True)
    if existing_combat:
        return error("Combat already active in this scene", code="CONFLICT", status=409)

    # Validate all combatants exist
    combatant_shapes = []
    for combatant in combatants_data:
        actor_id = combatant.get("actor_id")
        if not actor_id:
            return error("Each combatant must have actor_id", code="VALIDATION_ERROR", status=400)

        shape = Shape.get_or_none(uuid=actor_id)
        if shape is None:
            return error(f"Token {actor_id} not found", code="NOT_FOUND", status=404)

        combatant_shapes.append(shape)

    # Build initiative data structure
    initiative_data = []
    for i, combatant in enumerate(combatants_data):
        initiative_data.append({
            "shape": combatant["actor_id"],
            "initiative": combatant.get("initiative"),
            "isVisible": combatant.get("is_visible", True),
            "isGroup": False,
            "effects": []
        })

    # Sort if requested
    sort_mode = 0 if auto_sort else 2  # 0 = desc by initiative, 2 = manual
    initiative_data = sort_combatants(initiative_data, sort_mode)

    with db.atomic():
        # Create or update Initiative record
        initiative, created = Initiative.get_or_create(
            location=location,
            defaults={
                "round": 0,
                "turn": 0,
                "sort": sort_mode,
                "data": json.dumps(initiative_data),
                "is_active": True
            }
        )

        if not created:
            # Update existing initiative
            initiative.round = 0
            initiative.turn = 0
            initiative.sort = sort_mode
            initiative.data = json.dumps(initiative_data)
            initiative.is_active = True
            initiative.save()

        # Create CombatExt record
        combat_ext = CombatExt.create(
            uuid=str(uuid4()),
            location=location,
            round_number=0,
            turn_index=0,
            combatants=json.dumps([{
                "actor_id": c["actor_id"],
                "initiative": c.get("initiative"),
                "is_visible": c.get("is_visible", True)
            } for c in combatants_data]),
            active=True
        )

    # Broadcast to connected clients
    await broadcast_initiative(location)

    # Log event
    await log_event(
        event_type="combat_started",
        payload={
            "combat_id": combat_ext.uuid,
            "scene_id": location.id,
            "combatant_count": len(combatants_data)
        },
        scene_id=location.id,
    )

    return ok({
        "uuid": combat_ext.uuid,
        "scene_id": location.id,
        "round": 0,
        "turn": 0,
        "combatants": json.loads(combat_ext.combatants),
        "is_active": True
    }, status=201)


@require_role("dm", "player")
async def get_active_combat(request: web.Request) -> web.Response:
    """
    GET /api/v1/scenes/{uuid}/combats/active

    Get the currently active combat in the scene, if any.

    Response:
    {
        "success": true,
        "data": {
            "uuid": "combat-uuid",
            "scene_id": 123,
            "round": 2,
            "turn": 1,
            "combatants": [...],
            "is_active": true,
            "current_actor": "shape-uuid"
        }
    }

    Returns 404 if no active combat.
    """
    api_key = request["api_key"]
    scene_uuid = request.match_info["uuid"]

    try:
        scene_uuid_int = int(scene_uuid)
    except (ValueError, TypeError):
        return error("Invalid scene UUID", code="VALIDATION_ERROR", status=400)
    try:
        location = Location.get_by_id(scene_uuid_int)
    except DoesNotExist:
        return error("Scene not found", code="NOT_FOUND", status=404)

    # Verify user has access to this scene
    room = location.room
    if room.creator.id != api_key.user.id:
        if not any(rp.player.id == api_key.user.id for rp in room.players):
            return error("Access denied to this scene", code="FORBIDDEN", status=403)

    # Find active combat
    combat_ext = CombatExt.get_or_none(CombatExt.location == location, CombatExt.active == True)
    if combat_ext is None:
        return error("No active combat in this scene", code="NOT_FOUND", status=404)

    # Get Initiative data for current state
    initiative = Initiative.get_or_none(location=location)
    if initiative is None:
        return error("Initiative data not found", code="NOT_FOUND", status=404)

    initiative_data = json.loads(initiative.data)
    current_actor = None
    if 0 <= initiative.turn < len(initiative_data):
        current_actor = initiative_data[initiative.turn]["shape"]

    return ok({
        "uuid": combat_ext.uuid,
        "scene_id": location.id,
        "round": initiative.round,
        "turn": initiative.turn,
        "combatants": initiative_data,
        "is_active": True,
        "current_actor": current_actor
    })


@require_role("dm", "player")
async def get_combat(request: web.Request) -> web.Response:
    """
    GET /api/v1/combats/{uuid}

    Get combat details by UUID.

    Response:
    {
        "success": true,
        "data": {
            "uuid": "combat-uuid",
            "scene_id": 123,
            "round": 2,
            "turn": 1,
            "combatants": [...],
            "is_active": true,
            "current_actor": "shape-uuid"
        }
    }
    """
    api_key = request["api_key"]
    combat_uuid = request.match_info["uuid"]

    try:
        combat_ext = CombatExt.get(uuid=combat_uuid)
    except DoesNotExist:
        return error("Combat not found", code="NOT_FOUND", status=404)

    location = combat_ext.location

    # Verify user has access to this scene's room
    room = location.room
    if room.creator.id != api_key.user.id:
        if not any(rp.player.id == api_key.user.id for rp in room.players):
            return error("Access denied to this combat", code="FORBIDDEN", status=403)

    # Get Initiative data for current state
    initiative = Initiative.get_or_none(location=location)
    if initiative is None:
        return error("Initiative data not found", code="NOT_FOUND", status=404)

    initiative_data = json.loads(initiative.data)
    current_actor = None
    if 0 <= initiative.turn < len(initiative_data):
        current_actor = initiative_data[initiative.turn]["shape"]

    return ok({
        "uuid": combat_ext.uuid,
        "scene_id": location.id,
        "round": initiative.round,
        "turn": initiative.turn,
        "combatants": initiative_data,
        "is_active": combat_ext.active,
        "current_actor": current_actor
    })


@require_role("dm")
async def advance_turn(request: web.Request) -> web.Response:
    """
    PATCH /api/v1/combats/{uuid}/next

    Advance to the next turn in combat.
    Wraps around to turn 0 and increments round when reaching end.

    Request Body:
    {
        "process_effects": true  # Optional, default true
    }

    Response:
    {
        "success": true,
        "data": {
            "round": 2,
            "turn": 0,
            "current_actor": "shape-uuid"
        }
    }
    """
    api_key = request["api_key"]
    combat_uuid = request.match_info["uuid"]

    try:
        data = await request.json()
    except Exception:
        data = {}

    process_effects = data.get("process_effects", True)

    try:
        combat_ext = CombatExt.get(uuid=combat_uuid)
    except DoesNotExist:
        return error("Combat not found", code="NOT_FOUND", status=404)

    if not combat_ext.active:
        return error("Combat is not active", code="VALIDATION_ERROR", status=400)

    location = combat_ext.location

    # Verify user has access to this scene's room
    room = location.room
    if room.creator.id != api_key.user.id:
        if not any(rp.player.id == api_key.user.id for rp in room.players):
            return error("Access denied to this combat", code="FORBIDDEN", status=403)

    initiative = Initiative.get_or_none(location=location)

    if initiative is None:
        return error("Initiative data not found", code="NOT_FOUND", status=404)

    initiative_data = json.loads(initiative.data)
    total_combatants = len(initiative_data)

    if total_combatants == 0:
        return error("No combatants in combat", code="VALIDATION_ERROR", status=400)

    # Advance turn
    old_turn = initiative.turn
    new_turn = old_turn + 1
    round_advanced = False

    if new_turn >= total_combatants:
        new_turn = 0
        initiative.round += 1
        round_advanced = True

    if process_effects:
        _process_effects_on_advance(initiative_data, old_turn, new_turn)

    with db.atomic():
        initiative.turn = new_turn
        initiative.data = json.dumps(initiative_data)
        initiative.save()

        combat_ext.turn_index = new_turn
        combat_ext.round_number = initiative.round
        combat_ext.save()

    # Broadcast turn update
    await _send_game(
        "Initiative.Turn.Update",
        InitiativeTurnUpdate(
            turn=new_turn,
            direction=InitiativeDirection.FORWARD,
            processEffects=process_effects
        ),
        room=location.get_path()
    )

    # Broadcast round update if needed
    if round_advanced:
        await _send_game(
            "Initiative.Round.Update",
            InitiativeRoundUpdate(
                round=initiative.round,
                direction=InitiativeDirection.FORWARD,
                processEffects=process_effects
            ),
            room=location.get_path()
        )

    current_actor = None
    if 0 <= new_turn < len(initiative_data):
        current_actor = initiative_data[new_turn]["shape"]

    # Log event
    await log_event(
        event_type="turn_advanced",
        payload={
            "combat_id": combat_ext.uuid,
            "round": initiative.round,
            "turn": new_turn,
            "current_actor": current_actor
        },
        scene_id=location.id,
    )

    return ok({
        "round": initiative.round,
        "turn": new_turn,
        "current_actor": current_actor
    })


@require_role("dm")
async def modify_initiative(request: web.Request) -> web.Response:
    """
    PATCH /api/v1/combats/{uuid}/initiative

    Modify a combatant's initiative value.

    Request Body:
    {
        "actor_id": "shape-uuid",
        "initiative": 20
    }

    Response:
    {
        "success": true,
        "data": {
            "combatants": [...]  # Updated combatant list
        }
    }
    """
    api_key = request["api_key"]
    combat_uuid = request.match_info["uuid"]

    try:
        data = await request.json()
    except Exception:
        return error("Invalid JSON body", code="VALIDATION_ERROR", status=400)

    actor_id = data.get("actor_id")
    new_initiative = data.get("initiative")

    if not actor_id:
        return error("actor_id required", code="VALIDATION_ERROR", status=400)

    if new_initiative is None:
        return error("initiative value required", code="VALIDATION_ERROR", status=400)

    try:
        combat_ext = CombatExt.get(uuid=combat_uuid)
    except DoesNotExist:
        return error("Combat not found", code="NOT_FOUND", status=404)

    location = combat_ext.location

    # Verify user has access to this scene's room
    room = location.room
    if room.creator.id != api_key.user.id:
        if not any(rp.player.id == api_key.user.id for rp in room.players):
            return error("Access denied to this combat", code="FORBIDDEN", status=403)

    initiative = Initiative.get_or_none(location=location)

    if initiative is None:
        return error("Initiative data not found", code="NOT_FOUND", status=404)

    initiative_data = json.loads(initiative.data)

    # Find and update combatant
    found = False
    current_actor_shape = None
    if 0 <= initiative.turn < len(initiative_data):
        current_actor_shape = initiative_data[initiative.turn]["shape"]

    for combatant in initiative_data:
        if combatant["shape"] == actor_id:
            combatant["initiative"] = new_initiative
            found = True
            break

    if not found:
        return error(f"Combatant {actor_id} not found in combat", code="NOT_FOUND", status=404)

    # Re-sort if sort mode is not manual
    initiative_data = sort_combatants(initiative_data, initiative.sort)

    # Find new turn index for current actor
    new_turn = initiative.turn
    if current_actor_shape:
        for i, combatant in enumerate(initiative_data):
            if combatant["shape"] == current_actor_shape:
                new_turn = i
                break

    with db.atomic():
        initiative.turn = new_turn
        initiative.data = json.dumps(initiative_data)
        initiative.save()

    # Broadcast full initiative update
    await broadcast_initiative(location)

    # Log event
    await log_event(
        event_type="initiative_modified",
        payload={
            "combat_id": combat_ext.uuid,
            "actor_id": actor_id,
            "initiative": new_initiative
        },
        scene_id=location.id,
        actor_id=actor_id,
    )

    return ok({
        "combatants": initiative_data
    })


@require_role("dm")
async def add_combatant(request: web.Request) -> web.Response:
    """
    POST /api/v1/combats/{uuid}/add

    Add a combatant to an active combat.

    Request Body:
    {
        "actor_id": "shape-uuid",
        "initiative": 12,
        "is_visible": true
    }

    Response:
    {
        "success": true,
        "data": {
            "combatants": [...]  # Updated combatant list
        }
    }
    """
    api_key = request["api_key"]
    combat_uuid = request.match_info["uuid"]

    try:
        data = await request.json()
    except Exception:
        return error("Invalid JSON body", code="VALIDATION_ERROR", status=400)

    actor_id = data.get("actor_id")
    initiative_value = data.get("initiative")
    is_visible = data.get("is_visible", True)

    if not actor_id:
        return error("actor_id required", code="VALIDATION_ERROR", status=400)

    # Validate shape exists
    shape = Shape.get_or_none(uuid=actor_id)
    if shape is None:
        return error(f"Token {actor_id} not found", code="NOT_FOUND", status=404)

    try:
        combat_ext = CombatExt.get(uuid=combat_uuid)
    except DoesNotExist:
        return error("Combat not found", code="NOT_FOUND", status=404)

    location = combat_ext.location

    # Verify user has access to this scene's room
    room = location.room
    if room.creator.id != api_key.user.id:
        if not any(rp.player.id == api_key.user.id for rp in room.players):
            return error("Access denied to this combat", code="FORBIDDEN", status=403)

    initiative = Initiative.get_or_none(location=location)

    if initiative is None:
        return error("Initiative data not found", code="NOT_FOUND", status=404)

    initiative_data = json.loads(initiative.data)

    # Check if already in combat
    for combatant in initiative_data:
        if combatant["shape"] == actor_id:
            return error(f"Combatant {actor_id} already in combat", code="CONFLICT", status=409)

    # Add new combatant
    initiative_data.append({
        "shape": actor_id,
        "initiative": initiative_value,
        "isVisible": is_visible,
        "isGroup": False,
        "effects": []
    })

    # Re-sort if sort mode is not manual
    current_actor_shape = None
    if 0 <= initiative.turn < len(initiative_data) - 1:  # -1 because we just added one
        current_actor_shape = initiative_data[initiative.turn]["shape"]

    initiative_data = sort_combatants(initiative_data, initiative.sort)

    # Find new turn index for current actor (in case sort changed order)
    new_turn = initiative.turn
    if current_actor_shape:
        for i, combatant in enumerate(initiative_data):
            if combatant["shape"] == current_actor_shape:
                new_turn = i
                break

    with db.atomic():
        initiative.turn = new_turn
        initiative.data = json.dumps(initiative_data)
        initiative.save()

    # Broadcast full initiative update
    await broadcast_initiative(location)

    # Log event
    await log_event(
        event_type="combatant_added",
        payload={
            "combat_id": combat_ext.uuid,
            "actor_id": actor_id,
            "initiative": initiative_value
        },
        scene_id=location.id,
        actor_id=actor_id,
    )

    return ok({
        "combatants": initiative_data
    })


@require_role("dm")
async def remove_combatant(request: web.Request) -> web.Response:
    """
    DELETE /api/v1/combats/{uuid}/remove/{actor_uuid}

    Remove a combatant from combat.
    Adjusts turn index if necessary.

    Response:
    {
        "success": true,
        "data": {
            "combatants": [...]  # Updated combatant list
        }
    }
    """
    api_key = request["api_key"]
    combat_uuid = request.match_info["uuid"]
    actor_uuid = request.match_info["actor_uuid"]

    try:
        combat_ext = CombatExt.get(uuid=combat_uuid)
    except DoesNotExist:
        return error("Combat not found", code="NOT_FOUND", status=404)

    location = combat_ext.location

    # Verify user has access to this scene's room
    room = location.room
    if room.creator.id != api_key.user.id:
        if not any(rp.player.id == api_key.user.id for rp in room.players):
            return error("Access denied to this combat", code="FORBIDDEN", status=403)

    initiative = Initiative.get_or_none(location=location)

    if initiative is None:
        return error("Initiative data not found", code="NOT_FOUND", status=404)

    initiative_data = json.loads(initiative.data)

    # Find combatant index
    removed_index = None
    for i, combatant in enumerate(initiative_data):
        if combatant["shape"] == actor_uuid:
            removed_index = i
            break

    if removed_index is None:
        return error(f"Combatant {actor_uuid} not found in combat", code="NOT_FOUND", status=404)

    # Remove combatant
    initiative_data.pop(removed_index)

    # Adjust turn index
    original_turn = initiative.turn
    new_turn = initiative.turn
    round_advanced = False

    if removed_index < initiative.turn:
        # Removed before current turn, decrement turn index
        new_turn -= 1
    elif removed_index == initiative.turn:
        # Removed current actor, advance to next
        # If we removed the last actor, wrap around
        if new_turn >= len(initiative_data) and len(initiative_data) > 0:
            new_turn = 0
            if len(initiative_data) > 1:
                initiative.round += 1
                round_advanced = True

    # Ensure turn is within bounds
    if len(initiative_data) == 0:
        new_turn = 0
    elif new_turn >= len(initiative_data):
        new_turn = 0

    with db.atomic():
        initiative.turn = new_turn
        initiative.data = json.dumps(initiative_data)
        initiative.save()

        combat_ext.turn_index = new_turn
        combat_ext.round_number = initiative.round
        combat_ext.save()

    # Broadcast removal
    await _send_game(
        "Initiative.Remove",
        actor_uuid,
        room=location.get_path()
    )

    # Broadcast turn update if current actor was removed
    if removed_index == original_turn:
        await _send_game(
            "Initiative.Turn.Update",
            InitiativeTurnUpdate(
                turn=new_turn,
                direction=InitiativeDirection.FORWARD,
                processEffects=True
            ),
            room=location.get_path()
        )

    # Broadcast round update if needed
    if round_advanced:
        await _send_game(
            "Initiative.Round.Update",
            InitiativeRoundUpdate(
                round=initiative.round,
                direction=InitiativeDirection.FORWARD,
                processEffects=False
            ),
            room=location.get_path()
        )

    # Log event
    await log_event(
        event_type="combatant_removed",
        payload={
            "combat_id": combat_ext.uuid,
            "actor_id": actor_uuid
        },
        scene_id=location.id,
        actor_id=actor_uuid,
    )

    return ok({
        "combatants": initiative_data
    })


@require_role("dm")
async def end_combat(request: web.Request) -> web.Response:
    """
    POST /api/v1/combats/{uuid}/end

    End an active combat encounter.

    Response:
    {
        "success": true,
        "data": {
            "message": "Combat ended"
        }
    }
    """
    api_key = request["api_key"]
    combat_uuid = request.match_info["uuid"]

    try:
        combat_ext = CombatExt.get(uuid=combat_uuid)
    except DoesNotExist:
        return error("Combat not found", code="NOT_FOUND", status=404)

    location = combat_ext.location

    # Verify user has access to this scene's room
    room = location.room
    if room.creator.id != api_key.user.id:
        if not any(rp.player.id == api_key.user.id for rp in room.players):
            return error("Access denied to this combat", code="FORBIDDEN", status=403)

    with db.atomic():
        # Set Initiative to inactive
        initiative = Initiative.get_or_none(location=location)
        if initiative:
            initiative.is_active = False
            initiative.save()

        # Mark CombatExt as inactive
        combat_ext.active = False
        combat_ext.save()

    # Broadcast to clients
    await _send_game(
        "Initiative.Active.Set",
        False,
        room=location.get_path()
    )

    # Log event
    await log_event(
        event_type="combat_ended",
        payload={
            "combat_id": combat_ext.uuid,
            "final_round": combat_ext.round_number
        },
        scene_id=location.id,
    )

    return ok({
        "message": "Combat ended"
    })


@require_role("dm", "player")
async def get_round_info(request: web.Request) -> web.Response:
    """
    GET /api/v1/combats/{uuid}/round

    Get current round and turn information.

    Response:
    {
        "success": true,
        "data": {
            "round": 3,
            "turn": 2,
            "current_actor": "shape-uuid",
            "total_combatants": 5
        }
    }
    """
    api_key = request["api_key"]
    combat_uuid = request.match_info["uuid"]

    try:
        combat_ext = CombatExt.get(uuid=combat_uuid)
    except DoesNotExist:
        return error("Combat not found", code="NOT_FOUND", status=404)

    location = combat_ext.location

    # Verify user has access to this scene's room
    room = location.room
    if room.creator.id != api_key.user.id:
        if not any(rp.player.id == api_key.user.id for rp in room.players):
            return error("Access denied to this combat", code="FORBIDDEN", status=403)

    initiative = Initiative.get_or_none(location=location)

    if initiative is None:
        return error("Initiative data not found", code="NOT_FOUND", status=404)

    initiative_data = json.loads(initiative.data)
    current_actor = None
    if 0 <= initiative.turn < len(initiative_data):
        current_actor = initiative_data[initiative.turn]["shape"]

    return ok({
        "round": initiative.round,
        "turn": initiative.turn,
        "current_actor": current_actor,
        "total_combatants": len(initiative_data)
    })
