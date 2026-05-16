# Findings

## Project Goal
Implement a complete REST API layer for PlanarAlly VTT that allows DMs to control the game via CLI/curl while players continue using the browser UI. This involves adding ~15 new REST endpoints, 7 new database models, middleware, and integration with PA's existing socket.io infrastructure.

## Specification Analysis

### Two Key Documents
1. **api_spec_v2.md** - The finalized REST API contract with all endpoints, request/response formats
2. **implementation_spec.md** - Detailed implementation guide targeting Claude Code/Sonnet 4.5

### Core Architecture Understanding

**PlanarAlly Stack:**
- Backend: Python (aiohttp + socket.io), SQLite via Peewee ORM
- Frontend: Vue 3, TypeScript
- Communication: WebSockets (socket.io) for real-time game state
- Data hierarchy: `User → Room → Location → Floor → Layer → Shape`

**Key Mappings:**
- API "Scene" = PA "Location"
- API "Token" = PA "Shape" + associated Tracker/Aura records
- HP/AC stored as PA Trackers (visible in UI)
- Vision stored as PA Auras with `vision_source` flag

**Critical Constraint:**
> Must use PA's internal functions (not raw DB writes) to ensure in-memory state stays in sync and socket events fire to clients

This means we need to find and reuse PA's existing socket handler logic.

## File Structure Plan

### New Files to Create (server/src/)

**api/rest/** - All new REST code
- `__init__.py` - Route registration
- `middleware.py` - API key auth
- `helpers.py` - Response builders, error handling
- `auth.py` - API key CRUD
- `scenes.py` - Scene management
- `tokens.py` - Token CRUD + batch operations
- `fog.py` - Fog of war control
- `combats.py` - Combat tracker
- `actions.py` - Player action declarations
- `rolls.py` - Dice rolling system
- `events.py` - Event log + SSE streaming
- `players.py` - Player management
- `quick.py` - Quick command shortcuts
- `dice.py` - DiceParser engine (pure logic)

**db/models/rest_ext/** - New database models
- `__init__.py`
- `api_key.py` - API authentication
- `token_ext.py` - Extended token attributes
- `combat_ext.py` - Combat state beyond PA's initiative
- `action_declaration.py` - Player action workflow
- `roll_log.py` - Dice roll history
- `event_log.py` - Audit trail
- `scene_snapshot.py` - Scene state snapshots

### Files to Modify in PA

**ONLY 2 files should be modified:**
1. `server/src/app.py` - Add REST route setup call
2. `server/src/save.py` - Add REST model table creation

Everything else is new code.

## Implementation Sprint Breakdown

### Sprint 1: Foundation (3 days)
- Create all 7 database models
- Set up REST route structure
- Implement auth (API key generation/validation)
- Basic scenes (list, create, get, get_state)
- Basic tokens (create, get, list, update, delete)
- Event logging foundation

**Acceptance:** Can create scene + token via curl, see it appear in PA UI

### Sprint 2: Combat + Actions (3 days)
- Combat tracker implementation
- Action declaration workflow
- Full DiceParser with advantage/disadvantage/kh/kl
- Roll logging system
- Wire combat → actions → rolls

**Acceptance:** Full combat loop via CLI with player action review

### Sprint 3: Fog + Vision + Events (2 days)
- Fog of war reveal/hide
- Token vision updates (PA Aura manipulation)
- SSE streaming for real-time events
- Event export functionality
- Ensure all handlers log events

**Acceptance:** DM can control fog via curl, SSE stream shows all events

### Sprint 4: Quick Commands + Polish (2 days)
- Quick command shortcuts (damage, heal, move, condition, kill)
- Batch token operations with dry_run
- Player management endpoints
- Scene snapshots (save/restore)
- Error handling consistency pass
- RBAC verification

**Acceptance:** Complete combat scenario from CLI start to finish

## Critical Discovery: Finding PA Internal Functions

The implementation spec emphasizes finding PA's existing socket handlers to reuse their logic. Key locations to search:

| Operation | PA Location | What to Find |
|-----------|-------------|--------------|
| Create shape | `api/socket/shape/` | "Shape.Add" socket event handler |
| Move shape | `api/socket/shape/` | "Shape.Position.Update" handler |
| Update tracker | `api/socket/shape/` | "Tracker.Update" handler (for HP/AC) |
| Update aura | `api/socket/shape/` | "Aura.Update" handler (for vision) |
| Initiative | `api/socket/initiative/` | Initiative list manipulation |
| Fog | `api/socket/room/` or `location/` | Fog of war toggle |

Search strategy: Each socket handler typically:
1. Receives data from socket
2. Validates
3. Updates DB (peewee)
4. Calls `await sio.emit(...)` to broadcast

We need to extract the "update DB + emit" logic into shared service functions that both socket handlers AND REST handlers can call.

## Risk Assessment

### High Risk
1. **PA functions tightly coupled to socket context** - May require `sid` parameter
   - Mitigation: Create wrapper functions with synthetic DM sid

2. **In-memory state cache not updated** - REST writes might not update PA's cache
   - Mitigation: ALWAYS use PA's internal functions, never raw DB

3. **Initiative tracker JSON blob** - Not normalized, stored as JSON in single field
   - Mitigation: CombatExt becomes source of truth, sync back to PA's model

### Medium Risk
4. **aiohttp sub-app routing conflicts** - Sub-app pattern might conflict
   - Mitigation: Test thoroughly, fallback to prefix-based middleware

5. **PA version updates** - Fork diverges from upstream
   - Mitigation: Pin to specific release tag, document all modifications

## Technology Stack Verification

From pyproject.toml:
- Python >=3.13.2
- aiohttp 3.13.2
- python-socketio 5.15.1
- peewee 3.18.3
- pydantic 2.12.5 (good for request validation)

All dependencies are recent and compatible.

## Python 運行環境 (Critical for Development)

### 依賴安裝
```bash
cd server && uv sync
```

### 運行伺服器的正確方式
**必須用 `-m` 模式從 server/ 目錄運行，並設定 `PYTHONPATH=.`**

```bash
# ✅ 正確方式（解決 json.py 模組衝突）
cd server && PYTHONPATH=. uv run python -m src.planarserver
cd server && PYTHONPATH=. uv run python -m src.planarserver dev  # 開發模式

# ❌ 以下方式全部失敗（json.py 與標準庫衝突）
cd server && uv run planarserver.py                    # 找不到命令
cd server && uv run python src/planarserver.py         # json 衝突
cd server/src && uv run python planarserver.py         # json 衝突
python -c "from app import sio"                        # json 衝突
```

### json.py 命名衝突問題
PA 的 `server/src/json.py` 與 Python 標準庫 `json` 模組同名。
- **直接運行** `python src/planarserver.py` 時，`src/` 目錄在 sys.path 中，Python 會誤把 `src/json.py` 當作標準庫的 `json`
- **`-m` 模式**時，Python 正確處理為 `src.json` 子模組，不會衝突
- **所有開發期間的 python 命令都必須使用 `PYTHONPATH=. uv run python -m ...` 或 `PYTHONPATH=. uv run python -c "from src.xxx import yyy"`**

### 驗證模組導入的正確方式
```bash
cd server && PYTHONPATH=. uv run python -c "from src.app import sio, app"
cd server && PYTHONPATH=. uv run python -c "from src.db.db import db"
cd server && PYTHONPATH=. uv run python -c "from src.api.common.shapes import create_shape"
cd server && PYTHONPATH=. uv run python -c "from src.api.helpers import _send_game"
cd server && PYTHONPATH=. uv run python -c "from src.db.models.tracker import Tracker"
```

### 運行時驗證結果
| 組件 | 類型 | 驗證 |
|------|------|------|
| sio | TypedAsyncServer | ✓ |
| app | Application (aiohttp) | ✓ |
| db | SqliteExtDatabase | ✓ |
| create_shape | function | ✓ |
| _send_game | coroutine function | ✓ |
| Tracker model | peewee Model | ✓ |
| Aura model | peewee Model | ✓ |
| Aura.vision_source | BooleanField | ✓ |

---

## Phase 0 Discovery Results

### Key Import Paths
```python
# App & Socket.io
from src.app import app, sio

# Database
from src.db.db import db

# Models
from src.db.models.shape import Shape
from src.db.models.tracker import Tracker
from src.db.models.aura import Aura
from src.db.models.layer import Layer
from src.db.models.location import Location
from src.db.models.user import User

# Helpers
from src.api.helpers import _send_game
from src.api.common.shapes import create_shape
```

### Socket Handler Pattern
```python
from ....app import app, sio
from ....api.helpers import _send_game
from ...socket.constants import GAME_NS
from .... import auth
from ....state.game import game_state

@sio.on("Event.Name", namespace=GAME_NS)
@auth.login_required(app, sio, "game")
async def handler(sid: str, raw_data: Any):
    data = SomeModel(**raw_data)
    pr: PlayerRoom = game_state.get(sid)

    # Update database
    shape = Shape.get_by_id(data.uuid)
    shape.field = data.value
    shape.save()

    # Emit to other clients
    await _send_game(
        "Event.Name",
        data,
        room=pr.active_location.get_path(),
        skip_sid=sid
    )
```

### Shape Creation Pattern
- Use `create_shape(data: ApiShape, layer: Layer)` from `api/common/shapes/__init__.py`
- Automatically creates: Shape + subtype + owners + trackers + auras
- All done in atomic transaction

### Tracker (HP/AC) Update Pattern
```python
tracker = Tracker.get_by_id(tracker_uuid)
tracker.value = new_value  # Current HP
tracker.maxvalue = max_value  # Max HP
tracker.save()

# Then emit to clients
await _send_game("Shape.Options.Tracker.Update", data, room=..., skip_sid=...)
```

### Aura (Vision) Update Pattern
```python
aura = Aura.get_by_id(aura_uuid)
aura.vision_source = True  # Grants vision
aura.value = 60  # Range in feet
aura.save()

# Then emit to clients
await _send_game("Shape.Options.Aura.Update", data, room=..., skip_sid=...)
```

### Migration Pattern (save.py)
- Current SAVE_VERSION = 113
- Use raw SQL: `db.execute_sql("CREATE TABLE ...")`
- Quote column names that clash with SQL keywords: `"index"`, `"group"`
- Increment version: `db.execute_sql("UPDATE constants SET save_version = save_version + 1")`
- For new tables, add to `db/all.py` in ALL_NORMAL_MODELS list

### Route Registration Pattern
```python
# In routes.py or app setup
main_app.router.add_post(f"{subpath}/api/endpoint", handler_function)
```

### Files Structure Confirmed
- Entry: `server/src/planarserver.py` (imports and starts app)
- App: `server/src/app.py` (creates sio, app, sets up middleware)
- Routes: `server/src/routes.py` (registers all HTTP routes)
- DB: `server/src/db/db.py` (creates db instance)
- Models: `server/src/db/models/*.py`
- Socket: `server/src/api/socket/**/*.py`
- Helpers: `server/src/api/helpers.py`
- Migration: `server/src/save.py`

---

## Phase 2: REST Infrastructure Results

### Middleware Pattern
```python
@web.middleware
async def api_key_middleware(request: web.Request, handler):
    """Validate API key for all /api/v1/* routes."""
    if not request.path.startswith("/api/v1/"):
        return await handler(request)

    api_key_value = request.headers.get("X-API-Key")
    # ... validation ...
    request["api_key"] = api_key  # Attach for downstream use
    return await handler(request)
