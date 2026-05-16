#!/usr/bin/env python3
"""
Phase 26: Access Control Consistency Audit — Bug Tests
Tests reproduce 2 confirmed bugs in tokens.py, combats.py, actions.py.

Bugs:
  1. tokens.py, combats.py, actions.py: invalid scene UUID returns 404 (should be 400)
  2. combats.py, actions.py: 4 scene-scoped endpoints missing per-resource ownership check
"""

import json
import sqlite3
import sys
import time
import urllib.request
import urllib.error

BASE_URL = "http://localhost:8000"
TS = int(time.time())
USER_A = f"p26test_a_{TS}"
USER_B = f"p26test_b_{TS}"
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
        print(f"  {green('PASS')} {name}")
    else:
        fail_count += 1
        print(f"  {red('FAIL')} {name}" + (f" ({detail})" if detail else ""))


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
print("PlanarAlly REST API - Phase 26 Bug Hunt Tests")
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

# Create DM API key for User A
s, r, _ = http("POST", "/api/v1/auth/keys", {"username": USER_A, "password": USER_PASS, "role": "dm"})
KEY_A = jget(r, "data", "key")
if KEY_A:
    check(True, f"Create DM API key for User A")
    print(f"    Key A: {KEY_A[:20]}...")
else:
    check(False, "Create DM API key for User A - ABORTING")
    print(f"    Response: {r}")
    sys.exit(1)

# Create DM API key for User B
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
ROOM_NAME = f"P26Test_Room_{TS}"
db.execute("INSERT INTO location_options (spawn_locations) VALUES ('[]')")
LOC_OPT_ID = db.execute("SELECT last_insert_rowid()").fetchone()[0]
db.execute(
    "INSERT INTO room (name, creator_id, invitation_code, is_locked, default_options_id, enable_chat, enable_dice) "
    "VALUES (?, ?, ?, 0, ?, 1, 1)",
    (ROOM_NAME, USER_A_ID, f"invite-p26-{TS}", LOC_OPT_ID)
)
db.commit()
ROOM_ID = db.execute("SELECT id FROM room WHERE name=?", (ROOM_NAME,)).fetchone()[0]
check(bool(ROOM_ID), f"Create test room via DB (room_id={ROOM_ID})")

# Create a scene via REST (as User A)
s, r, _ = http("POST", "/api/v1/scenes", {"name": "P26 Test Scene", "room_id": ROOM_ID}, key=KEY_A)
check_status("Create scene (as User A) → 201", s, 201)
SCENE_UUID = jget(r, "data", "uuid")
if SCENE_UUID:
    check(True, f"Scene UUID: {SCENE_UUID}")
else:
    check(False, f"Get scene UUID - ABORTING (response: {r})")
    sys.exit(1)

# Create a token in User A's scene (needed for combat/action tests)
s, r, _ = http("POST", f"/api/v1/scenes/{SCENE_UUID}/tokens",
               {"name": "TestToken", "x": 0, "y": 0, "hp": 10, "hp_max": 10, "faction": "neutral"},
               key=KEY_A)
check_status("Create token in scene (as User A) → 201", s, 201)
TOKEN_UUID = jget(r, "data", "uuid")
if TOKEN_UUID:
    check(True, f"Token UUID: {TOKEN_UUID}")
else:
    check(False, "Could not create test token (some tests may be skipped)")

print()

# ============================================================
# BUG 1 — Invalid scene UUID → 404 (should be 400)
# ============================================================
print("--- BUG 1: Invalid scene UUID returns 404 (should be 400) ---")

# tokens.py — list_tokens
s, r, _ = http("GET", "/api/v1/scenes/not-an-int/tokens", key=KEY_A)
check_status(
    "GET /scenes/not-an-int/tokens → 400 (Bug 1: tokens.py list_tokens)",
    s, 400
)
check(
    jget(r, "error", "code") == "VALIDATION_ERROR",
    f"  error.code == VALIDATION_ERROR (got {jget(r, 'error', 'code')!r})"
)

# tokens.py — create_token
s, r, _ = http("POST", "/api/v1/scenes/not-an-int/tokens",
               {"name": "T", "x": 0, "y": 0},
               key=KEY_A)
check_status(
    "POST /scenes/not-an-int/tokens → 400 (Bug 1: tokens.py create_token)",
    s, 400
)
check(
    jget(r, "error", "code") == "VALIDATION_ERROR",
    f"  error.code == VALIDATION_ERROR (got {jget(r, 'error', 'code')!r})"
)

# tokens.py — batch_tokens
s, r, _ = http("POST", "/api/v1/scenes/not-an-int/tokens/batch",
               {"operations": [{"op": "create", "data": {"name": "T", "x": 0, "y": 0}}]},
               key=KEY_A)
check_status(
    "POST /scenes/not-an-int/tokens/batch → 400 (Bug 1: tokens.py batch_tokens)",
    s, 400
)
check(
    jget(r, "error", "code") == "VALIDATION_ERROR",
    f"  error.code == VALIDATION_ERROR (got {jget(r, 'error', 'code')!r})"
)

