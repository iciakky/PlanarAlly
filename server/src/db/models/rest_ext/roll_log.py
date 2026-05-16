from __future__ import annotations

import json
from datetime import datetime
from typing import cast

from peewee import BooleanField, DateTimeField, ForeignKeyField, IntegerField, TextField

from ...base import BaseDbModel
from ..shape import Shape
from .action_declaration import ActionDeclaration
from .combat_ext import CombatExt


class RollLog(BaseDbModel):
    """Dice roll history for audit trail.

    Stores complete roll information including all individual dice results.
    """
    uuid = cast(str, TextField(primary_key=True))
    roller = cast(Shape | None, ForeignKeyField(Shape, backref="rolls", on_delete="SET NULL", null=True))  # Who rolled
    combat = cast(CombatExt | None, ForeignKeyField(CombatExt, backref="rolls", on_delete="SET NULL", null=True))  # Combat context
    action = cast(ActionDeclaration | None, ForeignKeyField(ActionDeclaration, backref="rolls", on_delete="SET NULL", null=True))  # Action context
    dice_notation = cast(str, TextField())  # Original notation (e.g., "1d20+5")
    result = cast(str, TextField())  # JSON: {rolls: [[individual, dice, results]], kept: [values], total: N}
    total = cast(int, IntegerField())  # Final result after modifiers
    secret = cast(bool, BooleanField(default=False))  # DM-only roll
    rolled_at = cast(datetime, DateTimeField(default=datetime.now))

    def __repr__(self):
        roller_name = self.roller.name if self.roller else "DM"
        return f"<RollLog {self.dice_notation}={self.total} by {roller_name}>"

    def get_result(self) -> dict:
        """Parse result from JSON string."""
        return json.loads(self.result)

    def set_result(self, result: dict):
        """Serialize result to JSON string."""
        self.result = json.dumps(result)