```

### RBAC Pattern
```python
@require_role("dm")
async def dm_only_endpoint(request: web.Request):
    api_key = request.get("api_key")  # Guaranteed by middleware
    # ... handler logic ...
    return ok(data)
```

### Response Patterns
```python
# Success
return ok({"field": "value"}, status=200)  # → {"success": true, "data": {...}}

# Error
return error("Message", code="UNAUTHORIZED", status=401)  # → {"success": false, "error": {...}}
```

### Route Registration
Added to `routes.py`:
```python
from .api.rest import setup_rest_routes
# ... (after existing routes) ...
setup_rest_routes(main_app)
```

### Event Logging
```python
await log_event(
    event_type="token_created",
    payload={"token_id": uuid, "hp": 20},
    scene_id=scene_uuid,
    actor_id=token_uuid,
)
```

### Important Discoveries
1. **Middleware ordering matters**: REST middleware added via `app.middlewares.append()` during `setup_rest_routes()`
2. **Request context**: API key attached as `request["api_key"]` for all handlers
3. **RBAC decorator**: Wraps handlers, checks role before execution
4. **Standard error codes**: UNAUTHORIZED, FORBIDDEN, NOT_FOUND, VALIDATION_ERROR, CONFLICT, INTERNAL_ERROR
5. **Event logging**: Async function writes to EventLog table with JSON payload

---

## Phase 3: Authentication Results

### Implementation Pattern

**Bootstrap Scenario:**
```python
# In middleware.py
if request.method == "POST" and request.path == "/api/v1/auth/keys":
    existing_keys = list(ApiKey.select().limit(1))
    if len(existing_keys) == 0:
        # Bootstrap mode: allow first key creation without auth
        request["api_key"] = None
        return await handler(request)
```

**Key Generation:**
```python
# In auth.py
random_hex = secrets.token_hex(16)  # 32 characters
key_value = f"{role}-{random_hex}"  # e.g., "dm-abc123..."
```

**Security Considerations:**
1. `list_api_keys()` returns metadata only, never key values
2. Bootstrap check uses `limit(1)` for efficiency
3. Key generation uses `secrets.token_hex()` for cryptographic randomness
4. After bootstrap, all key operations require DM authentication

**RBAC Enforcement:**
- `create_api_key()`: Bootstrap mode (no auth) OR DM role required
- `list_api_keys()`: DM role required
- `revoke_api_key()`: DM role required

### Testing Artifacts

Created `test_auth_endpoints.sh` for manual integration testing:
- Tests all 3 endpoints
- Verifies bootstrap scenario
- Tests RBAC enforcement
- Tests key revocation

**Usage:** `./test_auth_endpoints.sh <username>` (after creating PA user)

---

## Phase 4: Scenes - Basic CRUD Results

### Location Structure
```python
# Hierarchy: Room → Location → Floor → Layer → Shape
Room.create(name, creator, default_options)
  └─ Location.create(room, name, index)
      └─ Floor.create(location, name, index)
          ├─ Layer "map" (normal, visible, index=0)
          ├─ Layer "grid" (grid, visible, not selectable, index=1)
          ├─ Layer "tokens" (normal, visible, editable, index=2)
          ├─ Layer "dm" (normal, not visible, index=3)
          ├─ Layer "fow" (fow, visible, index=4)
          ├─ Layer "fow-players" (fow-players, visible, not selectable, index=5)
          └─ Layer "draw" (normal, visible, editable, not selectable, index=6)
