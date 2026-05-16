"""Action declaration endpoints for player action submission and DM review workflow."""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from aiohttp import web
from peewee import DoesNotExist

from ...db.db import db
from ...db.models.location import Location
from ...db.models.rest_ext.action_declaration import ActionDeclaration
from ...db.models.rest_ext.api_key import ApiKey
from ...db.models.shape import Shape
from ...db.models.shape_owner import ShapeOwner
from .helpers import error, log_event, ok, require_role, serialize_datetime


@require_role("dm", "player")
async def submit_action(request: web.Request) -> web.Response:
    """POST /api/v1/scenes/{uuid}/actions - Submit action declaration.

    Players can submit actions for DM review. Actions start with status "pending".

    Request Body:
        {
            "actor_id": str,           # UUID of token performing action
            "action_type": str,        # "attack", "move", "spell", "ability", "other"
            "targets": [               # Optional, list of target objects
                {"uuid": str, "type": "token"},
                ...
            ],
            "meta": {                  # Optional, action-specific data
                "weapon": "longsword",
                "spell_name": "fireball",
                "distance": 30,
                ...
            }
        }

    Response:
        {
            "success": true,
            "data": {
                "uuid": str,
                "actor_id": str,
                "action_type": str,
                "targets": [...],
                "status": "pending",
                "meta": {...},
                "submitted_at": str
            }
        }

    RBAC: DM + Player (player can only submit for their owned tokens)
    """
    api_key = request["api_key"]
    scene_uuid = request.match_info["uuid"]

    try:
        body = await request.json()
    except Exception:
        return error("Invalid JSON body", code="VALIDATION_ERROR", status=400)

    # Validate required fields
    actor_id = body.get("actor_id")
    action_type = body.get("action_type")

    if not actor_id or not action_type:
        return error("Missing required fields: actor_id, action_type", code="VALIDATION_ERROR", status=400)

    # Validate action_type
    valid_action_types = ["attack", "move", "spell", "ability", "other"]
    if action_type not in valid_action_types:
        return error(
            f"Invalid action_type. Must be one of: {', '.join(valid_action_types)}",
            code="VALIDATION_ERROR",
            status=400
        )

    # Verify scene exists
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

    # Verify actor exists and belongs to scene
    try:
        actor = Shape.get_by_id(actor_id)
    except Exception:
        return error("Actor not found", code="NOT_FOUND", status=404)

    # Verify actor is in the scene's layers
    actor_location = actor.layer.floor.location
    if actor_location.id != location.id:
        return error("Actor does not belong to this scene", code="VALIDATION_ERROR", status=400)

    # RBAC: Players can only submit actions for their owned tokens
    if api_key.role == "player":
        # Check if player owns the token
        actor_owners = [owner.user.id for owner in actor.owners]
        if api_key.user.id not in actor_owners:
            return error("You do not own this token", code="FORBIDDEN", status=403)

    # Parse optional fields
    targets = body.get("targets", [])
    meta = body.get("meta", {})

    # Validate targets if provided
    if not isinstance(targets, list):
        return error("targets must be a list", code="VALIDATION_ERROR", status=400)

    # Verify all target tokens exist
    for target in targets:
        if not isinstance(target, dict) or "uuid" not in target:
            return error("Each target must be an object with 'uuid' field", code="VALIDATION_ERROR", status=400)

        target_uuid = target.get("uuid")
        try:
            target_shape = Shape.get_by_id(target_uuid)
            # Verify target is in the same scene
            target_location = target_shape.layer.floor.location
            if target_location.id != location.id:
                return error(
                    f"Target {target_uuid} does not belong to this scene",
                    code="VALIDATION_ERROR",
                    status=400
                )
        except Exception:
            return error(f"Target not found: {target_uuid}", code="NOT_FOUND", status=404)

    # Create action declaration
    action_uuid = str(uuid.uuid4())
    action = ActionDeclaration.create(
        uuid=action_uuid,
        actor=actor,
        action_type=action_type,
        targets=json.dumps(targets),
        status="pending",
        meta=json.dumps(meta),
        submitted_at=datetime.now()
    )

    # Log event
    await log_event(
        event_type="action_submitted",
        payload={
            "action_id": action_uuid,
            "action_type": action_type,
            "actor_id": actor_id,
            "actor_name": actor.name,
            "targets": targets,
            "meta": meta
        },
        scene_id=location.id,
        actor_id=actor_id,
    )

    return ok({
        "uuid": action.uuid,
        "actor_id": str(action.actor.uuid),
        "actor_name": action.actor.name,
        "action_type": action.action_type,
        "targets": action.get_targets(),
        "status": action.status,
        "meta": action.get_meta(),
        "dm_note": action.dm_note,
        "submitted_at": serialize_datetime(action.submitted_at)
    }, status=201)


