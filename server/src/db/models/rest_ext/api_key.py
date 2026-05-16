from __future__ import annotations

from datetime import datetime
from typing import cast

from peewee import DateTimeField, ForeignKeyField, TextField

from ...base import BaseDbModel
from ..user import User


class ApiKey(BaseDbModel):
    """API key for REST API authentication.

    Supports two roles:
    - dm: Full access to all endpoints
    - player: Limited to action submission and querying owned tokens
    """
    uuid = cast(str, TextField(primary_key=True))
    user = cast(User, ForeignKeyField(User, backref="api_keys", on_delete="CASCADE"))
    role = cast(str, TextField())  # "dm" or "player"
    key = cast(str, TextField(unique=True, index=True))  # Format: "dm-{hex}" or "player-{hex}"
    created_at = cast(datetime, DateTimeField(default=datetime.now))
    last_used_at = cast(datetime | None, DateTimeField(null=True))

    def __repr__(self):
        return f"<ApiKey {self.key[:10]}... role={self.role} user={self.user.name}>"