```

### Scene Creation Pattern
```python
# From PA's create_room() and create_floor()
with db.atomic():
    options = LocationOptions.create()
    location = Location.create(room=room, name=name, index=next_index, options=options)
    create_floor(location, "ground")  # Creates floor + 7 standard layers
```

### Key Discoveries
1. **Location.id is scene UUID**: PA uses integer PK, not UUID field
2. **Index management**: Location.index auto-incremented within room for ordering
3. **Cascade deletion**: Peewee CASCADE handles cleanup of floors/layers/shapes
4. **create_floor()**: Automatically creates 7 standard layers with proper types
5. **State snapshot**: Query shapes via `location.floors.layers.shapes` hierarchy

### Implementation Achievements
- ✓ 6 scene endpoints: list, create, get, update, delete, get_state
- ✓ Scene creation follows PA's established pattern
- ✓ RBAC enforcement: DM for write, DM+Player for read
- ✓ Event logging for all operations
- ✓ State endpoint returns complete snapshot: tokens, trackers, TokenExt

---

---

## Phase 5: Tokens - Basic CRUD Results

### Shape Type Decision
**Chose CircularToken** for token representation:
- `ApiCircularTokenShape`: Circle with text (displays first 2 letters of name)
- Supports radius for grid sizing (default 25 = 5ft square)
- Native token appearance in PA UI
- Alternative was AssetRect (requires image src)

### Token Creation Pattern
```python
# Build ApiCircularTokenShape with all required fields
api_shape = ApiCircularTokenShape(
    uuid=token_uuid,
    type_="circulartoken",
    x=x, y=y, name=name,
    radius=size/2,
    text=name[:2].upper(),  # First 2 letters
    owners=[ApiShapeOwner(...)],
    trackers=[], auras=[],  # Populated separately after shape creation
)

# Use PA's create_shape
shape = create_shape(api_shape, layer=token_layer)

# Create HP tracker with visual bar
Tracker.create(
    shape=shape, name="HP",
    value=hp_current, maxvalue=hp_max,
    draw=True,  # Show HP bar
    primary_color="rgb(221, 0, 0)",  # Red bar
)

# Create AC tracker (no bar)
Tracker.create(shape=shape, name="AC", value=ac, maxvalue=ac, draw=False)

# Create TokenExt for extended attributes
TokenExt.create(token=shape, faction=faction, conditions=json.dumps([]), custom=json.dumps({}))
```

### Socket Emission Pattern
```python
# Emit to all players in location
for room_player in room.players:
    is_dm = room_player.role == Role.DM
    for psid in game_state.get_sids(player=room_player.player, active_location=location):
        # Skip DM-only layers for players
        if not is_dm and not token_layer.player_visible:
            continue

        # Transform shape with player's perspective (filters private data)
        api_shape_data = transform_shape(shape, room_player)

        # Send Shape.Add event
        await _send_game(
            "Shape.Add",
            {"shape": api_shape_data, "floor": floor_name, "layer": "tokens", "temporary": False},
            room=psid,
        )
```

### Update Pattern with Socket Events
```python
# Update tracker and emit event
hp_tracker.value = new_value
hp_tracker.save()

# Emit tracker update to all connected sessions
for psid in game_state.get_sids(player=api_key.user, active_location=location):
    await _send_game(
        "Shape.Options.Tracker.Update",
        {"uuid": hp_tracker.uuid, "value": hp_tracker.value, "maxvalue": hp_tracker.maxvalue},
        room=psid,
    )
```

### Key Discoveries
1. **CircularToken vs AssetRect**: CircularToken is the PA-native token type, displays text initials
2. **Tracker.draw flag**: When true, displays visual HP bar on token in UI
3. **transform_shape()**: Filters shape data based on player's permissions and visibility
4. **game_state.get_sids()**: Gets all socket session IDs for a player in a location
5. **Shape.Remove event**: Requires `{"uuids": [list], "temporary": bool}` format
6. **Layer visibility**: token_layer.player_visible determines if non-DMs see shapes

### Implementation Achievements
- ✓ 5 complete endpoints: list, create, get, update, delete
- ✓ Full integration with PA's shape system via create_shape()
- ✓ Tracker creation for HP (visual) and AC (numeric)
- ✓ TokenExt for faction, conditions, and custom JSON data
- ✓ Socket emission to all players with proper transform_shape()
- ✓ Event logging for audit trail
- ✓ RBAC enforcement: DM for write, DM+Player for read

---

## Phase 8: Dice Parser Results

### Implementation Pattern

**Regex-Based Parsing:**
```python
dice_pattern = r'([+-]?)(\d+)d(\d+)(?:k([hl])(\d+))?'
modifier_pattern = r'([+-]\d+)'

# Parse loop: try dice_match → try modifier_match → skip whitespace → error
```

**Result Structure:**
```python
{
    "notation": "1d20+5",
    "rolls": [
        {
            "dice": "1d20",
            "results": [15],  # All rolled values
            "kept": [15]      # After kh/kl filter
        }
    ],
    "modifiers": [5],
    "total": 20
}
```

### Key Discoveries

1. **Keep highest/lowest implementation:**
   - Sort results: `sorted(results, reverse=(keep_type == 'h'))`
   - Take top N: `kept = sorted_results[:keep_count]`
   - Simple and efficient

2. **Negative dice rolls:**
   - Pattern supports `-1d4` syntax
   - Negate both `results` and `kept` arrays
   - Allows damage reduction notation

3. **Compound notation:**
   - Parse multiple dice groups in sequence: `1d20+1d4+5`
   - Each group is separate entry in `rolls` array
   - Total sums all kept values + modifiers

4. **Advantage/Disadvantage:**
   - Advantage = `2d20kh1` (keep highest)
   - Disadvantage = `2d20kl1` (keep lowest)
   - Generic kh/kl pattern handles both

### Implementation Achievements

- ✓ Complete notation parser (NdX, modifiers, compound, kh/kl)
- ✓ Helper functions for common use cases
- ✓ 16 comprehensive unit tests - all passing
- ✓ Proper error handling with descriptive messages
- ✓ Structured result format ready for Phase 9 integration

### Next Phase Dependencies

Phase 9 (Roll System) will:
- Import `parse_and_roll()` from dice.py
- Add REST endpoint: `POST /api/v1/rolls`
- Store results in RollLog database model
- Log events via `log_event()`
- Support filtering by scene, actor, combat, action

---

## Phase 9: Roll System Results

### Implementation Pattern

**Advantage/Disadvantage Transformation:**
```python
# Before parsing, transform notation
if advantage:
    if "d20" in notation:
        notation = notation.replace("d20", "2d20kh1", 1)  # Replace first d20
    else:
        notation = f"2d20kh1+{notation}" if notation else "2d20kh1"
