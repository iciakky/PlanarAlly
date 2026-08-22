"""Reference marker model for live pointing feature."""

from __future__ import annotations

import datetime
from typing import cast

from peewee import (
    BooleanField,
    DateTimeField,
    FloatField,
    ForeignKeyField,
    TextField,
)

from ...base import BaseDbModel
from ..location import Location
from ..user import User


class ReferenceMarker(BaseDbModel):
    """A reference marker placed on the map for live pointing/memory.

    Markers can be rings, arrows, labels, or flags. They support
    visibility scoping (dm-only or specific players) and persistence options.
    """

    id: int

    external_id = cast(str, TextField())
    location = cast(
        Location,
        ForeignKeyField(Location, backref="reference_markers", on_delete="CASCADE"),
    )
    owner = cast(
        User,
        ForeignKeyField(User, backref="owned_markers", on_delete="CASCADE"),
    )
    x = cast(float, FloatField())
    y = cast(float, FloatField())
    target_x = cast(float | None, FloatField(null=True))
    target_y = cast(float | None, FloatField(null=True))
    shape = cast(str, TextField())  # ring, arrow, label, flag
    label = cast(str, TextField())
    text = cast(str | None, TextField(null=True))
    comment = cast(str | None, TextField(null=True))
    colour = cast(str | None, TextField(null=True))
    scope = cast(str, TextField(default="player"))  # "player" or "dm"
    visible_to = cast(str, TextField(default="[]"))  # JSON array of usernames
    render_above_fog = cast(bool, BooleanField(default=True))
    record = cast(bool, BooleanField(default=True))
    metadata = cast(str | None, TextField(null=True))  # JSON string
    created_at = cast(datetime.datetime, DateTimeField(default=datetime.datetime.now))

    class Meta:
        indexes = ((("location", "external_id"), True),)

    def __repr__(self):
        return f"<ReferenceMarker {self.external_id} shape={self.shape} owner={self.owner.name}>"
