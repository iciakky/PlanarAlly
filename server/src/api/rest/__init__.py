"""
REST API route registration and endpoint handlers.

This module sets up all REST API routes under /api/v1/*.
"""

from aiohttp import web

from .helpers import ok, require_role
from .middleware import api_key_middleware
from . import access
from . import actions
from . import assets
from . import auth
from . import combats
from . import diagnostics
from . import events
from . import fog
from . import grid_options
from . import map_refs
from . import markers
from . import options
from . import players
from . import quick
from . import rolls
from . import rooms
from . import scenes
from . import shapes
from . import tokens
from . import visibility


async def health_check(request: web.Request) -> web.Response:
    """
    Health check endpoint for testing middleware.

    GET /api/v1/health
    """
    api_key = request.get("api_key")
    return ok({
        "status": "ok",
        "message": "REST API is running",
        "authenticated": api_key is not None,
        "role": api_key.role if api_key else None,
    })


@require_role("dm")
async def dm_test(request: web.Request) -> web.Response:
    """
    Test endpoint for DM role enforcement.

    GET /api/v1/test/dm
    """
    return ok({"message": "DM access granted"})


@require_role("dm", "player")
async def player_test(request: web.Request) -> web.Response:
    """
    Test endpoint for player/DM role enforcement.

    GET /api/v1/test/player
    """
    api_key = request.get("api_key")
    return ok({
        "message": f"Access granted to {api_key.role}",
        "role": api_key.role,
    })


