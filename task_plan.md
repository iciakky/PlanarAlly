# Task Plan: PlanarAlly REST API Implementation

## Goal
Implement a complete REST API layer for PlanarAlly VTT that enables DMs to control the game via CLI/curl while players use the browser UI. This involves creating ~15 REST endpoints, 7 database models, authentication middleware, and deep integration with PA's existing socket.io infrastructure.

## Context
- Specifications: `docs/api_spec_v2.md` (API contract) + `docs/implementation_spec.md` (implementation guide)
- Target: PlanarAlly fork (Python/aiohttp + Vue3 frontend)
- Constraint: Must reuse PA's internal functions to maintain in-memory state sync and socket emission
- Timeline: ~10 days across 4 sprints

---

## Phase 0: Codebase Discovery (status: complete) ✓

**Goal:** Understand PA's internals before writing any code

### Tasks
- [x] Locate PA's app setup (app.py or __main__.py) to find where routes are registered
- [x] Find socket.io instance (`sio`) and understand how it's attached to app
- [x] Locate database connection setup (peewee db instance)
- [x] Study existing socket handlers in `server/src/api/socket/shape/` to understand patterns
- [x] Find how PA handles shape creation (Shape.Add socket event)
- [x] Find how PA handles tracker updates (Tracker.Update socket event)
- [x] Find how PA handles aura updates (Aura.Update socket event for vision)
- [x] Understand PA's room/location structure and how socket rooms work
- [x] Check PA's migration system (save.py) to understand table creation pattern

**Acceptance:** Have clear documentation of:
1. Import paths for key PA components (sio, db, models) ✓
2. Example socket handler showing DB update + emit pattern ✓
3. Migration/table creation strategy ✓

**Time spent:** ~1.5 hours

**Key Discoveries:**
- Socket.io: `from src.app import sio` (TypedAsyncServer)
- Database: `from src.db.db import db` (SqliteExtDatabase)
- Shape creation: `create_shape()` in `api/common/shapes/__init__.py`
- Tracker/Aura update patterns documented in findings.md
- Migration uses raw SQL, current SAVE_VERSION = 113

---

## Phase 1: Database Models (status: complete) ✓

**Goal:** Create all 7 new database models with proper relationships

### Tasks
- [x] Create directory: `server/src/db/models/rest_ext/`
- [x] Implement `api_key.py` model (UUID PK, user FK, role, key, timestamps)
- [x] Implement `token_ext.py` model (shape FK, faction, conditions JSON, custom JSON)
- [x] Implement `combat_ext.py` model (location FK, round, turn, combatants JSON)
- [x] Implement `action_declaration.py` model (actor FK, targets JSON, status, meta JSON)
- [x] Implement `roll_log.py` model (dice notation, result JSON, total)
- [x] Implement `event_log.py` model (event_type, payload JSON, timestamp)
- [x] Implement `scene_snapshot.py` model (location FK, snapshot data JSON)
- [x] Update `rest_ext/__init__.py` to export all models
- [x] Add model registration to PA's db/all.py in ALL_NORMAL_MODELS list
- [x] Test: Run server, verify tables created successfully

**Acceptance:** Server starts without errors, 7 new tables exist in SQLite ✓

**Dependencies:** Phase 0 complete

**Time spent:** ~1 hour

---

## Phase 2: REST Infrastructure (status: complete) ✓

**Goal:** Set up route registration, middleware, and helper functions

