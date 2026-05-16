"""Global mutation revision counter for automation sync."""

import logging

from ..helpers import _send_game

logger = logging.getLogger(__name__)

_revision: int = 0


def next_revision() -> int:
    """Return the next revision number. Monotonically increasing within server lifetime."""
    global _revision
    _revision += 1
    return _revision


async def broadcast_revision(revision: int, room_path: str) -> None:
    """Broadcast revision number to connected clients for waitForSync."""
    try:
        await _send_game("Automation.Revision", {"revision": revision}, room=room_path)
    except Exception:
        logger.warning("Failed to broadcast revision %d to %s", revision, room_path, exc_info=True)