@require_role("dm", "player")
async def list_actions(request: web.Request) -> web.Response:
    """GET /api/v1/scenes/{uuid}/actions - List actions in a scene.

    Query Parameters:
        - status: Filter by status (pending/accepted/rejected/modified)
        - actor_id: Filter by actor UUID
        - limit: Maximum results (default 50, max 200)
        - offset: Pagination offset (default 0)

    Response:
        {
            "success": true,
            "data": {
                "actions": [
                    {
                        "uuid": str,
                        "actor_id": str,
                        "actor_name": str,
                        "action_type": str,
                        "targets": [...],
                        "status": str,
                        "meta": {...},
                        "dm_note": str | null,
                        "modifications": {...} | null,
                        "submitted_at": str,
                        "reviewed_at": str | null
                    },
                    ...
                ],
                "total_count": int,
                "limit": int,
                "offset": int,
                "has_more": bool
            }
        }

    RBAC: DM + Player (player sees only actions for their owned tokens)
    """
    api_key = request["api_key"]
    scene_uuid = request.match_info["uuid"]

    # Verify scene exists
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

    # Parse query parameters
    status = request.query.get("status")
    actor_id = request.query.get("actor_id")

    try:
        limit = min(int(request.query.get("limit", 50)), 200)
        offset = int(request.query.get("offset", 0))
    except ValueError:
        return error("Invalid limit or offset", code="VALIDATION_ERROR", status=400)

    # Build query - find all actions for shapes in this location
    # Collect all shape UUIDs for this location by traversing the hierarchy in Python
    location_shape_uuid_list: list[str] = []
    for floor in location.floors:
        for layer in floor.layers:
            for shape in layer.shapes:
                location_shape_uuid_list.append(shape.uuid)

    if not location_shape_uuid_list:
        return ok({
            "actions": [],
            "total_count": 0,
            "limit": limit,
            "offset": offset,
            "has_more": False
        })

    query = ActionDeclaration.select().where(
        ActionDeclaration.actor.in_(location_shape_uuid_list)
    )

    # Filter by status
    if status:
        valid_statuses = ["pending", "accepted", "rejected", "modified"]
        if status not in valid_statuses:
            return error(
                f"Invalid status. Must be one of: {', '.join(valid_statuses)}",
                code="VALIDATION_ERROR",
                status=400
            )
        query = query.where(ActionDeclaration.status == status)

    # Filter by actor
    if actor_id:
        query = query.where(ActionDeclaration.actor == actor_id)

    # RBAC: Players only see actions for their owned tokens
    if api_key.role == "player":
        # Filter to only actions where actor is owned by the player
        owned_shape_ids = list(
            ShapeOwner
            .select(ShapeOwner.shape)
            .where(ShapeOwner.user == api_key.user)
            .tuples()
        )
        owned_shape_id_list = [row[0] for row in owned_shape_ids]
        query = query.where(ActionDeclaration.actor.in_(owned_shape_id_list))

    # Get total count
    total_count = query.count()

    # Apply pagination
    query = query.order_by(ActionDeclaration.submitted_at.desc()).limit(limit).offset(offset)

    # Serialize results
    actions = []
    for action in query:
        actions.append({
            "uuid": action.uuid,
            "actor_id": str(action.actor.uuid),
            "actor_name": action.actor.name,
            "action_type": action.action_type,
            "targets": action.get_targets(),
            "status": action.status,
            "meta": action.get_meta(),
            "dm_note": action.dm_note,
            "modifications": action.get_modifications(),
            "submitted_at": serialize_datetime(action.submitted_at),
            "reviewed_at": serialize_datetime(action.reviewed_at) if action.reviewed_at else None
        })

    return ok({
        "actions": actions,
        "total_count": total_count,
        "limit": limit,
        "offset": offset,
        "has_more": offset + limit < total_count
    })