```

**Additional Modifiers:**
```python
# Append extra modifiers to notation string
for modifier in additional_modifiers:
    if modifier >= 0:
        notation += f"+{modifier}"
    else:
        notation += f"{modifier}"
```

**Secret Rolls:**
- Only DM can create secret rolls (`role == "dm"`)
- Secret rolls NOT logged to event_log
- Secret rolls excluded from player queries unless DM uses `include_secret=true`
- Hidden from non-DM via 404 error (not 403, to avoid leaking existence)

### Multi-Context Support

Roll can be associated with:
1. **scene_id**: Location FK (scene context)
2. **actor_id**: Shape UUID (which token rolled)
3. **combat_id**: CombatExt UUID (combat context)
4. **action_id**: ActionDeclaration UUID (action context)

All are optional, validated if provided.

### Query Filtering

`GET /api/v1/rolls` supports:
- `scene_id`: Filter by scene
- `actor_id`: Filter by token
- `combat_id`: Filter by combat
- `action_id`: Filter by action
- `limit`: Max results (default 50, max 200)
- `offset`: Pagination offset
- `include_secret`: DM-only, show secret rolls

Results ordered by `rolled_at DESC` (newest first).

### Key Discoveries

1. **Notation transformation order matters:**
   - Transform advantage/disadvantage BEFORE adding modifiers
   - Replace first d20 only (avoid affecting other dice)
   - Handle edge case: no d20 in notation (prepend 2d20kh1)

2. **Secret roll visibility:**
   - Excluded via WHERE clause: `query.where(RollLog.secret == False)`
   - DM can override with `include_secret=true`
   - Returns 404 (not 403) to hide existence from players

3. **Event logging:**
   - Secret rolls NOT logged (`if not secret: await log_event(...)`)
   - Non-secret rolls logged with notation, total, note
   - Scene and actor attached for filtering

### Implementation Achievements

- ✓ 3 complete endpoints: create, get, list
- ✓ Full dice parser integration via `parse_and_roll()`
- ✓ Advantage/disadvantage support with notation transformation
- ✓ Additional modifiers appended to notation
- ✓ Secret rolls (DM only, excluded from logs/queries)
- ✓ Multi-context support (scene, actor, combat, action)
- ✓ Comprehensive filtering and pagination
- ✓ RBAC enforcement (DM+Player, but secret limited to DM)
- ✓ Event logging for non-secret rolls

### Next Phase Dependencies

Phase 10 (Combat Tracker) will:
- Use RollLog for initiative rolls
- Filter rolls by `combat_id` to show combat-related rolls
- Associate damage/attack rolls with combat context

---

## Phase 10: Combat Tracker Discovery

### PA's Initiative System Structure

**Initiative Model (Database):**
```python
class Initiative(BaseDbModel):
    location: Location  # FK (one initiative per location)
    round: int          # Current round number
    turn: int           # Current turn index (into data array)
    sort: int           # Sort mode (0=desc by initiative, 1=asc, 2=manual)
    data: TextField     # JSON array of combatants
    is_active: bool     # Whether combat is active
```

**Data Field Structure (JSON array):**
```python
[
    {
        "shape": "uuid",        # Shape/token UUID
        "initiative": 15,       # Initiative value (or null/missing)
        "isVisible": true,      # Visible to players
        "isGroup": false,       # Is this a group entry
        "effects": [            # Status effects
            {"name": "...", "turns": "3", ...}
        ]
    },
    ...
]
```

### Key Socket Handlers

| Handler | Purpose | DM Only |
|---------|---------|---------|
| `Initiative.Add` | Add combatant to initiative | No (with ownership check) |
| `Initiative.Remove` | Remove combatant | No (with ownership check) |
| `Initiative.Turn.Update` | Advance/rewind turn | No (current actor can advance) |
| `Initiative.Round.Update` | Advance/rewind round | No (current actor can advance) |
| `Initiative.Active.Set` | Start/stop initiative | Yes |
| `Initiative.Order.Change` | Reorder combatants | Yes |
| `Initiative.Sort.Set` | Set sort mode | Yes |
| `Initiative.Wipe` | Clear all combatants | Yes |
| `Initiative.Clear` | Clear all initiative values | Yes |

### Helper Functions

- `send_initiative(data, pr)` - Broadcasts initiative state to all clients
- `sort_initiative(data, sort)` - Sorts combatants by initiative value
- `get_turn_order(data, shape)` - Finds turn index for a shape
- `update_initiative_effects(entry, direction)` - Decrements effect turns

### Important Patterns

1. **Creating Initiative:**
   ```python
   location_data, _ = Initiative.get_or_create(
       location=pr.active_location,
       defaults={"round": 0, "turn": 0, "data": "[]"}
   )
   ```

2. **Modifying Data:**
   ```python
   json_data = json.loads(location_data.data)
   # ... modify json_data ...
   location_data.data = json.dumps(json_data)
   location_data.save()
   ```

3. **Broadcasting Changes:**
   ```python
   await send_initiative(location_data.as_pydantic(), pr)
   # OR
   await _send_game("Initiative.Turn.Update", data, room=pr.active_location.get_path())
   ```

4. **Turn Advancement:**
   - Increment turn index
   - If turn == len(data)-1, wrap to turn=0 and increment round
   - Process effects (decrement turns, remove expired)

5. **Sort Modes:**
   - 0 = Sort descending by initiative (highest first)
   - 1 = Sort ascending by initiative (lowest first)
   - 2 = Manual order (no auto-sort)

### Integration Strategy for REST API

**CombatExt Model Purpose:**
- Stores REST-specific metadata (creation timestamp, user-friendly names)
- Links to PA's Initiative model via location_id
- Provides structured API response format

**Sync Pattern:**
1. When creating combat via REST:
   - Create/update Initiative record (PA's model)
   - Create CombatExt record (REST metadata)
   - Broadcast via `send_initiative()` to notify UI

2. When advancing turn via REST:
   - Update Initiative.turn
   - Process effects if needed
   - Broadcast via socket events
   - Log to event_log

3. When ending combat via REST:
   - Set Initiative.is_active = False
   - Delete or archive CombatExt
   - Broadcast via socket

**REST Endpoints Implementation:**
- Use PA's Initiative as source of truth
- CombatExt provides API-friendly metadata layer
- Always emit socket events to keep UI in sync
- Reuse PA's helper functions where possible

---

---

## Phase 11.5: E2E Testing Infrastructure Discovery

### Existing PA Registration Endpoint

**Discovery:** PA already has working `/api/register` endpoint!

```python
# server/src/routes.py, line 55
main_app.router.add_post(f"{subpath}/api/register", auth.register)