# combats.py — start_combat
s, r, _ = http("POST", "/api/v1/scenes/not-an-int/combats",
               {"combatants": [{"actor_id": "00000000-0000-0000-0000-000000000001", "initiative": 10}]},
               key=KEY_A)
check_status(
    "POST /scenes/not-an-int/combats → 400 (Bug 1: combats.py start_combat)",
    s, 400
)
check(
    jget(r, "error", "code") == "VALIDATION_ERROR",
    f"  error.code == VALIDATION_ERROR (got {jget(r, 'error', 'code')!r})"
)

# combats.py — get_active_combat
s, r, _ = http("GET", "/api/v1/scenes/not-an-int/combats/active", key=KEY_A)
check_status(
    "GET /scenes/not-an-int/combats/active → 400 (Bug 1: combats.py get_active_combat)",
    s, 400
)
check(
    jget(r, "error", "code") == "VALIDATION_ERROR",
    f"  error.code == VALIDATION_ERROR (got {jget(r, 'error', 'code')!r})"
)

# actions.py — submit_action
s, r, _ = http("POST", "/api/v1/scenes/not-an-int/actions",
               {"actor_id": "00000000-0000-0000-0000-000000000001", "action_type": "attack"},
               key=KEY_A)
check_status(
    "POST /scenes/not-an-int/actions → 400 (Bug 1: actions.py submit_action)",
    s, 400
)
check(
    jget(r, "error", "code") == "VALIDATION_ERROR",
    f"  error.code == VALIDATION_ERROR (got {jget(r, 'error', 'code')!r})"
)

# actions.py — list_actions
s, r, _ = http("GET", "/api/v1/scenes/not-an-int/actions", key=KEY_A)
check_status(
    "GET /scenes/not-an-int/actions → 400 (Bug 1: actions.py list_actions)",
    s, 400
)
check(
    jget(r, "error", "code") == "VALIDATION_ERROR",
    f"  error.code == VALIDATION_ERROR (got {jget(r, 'error', 'code')!r})"
)

print()

# ============================================================
# BUG 2 — combats.py / actions.py: missing per-resource ownership check
# ============================================================
print("--- BUG 2: Missing scene-level ownership check (User B accesses User A's scene) ---")

# combats.py — start_combat (as User B)
if TOKEN_UUID:
    s, r, _ = http("POST", f"/api/v1/scenes/{SCENE_UUID}/combats",
                   {"combatants": [{"actor_id": TOKEN_UUID, "initiative": 10}]},
                   key=KEY_B)
    check_status(
        f"POST /scenes/{{uuid}}/combats (as User B) → 403 (Bug 2: start_combat cross-DM isolation)",
        s, 403
    )
else:
    check(False, "POST /scenes/{uuid}/combats (as User B) → SKIPPED (no token)")

# combats.py — get_active_combat (as User B)
s, r, _ = http("GET", f"/api/v1/scenes/{SCENE_UUID}/combats/active", key=KEY_B)
check_status(
    f"GET /scenes/{{uuid}}/combats/active (as User B) → 403 (Bug 2: get_active_combat cross-DM isolation)",
    s, 403
)

# actions.py — submit_action (as User B)
if TOKEN_UUID:
    s, r, _ = http("POST", f"/api/v1/scenes/{SCENE_UUID}/actions",
                   {"actor_id": TOKEN_UUID, "action_type": "attack"},
                   key=KEY_B)
    check_status(
        f"POST /scenes/{{uuid}}/actions (as User B) → 403 (Bug 2: submit_action cross-DM isolation)",
        s, 403
    )
else:
    check(False, "POST /scenes/{uuid}/actions (as User B) → SKIPPED (no token)")

# actions.py — list_actions (as User B)
s, r, _ = http("GET", f"/api/v1/scenes/{SCENE_UUID}/actions", key=KEY_B)
check_status(
    f"GET /scenes/{{uuid}}/actions (as User B) → 403 (Bug 2: list_actions cross-DM isolation)",
    s, 403
)

print()

# ============================================================
# REGRESSION — Phase 25 minimal smoke: fog + scenes access control still hold
# ============================================================
print("--- REGRESSION (Phase 25 smoke: fog/scenes access control) ---")

# fog invalid UUID still 400
s, r, _ = http("POST", "/api/v1/scenes/not-an-int/fog/reveal",
               {"type": "rect", "x": 0, "y": 0, "width": 100, "height": 100},
               key=KEY_A)
check_status("POST /scenes/not-an-int/fog/reveal → 400 (Phase 25 Bug 1 regression)", s, 400)

# scenes cross-DM isolation still 403
s, r, _ = http("GET", f"/api/v1/scenes/{SCENE_UUID}", key=KEY_B)
check_status(f"GET /scenes/{{uuid}} (as User B) → 403 (Phase 25 Bug 2 regression)", s, 403)

# Phase 23 Bug 1 still holds: non-int player ID → 400
s, r, _ = http("GET", "/api/v1/players/abc/tokens", key=KEY_A)
check_status("GET /players/abc/tokens → 400 (Phase 23 Bug 1 regression)", s, 400)

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
