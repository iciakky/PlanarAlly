#!/usr/bin/env python3
"""
Phase 25: Bug Hunt Round 3 — Regression Tests
Tests reproduce 2 confirmed bugs in the Phase 1-24 REST API code.

Bugs:
  1. fog.py: reveal_fog/hide_fog/get_fog_state return status=404 for invalid UUID format (should be 400)
  2. scenes.py: 7 single-scene endpoints missing per-resource ownership/access control check
"""

import json
import sqlite3
import sys
import time
import urllib.request
import urllib.error

BASE_URL = "http://localhost:8000"
TS = int(time.time())
USER_A = f"p25test_a_{TS}"
USER_B = f"p25test_b_{TS}"
USER_PASS = "testpass123"
DB_PATH = "D:/repo/PlanarAlly/server/data/planar.sqlite"

pass_count = 0
fail_count = 0
total_count = 0


def green(s):
    return f"\033[0;32m{s}\033[0m"

def red(s):
    return f"\033[0;31m{s}\033[0m"

def yellow(s):
    return f"\033[1;33m{s}\033[0m"


def check(condition, name, detail=""):
    global pass_count, fail_count, total_count
    total_count += 1
    if condition:
        pass_count += 1
        print(f"  {green('✓')} {name}")
    else:
        fail_count += 1
        print(f"  {red('✗')} {name}" + (f" ({detail})" if detail else ""))


def http(method, path, body=None, headers=None, key=None):
    """Make HTTP request, return (status, response_body, response_headers)."""
    url = f"{BASE_URL}{path}"
    data = json.dumps(body).encode() if body is not None else None
    hdrs = {"Content-Type": "application/json"} if body is not None else {}
    if headers:
        hdrs.update(headers)
    if key:
        hdrs["X-API-Key"] = key

    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            status = resp.status
            raw = resp.read()
            resp_headers = dict(resp.headers)
            try:
                resp_body = json.loads(raw)
            except Exception:
                resp_body = {"_raw": raw.decode("utf-8", errors="replace")}
            return status, resp_body, resp_headers
    except urllib.error.HTTPError as e:
        status = e.code
        resp_headers = dict(e.headers)
        try:
            raw = e.read()
            try:
                resp_body = json.loads(raw)
            except Exception:
                resp_body = {"_raw": raw.decode("utf-8", errors="replace")}
        except Exception:
            resp_body = {}
        return status, resp_body, resp_headers
    except Exception as e:
        return 0, {"error": str(e)}, {}


def check_status(name, actual, expected=200):
    check(actual == expected, name, f"expected {expected}, got {actual}")


def jget(body, *keys, default=None):
    """Safely navigate nested dict."""
    try:
        val = body
        for k in keys:
            val = val[k]
        return val
    except (KeyError, TypeError, IndexError):
        return default


print("=" * 60)
print("PlanarAlly REST API - Phase 25 Bug Hunt Tests")
print("=" * 60)
print(f"User A: {USER_A}")
print(f"User B: {USER_B}")
print(f"Timestamp: {TS}")
print()

# ============================================================
# SETUP
# ============================================================
print("--- SETUP ---")

# Register User A
s, r, _ = http("POST", "/api/register", {"username": USER_A, "password": USER_PASS})
check_status("Register User A", s, 200)

# Register User B
s, r, _ = http("POST", "/api/register", {"username": USER_B, "password": USER_PASS})
check_status("Register User B", s, 200)

# Create API key for User A (DM)
s, r, _ = http("POST", "/api/v1/auth/keys", {"username": USER_A, "password": USER_PASS, "role": "dm"})
KEY_A = jget(r, "data", "key")
if KEY_A:
    check(True, f"Create DM API key for User A")
    print(f"    Key A: {KEY_A[:20]}...")
else:
    check(False, "Create DM API key for User A - ABORTING")
    print(f"    Response: {r}")
    sys.exit(1)

# Create API key for User B (DM)
s, r, _ = http("POST", "/api/v1/auth/keys", {"username": USER_B, "password": USER_PASS, "role": "dm"})
KEY_B = jget(r, "data", "key")
if KEY_B:
    check(True, f"Create DM API key for User B")
    print(f"    Key B: {KEY_B[:20]}...")
else:
    check(False, "Create DM API key for User B - ABORTING")
    print(f"    Response: {r}")
    sys.exit(1)

# Get User A ID from DB
db = sqlite3.connect(DB_PATH)
USER_A_ID = db.execute("SELECT id FROM user WHERE name=?", (USER_A,)).fetchone()
if USER_A_ID:
    USER_A_ID = USER_A_ID[0]
    check(True, f"Got User A ID: {USER_A_ID}")
else:
    check(False, "Get User A ID - ABORTING")
    sys.exit(1)