def setup_rest_routes(app: web.Application) -> None:
    """
    Register all REST API routes and middleware.

    This function is called from app.py during application setup.

    Args:
        app: aiohttp Application instance
    """
    # Add middleware
    app.middlewares.append(api_key_middleware)

    # Health check and test endpoints
    app.router.add_get("/api/v1/health", health_check)
    app.router.add_get("/api/v1/test/dm", dm_test)
    app.router.add_get("/api/v1/test/player", player_test)

    # Authentication endpoints (Phase 3)
    app.router.add_post("/api/v1/auth/keys", auth.create_api_key)
    app.router.add_get("/api/v1/auth/keys", auth.list_api_keys)
    app.router.add_route("DELETE", "/api/v1/auth/keys/{id}", auth.revoke_api_key)

    # Scene endpoints (Phase 4)
    app.router.add_get("/api/v1/scenes", scenes.list_scenes)
    app.router.add_post("/api/v1/scenes", scenes.create_scene)
    app.router.add_get("/api/v1/scenes/{uuid}", scenes.get_scene)
    app.router.add_route("PUT", "/api/v1/scenes/{uuid}", scenes.update_scene)
    app.router.add_route("DELETE", "/api/v1/scenes/{uuid}", scenes.delete_scene)
    app.router.add_get("/api/v1/scenes/{uuid}/state", scenes.get_scene_state)

    # Token endpoints (Phase 5, Phase 13 & Phase 17)
    app.router.add_get("/api/v1/scenes/{uuid}/tokens", tokens.list_tokens)
    app.router.add_post("/api/v1/scenes/{uuid}/tokens", tokens.create_token)
    app.router.add_post("/api/v1/scenes/{uuid}/tokens/batch", tokens.batch_tokens)  # Phase 17: Batch operations
    app.router.add_get("/api/v1/tokens/{uuid}", tokens.get_token)
    app.router.add_route("PATCH", "/api/v1/tokens/{uuid}", tokens.update_token)
    app.router.add_route("DELETE", "/api/v1/tokens/{uuid}", tokens.delete_token)
    app.router.add_route("PATCH", "/api/v1/tokens/{uuid}/vision", tokens.update_token_vision)  # Phase 13

    # Event endpoints (Phase 7, Phase 14 & Phase 15)
    app.router.add_get("/api/v1/events", events.query_events)
    app.router.add_post("/api/v1/events/note", events.create_dm_note)
    app.router.add_get("/api/v1/events/stream", events.event_stream)  # SSE streaming (Phase 14)
    app.router.add_get("/api/v1/events/export", events.export_events)  # Event export (Phase 15)

    # Roll endpoints (Phase 9)
    app.router.add_post("/api/v1/rolls", rolls.create_roll)
    app.router.add_get("/api/v1/rolls/{uuid}", rolls.get_roll)
    app.router.add_get("/api/v1/rolls", rolls.list_rolls)

    # Combat endpoints (Phase 10)
    app.router.add_post("/api/v1/scenes/{uuid}/combats", combats.start_combat)
    app.router.add_get("/api/v1/scenes/{uuid}/combats/active", combats.get_active_combat)
    app.router.add_get("/api/v1/combats/{uuid}", combats.get_combat)
    app.router.add_route("PATCH", "/api/v1/combats/{uuid}/next", combats.advance_turn)
    app.router.add_route("PATCH", "/api/v1/combats/{uuid}/initiative", combats.modify_initiative)
    app.router.add_post("/api/v1/combats/{uuid}/add", combats.add_combatant)
    app.router.add_route("DELETE", "/api/v1/combats/{uuid}/remove/{actor_uuid}", combats.remove_combatant)
    app.router.add_post("/api/v1/combats/{uuid}/end", combats.end_combat)
    app.router.add_get("/api/v1/combats/{uuid}/round", combats.get_round_info)

    # Action endpoints (Phase 11)
    app.router.add_post("/api/v1/scenes/{uuid}/actions", actions.submit_action)
    app.router.add_get("/api/v1/scenes/{uuid}/actions", actions.list_actions)
    app.router.add_get("/api/v1/actions/{uuid}", actions.get_action)
    app.router.add_route("PATCH", "/api/v1/actions/{uuid}", actions.review_action)

    # Fog endpoints (Phase 12)
    app.router.add_post("/api/v1/scenes/{uuid}/fog/reveal", fog.reveal_fog)
    app.router.add_post("/api/v1/scenes/{uuid}/fog/hide", fog.hide_fog)
    app.router.add_get("/api/v1/scenes/{uuid}/fog", fog.get_fog_state)

    # Quick command endpoints (Phase 16)
    app.router.add_post("/api/v1/quick/damage", quick.apply_damage)
    app.router.add_post("/api/v1/quick/heal", quick.apply_heal)
    app.router.add_post("/api/v1/quick/move", quick.move_token)
    app.router.add_post("/api/v1/quick/condition", quick.update_condition)
    app.router.add_post("/api/v1/quick/kill", quick.kill_token)

    # Player endpoints (Phase 18)
    app.router.add_get("/api/v1/players", players.list_players)
    app.router.add_get("/api/v1/players/{id}/tokens", players.get_player_tokens)
    app.router.add_post("/api/v1/players/{id}/message", players.send_message)

    # Snapshot endpoints (Phase 19)
    app.router.add_post("/api/v1/scenes/{uuid}/snapshot", scenes.create_snapshot)
    app.router.add_get("/api/v1/scenes/{uuid}/snapshots", scenes.list_snapshots)
    app.router.add_post("/api/v1/scenes/{uuid}/restore/{snap_id}", scenes.restore_snapshot)

    # Asset upload (Automation API)
    app.router.add_post("/api/v1/assets", assets.upload_asset)

    # Room management (Automation API)
    app.router.add_post("/api/v1/rooms", rooms.create_room_endpoint)
    app.router.add_post("/api/v1/rooms/{room_id}/players", rooms.add_player_to_room)

    # Generic shape management (Automation API)
    app.router.add_post("/api/v1/scenes/{scene_id}/shapes", shapes.create_shape_endpoint)
    app.router.add_get("/api/v1/scenes/{scene_id}/shapes", shapes.query_shape_by_external_id)
    app.router.add_route("PUT", "/api/v1/scenes/{scene_id}/shapes/by-external-id/{external_id}", shapes.upsert_shape_by_external_id)

    # Shape access control (Automation API)
    app.router.add_route("PATCH", "/api/v1/shapes/{uuid}/access", access.update_shape_access)

    # Scene options (Automation API)
    app.router.add_route("PATCH", "/api/v1/scenes/{uuid}/options", options.update_scene_options)

    # Diagnostics (Automation API)
    app.router.add_get("/api/v1/scenes/{uuid}/diagnostics", diagnostics.scene_diagnostics)

    # Visibility (Automation API)
    app.router.add_get("/api/v1/scenes/{uuid}/visibility", visibility.scene_visibility)

    # Reference Markers (Live Pointing)
    app.router.add_route("PUT", "/api/v1/scenes/{scene_id}/markers/by-external-id/{external_id}", markers.upsert_marker)
    app.router.add_route("DELETE", "/api/v1/scenes/{scene_id}/markers/by-external-id/{external_id}", markers.delete_marker)
    app.router.add_route("DELETE", "/api/v1/scenes/{scene_id}/markers", markers.batch_delete_markers)
    app.router.add_get("/api/v1/scenes/{scene_id}/markers", markers.list_markers)

    # Map References (Live Pointing)
    app.router.add_post("/api/v1/scenes/{scene_id}/map-refs", map_refs.create_map_ref)
    app.router.add_get("/api/v1/scenes/{scene_id}/map-refs", map_refs.query_map_refs)

    # Grid Options (Live Pointing)
    app.router.add_route("PATCH", "/api/v1/scenes/{scene_id}/grid-options", grid_options.update_grid_options)