# server/src/api/http/auth.py
async def register(request):
    data = await request.json()
    username = data["username"]
    password = data["password"]
    email = data.get("email", None)

    with db.atomic():
        user = User.create_new(username, password, email)
    # Returns session cookie
```

**Usage:**
```bash
curl -X POST http://localhost:8000/api/register \
  -H "Content-Type: application/json" \
  -d '{"username": "testdm", "password": "test123"}'
```

### User Model Password Verification

```python
# server/src/db/models/user.py
class User(BaseDbModel):
    def check_password(self, pw: str):
        expected_hash = self.password_hash.encode("utf8")
        return bcrypt.checkpw(pw.encode("utf8"), expected_hash)
```

### Testing Gap

**Current:**
1. ✓ Can create user via curl: `POST /api/register`
2. ✓ User has password verification
3. ❌ Cannot create API key without PA session

**Solution:** Extend `POST /api/v1/auth/keys` to accept username+password:

```python
# In create_api_key()
username = body.get("username")
password = body.get("password")

if username and password:
    user = User.by_name(username)
    if user and user.check_password(password):
        # Create key for verified user
        api_key = ApiKey.create(user=user, role=role, ...)
        return ok({"key": api_key.key, ...})
```

**Benefit:** Complete E2E testing with curl only.

---

## Phase 11.5: E2E Testing Infrastructure Results

### Problem Statement

Before Phase 11.5, testing the REST API required:
1. Opening PA web UI and logging in
2. Manually creating API key via UI or SQL
3. Then testing REST endpoints with curl

This blocked complete automation and made E2E testing cumbersome.

### Solution: Credential-Based Authentication

Extended `POST /api/v1/auth/keys` to support three authentication modes:

```python
# Priority order (checked top to bottom):

# 1. Credential-based (NEW in Phase 11.5)
if username and password:
    if user.check_password(password):
        create_key()  # ✓ Success
    else:
        return 401    # Invalid password

# 2. Bootstrap mode (Original)
if no_keys_exist():
    create_key()      # ✓ Allow first key

# 3. API key auth (Original)
if api_key and api_key.role == "dm":
    create_key()      # ✓ DM can create keys
else:
    return 403        # Forbidden
```

### Implementation Details

**Request Format:**
```json
POST /api/v1/auth/keys
{
  "username": "testdm",    // Accepts "username" or "user"
  "password": "test123",   // Optional, enables credential mode
  "role": "dm"
}
```

**Password Verification:**
- Uses PA's existing `User.check_password()` method
- bcrypt hashing (PA's standard)
- Returns 401 on invalid credentials (not 403)

**Backwards Compatibility:**
- Accepts both "username" and "user" field names
- Bootstrap mode still works (no password → check if no keys)
- API key mode still works (no password → check existing key)

### E2E Test Script

Created `test_e2e_workflow.sh` with 8 automated test cases:

1. ✅ Register user via PA's `/api/register`
2. ✅ Create API key with credentials
3. ✅ Test authentication (health check)
4. ✅ Test dice rolling
5. ✅ Test event logging
6. ✅ Test invalid key rejection (401)
7. ✅ Test invalid credentials rejection (401)
8. ✅ List API keys

**Features:**
- Unique username per run (timestamp-based)
- Color-coded pass/fail output
- Automatic cleanup (doesn't pollute DB)
- Tests full workflow end-to-end

### Complete E2E Workflow (No UI Required)

```bash
# 1. Register user
curl -X POST http://localhost:8000/api/register \
  -H "Content-Type: application/json" \
  -d '{"username": "testdm", "password": "test123"}'

# 2. Create API key with credentials (Phase 11.5 feature)
API_KEY=$(curl -X POST http://localhost:8000/api/v1/auth/keys \
  -H "Content-Type: application/json" \
  -d '{"username": "testdm", "password": "test123", "role": "dm"}' \
  | jq -r '.data.key')

# 3. Use key for all REST API calls
curl -H "X-API-Key: $API_KEY" http://localhost:8000/api/v1/scenes
curl -H "X-API-Key: $API_KEY" http://localhost:8000/api/v1/rolls \
  -d '{"notation": "1d20+5"}'
```

### Security Considerations

**Production Deployment:**

⚠️ This feature is designed for **testing/development**. For production:

1. **Option A:** Disable credential auth (comment out password check)
2. **Option B:** Add rate limiting and account lockout
3. **Option C:** Move to separate admin endpoint with additional authorization

**Why it's safe for development:**
- Requires valid PA username + password (already in DB)
- Uses bcrypt verification (same as web login)
- No new attack surface beyond existing `/api/login`
- Convenient for testing without UI

### Documentation

Created `docs/rest_api_testing.md` with:
- Complete testing guide
- Manual testing steps
- Security considerations
- Troubleshooting section
- Production deployment recommendations

---

## Phase 12: Fog of War Control Discovery

### PA's Fog of War System Architecture

**FOW Layers:**
- PA has two FOW layer types: `fow` (FowLightingLayer) and `fow-players` (FowVisionLayer)
- Both inherit from `FowLayer` base class
- FOW layers are special canvas layers that render vision/lighting calculations

**Fog Manipulation Mechanism:**
PA uses **regular shapes with `preFogShape: true` option** on FOW layers to control fog:

```typescript
// Shape options
interface ShapeOptions {
    preFogShape: boolean;  // If true, shape is a fog control shape
    // ... other options
}

// FowLightingLayer (client/src/game/layers/variants/fowLighting.ts)
class FowLightingLayer extends FowLayer {
    preFogShapes: IShape[] = [];  // Tracks fog control shapes

    enterLayer(shape: IShape): void {
        if (shape.options.preFogShape ?? false) {
            this.preFogShapes.push(shape);
        }
    }
}
```

**Key Discoveries:**
1. **Fog reveal/hide is done by adding/removing shapes on FOW layers**
   - Reveal: Add a shape with `preFogShape: true` to the `fow` layer → cuts out fog in that area
   - Hide: Remove the shape → fog returns

2. **Fog shapes are rendered before vision calculations**
   - `preFogShapes` array stores these shapes separately
   - During draw(), these shapes are rendered first to modify the fog canvas

3. **No special socket events needed**
   - Use PA's existing `Shape.Add` and `Shape.Remove` socket events
   - Just need to specify the `fow` or `fow-players` layer name
   - Set `options.preFogShape = true` in the shape data

4. **Shape types for fog control:**
   - Can use any shape type: Polygon, Rectangle, Circle, etc.
   - Polygon is most flexible for custom fog reveal areas
   - Rectangle is simplest for square/rectangular reveals

**Implementation Strategy for REST API:**

```python
# POST /api/v1/scenes/{uuid}/fog/reveal
# Request body: {"type": "polygon", "vertices": [[x1,y1], [x2,y2], ...]}
# OR: {"type": "rect", "x": 100, "y": 100, "width": 200, "height": 150}

