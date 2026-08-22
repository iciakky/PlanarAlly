"""Socket handlers for reference marker UI operations."""

import json

from ... import auth
from ...api.socket.constants import GAME_NS
from ...app import app, sio
from ...db.db import db
from ...db.models.player_room import PlayerRoom
from ...db.models.rest_ext.reference_marker import ReferenceMarker
from ...models.role import Role
from ...state.game import game_state
from ..helpers import _send_game
from ..rest.markers import _marker_to_dict
from ..rest.revision import broadcast_revision, next_revision


@sio.on("ReferenceMarker.Create", namespace=GAME_NS)
@auth.login_required(app, sio, "game")
async def create_reference_marker(sid: str, data: dict):
    pr: PlayerRoom = game_state.get(sid)
    user = pr.player
    location = pr.active_location
    room = pr.room

    external_id = data.get("external_id", "")
    if not external_id:
        return {"success": False, "error": "external_id required"}

    shape = data.get("shape", "ring")
    if shape not in {"ring", "arrow", "label", "flag"}:
        return {"success": False, "error": f"Invalid shape: {shape}"}

    scope = data.get("scope", "player")
    if scope == "dm":
        is_dm = room.creator_id == user.id or pr.role == Role.DM
        if not is_dm:
            return {"success": False, "error": "Only DM can create dm-scope markers"}

    if shape == "arrow" and ("target_x" not in data or "target_y" not in data):
        return {"success": False, "error": "Arrow requires target_x and target_y"}

    visible_to = data.get("visible_to", [user.name] if scope == "player" else [])
    if scope == "player" and not visible_to:
        visible_to = [user.name]

    existing = ReferenceMarker.get_or_none(
        ReferenceMarker.location == location,
        ReferenceMarker.external_id == external_id,
    )

    if existing:
        is_dm = room.creator_id == user.id or pr.role == Role.DM
        if not is_dm and existing.owner_id != user.id:
            return {"success": False, "error": "Cannot modify another user's marker"}

        if "x" in data:
            existing.x = float(data["x"])
        if "y" in data:
            existing.y = float(data["y"])
        if "shape" in data:
            existing.shape = data["shape"]
        if "label" in data:
            existing.label = data["label"]
        if "text" in data:
            existing.text = data.get("text")
        if "comment" in data:
            existing.comment = data.get("comment")
        if "colour" in data:
            existing.colour = data["colour"]
        if "scope" in data:
            existing.scope = data["scope"]
        if "visible_to" in data:
            existing.visible_to = json.dumps(data["visible_to"])
        if "render_above_fog" in data:
            existing.render_above_fog = data["render_above_fog"]
        if "record" in data:
            existing.record = data["record"]
        if "target_x" in data:
            existing.target_x = float(data["target_x"]) if data["target_x"] is not None else None
        if "target_y" in data:
            existing.target_y = float(data["target_y"]) if data["target_y"] is not None else None

        with db.atomic():
            existing.save()

        marker = existing
    else:
        with db.atomic():
            marker = ReferenceMarker.create(
                external_id=external_id,
                location=location,
                owner=user,
                x=float(data.get("x", 0)),
                y=float(data.get("y", 0)),
                target_x=float(data["target_x"]) if data.get("target_x") is not None else None,
                target_y=float(data["target_y"]) if data.get("target_y") is not None else None,
                shape=shape,
                label=data.get("label", ""),
                text=data.get("text"),
                comment=data.get("comment"),
                colour=data.get("colour"),
                scope=scope,
                visible_to=json.dumps(visible_to),
                render_above_fog=data.get("render_above_fog", True),
                record=data.get("record", True),
            )

    rev = next_revision()
    await broadcast_revision(rev, location.get_path())

    marker_data = _marker_to_dict(marker)

    # Broadcast to appropriate clients
    if scope == "dm":
        for rp in room.players:
            if rp.role == Role.DM:
                for psid in game_state.get_sids(player=rp.player, active_location=location):
                    await _send_game("ReferenceMarker.Add", marker_data, room=psid)
        for psid in game_state.get_sids(player=room.creator, active_location=location):
            await _send_game("ReferenceMarker.Add", marker_data, room=psid)
    else:
        for username in visible_to:
            from ...db.models.user import User
            target = User.get_or_none(User.name == username)
            if target:
                for psid in game_state.get_sids(player=target, active_location=location):
                    await _send_game("ReferenceMarker.Add", marker_data, room=psid)
        for rp in room.players:
            if rp.role == Role.DM:
                for psid in game_state.get_sids(player=rp.player, active_location=location):
                    await _send_game("ReferenceMarker.Add", marker_data, room=psid)
        for psid in game_state.get_sids(player=room.creator, active_location=location):
            await _send_game("ReferenceMarker.Add", marker_data, room=psid)

    return {"success": True, "data": {**marker_data, "revision": rev}}


@sio.on("ReferenceMarker.Delete", namespace=GAME_NS)
@auth.login_required(app, sio, "game")
async def delete_reference_marker(sid: str, data: dict):
    pr: PlayerRoom = game_state.get(sid)
    user = pr.player
    location = pr.active_location
    room = pr.room

    external_id = data.get("external_id", "")
    if not external_id:
        return {"success": False, "error": "external_id required"}

    marker = ReferenceMarker.get_or_none(
        ReferenceMarker.location == location,
        ReferenceMarker.external_id == external_id,
    )
    if not marker:
        return {"success": False, "error": "Marker not found"}

    is_dm = room.creator_id == user.id or pr.role == Role.DM
    if not is_dm and marker.owner_id != user.id:
        return {"success": False, "error": "Cannot delete another user's marker"}

    marker_scope = marker.scope
    marker_visible_to = marker.visible_to

    with db.atomic():
        marker.delete_instance()

    rev = next_revision()
    await broadcast_revision(rev, location.get_path())

    # Broadcast removal respecting scope
    try:
        vis = json.loads(marker_visible_to)
    except (json.JSONDecodeError, TypeError):
        vis = []

    payload = {"external_id": external_id}
    if marker_scope == "dm":
        for rp in room.players:
            if rp.role == Role.DM:
                for psid in game_state.get_sids(player=rp.player, active_location=location):
                    await _send_game("ReferenceMarker.Remove", payload, room=psid)
        for psid in game_state.get_sids(player=room.creator, active_location=location):
            await _send_game("ReferenceMarker.Remove", payload, room=psid)
    else:
        for username in vis:
            from ...db.models.user import User
            target = User.get_or_none(User.name == username)
            if target:
                for psid in game_state.get_sids(player=target, active_location=location):
                    await _send_game("ReferenceMarker.Remove", payload, room=psid)
        for rp in room.players:
            if rp.role == Role.DM:
                for psid in game_state.get_sids(player=rp.player, active_location=location):
                    await _send_game("ReferenceMarker.Remove", payload, room=psid)
        for psid in game_state.get_sids(player=room.creator, active_location=location):
            await _send_game("ReferenceMarker.Remove", payload, room=psid)

    return {"success": True, "data": {"external_id": external_id, "revision": rev}}