# Create room owned by User A via direct SQLite INSERT
ROOM_NAME = f"P25Test_Room_{TS}"
db.execute("INSERT INTO location_options (spawn_locations) VALUES ('[]')")
LOC_OPT_ID = db.execute("SELECT last_insert_rowid()").fetchone()[0]
db.execute(
    "INSERT INTO room (name, creator_id, invitation_code, is_locked, default_options_id, enable_chat, enable_dice) "
    "VALUES (?, ?, ?, 0, ?, 1, 1)",
    (ROOM_NAME, USER_A_ID, f"invite-p25-{TS}", LOC_OPT_ID)
)
db.commit()
ROOM_ID = db.execute("SELECT id FROM room WHERE name=?", (ROOM_NAME,)).fetchone()[0]
check(bool(ROOM_ID), f"Create test room via DB (room_id={ROOM_ID})")

# Create a scene via REST (as User A)
s, r, _ = http("POST", "/api/v1/scenes", {"name": "P25 Test Scene", "room_id": ROOM_ID}, key=KEY_A)
check_status("Create scene (as User A) → 201", s, 201)
SCENE_UUID = jget(r, "data", "uuid")
if SCENE_UUID:
    check(True, f"Scene UUID: {SCENE_UUID}")
else:
    check(False, f"Get scene UUID - ABORTING (response: {r})")
    sys.exit(1)

print()

# ============================================================
# BUG 1 — fog.py: invalid scene UUID returns 404 instead of 400
# ============================================================
print("--- BUG 1: fog.py — invalid scene UUID returns 404 (should be 400) ---")

# reveal_fog — POST /api/v1/scenes/not-an-int/fog/reveal
s, r, _ = http("POST", "/api/v1/scenes/not-an-int/fog/reveal",
               {"type": "rect", "x": 0, "y": 0, "width": 100, "height": 100},
               key=KEY_A)
check_status(
    "POST /scenes/not-an-int/fog/reveal → 400 (Bug 1: invalid UUID is validation error, not NOT_FOUND)",
    s, 400
)
check(
    jget(r, "error", "code") == "VALIDATION_ERROR",
    f"Error code == VALIDATION_ERROR (got {jget(r, 'error', 'code')!r})"
)

# hide_fog — POST /api/v1/scenes/not-an-int/fog/hide
s, r, _ = http("POST", "/api/v1/scenes/not-an-int/fog/hide",
               {"shape_id": "00000000-0000-0000-0000-000000000001"},
               key=KEY_A)
check_status(
    "POST /scenes/not-an-int/fog/hide → 400 (Bug 1: invalid UUID is validation error)",
    s, 400
)
check(
    jget(r, "error", "code") == "VALIDATION_ERROR",
    f"Error code == VALIDATION_ERROR (got {jget(r, 'error', 'code')!r})"
)

# get_fog_state — GET /api/v1/scenes/not-an-int/fog
s, r, _ = http("GET", "/api/v1/scenes/not-an-int/fog", key=KEY_A)
check_status(
    "GET /scenes/not-an-int/fog → 400 (Bug 1: invalid UUID is validation error)",
    s, 400
)
check(
    jget(r, "error", "code") == "VALIDATION_ERROR",
    f"Error code == VALIDATION_ERROR (got {jget(r, 'error', 'code')!r})"
)

print()

# ============================================================
# BUG 2 — scenes.py: missing per-resource access control (User B accesses User A's scene)
# ============================================================
print("--- BUG 2: scenes.py — cross-user access (User B accesses User A's scene) ---")

# GET /api/v1/scenes/{uuid} (as User B)
s, r, _ = http("GET", f"/api/v1/scenes/{SCENE_UUID}", key=KEY_B)
check_status(
    f"GET /scenes/{{uuid}} (as User B) → 403 (Bug 2: cross-DM isolation missing)",
    s, 403
)

# PUT /api/v1/scenes/{uuid} (as User B)
s, r, _ = http("PUT", f"/api/v1/scenes/{SCENE_UUID}", {"name": "Hijacked Scene"}, key=KEY_B)
check_status(
    f"PUT /scenes/{{uuid}} (as User B) → 403 (Bug 2: cross-DM update blocked)",
    s, 403
)

# GET /api/v1/scenes/{uuid}/state (as User B)
s, r, _ = http("GET", f"/api/v1/scenes/{SCENE_UUID}/state", key=KEY_B)
check_status(
    f"GET /scenes/{{uuid}}/state (as User B) → 403 (Bug 2: cross-DM state read blocked)",
    s, 403
)

# POST /api/v1/scenes/{uuid}/snapshot (as User B)
s, r, _ = http("POST", f"/api/v1/scenes/{SCENE_UUID}/snapshot", {"name": "Rogue Snapshot"}, key=KEY_B)
check_status(
    f"POST /scenes/{{uuid}}/snapshot (as User B) → 403 (Bug 2: cross-DM snapshot blocked)",
    s, 403
)