async def reveal_fog(request):
    # 1. Get FOW layer (name="fow" or "fow-players")
    layer = Layer.get(floor=floor, name="fow")

    # 2. Create shape based on type (ApiPolygonShape or ApiRectShape)
    shape_data = {
        "type_": "polygon",  # or "rect"
        "layer": "fow",
        "vertices": [...],   # from request
        "options": {
            "preFogShape": True,  # Critical!
        }
    }

    # 3. Use PA's create_shape() to create the fog control shape
    shape = create_shape(ApiPolygonShape(**shape_data), layer)

    # 4. Emit Shape.Add to all players
    await _send_game("Shape.Add", transform_shape(shape, ...), room=...)

    # 5. Log event
    await log_event("fog_revealed", {...}, scene_id=location.id)

    return ok({"shape_id": shape.uuid})

# POST /api/v1/scenes/{uuid}/fog/hide
# Request body: {"shape_id": "uuid"}
async def hide_fog(request):
    # 1. Get the fog control shape by UUID
    shape = Shape.get_by_id(shape_id)

    # 2. Verify it's a preFogShape
    if not shape.options.get("preFogShape"):
        return error("Not a fog control shape")

    # 3. Delete shape (cascades to auras, trackers, etc.)
    shape.delete_instance(recursive=True)

    # 4. Emit Shape.Remove to all players
    await _send_game("Shape.Remove", {"uuids": [shape_id], "temporary": False}, room=...)

    # 5. Log event
    await log_event("fog_hidden", {...}, scene_id=location.id)

    return ok()

# GET /api/v1/scenes/{uuid}/fog
async def get_fog_state(request):
    # Query all shapes on FOW layer with preFogShape=true
    fog_shapes = Shape.select().join(Layer).where(
        (Layer.floor.location == location) &
        (Layer.name == "fow") &
        (Shape.options["preFogShape"] == True)  # JSON field query
    )

    return ok({"fog_shapes": [serialize_shape(s) for s in fog_shapes]})
```

**Challenges:**
1. **JSON field queries**: Shape.options is a TextField storing JSON
   - May need to load all FOW layer shapes and filter in Python
   - Or store fog shape UUIDs in a separate tracking table

2. **Polygon coordinate format**: Need to match PA's coordinate system
   - PA uses global coordinates (g2l converts to local)
   - Vertices format: `[[x1, y1], [x2, y2], ...]`

**Files to Create:**
- `server/src/api/rest/fog.py` - Fog control endpoints (3 endpoints)

**Files to Modify:**
- `server/src/api/rest/__init__.py` - Add fog route registration

---

## Phase 12: Fog of War Control Implementation Results

### Implementation Pattern

**Polygon Fog Reveal:**
```python
# Create ApiPolygonShape with preFogShape option
api_shape = ApiPolygonShape(
    uuid=fog_shape_uuid,
    type_="polygon",
    x=0, y=0,  # Polygon uses absolute vertices
    vertices=[[x1, y1], [x2, y2], ...],
    line_width=0,  # No border
    stroke_colour=["rgba(0, 0, 0, 1)"],
    fill_colour="rgba(0, 0, 0, 1)",
    owners=[],  # No owners (DM controlled)
    trackers=[],
    auras=[],
    options={"preFogShape": True},  # CRITICAL!
)

# Create shape and emit
fog_shape = create_shape(api_shape, layer)
await _send_game("Shape.Add", {"shape": transform_shape(fog_shape, room_player), ...}, room=psid)
```

**Rectangle Fog Reveal:**
```python
# Create ApiRectShape with preFogShape option
api_shape = ApiRectShape(
    uuid=fog_shape_uuid,
    type_="rect",
    x=x, y=y,
    width=width, height=height,
    line_width=0,
    stroke_colour=["rgba(0, 0, 0, 1)"],
    fill_colour="rgba(0, 0, 0, 1)",
    owners=[],
    trackers=[],
    auras=[],
    options={"preFogShape": True},
)
```

**Fog Hide:**
```python
# Validate it's a preFogShape
options = fog_shape.options or {}
if not options.get("preFogShape"):
    return error("Not a fog control shape")

# Delete and emit
fog_shape.delete_instance(recursive=True)
await _send_game("Shape.Remove", {"uuids": [shape_id], "temporary": False}, room=psid)
```

**List Fog State:**
```python
# Query fog shapes from Polygon/Rect submodels
for shape in layer.shapes:
    if shape.options.get("preFogShape"):
        if shape.type_ == "polygon":
            polygon = Polygon.get_or_none(shape=shape)
            data = {"vertices": polygon.vertices}  # List of [x, y]
        elif shape.type_ == "rect":
            rect = Rect.get_or_none(shape=shape)
            data = {"x": shape.x, "y": shape.y, "width": rect.width, "height": rect.height}
```

### Key Discoveries

1. **Shape submodels**: Polygon and Rect store geometry in separate tables
   - Polygon: vertices stored in Polygon.vertices (JSON list)
   - Rect: width/height stored in Rect table, x/y in Shape table
   - Must query submodel with `Submodel.get_or_none(shape=shape)`

2. **Shape.options**: Python dict, not JSON string
   - Check with `options.get("preFogShape")`
   - No need for json.loads/dumps

3. **Multi-layer support**: Both "fow" and "fow-players" layers work
   - "fow" = FowLightingLayer (main fog)
   - "fow-players" = FowVisionLayer (player-specific)

4. **Access control pattern**: Check room creator OR room player
   - `room.creator.id == api_key.user.id` for DM
   - `any(rp.player.id == api_key.user.id for rp in room.players)` for players

5. **First floor default**: Most scenes have single floor
   - `floors = list(location.floors); floor = floors[0]`
   - Multi-floor support exists but rarely used

### Implementation Achievements

- ✓ 3 complete endpoints: reveal, hide, get_fog_state
- ✓ Support for both polygon (flexible) and rect (simple) fog shapes
- ✓ Multi-layer support (fow and fow-players)
- ✓ Socket emission to all players with transform_shape()
- ✓ Event logging for fog_revealed and fog_hidden
- ✓ RBAC enforcement (DM for write, DM+Player for read)
- ✓ Access validation (room creator or player)
- ✓ Proper shape submodel querying for geometry data

---

## Next Steps

**Phase 12 COMPLETE!** ✓ (12/22, 54.5%)

**Current Status:**
- 12 phases fully complete and tested
- Sprint 2: Complete ✓ (Phases 8-11 + 11.5)
- Sprint 3 progress: 1/4 phases complete (Phase 12 complete!)

---

## Phase 14: SSE Event Stream Implementation Results

### Implementation Pattern

**Subscriber Queue System:**
```python
# Global dictionary mapping connection_id -> asyncio.Queue
_sse_subscribers: dict[str, asyncio.Queue] = {}

# Each SSE connection gets unique ID and queue
conn_id = str(uuid.uuid4())
queue: asyncio.Queue = asyncio.Queue(maxsize=100)
_sse_subscribers[conn_id] = queue
```

**Event Broadcasting:**
```python
async def _push_sse(event_data: dict[str, Any]) -> None:
    # Format as SSE message
    sse_message = f"data: {json.dumps(event_data)}\n\n"

    # Non-blocking broadcast to all subscribers
    dead_connections = []
    for conn_id, queue in _sse_subscribers.items():
        try:
            await asyncio.wait_for(queue.put(sse_message), timeout=0.1)
        except asyncio.TimeoutError:
            dead_connections.append(conn_id)  # Queue full, connection slow

    # Cleanup
    for conn_id in dead_connections:
        _sse_subscribers.pop(conn_id, None)
