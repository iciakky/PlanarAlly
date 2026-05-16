from __future__ import annotations

import json
from datetime import datetime
from typing import cast, TYPE_CHECKING

from peewee import DateTimeField, DeferredForeignKey, ForeignKeyField, IntegerField, TextField

from ...base import BaseDbModel
from ..location import Location
from ..shape import Shape

if TYPE_CHECKING:
    from .combat_ext import CombatExt
    from .action_declaration import ActionDeclaration


class EventLog(BaseDbModel):
    """Event log for complete audit trail of all game actions.

    Supports SSE streaming for real-time monitoring and filtering by various criteria.
    """
    uuid = cast(str, TextField(primary_key=True))
    event_type = cast(str, TextField(index=True))  # "token_created", "hp_changed", "combat_started", etc.
    scene = cast(Location | None, ForeignKeyField(Location, backref="events", on_delete="SET NULL", null=True, index=True))
    actor = cast(Shape | None, ForeignKeyField(Shape, backref="events", on_delete="SET NULL", null=True, index=True))  # Who caused the event
    combat = cast("CombatExt | None", DeferredForeignKey("CombatExt", backref="events", on_delete="SET NULL", null=True))  # Combat context
    action = cast("ActionDeclaration | None", DeferredForeignKey("ActionDeclaration", backref="events", on_delete="SET NULL", null=True))  # Action context
    payload = cast(str, TextField())  # JSON: Event-specific data
    created_at = cast(datetime, DateTimeField(default=datetime.now, index=True))
    sequence_id = cast(int, IntegerField(unique=True))  # Auto-incrementing for SSE Last-Event-ID

    def __repr__(self):
        scene_name = self.scene.name if self.scene else "global"
        return f"<EventLog #{self.sequence_id} {self.event_type} in {scene_name}>"

    def get_payload(self) -> dict:
        """Parse payload from JSON string."""
        return json.loads(self.payload)

    def set_payload(self, payload: dict):
        """Serialize payload to JSON string."""
        self.payload = json.dumps(payload)