# GET /api/v1/scenes/{uuid}/snapshots (as User B)
s, r, _ = http("GET", f"/api/v1/scenes/{SCENE_UUID}/snapshots", key=KEY_B)
check_status(
    f"GET /scenes/{{uuid}}/snapshots (as User B) → 403 (Bug 2: cross-DM snapshot list blocked)",
    s, 403
)

# Create a legitimate snapshot as User A (needed for restore test)
s, r, _ = http("POST", f"/api/v1/scenes/{SCENE_UUID}/snapshot", {"name": "Legit Snapshot"}, key=KEY_A)
check_status("Create snapshot as User A → 201 (setup for restore test)", s, 201)
SNAP_UUID = jget(r, "data", "uuid")
if SNAP_UUID:
    check(True, f"Snapshot UUID: {SNAP_UUID}")
else:
    check(False, "Could not get snapshot UUID (skipping restore test)")
    SNAP_UUID = None

# POST /api/v1/scenes/{uuid}/restore/{snap_id} (as User B)
if SNAP_UUID:
    s, r, _ = http("POST", f"/api/v1/scenes/{SCENE_UUID}/restore/{SNAP_UUID}", {}, key=KEY_B)
    check_status(
        f"POST /scenes/{{uuid}}/restore/{{snap_id}} (as User B) → 403 (Bug 2: cross-DM restore blocked)",
        s, 403
    )

# DELETE /api/v1/scenes/{uuid} (as User B) — test LAST to avoid destroying scene during testing
s, r, _ = http("DELETE", f"/api/v1/scenes/{SCENE_UUID}", key=KEY_B)
check_status(
    f"DELETE /scenes/{{uuid}} (as User B) → 403 (Bug 2: cross-DM delete blocked)",
    s, 403
)

# Verify scene still exists (User B's delete should have been rejected)
s, r, _ = http("GET", f"/api/v1/scenes/{SCENE_UUID}", key=KEY_A)
check(
    s == 200,
    f"Scene still exists after User B's blocked DELETE (User A GET → 200, got {s})"
)

print()

# ============================================================
# REGRESSION — Phase 23/24 smoke tests
# ============================================================
print("--- REGRESSION (Phase 23/24 minimal smoke test) ---")

# Phase 23 Bug 1: non-UUID player ID → 400
s, r, _ = http("GET", "/api/v1/players/abc/tokens", key=KEY_A)
check_status("GET /players/abc/tokens → 400 (Phase 23 Bug 1 regression)", s, 400)

# Phase 24 Bug 3: start_combat → 201
import uuid as _uuid
TOKEN_UUID = None
s, r, _ = http("GET", f"/api/v1/scenes/{SCENE_UUID}/tokens", key=KEY_A)
tokens_list = jget(r, "data", "tokens", default=[])
if tokens_list:
    TOKEN_UUID = tokens_list[0].get("uuid")

if TOKEN_UUID is None:
    # Create a token for combat test
    s, r, _ = http("POST", f"/api/v1/scenes/{SCENE_UUID}/tokens",
                   {"name": "CombatToken", "x": 0, "y": 0, "hp": 10, "hp_max": 10, "faction": "neutral"},
                   key=KEY_A)
    TOKEN_UUID = jget(r, "data", "uuid")

if TOKEN_UUID:
    s, r, _ = http("POST", f"/api/v1/scenes/{SCENE_UUID}/combats",
                   {"combatants": [{"actor_id": TOKEN_UUID, "initiative": 10}]},
                   key=KEY_A)
    check_status("POST /scenes/{id}/combats → 201 (Phase 24 Bug 3 regression)", s, 201)
else:
    check(False, "Could not get token for combat test (skipping)")

# Phase 24 Bug 4: invalid actor_id → 0 rolls
NONEXISTENT = "00000000-0000-0000-0000-000000000001"
s, r, _ = http("GET", f"/api/v1/rolls?actor_id={NONEXISTENT}", key=KEY_A)
check_status("GET /rolls?actor_id=<nonexistent> → 200 (Phase 24 Bug 4 regression)", s, 200)
check(jget(r, "data", "total_count", default=-1) == 0,
      "total_count == 0 for non-existent actor_id (regression check)")

print()

# ============================================================
# SUMMARY
# ============================================================
print("=" * 60)
print(f"Results: {pass_count}/{total_count} passed, {fail_count} failed")
if fail_count == 0:
    print(green("ALL TESTS PASSED"))
else:
    print(red(f"{fail_count} TESTS FAILED"))
print("=" * 60)

sys.exit(0 if fail_count == 0 else 1)
