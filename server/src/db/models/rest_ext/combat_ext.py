from __future__ import annotations

import json
from typing import cast

from peewee import BooleanField, ForeignKeyField, IntegerField, TextField

from ...base import BaseDbModel
from ..location import Location


class CombatExt(BaseDbModel):
    """Extended combat state for REST API.

    Tracks combat encounters with full initiative order, round/turn tracking.
    Complements PA's Initiative model which stores initiative as a JSON blob.
    """
    uuid = cast(str, TextField(primary_key=True))
    location = cast(Location, ForeignKeyField(Location, backref="combats", on_delete="CASCADE"))
    round_number = cast(int, IntegerField(default=1))  # Current round
    turn_index = cast(int, IntegerField(default=0))  # Index into combatants array
    active = cast(bool, BooleanField(default=True))  # Combat in progress
    combatants = cast(str, TextField(default="[]"))  # JSON: [{uuid, initiative, name, ...}, ...]
    auto_sort = cast(bool, BooleanField(default=True))  # Auto-sort by initiative

    def __repr__(self):
        location_name = self.location.name if self.location else "unknown"
        return f"<CombatExt round={self.round_number} turn={self.turn_index} active={self.active} location={location_name}>"

    def get_combatants(self) -> list:
        """Parse combatants from JSON string."""
        return json.loads(self.combatants)

    def set_combatants(self, combatants: list):
        """Serialize combatants to JSON string."""
        self.combatants = json.dumps(combatants)

    def get_active_combatant(self):
        """Get the currently active combatant."""
        combatants_list = self.get_combatants()
        if not combatants_list or self.turn_index >= len(combatants_list):
            return None
        return combatants_list[self.turn_index]
