from __future__ import annotations

import json
from datetime import datetime
from typing import cast

from peewee import DateTimeField, ForeignKeyField, TextField

from ...base import BaseDbModel
from ..location import Location


class SceneSnapshot(BaseDbModel):
    """Scene state snapshots for save/restore functionality.

    Stores complete scene state (tokens, combat, fog) for experimentation.
    """
    uuid = cast(str, TextField(primary_key=True))
    location = cast(Location, ForeignKeyField(Location, backref="snapshots", on_delete="CASCADE"))
    name = cast(str, TextField())  # User-friendly snapshot name
    snapshot_data = cast(str, TextField())  # JSON: Complete serialized scene state
    created_at = cast(datetime, DateTimeField(default=datetime.now))

    def __repr__(self):
        location_name = self.location.name if self.location else "unknown"
        return f"<SceneSnapshot '{self.name}' of {location_name}>"

    def get_snapshot_data(self) -> dict:
        """Parse snapshot data from JSON string."""
        return json.loads(self.snapshot_data)

    def set_snapshot_data(self, data: dict):
        """Serialize snapshot data to JSON string."""
        self.snapshot_data = json.dumps(data)
