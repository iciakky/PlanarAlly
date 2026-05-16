from __future__ import annotations

import json
from datetime import datetime
from typing import cast

from peewee import DateTimeField, ForeignKeyField, TextField

from ...base import BaseDbModel
from ..shape import Shape


class ActionDeclaration(BaseDbModel):
    """Player action declaration for DM review workflow.

    Status flow: pending → accepted/rejected/modified
    """
    uuid = cast(str, TextField(primary_key=True))
    actor = cast(Shape, ForeignKeyField(Shape, backref="actions", on_delete="CASCADE"))  # Token performing action
    action_type = cast(str, TextField())  # "attack", "move", "spell", "ability", "other"
    targets = cast(str, TextField(default="[]"))  # JSON: [{"uuid": "...", "type": "token"}, ...]
    status = cast(str, TextField(default="pending"))  # "pending", "accepted", "rejected", "modified"
    meta = cast(str, TextField(default="{}"))  # JSON: Action-specific data (spell name, weapon, etc.)
    dm_note = cast(str | None, TextField(null=True))  # DM feedback
    modifications = cast(str | None, TextField(null=True))  # JSON: DM modifications if status=modified
    submitted_at = cast(datetime, DateTimeField(default=datetime.now))
    reviewed_at = cast(datetime | None, DateTimeField(null=True))

    def __repr__(self):
        actor_name = self.actor.name if self.actor else "unknown"
        return f"<ActionDeclaration {self.action_type} by {actor_name} status={self.status}>"

    def get_targets(self) -> list:
        """Parse targets from JSON string."""
        return json.loads(self.targets)

    def set_targets(self, targets: list):
        """Serialize targets to JSON string."""
        self.targets = json.dumps(targets)

    def get_meta(self) -> dict:
        """Parse meta data from JSON string."""
        return json.loads(self.meta)

    def set_meta(self, meta: dict):
        """Serialize meta data to JSON string."""
        self.meta = json.dumps(meta)

    def get_modifications(self) -> dict | None:
        """Parse modifications from JSON string."""
        return json.loads(self.modifications) if self.modifications else None

    def set_modifications(self, modifications: dict | None):
        """Serialize modifications to JSON string."""
        self.modifications = json.dumps(modifications) if modifications else None
