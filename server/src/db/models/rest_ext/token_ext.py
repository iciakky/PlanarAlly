from __future__ import annotations

import json
from typing import cast

from peewee import ForeignKeyField, TextField

from ...base import BaseDbModel
from ..shape import Shape


class TokenExt(BaseDbModel):
    """Extended token attributes for REST API.

    Stores additional token metadata not in PA's core Shape model:
    - faction: Team/side affiliation
    - conditions: Status effects (JSON array of strings)
    - custom: Arbitrary custom attributes (JSON object)
    """
    uuid = cast(str, TextField(primary_key=True))
    shape = cast(Shape, ForeignKeyField(Shape, backref="token_ext", on_delete="CASCADE", unique=True))
    faction = cast(str, TextField())  # "player", "enemy", "neutral"
    conditions = cast(str, TextField(default="[]"))  # JSON: ["stunned", "prone", ...]
    custom = cast(str, TextField(default="{}"))  # JSON: Arbitrary key-value data

    def __repr__(self):
        return f"<TokenExt {self.shape.name} faction={self.faction}>"

    def get_conditions(self) -> list:
        """Parse conditions from JSON string."""
        return json.loads(self.conditions)

    def set_conditions(self, conditions: list):
        """Serialize conditions to JSON string."""
        self.conditions = json.dumps(conditions)

    def get_custom(self) -> dict:
        """Parse custom data from JSON string."""
        return json.loads(self.custom)

    def set_custom(self, custom: dict):
        """Serialize custom data to JSON string."""
        self.custom = json.dumps(custom)