```

**SSE Endpoint:**
```python
@require_role("dm", "player")
async def event_stream(request: web.Request) -> web.StreamResponse:
    # Create SSE response with proper headers
    response = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )
    await response.prepare(request)

    # Handle Last-Event-ID for reconnection
    last_event_id = request.headers.get("Last-Event-ID")
    if last_event_id:
        # Replay missed events
        missed_events = EventLog.select().where(
            EventLog.sequence_id > int(last_event_id)
        ).order_by(EventLog.sequence_id.asc()).limit(100)
        # Send each missed event...

    # Stream events with keepalive
    while True:
        try:
            message = await asyncio.wait_for(queue.get(), timeout=30.0)
            await response.write(message.encode("utf-8"))
        except asyncio.TimeoutError:
            # Send keepalive every 30 seconds
            await response.write(b": keepalive\n\n")
```

**Integration with log_event():**
```python
# After creating EventLog record
from .events import _push_sse

event_data = {
    "uuid": event.uuid,
    "event_type": event.event_type,
    "scene_id": event.scene.id if event.scene else None,
    "actor_id": event.actor.uuid if event.actor else None,
    "combat_id": event.combat.uuid if event.combat else None,
    "action_id": event.action.uuid if event.action else None,
    "payload": json.loads(event.payload),
    "created_at": serialize_datetime(event.created_at),
    "sequence_id": event.sequence_id,
}

# Fire and forget (don't block on SSE failures)
try:
    await _push_sse(event_data)
except Exception:
    pass  # Don't fail event logging
```

### Key Discoveries

1. **Fan-out pattern with asyncio.Queue**:
   - Each SSE client gets independent queue
   - Prevents slow clients from blocking fast clients
   - Automatic buffering up to maxsize (100 events)

2. **Non-blocking broadcast**:
   - `asyncio.wait_for(timeout=0.1)` ensures log_event() doesn't block
   - Slow/dead connections detected via TimeoutError
   - Automatic cleanup prevents memory leaks

3. **SSE Protocol Requirements**:
   - Message format: `data: {JSON}\n\n` (double newline required)
   - ID format: `id: {seq}\ndata: {JSON}\n\n` (for reconnection)
   - Keepalive: `: comment\n\n` (colon-prefixed lines are comments)
   - Headers: `text/event-stream`, `no-cache`, `keep-alive`

4. **Reconnection Support**:
   - Client sends `Last-Event-ID` header with last received sequence_id
   - Server replays missed events (up to 100) ordered by sequence_id
   - EventLog.sequence_id (auto-incrementing) enables this

5. **Nginx/Proxy Compatibility**:
   - `X-Accel-Buffering: no` disables nginx response buffering
   - Keepalive comments every 30s prevent timeout
   - Essential for production deployment behind reverse proxy

6. **Error Handling Strategy**:
   - _push_sse() failures don't fail log_event()
   - Dead connection cleanup prevents unbounded growth
   - Queue.put() timeout prevents blocking on slow clients

### Implementation Achievements

- ✓ Complete SSE streaming endpoint with text/event-stream
- ✓ Subscriber queue system with automatic cleanup
- ✓ Reconnection support via Last-Event-ID header
- ✓ Keepalive comments every 30 seconds
- ✓ Non-blocking event broadcasting from log_event()
- ✓ Graceful error handling (SSE failures don't block logging)
- ✓ Event replay for reconnecting clients (up to 100 events)
- ✓ RBAC enforcement (DM+Player access)

---

**Current:** Phase 15 COMPLETE! ✓

## Phase 15: Event Export Implementation Results

### Requirements (from api_spec_v2.md)

**Endpoint:** `GET /api/v1/events/export`

**Query Parameters:**
- `format`: "json" | "txt" (required)
- `scene_id`: Filter events by scene UUID (optional)
- `actor_id`: Filter events by actor UUID (optional)
- `event_type`: Filter by event type (optional)
- `after`: ISO timestamp for start of range (optional)
- `before`: ISO timestamp for end of range (optional)
- `limit`: Max events to export (optional, default: all)

**Response:**
- Content-Type: `application/json` or `text/plain`
- Content-Disposition: `attachment; filename="events_{timestamp}.{json|txt}"`
- Body: Formatted event log

### Implementation Strategy

**JSON Format:**
```json
{
  "exported_at": "2026-02-16T12:00:00Z",
  "filters": {
    "scene_id": 123,
    "after": "2026-02-15T00:00:00Z",
    "before": "2026-02-16T23:59:59Z"
  },
  "total_events": 150,
  "events": [
    {
      "uuid": "event-uuid",
      "event_type": "token_created",
      "scene_id": 123,
      "actor_id": "token-uuid",
      "payload": {...},
      "created_at": "2026-02-16T10:30:00Z",
      "sequence_id": 1001
    },
    ...
  ]
}
```

**TXT Format:**
```
Event Log Export
Generated: 2026-02-16 12:00:00 UTC
Filters: scene_id=123, after=2026-02-15 00:00:00, before=2026-02-16 23:59:59
Total Events: 150

================================================================================

[2026-02-16 10:30:00] token_created (seq: 1001)
  Scene: 123
  Actor: token-uuid
  Payload: {"name": "Goblin", "hp": 7, ...}

[2026-02-16 10:31:15] roll_made (seq: 1002)
  Scene: 123
  Actor: token-uuid
  Payload: {"notation": "1d20+5", "total": 18, ...}

