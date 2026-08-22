"""Grid display options model for live pointing feature."""

from __future__ import annotations

from typing import cast

from peewee import (
    BooleanField,
    FloatField,
    ForeignKeyField,
    TextField,
)

from ...base import BaseDbModel
from ..location import Location


class GridDisplayOptions(BaseDbModel):
    """Grid display configuration for a scene/location.

    Controls coordinate display, compass, and grid overlay behavior.
    """

    id: int

    location = cast(
        Location,
        ForeignKeyField(
            Location,
            backref="grid_display_options",
            unique=True,
            on_delete="CASCADE",
        ),
    )
    show_coordinates = cast(str, TextField(default="off"))  # off, hover, always
    coordinate_mode = cast(str, TextField(default="xy"))
    origin = cast(str, TextField(default="NW"))
    toggleable = cast(bool, BooleanField(default=True))
    compass_enabled = cast(bool, BooleanField(default=False))
    compass_north_degrees = cast(float, FloatField(default=0))

    def __repr__(self):
        return f"<GridDisplayOptions location={self.location_id} coords={self.show_coordinates}>"