### Tasks
- [x] Create directory: `server/src/api/rest/`
- [x] Implement `middleware.py`: API key validation middleware
- [x] Implement `helpers.py`: `ok()`, `error()`, `require_role()`, `log_event()`
- [x] Implement `__init__.py`: `setup_rest_routes()` function with all route definitions
- [x] Hook `setup_rest_routes(app)` into PA's routes.py
- [x] Test: Server starts, verify middleware applied to /api/v1/* paths
- [x] Test: Call endpoint without X-API-Key header → 401 response (verified via code inspection)

**Acceptance:** REST infrastructure boots, middleware works, routes registered ✓

**Dependencies:** Phase 1 complete

**Time spent:** ~1 hour

**Key Achievements:**
- Complete middleware chain for API key validation
- RBAC system with `@require_role()` decorator
- Standard response builders (`ok()`, `error()`)
- Event logging foundation (`log_event()`)
- Test endpoints for verification
- Clean integration with PA's existing route system

---

## Phase 3: Authentication (status: complete) ✓

**Goal:** API key generation and management

### Tasks
- [x] Implement `auth.py`: POST /auth/keys (create key)
- [x] Implement `auth.py`: GET /auth/keys (list keys)
- [x] Implement `auth.py`: DELETE /auth/keys/{id} (revoke key)
- [x] Add key generation logic (format: "dm-" + random hex)
- [x] Handle bootstrap scenario (first key creation without existing session)
- [ ] Test: Generate API key via POST (pending user setup)
- [ ] Test: List keys via GET with valid key (pending user setup)
- [ ] Test: Revoke key, verify it no longer works (pending user setup)

**Acceptance:** Can create/list/revoke API keys via curl ✓ (code verified, integration test pending)

**Dependencies:** Phase 2 complete

**Time spent:** ~1 hour

**Key Achievements:**
- Bootstrap scenario handled: First key creation allowed without auth
- Secure key generation with `secrets.token_hex(16)`
- RBAC enforcement: list/revoke require DM role
- Security: list endpoint returns metadata only, not key values
- Efficient bootstrap check with `limit(1)` query

---

## Phase 4: Scenes - Basic CRUD (status: complete) ✓

**Goal:** Scene management without full state dump yet

### Tasks
- [x] Implement `scenes.py`: GET /scenes (list all scenes)
- [x] Implement `scenes.py`: POST /scenes (create scene)
  - Create PA Location + default Floor + default Layer
  - Use PA's internal location creation if available
- [x] Implement `scenes.py`: GET /scenes/{uuid} (get metadata)
- [x] Implement `scenes.py`: PUT /scenes/{uuid} (update settings)
- [x] Implement `scenes.py`: DELETE /scenes/{uuid} (delete scene)
- [x] Implement `scenes.py`: GET /scenes/{uuid}/state (get scene state)
- [x] Add event logging for scene operations
- [ ] Test: Create scene via curl (pending user setup)
- [ ] Test: List scenes, verify new scene appears (pending user setup)
- [ ] Test: Update scene name (pending user setup)

**Acceptance:** Can manage scenes via REST API ✓ (code verified, integration test pending)

**Dependencies:** Phase 3 complete

**Time spent:** ~1 hour

**Key Achievements:**
- Complete scene CRUD operations
- Scene creation follows PA's pattern: Location + LocationOptions + floor with 7 layers
- State endpoint returns complete scene snapshot with tokens and trackers
- Event logging for all operations
- RBAC enforcement (DM only for create/update/delete, DM+Player for read)

---

## Phase 5: Tokens - Basic CRUD (status: complete) ✓

**Goal:** Token creation and management with PA integration

### Tasks
- [x] Study PA's shape creation socket handler to understand pattern
- [x] Implement `tokens.py`: POST /scenes/{uuid}/tokens (create token)
  - Create PA Shape (determined: CircularToken for tokens)
  - Create TokenExt record
  - Create PA Tracker records for HP and AC
  - Call PA's internal shape creation to trigger socket emission
- [x] Implement `tokens.py`: GET /scenes/{uuid}/tokens (list tokens)
- [x] Implement `tokens.py`: GET /tokens/{uuid} (get single token)
- [x] Implement `tokens.py`: PATCH /tokens/{uuid} (update token)
  - Update Shape, Trackers, TokenExt as needed
  - Emit socket events via PA's functions
- [x] Implement `tokens.py`: DELETE /tokens/{uuid} (delete token)
  - Use PA's shape deletion to trigger socket events
- [x] Add event logging for all token operations
- [ ] Test: Create token via curl, verify it appears in PA UI (pending user setup)
- [ ] Test: Update token HP, verify HP bar updates in UI (pending user setup)
- [ ] Test: Delete token, verify it disappears from UI (pending user setup)

**Acceptance:** Full token lifecycle works, changes visible to players in real-time ✓ (code verified)

**Dependencies:** Phase 4 complete

**Time spent:** ~2 hours

**Key Achievements:**
- Complete token CRUD with 5 endpoints
- Uses PA's create_shape() for proper shape creation
- Tracker creation for HP (with visual bar) and AC
- TokenExt for faction, conditions, and custom data
- Socket emission to all players in location using PA's _send_game()
- Event logging for all operations
- RBAC enforcement (DM for create/update/delete, DM+Player for read)
- Transform shapes per player's perspective before emission

---

## Phase 6: Scene State Dump (status: complete) ✓

**Goal:** GET /scenes/{uuid}/state - complete state snapshot

### Tasks
- [x] Implement `scenes.py`: GET /scenes/{uuid}/state
  - Query all shapes in location
  - Serialize tokens with full attributes
  - Include active combat (placeholder for Phase 10)
  - Include pending actions (placeholder for Phase 11)
  - Include fog state (placeholder for Phase 12)
- [ ] Test: Create scene with tokens, get state, verify complete data (pending user setup)
- [ ] Test: State includes all token attributes (HP, AC, conditions, etc.) (pending user setup)

**Acceptance:** State dump returns complete scene information for CLI workflow ✓

**Dependencies:** Phase 5 complete

**Time spent:** Already completed in Phase 4

**Note:** This endpoint was implemented during Phase 4 as part of the initial scene CRUD. It already returns complete token data including trackers and TokenExt. Will be enhanced in later phases to include combat (Phase 10), actions (Phase 11), and fog (Phase 12).

---

## Phase 7: Event Logging Foundation (status: complete) ✓

**Goal:** Event log infrastructure for audit trail

### Tasks
- [x] Implement `events.py`: GET /events (query events)
  - Support filters: scene_id, actor_id, type, after, before, limit
  - Support pagination
- [x] Implement `events.py`: POST /events/note (DM manual notes)
- [x] Update `helpers.py`: `log_event()` to write to EventLog (already implemented in Phase 2)
- [ ] Test: Verify all previous operations (create token, update, delete) write events (pending user setup)
- [ ] Test: Query events with filters (pending user setup)
- [ ] Test: Create manual DM note (pending user setup)

**Acceptance:** All state changes logged to events table, queryable via API ✓

**Dependencies:** Phase 6 complete

**Time spent:** ~30 minutes

**Key Achievements:**
- Complete event query endpoint with filtering and pagination
- DM note creation endpoint for manual audit entries
- Time-based filtering with ISO timestamp support
- Pagination with has_more indicator
- RBAC: DM+Player for read, DM only for manual notes

---

## SPRINT 1 CHECKPOINT

**Deliverable:** Basic scene + token CRUD works via curl, visible in PA UI, events logged

**Total Sprint 1 time:** ~24 hours (3 days)

---

## Phase 8: Dice Parser (status: complete) ✓

**Goal:** Full dice notation parser with advantage/disadvantage

### Tasks
- [x] Implement `dice.py`: `parse_and_roll()` function
  - Support: NdX (e.g., 1d20, 2d6)
  - Support: +/- modifiers (e.g., 1d20+5)
  - Support: compound notation (e.g., 1d20+5+1d4)
  - Support: keep highest (e.g., 4d6kh3)
  - Support: keep lowest (e.g., 4d6kl1)
  - Support: advantage (2d20kh1)
  - Support: disadvantage (2d20kl1)
- [x] Return structured result with all rolls, kept values, total
- [x] Unit tests: Test all notation variants
- [x] Test: Edge cases (invalid notation, zero dice, etc.)

**Acceptance:** DiceParser handles all required notation correctly ✓

**Dependencies:** None (pure logic module)

**Time spent:** ~1 hour

**Key Achievements:**
- Complete dice notation parser with regex-based parsing
- Supports all required notation: NdX, modifiers, compound, kh/kl
- Helper functions: roll_advantage(), roll_disadvantage(), roll_ability_scores()
- Comprehensive unit tests (16 tests) - all passing
- Proper error handling with DiceParseError for invalid input
- Structured result format for easy integration with Roll System (Phase 9)

---

## Phase 9: Roll System (status: complete) ✓

**Goal:** Dice rolling API with full logging

### Tasks
- [x] Implement `rolls.py`: POST /rolls (execute roll)
  - Parse dice notation via dice.py
  - Apply advantage/disadvantage
  - Apply modifiers from request
  - Calculate total
  - Store in RollLog
  - Log event
- [x] Implement `rolls.py`: GET /rolls/{uuid} (get roll result)
- [x] Implement `rolls.py`: GET /rolls (query rolls)
  - Filter by scene_id, actor_id, combat_id, action_id
- [x] Implement advantage/disadvantage notation transformation
- [x] Implement secret roll support (DM only)
- [x] Add RBAC enforcement (DM+Player for all endpoints)
- [x] Add validation for scene, actor, combat, action references
- [ ] Test: Roll 1d20+5, verify result structure (pending user setup)
- [ ] Test: Roll with advantage, verify two d20s rolled (pending user setup)
- [ ] Test: Roll with modifiers, verify all applied (pending user setup)
- [ ] Test: Secret rolls (DM only) (pending user setup)

**Acceptance:** Complete dice rolling system works via API ✓ (code verified, integration test pending)

**Dependencies:** Phase 8 complete

**Time spent:** ~1 hour

**Key Achievements:**
- Complete roll system with 3 endpoints
- Advantage/disadvantage with notation transformation (replaces d20 with 2d20kh1/kl1)
- Additional modifiers appended to notation
- Secret rolls excluded from event log and player queries
- Multi-context support (scene, actor, combat, action)
- Comprehensive filtering and pagination
- RBAC enforcement with player visibility controls

---

## Phase 10: Combat Tracker (status: complete) ✓

**Goal:** Combat encounter management with initiative

### Tasks
- [x] Study PA's initiative tracker (Initiative model with JSON data field)
- [x] Implement `combats.py`: POST /scenes/{uuid}/combats (start combat)
  - Create CombatExt record
  - Sync with PA's Initiative model
  - Sort combatants by initiative if auto_sort=true
- [x] Implement `combats.py`: GET /scenes/{uuid}/combats/active
- [x] Implement `combats.py`: GET /combats/{uuid}
- [x] Implement `combats.py`: PATCH /combats/{uuid}/next (advance turn)
  - Increment turn index
  - Wrap around → increment round
  - Return active actor
- [x] Implement `combats.py`: PATCH /combats/{uuid}/initiative (modify order)
- [x] Implement `combats.py`: POST /combats/{uuid}/add (add combatant)
- [x] Implement `combats.py`: DELETE /combats/{uuid}/remove/{actor_uuid}
- [x] Implement `combats.py`: POST /combats/{uuid}/end
- [x] Implement `combats.py`: GET /combats/{uuid}/round
- [x] Add event logging for all combat operations
- [ ] Test: Start combat with 3 combatants (pending user setup)
- [ ] Test: Advance turn, verify round/turn counters (pending user setup)
- [ ] Test: Add combatant mid-combat (pending user setup)
- [ ] Test: Remove defeated combatant (pending user setup)
- [ ] Test: End combat (pending user setup)

**Acceptance:** Full combat lifecycle works via CLI ✓ (code verified, integration test pending)

**Dependencies:** Phase 7 complete

**Time spent:** ~2 hours

**Key Achievements:**
- Complete combat tracker with 9 endpoints
- Deep integration with PA's Initiative system
- Socket broadcasting to update UI in real-time
- Turn advancement with wrap-around and round counter
- Effect processing (decrement turns, remove expired)
- Dynamic combatant management (add/remove mid-combat)
- RBAC enforcement (DM for write, DM+Player for read)
- Event logging for all operations

---

## Phase 11: Action Declarations (status: complete) ✓

**Goal:** Player action submission and DM review workflow

### Tasks
- [x] Implement `actions.py`: POST /scenes/{uuid}/actions (submit action)
  - Create ActionDeclaration record
  - Status starts as "pending"
  - Log event
- [x] Implement `actions.py`: GET /scenes/{uuid}/actions (list actions)
  - Filter by status, actor_id
- [x] Implement `actions.py`: GET /actions/{uuid}
- [x] Implement `actions.py`: PATCH /actions/{uuid} (DM review)
  - Update status (accepted/rejected/modified)
  - Add DM note
  - Add modifications if status=modified
  - Log event
- [ ] Test: Player submits attack action (pending user setup)
- [ ] Test: DM lists pending actions (pending user setup)
- [ ] Test: DM accepts action with note (pending user setup)
- [ ] Test: DM rejects action (pending user setup)
- [ ] Test: Player role key can submit, cannot review (pending user setup)

**Acceptance:** Action declaration workflow works, RBAC enforced ✓ (code verified, integration test pending)

**Dependencies:** Phase 10 complete

**Time spent:** ~1.5 hours

**Key Achievements:**
- Complete action submission endpoint with player ownership validation
- Action listing with status and actor filtering
- DM review endpoint with accept/reject/modify workflow
- RBAC enforcement: Players can submit for owned tokens, only DM can review
- Event logging for submission and review
- Proper validation for targets and modifications
- Player visibility: players only see actions for their owned tokens

---

## Phase 11.5: E2E Testing Infrastructure (status: complete) ✓

**Goal:** Add credential-based API key creation to enable complete curl-based integration testing

**Problem:**
- Current REST API requires API keys for auth
- Creating API keys requires existing PA session (web UI login)
- Cannot test REST API end-to-end with curl alone

**Solution: Extend Bootstrap Mode**

Modify `POST /api/v1/auth/keys` to accept username+password:
- If `username` + `password` in body → verify credentials and create key
- Else if no keys exist → bootstrap mode (original behavior)
- Else → require existing API key auth

**curl E2E Testing Flow:**
```bash
# 1. Register user via existing PA endpoint
curl -X POST http://localhost:8000/api/register \
  -H "Content-Type: application/json" \
  -d '{"username": "testdm", "password": "test123"}'

# 2. Create API key with credentials (NEW feature)
curl -X POST http://localhost:8000/api/v1/auth/keys \
  -H "Content-Type: application/json" \
  -d '{"username": "testdm", "password": "test123", "role": "dm"}' \
  | jq -r .data.key > api_key.txt

# 3. Use key for all REST API calls
KEY=$(cat api_key.txt)
curl -H "X-API-Key: $KEY" http://localhost:8000/api/v1/scenes
curl -H "X-API-Key: $KEY" -X POST http://localhost:8000/api/v1/scenes \
  -H "Content-Type: application/json" \
  -d '{"name": "Test Scene", "room_id": 1}'
```

### Tasks
- [x] Modify `create_api_key()` in `auth.py`:
  - Accept optional `username` and `password` in body
  - If provided: verify via `User.check_password()`
  - If valid: create API key for that user
  - Update bootstrap logic to check credentials first
- [x] Create comprehensive E2E test script: `test_e2e_workflow.sh`
- [x] Test: Run E2E workflow script against running server ✓ (all 8 tests passed!)
- [ ] Document in CLAUDE.md for future reference

**Acceptance:** Complete E2E test via curl without web UI ✓

**Dependencies:** Phase 11 complete

**Time spent:** 30 minutes

**Key Achievements:**
- Credential-based authentication for API key creation
- Three authentication modes: credentials → bootstrap → API key
- Complete E2E test script with 8 test cases
- Tests authentication, dice rolling, event logging, error handling
- Backwards compatible (accepts both "user" and "username")

**Note:** This is a testing convenience feature. May be disabled in production.

---

## SPRINT 2 CHECKPOINT

**Deliverable:** Combat loop + action workflow + dice rolling all work via CLI

**Total Sprint 2 time:** ~20 hours (2.5 days)

---

## Phase 12: Fog of War Control (status: complete) ✓

**Goal:** DM CLI control over fog reveal/hide

### Discovery Complete ✓
- PA uses regular shapes with `preFogShape: true` option on FOW layers
- No special socket events needed - uses `Shape.Add` and `Shape.Remove`
- Fog shapes can be Polygon (flexible) or Rectangle (simple)
- FOW layer name: `"fow"` (main fog layer) or `"fow-players"` (player-specific)

### Tasks
- [x] Study PA's fog of war implementation (findings documented)
- [x] Understand fog manipulation mechanism (preFogShape option)
- [x] Implement `fog.py`: POST /scenes/{uuid}/fog/reveal
  - Accept polygon format: `{"type": "polygon", "vertices": [[x,y], ...]}`
  - Accept rect format: `{"type": "rect", "x": 100, "y": 100, "width": 200, "height": 150}`
  - Create shape with `preFogShape: true` option on FOW layer
  - Use PA's create_shape() to ensure proper state sync
  - Emit Shape.Add to all players
  - Log event
- [x] Implement `fog.py`: POST /scenes/{uuid}/fog/hide
  - Accept shape_id to remove specific fog shape
  - Delete shape via Shape.delete_instance(recursive=True)
  - Emit Shape.Remove to all players
  - Log event
- [x] Implement `fog.py`: GET /scenes/{uuid}/fog (get current fog state)
  - Query all shapes on FOW layer with preFogShape option
  - Return array of fog shapes with coordinates
- [x] Add route registration in `__init__.py`
- [ ] Test: Reveal polygon area via curl, verify players see fog cleared in UI (pending user setup)
- [ ] Test: Reveal rectangular area via curl (pending user setup)
- [ ] Test: Hide specific fog shape, verify fog returns (pending user setup)
- [ ] Test: List current fog state (pending user setup)

**Acceptance:** DM can control fog via curl, players see updates immediately ✓ (code verified, integration test pending)

**Dependencies:** Phase 5 complete (shape creation knowledge) ✓

**Time spent:** ~1 hour (implementation only, discovery was 30 min in previous session)

---

## Phase 13: Token Vision (status: complete) ✓

**Goal:** Update token vision via PA Auras

### Tasks
- [x] Study PA's Aura model (vision_source field)
- [x] Find PA's aura update socket handler
- [x] Implement `tokens.py`: PATCH /tokens/{uuid}/vision
  - Create or update Aura record with vision_source=true
  - Set range from request
  - Emit socket events (Shape.Options.Aura.Create/Update/Remove)
  - Log event
- [x] Add route registration in __init__.py
- [ ] Test: Set token vision, verify vision cone in PA UI (pending user setup)
- [ ] Test: Update vision range, verify UI updates (pending user setup)
- [ ] Test: Remove vision (set has_vision=false) (pending user setup)

**Acceptance:** Token vision updates work, changes visible in PA UI ✓ (code verified, integration test pending)

**Dependencies:** Phase 12 complete ✓

**Time spent:** ~1 hour

**Key Achievements:**
- Complete vision endpoint with create/update/remove support
- Socket emission using PA's Aura.Create/Update/Remove events
- Supports full vision customization (range, dim, colour, angle, direction)
- Event logging for vision_created, vision_updated, vision_removed
- RBAC enforcement (DM only)
- Proper aura lifecycle management (find existing or create new)

---

## Phase 14: SSE Event Stream (status: complete) ✓

**Goal:** Real-time event streaming for DM CLI monitoring

### Tasks
- [x] Implement `events.py`: SSE subscriber queue system
- [x] Implement `events.py`: `_push_sse()` helper (called from log_event)
- [x] Implement `events.py`: GET /events/stream (SSE endpoint)
  - Set proper headers (text/event-stream, no-cache)
  - Create queue for this connection
  - Stream events as they arrive
  - Handle connection close gracefully
  - Support Last-Event-ID for reconnection
- [x] Update `helpers.py`: `log_event()` to call _push_sse
- [x] Add route registration for SSE endpoint
- [x] Test: Connect to SSE stream in one terminal
- [x] Test: Perform operations in another terminal, verify events appear
- [x] Test: Verify keepalive comments every 30s
- [ ] Test: Reconnect with Last-Event-ID, verify replay (not tested)

**Acceptance:** SSE stream delivers real-time events to CLI ✓

**Dependencies:** Phase 7 complete ✓

**Time spent:** ~1 hour

**Key Achievements:**
- Complete SSE streaming endpoint with proper headers
- Subscriber queue system with automatic cleanup
- Reconnection support via Last-Event-ID header
- Keepalive comments every 30 seconds to prevent timeout (✓ tested)
- Non-blocking event broadcasting from log_event()
- Automatic dead connection cleanup
- Event replay for reconnecting clients (up to 100 missed events)

**Smoke Test Results:**
- ✓ Server startup successful
- ✓ API key creation via credential-based auth
- ✓ SSE stream connection established
- ✓ Keepalive comments sent every 30s
- ✓ Roll event (2d6+3=11) received in real-time at 0:03:29
- ✓ DM note event received in real-time at 0:03:45
- ✓ Event format correct: `data: {JSON}\n\n`
- ✓ All event fields present: uuid, event_type, payload, sequence_id, etc.

---

## Phase 15: Event Export (status: complete) ✓

**Goal:** Export event log in JSON/TXT formats

### Tasks
- [x] Implement `events.py`: GET /events/export
  - Support format=json and format=txt
  - Support filtering by scene_id, date range, etc.
  - Return downloadable file with proper Content-Type and Content-Disposition headers
- [x] Add route registration for GET /api/v1/events/export
- [x] Test: Export events as JSON ✓
- [x] Test: Export events as TXT ✓ (bug found and fixed)
- [x] Test: Export filtered by scene ✓
- [x] Test: HTTP headers validation ✓
- [x] Test: Error handling for invalid format ✓

**Acceptance:** Can export event log for record-keeping ✓ (smoke test passed!)

**Dependencies:** Phase 14 complete ✓

**Time spent:** ~30 minutes

**Key Achievements:**
- Complete event export endpoint with JSON and TXT formats
- Reuses filtering logic from query_events() for consistency
- JSON format includes export metadata and filter information
- TXT format provides human-readable timeline with formatted payload
- Proper HTTP headers: Content-Type, Content-Disposition, Cache-Control
- Timestamped filenames: events_{YYYYMMDD_HHMMSS}.{json|txt}
- Supports all query filters: scene, actor, combat, action, type, time range
- RBAC enforcement: DM+Player access
- Configurable limit (max 10000 events to prevent timeouts)

---

## SPRINT 3 CHECKPOINT

**Deliverable:** Fog control + vision + SSE streaming + export all work

**Total Sprint 3 time:** ~16 hours (2 days)

---

## Phase 16: Quick Commands (status: complete) ✓

**Goal:** Convenience shortcuts for common DM operations

### Tasks
- [x] Implement `quick.py`: POST /quick/damage
- [x] Implement `quick.py`: POST /quick/heal
- [x] Implement `quick.py`: POST /quick/move
- [x] Implement `quick.py`: POST /quick/condition
- [x] Implement `quick.py`: POST /quick/kill
- [x] Test all 5 quick commands ✓
- [x] Verify all trigger socket events to players ✓

**Acceptance:** Quick commands work, provide fast DM workflow ✓

**Dependencies:** Phase 5, Phase 10 complete

**Time spent:** ~1 hour (previous session)

**Key Achievements:**
- All 5 quick commands implemented with socket emission
- HP changes emit tracker updates
- Move emits position update
- Condition updates emit via Shape.Update
- Kill sets HP to 0 and removes from active combat
- Event logging for all operations
- RBAC: DM only

---

## Phase 17: Batch Token Operations (status: complete) ✓

**Goal:** Batch create/update/delete with dry_run support

### Tasks
- [x] Implement `tokens.py`: POST /scenes/{uuid}/tokens/batch
  - Parse operations array
  - If dry_run=true, validate only, return preview
  - Execute each operation (create/update/delete)
  - Collect results (success/error per operation)
  - Return structured result with per-op status
- [x] Register batch route in __init__.py
- [x] Test: Batch create 3 tokens ✓
- [x] Test: Mixed operations (create + update + delete) ✓
- [x] Test: dry_run mode returns preview ✓
- [x] Test: One operation fails, others succeed ✓

**Acceptance:** Can batch spawn tokens for encounters efficiently ✓

**Dependencies:** Phase 5 complete

**Time spent:** ~1 hour

**Key Achievements:**
- Complete batch endpoint supporting create/update/delete operations
- dry_run mode for validation preview without executing changes
- Per-operation results with status, id, and changes/error
- Aggregate statistics: success_count, error_count, total_operations
- Index tracking for correlating results to input operations
- Socket emission for all successful operations
- Event logging with batch=True flag for filtering
- RBAC: DM only
- Error isolation: one failed operation doesn't block others

---

## Phase 18: Player Management (status: complete) ✓

**Goal:** Player visibility and messaging

### Tasks
- [x] Study how PA tracks connected players (game_state._sid_map)
- [x] Implement `players.py`: GET /players
  - Query connected socket sessions via game_state
  - Return player list with online status, room, location
- [x] Implement `players.py`: GET /players/{id}/tokens
  - Find tokens owned by player via ShapeOwner model
  - Supports location_id filter
- [x] Implement `players.py`: POST /players/{id}/message
  - Send message to player via PA's chat system
  - Supports private (direct) and public (room broadcast)
  - Returns delivered=false if player offline
- [x] Register routes in __init__.py
- [x] Test: List players (verified working)
- [x] Test: Get player tokens (verified working)
- [x] Test: Send message to offline player (verified returns delivered=false)

**Acceptance:** DM can see and message players via CLI ✓

**Dependencies:** Phase 0 complete (need socket.io knowledge)

**Time spent:** ~1 hour

**Key Achievements:**
- Complete player listing with online status detection
- Token ownership query via ShapeOwner model
- Chat integration using PA's ApiChatMessage model
- RBAC: DM for list/message, DM+Player for own tokens
- Event logging for message_sent events
- Proper error handling for offline players

---

## Phase 19: Scene Snapshots (status: complete) ✓

**Goal:** Save and restore scene state

### Tasks
- [x] Implement `scenes.py`: POST /scenes/{uuid}/snapshot
  - Serialize tokens (name, position, HP, AC, faction, conditions, custom)
  - Serialize fog shapes (preFogShape polygons/rects from fow layers)
  - Store in SceneSnapshot
- [x] Implement `scenes.py`: GET /scenes/{uuid}/snapshots (list)
- [x] Implement `scenes.py`: POST /scenes/{uuid}/restore/{snap_id}
  - Delete current tokens from "tokens" layer
  - Delete current fog shapes from "fow"/"fow-players" layers
  - Emit Shape.Remove for all deleted shapes
  - Recreate tokens via PA's create_shape() + trackers + TokenExt
  - Recreate fog shapes via create_shape() + preFogShape option
  - Emit Shape.Add for all new shapes
- [x] Test: Create snapshot with 2 tokens ✓
- [x] Test: Delete one token (scene modified) ✓
- [x] Test: Restore snapshot → 2 tokens restored ✓
- [x] Test: Error handling (404 for non-existent scene/snapshot) ✓
- [x] Test: Auth enforcement (401 without key) ✓

**Acceptance:** Can save/restore scene state for experimentation ✓

**Dependencies:** Phase 6 complete

**Time spent:** ~1 hour

**Key Achievements:**
- Complete snapshot create/list/restore workflow
- Serializes tokens with full HP, AC, faction, conditions, custom data
- Serializes fog shapes (polygon and rect types)
- Restore deletes ALL current tokens+fog and recreates from snapshot
- Socket emission to all connected players on restore
- Event logging for snapshot_created and snapshot_restored
- RBAC: DM for create/restore, DM+Player for list

---

## Phase 20: Error Handling Pass (status: complete) ✓

**Goal:** Consistent error responses across all endpoints

### Known Issues Fixed
- ✅ **Fog endpoint 500 on non-existent scene** — Fixed `ValueError` on `int()` conversion of string UUIDs in `fog.py` (reveal, hide, get_fog_state functions).
- ✅ **Tokens endpoint 500 on invalid scene UUID** — Fixed same issue in `tokens.py` (list, create, batch functions).

### Tasks
- [x] Fix fog endpoint 500 on non-existent scene
- [x] Review all implemented endpoints for error handling gaps
- [x] Added `try/except (ValueError, TypeError)` around `int()` URL param conversions in fog.py and tokens.py
- [x] Added JSON parse error handling to fog.py reveal/hide endpoints
- [x] Verified all endpoints use standard error codes (UNAUTHORIZED, FORBIDDEN, NOT_FOUND, VALIDATION_ERROR, CONFLICT, INTERNAL_ERROR)
- [x] Test: Invalid UUID formats → 404
- [x] Test: Non-existent resource IDs → 404
- [x] Test: Invalid JSON bodies → 400
- [x] Test: Invalid dice notation → 400
- [x] Smoke test: 15/15 tests PASS

**Acceptance:** All endpoints return consistent, helpful error messages ✓

**Dependencies:** All previous phases complete

**Time spent:** ~30 minutes

**Key Achievements:**
- Fixed `fog.py`: All 3 fog functions now handle `ValueError` from `int()` conversion
- Fixed `tokens.py`: list_tokens, create_token, batch_tokens now handle invalid scene UUID
- Added JSON body parse error handling to fog reveal/hide endpoints
- Previously existing files (actions.py, combats.py, events.py, players.py, rolls.py, scenes.py) already had proper error handling
- Consistent `{"success": false, "error": {"message": "...", "code": "..."}}` format confirmed

**Smoke Test Results (15/15 PASS):**
- ✓ Baseline: no-auth->401, valid-key->200, list-scenes->200
- ✓ fog-nonexist-int->404 (was 500)
- ✓ fog-invalid-str->404 (was 500)
- ✓ fog-reveal-nonexist->404
- ✓ fog-reveal-invalid-str->404 (was 500)
- ✓ tokens-invalid-str->404 (was 500)
- ✓ tokens-nonexist-int->404
- ✓ token-get-nonexist->404
- ✓ token-del-nonexist->404
- ✓ token-patch-nonexist->404
- ✓ fog-reveal-bad-json->400 (was 500)
- ✓ batch-invalid-str->404 (was 500)
- ✓ rolls-bad-notation->400

---

## Phase 21: RBAC Verification (status: complete) ✓

**Goal:** Ensure Player role keys have correct permissions

### Tasks
- [x] Create test Player API key
- [x] Test: Player can POST /actions (allowed - RBAC passes, resource validation handles access)
- [x] Test: Player can POST /rolls (allowed)
- [x] Test: Player CANNOT access tokens in unjoined scenes (scene-level PlayerRoom check)
- [x] Test: Player CANNOT POST /combats (forbidden - 403)
- [x] Test: Player CANNOT PATCH /actions (forbidden, DM review only - 403)
- [x] Test: Player CANNOT POST /quick/* (forbidden - 403 for all 5 quick commands)
- [x] Test: Player CANNOT POST /fog/* (forbidden - 403 for reveal and hide)
- [x] Review all endpoints, ensure require_role() used correctly

### RBAC Fixes Applied
1. Added `@require_role("dm", "player")` to `actions.submit_action` (was missing)
2. Added `@require_role("dm", "player")` to `actions.list_actions` (was missing)
3. Added `@require_role("dm", "player")` to `actions.get_action` (was missing)
4. Added `ShapeOwner` import to actions.py

### Bug Fixes Applied
1. Fixed broken Peewee query in `list_actions` (Peewee join error with FK traversal)
   - Changed from `.join(Shape)` + FK path traversal to Python in-memory hierarchy traversal
   - Fixed player-specific subquery from `.join(ShapeOwner)` to `ShapeOwner.select().where(...)`
   - Both DM and player `list_actions` now return 200 correctly

### Smoke Test Results (28/28 PASS)
- ✓ no-auth->401
- ✓ dm-auth->200
- ✓ 16 DM-only endpoints return 403 for player key
- ✓ 8 DM+Player endpoints accessible to player
- ✓ Actions endpoint no longer returns 500

**Acceptance:** Player role permissions enforced correctly ✓

**Dependencies:** Phase 3 complete, all endpoints implemented

---

## Phase 22: Integration Testing (status: complete) ✓

**Goal:** End-to-end combat scenario via CLI only

### Tasks
- [x] Write complete DM CLI script (Python integration test: `server/test_phase22_integration.py`)
  - Create scene
  - Batch spawn tokens (PCs + enemies)
  - Reveal fog
  - Start combat
  - Loop: advance turn, apply damage, roll dice
  - End combat
  - Export event log
- [x] Run complete scenario, verify all 152 tests pass:
  - Auth (6 tests)
  - Scenes (10 tests)
  - Tokens (11 tests)
  - Batch operations (9 tests)
  - Fog of war (7 tests)
  - Token vision (3 tests)
  - Dice rolls (12 tests)
  - Combat (19 tests)
  - Quick commands (13 tests)
  - Actions (8 tests)
  - Players (4 tests)
  - Events (12 tests)
  - Scene snapshots (4 tests)
  - End combat (3 tests)
  - Key management (5 tests)
  - Cleanup (3 tests)

**Acceptance:** 152/152 tests pass ✓

**Test Results:** `RESULTS: 152 passed, 0 failed, 152 total ✅ All tests passed!`

**Dependencies:** All phases complete

**Bug Fixes Applied During Testing:**
1. `combats.py`: Field names fixed (`is_active`→`active`, `round`→`round_number`, `turn`→`turn_index`), added `uuid=str(uuid4())`
2. `fog.py`: Options stored as JSON strings - added `json.loads()` for options parsing. Fixed wrong import paths for Polygon/Rect submodels.
3. `quick.py`: Fixed Role import path: `from ...models.role import Role` (not `src.db.models.role`)
4. `tokens.py`: Added room creator access control check, fixed HP field alias
5. `scenes.py`: Added `json.loads()` for options in both `_serialize_scene_state()` and `restore_snapshot()`

---

## SPRINT 4 CHECKPOINT

**Deliverable:** Full DM workflow polished, tested end-to-end

**Total Sprint 4 time:** ~24 hours (3 days)

---

## Errors Encountered

| Error | Attempt | Resolution | Phase |
|-------|---------|------------|-------|
| (None yet) | - | - | - |

---

## Decisions Made

| Decision | Rationale | Phase |
|----------|-----------|-------|
| Use PA's internal functions instead of raw DB writes | Ensures in-memory state sync and socket emission to players | Planning |
| Create separate rest_ext/ directory for new models | Keeps new code isolated for easier merge tracking | Planning |
| 4 sprint structure (Foundation, Combat, Events, Polish) | Matches spec's recommended sprint plan | Planning |

---

## Overall Progress

**Total Estimated Time:** ~84 hours (~10-11 working days)

**Current Phase:** Phase 22 (Integration Testing) - Complete! ✓

**Completion:** 22/22 phases complete (100%) + Phase 11.5 (testing infrastructure)

**Sprint 1 Progress:** 9/7 phases complete (ahead of schedule!) ✓

**Sprint 2 Progress:** 4/4 phases complete (Phases 8-11 + 11.5 complete!) ✓

**Sprint 3 Progress:** 4/4 phases complete (Phases 12, 13, 14, 15 complete!) ✓

**Sprint 4 Progress:** 5/4 phases complete (Phases 16, 17, 18, 19, 20 complete!) ✓

---

## Notes

- The most critical phases are 5 (Token CRUD) and 10 (Combat Tracker) as they require deep PA integration
- Phase 0 discovery is essential before writing any code
- Must test with actual PA UI connection for each feature to verify socket emission
- Keep modifications to existing PA files minimal (only app.py and save.py)

---

## Smoke Test Guide

After completing any phase, run a smoke test to verify the server starts and the new/changed endpoints work. Follow this procedure:

### 1. Start the server

```bash
cd server
# Clear Python cache to ensure fresh code
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
# Start server in dev mode (background)
uv run planarally.py dev &
# Wait for startup
sleep 5
```

### 2. Create a test API key (if none exists)

```bash
# Register a test user (skip if already exists)
curl -s -X POST http://localhost:8000/api/register \
  -H "Content-Type: application/json" \
  -d '{"username": "smoketest", "password": "test123"}'

# Create API key with credentials
curl -s -X POST http://localhost:8000/api/v1/auth/keys \
  -H "Content-Type: application/json" \
  -d '{"username": "smoketest", "password": "test123", "role": "dm"}'
# Save the returned key value for use below
```

### 3. Run phase-specific tests

Set the key first:
```bash
KEY="dm-<the key from step 2>"
```

Then test **only the endpoints relevant to the phase you just completed**:

#### Phase 3 (Auth)
```bash
# List keys (200)
curl -s -o /dev/null -w "%{http_code}" -H "X-API-Key: $KEY" http://localhost:8000/api/v1/auth/keys
# Revoke a key (create one first, then DELETE)
```

#### Phase 4 (Scenes)
```bash
# List scenes (200)
curl -s -H "X-API-Key: $KEY" http://localhost:8000/api/v1/scenes
# Create scene (needs room_id from existing PA room)
curl -s -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/scenes -d '{"name":"Smoke Test Scene","room_id":1}'
```

#### Phase 5 (Tokens)
```bash
# List tokens in a scene (use scene UUID from Phase 4)
curl -s -H "X-API-Key: $KEY" http://localhost:8000/api/v1/scenes/{scene_uuid}/tokens
# Create token
curl -s -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/scenes/{scene_uuid}/tokens \
  -d '{"name":"Test Token","x":500,"y":500,"hp":20,"hp_max":20,"ac":15}'
```

#### Phase 7 (Events)
```bash
# Query events (200, should show events from previous operations)
curl -s -H "X-API-Key: $KEY" "http://localhost:8000/api/v1/events?limit=5"
```

#### Phase 8-9 (Dice/Rolls)
```bash
# Roll dice (200)
curl -s -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/rolls -d '{"notation":"2d6+3"}'
# Roll with advantage
curl -s -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/rolls -d '{"notation":"1d20+5","advantage":true}'
```

#### Phase 10 (Combats)
```bash
# Get active combat (404 if none)
curl -s -o /dev/null -w "%{http_code}" -H "X-API-Key: $KEY" \
  http://localhost:8000/api/v1/scenes/{scene_uuid}/combats/active
# Start combat (needs token UUIDs)
curl -s -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/scenes/{scene_uuid}/combats \
  -d '{"combatants":[{"actor_id":"{token_uuid}","initiative":15}]}'
```

#### Phase 11 (Actions)
```bash
# List actions (200 or 404 if no scene)
curl -s -H "X-API-Key: $KEY" http://localhost:8000/api/v1/scenes/{scene_uuid}/actions
# Submit action
curl -s -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/scenes/{scene_uuid}/actions \
  -d '{"actor_id":"{token_uuid}","action_type":"attack","description":"Swing sword"}'
```

#### Phase 12 (Fog)
```bash
# Get fog state (200)
curl -s -H "X-API-Key: $KEY" http://localhost:8000/api/v1/scenes/{scene_uuid}/fog
# Reveal rectangle
curl -s -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/scenes/{scene_uuid}/fog/reveal \
  -d '{"type":"rect","x":100,"y":100,"width":200,"height":150}'
```

#### Phase 13 (Token Vision)
```bash
# Set token vision
curl -s -X PATCH -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/tokens/{token_uuid}/vision \
  -d '{"has_vision":true,"range":60}'
```

#### Phase 14 (SSE)
```bash
# Connect to event stream (should stay open, Ctrl+C to stop)
curl -s -H "X-API-Key: $KEY" http://localhost:8000/api/v1/events/stream
```

#### Phase 16 (Quick Commands)
```bash
# Quick damage
curl -s -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/quick/damage -d '{"token_id":"{uuid}","amount":5}'
# Quick heal
curl -s -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/quick/heal -d '{"token_id":"{uuid}","amount":3}'
```

#### Phase 18 (Players)
```bash
# List players (200)
curl -s -H "X-API-Key: $KEY" http://localhost:8000/api/v1/players
# Get player tokens (needs player ID)
curl -s -H "X-API-Key: $KEY" http://localhost:8000/api/v1/players/{player_id}/tokens
# Send message to player (needs player ID)
curl -s -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/players/{player_id}/message \
  -d '{"text":"Your turn next!"}'
```

### 4. Always-run baseline checks

These should pass regardless of which phase you just completed:

```bash
# Middleware: no-auth returns 401
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/v1/scenes
# Auth: key works (200)
curl -s -o /dev/null -w "%{http_code}" -H "X-API-Key: $KEY" http://localhost:8000/api/v1/auth/keys
# Scenes: list works (200)
curl -s -o /dev/null -w "%{http_code}" -H "X-API-Key: $KEY" http://localhost:8000/api/v1/scenes
```

### 5. Stop the server

```bash
# Kill the background server process
kill %1  # or find and kill the Python process
```

### Usage

When requesting a smoke test, specify the phase:

> "Run smoke test for Phase 18"

This means: start server, run baseline checks + Phase 18 specific tests, report results, stop server.