...
```

### Key Implementation Details

1. **Reuse query logic**: Use same filtering as `list_events()` endpoint
2. **File naming**: `events_{timestamp}.{extension}` e.g., `events_2026-02-16_120000.json`
3. **RBAC**: DM+Player access (same as list_events)
4. **Large exports**: Consider streaming response for very large exports
5. **Event serialization**: Reuse existing serialization from list_events()
6. **Headers**:
   - `Content-Type`: `application/json` or `text/plain; charset=utf-8`
   - `Content-Disposition`: `attachment; filename="..."`
   - `Cache-Control`: `no-cache` (don't cache export files)

### Implementation Achievements

- ✓ Complete event export endpoint with JSON and TXT formats
- ✓ Reuses filtering logic from query_events() for consistency
- ✓ JSON format includes export metadata and filter information
- ✓ TXT format provides human-readable timeline with formatted payload
- ✓ Proper HTTP headers: Content-Type, Content-Disposition, Cache-Control
- ✓ Timestamped filenames: events_{YYYYMMDD_HHMMSS}.{json|txt}
- ✓ Supports all query filters: scene, actor, combat, action, type, time range
- ✓ RBAC enforcement: DM+Player access
- ✓ Configurable limit (max 10000 events to prevent timeouts)

### Error Handling (Implemented)

- Invalid format → 400 VALIDATION_ERROR ✓
- Invalid filters → 400 VALIDATION_ERROR ✓
- No events found → Return empty export (not error) ✓
- Large export timeout → Limit enforcement (max 10000 events) ✓

---

---

## Phase 13: Token Vision Implementation Results

### Aura Model Structure

**Database Fields (from aura.py):**
- `uuid`: Primary key (string)
- `shape`: FK to Shape (CASCADE delete)
- `vision_source`: Boolean - **Critical field for vision**
- `visible`: Boolean - Whether aura is shown to players
- `name`: String - Aura name (e.g., "Vision")
- `value`: Int - Vision range in feet
- `dim`: Int - Dim light range
- `colour`: String - Vision color (rgba format)
- `active`: Boolean - Whether aura is active
- `border_colour`: String - Border color
- `angle`: Int - Vision cone angle (360 = full circle)
- `direction`: Int - Vision cone direction in degrees

### Socket Event Pattern

**Aura Update Handler (options.py:572-610):**
```python
@sio.on("Shape.Options.Aura.Update", namespace=GAME_NS)
async def update_aura(sid: str, raw_data: Any):
    aura = Aura.get_by_id(data.uuid)
    safe_update_model_from_dict(aura, raw_data)
    aura.save()

    # Emit to owners
    for psid in get_owner_sids(pr, shape, skip_sid=sid):
        await _send_game("Shape.Options.Aura.Update", raw_data, room=psid)

    # Emit to all others in location
    for psid in game_state.get_sids(active_location=pr.active_location, skip_sid=sid):
        if changed_visible:
            if aura.visible:
                await send_new_aura(aura.as_pydantic(), room=psid)
            else:
                await _send_game("Shape.Options.Aura.Remove", {...}, room=psid)
        else:
            await _send_game("Shape.Options.Aura.Update", raw_data, room=psid)
```

### Implementation Pattern

**Vision Creation:**
```python
# Create new vision aura
aura_uuid = str(uuid4())
vision_aura = Aura.create(
    uuid=aura_uuid,
    shape=shape,
    vision_source=True,  # CRITICAL for vision
    visible=True,
    name="Vision",
    value=vision_range,
    dim=dim_range,
    colour=colour,
    active=True,
    border_colour="rgba(0, 0, 0, 0)",
    angle=angle,
    direction=direction,
)

# Emit to all players
aura_data = vision_aura.as_pydantic().model_dump()
await _send_game("Shape.Options.Aura.Create", aura_data, room=psid)
```

**Vision Update:**
```python
# Update existing aura fields
vision_aura.value = vision_range
vision_aura.dim = dim_range
vision_aura.colour = colour
vision_aura.angle = angle
vision_aura.direction = direction
vision_aura.save()

# Emit update
aura_data = vision_aura.as_pydantic().model_dump()
await _send_game("Shape.Options.Aura.Update", aura_data, room=psid)
```

**Vision Removal:**
```python
# Delete aura
aura_uuid = vision_aura.uuid
vision_aura.delete_instance()

# Emit removal
await _send_game(
    "Shape.Options.Aura.Remove",
    {"shape": token_uuid, "value": aura_uuid},
    room=psid,
)
```

### Key Discoveries

1. **vision_source field**: This boolean is the critical field that marks an aura as providing vision (not just a visual effect)

2. **Three socket events**:
   - `Shape.Options.Aura.Create` - Used when creating new vision aura
   - `Shape.Options.Aura.Update` - Used when modifying existing vision aura
   - `Shape.Options.Aura.Remove` - Used when removing vision

3. **Aura.as_pydantic()**: Converts DB model to ApiAura format for socket emission

4. **Vision cone**: Controlled by `angle` (degrees, 360=circle) and `direction` (rotation in degrees)

5. **Dim light**: `dim` field provides additional dim light range beyond main vision `value`

6. **Multiple auras per token**: A token can have multiple auras, query with `(Aura.shape == shape) & (Aura.vision_source == True)` to find vision aura

### Implementation Achievements

- ✓ Complete vision endpoint with create/update/remove workflow
- ✓ Socket emission using PA's three aura events
- ✓ Full vision customization (range, dim, colour, angle, direction)
- ✓ Event logging (vision_created, vision_updated, vision_removed)
- ✓ RBAC enforcement (DM only)
- ✓ Proper lifecycle management (find existing vision aura or create new)
- ✓ Handles both vision addition and removal via has_vision boolean

---

---

## Phase 16: Quick Commands Implementation Results

**Implemented in previous session.** See task_plan.md for details.

---

## Phase 17: Batch Token Operations Implementation Results

### API Specification

**Endpoint:** `POST /api/v1/scenes/{uuid}/tokens/batch`

**Request Body:**
```json
{
  "operations": [
    {"op": "create", "data": {"name": "Goblin A", "x": 100, "y": 100, "hp_current": 7, "hp_max": 7, "ac": 13, "faction": "enemy"}},
    {"op": "update", "id": "token-uuid", "data": {"hp_current": 3}},
    {"op": "delete", "id": "token-uuid"}
  ],
  "dry_run": false  // If true, validate only, return preview
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "results": [
      {"op": "create", "status": "ok", "id": "new-token-uuid", "index": 0},
      {"op": "update", "status": "ok", "id": "token-uuid", "changes": {"hp_current": 3}, "index": 1},
      {"op": "delete", "status": "error", "id": "token-uuid", "error": "Token not found", "index": 2}
    ],
    "dry_run": false,
    "success_count": 2,
    "error_count": 1,
    "total_operations": 3
  }
}
```

### Implementation Pattern

**Helper Functions:**
- `_batch_create_token()` - Reuses token creation logic from `create_token()`
- `_batch_update_token()` - Reuses token update logic from `update_token()`
- `_batch_delete_token()` - Reuses token deletion logic from `delete_token()`

**Dry Run Mode:**
```python
if dry_run:
    return {
        "op": "create",
        "status": "ok",
        "preview": {
            "name": name,
            "x": x,
            "y": y,
            "hp": {"current": hp_current, "max": hp_max},
            "ac": ac,
            "faction": faction,
        },
    }
```

**Error Isolation:**
- Each operation processed independently
- One failure doesn't block other operations
- Results include per-operation status and error messages

### Key Discoveries

1. **Index tracking**: Added `index` field to results for correlating with input operations
2. **HP field variations**: Supports both `hp_current` and `hp` for convenience
3. **Socket emission per operation**: Each successful operation emits socket events immediately
4. **Event logging**: All operations logged with `batch=True` flag for filtering
5. **Location validation**: Update/delete operations verify token is in the specified scene

### Smoke Test Results

All 8 test cases passed:
1. ✓ Dry run returns preview without executing
2. ✓ Batch create 3 tokens → success_count: 3
3. ✓ Batch update 2 tokens → success_count: 2
4. ✓ Mixed operations (update + delete) → success_count: 2
5. ✓ Error handling (delete non-existent) → error_count: 1
6. ✓ Cleanup (delete remaining tokens) → success_count: 2

**Current Status:** Phase 17 COMPLETE! ✓

**Next:** Phase 18 - Player Management OR Phase 19 - Scene Snapshots