@require_role("dm", "player")
async def get_action(request: web.Request) -> web.Response:
    """GET /api/v1/actions/{uuid} - Get single action declaration.

    Response:
        {
            "success": true,
            "data": {
                "uuid": str,
                "actor_id": str,
                "actor_name": str,
                "action_type": str,
                "targets": [...],
                "status": str,
                "meta": {...},
                "dm_note": str | null,
                "modifications": {...} | null,
                "submitted_at": str,
                "reviewed_at": str | null
            }
        }

    RBAC: DM + Player (player can only view actions for their owned tokens)
    """
    api_key = request["api_key"]
    action_uuid = request.match_info["uuid"]

    # Get action
    try:
        action = ActionDeclaration.get_by_id(action_uuid)
    except Exception:
        return error("Action not found", code="NOT_FOUND", status=404)

    # RBAC: Players can only view actions for their owned tokens
    if api_key.role == "player":
        actor_owners = [owner.user.id for owner in action.actor.owners]
        if api_key.user.id not in actor_owners:
            return error("Action not found", code="NOT_FOUND", status=404)

    return ok({
        "uuid": action.uuid,
        "actor_id": str(action.actor.uuid),
        "actor_name": action.actor.name,
        "action_type": action.action_type,
        "targets": action.get_targets(),
        "status": action.status,
        "meta": action.get_meta(),
        "dm_note": action.dm_note,
        "modifications": action.get_modifications(),
        "submitted_at": serialize_datetime(action.submitted_at),
        "reviewed_at": serialize_datetime(action.reviewed_at) if action.reviewed_at else None
    })


@require_role("dm")
async def review_action(request: web.Request) -> web.Response:
    """PATCH /api/v1/actions/{uuid} - DM review of action declaration.

    Request Body:
        {
            "status": str,              # Required: "accepted", "rejected", or "modified"
            "dm_note": str,             # Optional: DM feedback/explanation
            "modifications": {          # Required if status="modified": DM modifications
                "damage_modifier": -5,
                "advantage": false,
                ...
            }
        }

    Response:
        {
            "success": true,
            "data": {
                "uuid": str,
                "actor_id": str,
                "actor_name": str,
                "action_type": str,
                "targets": [...],
                "status": str,
                "meta": {...},
                "dm_note": str | null,
                "modifications": {...} | null,
                "submitted_at": str,
                "reviewed_at": str
            }
        }

    RBAC: DM only
    """
    action_uuid = request.match_info["uuid"]

    try:
        body = await request.json()
    except Exception:
        return error("Invalid JSON body", code="VALIDATION_ERROR", status=400)

    # Validate required fields
    new_status = body.get("status")
    dm_note = body.get("dm_note")
    modifications = body.get("modifications")

    if not new_status:
        return error("Missing required field: status", code="VALIDATION_ERROR", status=400)

    # Validate status
    valid_statuses = ["accepted", "rejected", "modified"]
    if new_status not in valid_statuses:
        return error(
            f"Invalid status. Must be one of: {', '.join(valid_statuses)}",
            code="VALIDATION_ERROR",
            status=400
        )

    # Validate modifications if status is modified
    if new_status == "modified" and not modifications:
        return error(
            "modifications field is required when status is 'modified'",
            code="VALIDATION_ERROR",
            status=400
        )

    # Get action
    try:
        action = ActionDeclaration.get_by_id(action_uuid)
    except Exception:
        return error("Action not found", code="NOT_FOUND", status=404)

    # Update action
    action.status = new_status
    action.dm_note = dm_note
    action.reviewed_at = datetime.now()

    if new_status == "modified" and modifications:
        action.set_modifications(modifications)

    action.save()

    # Log event
    await log_event(
        event_type="action_reviewed",
        payload={
            "action_id": action.uuid,
            "action_type": action.action_type,
            "actor_id": str(action.actor.uuid),
            "actor_name": action.actor.name,
            "new_status": new_status,
            "dm_note": dm_note,
            "modifications": modifications
        },
        scene_id=action.actor.layer.floor.location.id,
        actor_id=str(action.actor.uuid),
    )

    return ok({
        "uuid": action.uuid,
        "actor_id": str(action.actor.uuid),
        "actor_name": action.actor.name,
        "action_type": action.action_type,
        "targets": action.get_targets(),
        "status": action.status,
        "meta": action.get_meta(),
        "dm_note": action.dm_note,
        "modifications": action.get_modifications(),
        "submitted_at": serialize_datetime(action.submitted_at),
        "reviewed_at": serialize_datetime(action.reviewed_at) if action.reviewed_at else None
    })
