"""Socket handlers for automation bridge."""

from ... import auth
from ...app import app, sio
from ...db.models.rest_ext.shape_external_id import ShapeExternalId
from ...state.game import game_state
from .constants import GAME_NS


@sio.on("Automation.ExternalIds.Request", namespace=GAME_NS)
@auth.login_required(app, sio, "game")
async def get_external_ids(sid: str, _data):
    pr = game_state.get(sid)
    location = pr.active_location

    mappings = {}
    for eid in ShapeExternalId.select().where(ShapeExternalId.location == location):
        mappings[eid.shape.uuid] = eid.external_id

    return mappings
