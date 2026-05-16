from __future__ import annotations

from typing import cast

from peewee import ForeignKeyField, TextField

from ...base import BaseDbModel
from ..location import Location
from ..shape import Shape


class ShapeExternalId(BaseDbModel):
    """Maps caller-defined external IDs to PA's internal shape UUIDs.

    Scoped to (location, external_id) unique — the same external_id can
    exist in different scenes but not within the same scene.
    """

    shape = cast(Shape, ForeignKeyField(Shape, backref="external_ids", on_delete="CASCADE", unique=True))
    location = cast(Location, ForeignKeyField(Location, backref="shape_external_ids", on_delete="CASCADE"))
    external_id = cast(str, TextField())

    class Meta:
        indexes = ((("location", "external_id"), True),)
