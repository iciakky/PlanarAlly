"""Map reference model for live pointing feature."""

from __future__ import annotations

import datetime
from typing import cast

from peewee import (
    BooleanField,
    DateTimeField,
    FloatField,
    ForeignKeyField,
    IntegerField,
    TextField,
)

from ...base import BaseDbModel
from ..location import Location
from ..user import User


class MapRef(BaseDbModel):
    """A map reference recording a player's coordinate on the map.

    Can be a pure coordinate ref (x, y, grid) or linked to a marker.
    Used for player-DM communication about map positions.
    """

    id: int

    location = cast(
        Location,
        ForeignKeyField(Location, backref="map_refs", on_delete="CASCADE"),
    )
    player = cast(
        User,
        ForeignKeyField(User, backref="map_refs", on_delete="CASCADE"),
    )
    x = cast(float, FloatField())
    y = cast(float, FloatField())
    grid = cast(str | None, TextField(null=True))
    inside_scene = cast(bool | None, BooleanField(null=True))
    scene_bounds_source = cast(str | None, TextField(null=True))
    direction_from_bounds = cast(str | None, TextField(null=True))
    marker_id = cast(str | None, TextField(null=True))
    comment = cast(str | None, TextField(null=True))
    revision = cast(int | None, IntegerField(null=True))
    created_at = cast(
        datetime.datetime, DateTimeField(default=datetime.datetime.now)
    )

    def __repr__(self):
        return f"<MapRef ({self.x}, {self.y}) player={self.player.name}>"
