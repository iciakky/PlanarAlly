#!/usr/bin/env python3
"""
Phase 27: White-Box Scan — quick.py — Bug Tests
Tests reproduce Bug 2: 5 quick endpoints missing per-token ownership check.

Bug:
  2. quick.py: all 5 endpoints (damage/heal/move/condition/kill) lack per-token
     ownership check — any DM can operate on any token by UUID.
"""

import json
import sqlite3
import sys
import time
import urllib.request
import urllib.error

BASE_URL = "http://localhost:8000"
TS = int(time.time())
USER_A = f"p27test_a_{TS}"
USER_B = f"p27test_b_{TS}"
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
print("PlanarAlly REST API - Phase 27 Bug Hunt Tests")
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
    check(True, "Create DM API key for User A")
    print(f"    Key A: {KEY_A[:20]}...")
else:
    check(False, "Create DM API key for User A - ABORTING")
    print(f"    Response: {r}")
    sys.exit(1)

# Create DM API key for User B
s, r, _ = http("POST", "/api/v1/auth/keys", {"username": USER_B, "password": USER_PASS, "role": "dm"})
KEY_B = jget(r, "data", "key")
if KEY_B:
    check(True, "Create DM API key for User B")
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
ROOM_NAME = f"P27Test_Room_{TS}"
db.execute("INSERT INTO location_options (spawn_locations) VALUES ('[]')")
LOC_OPT_ID = db.execute("SELECT last_insert_rowid()").fetchone()[0]
db.execute(
    "INSERT INTO room (name, creator_id, invitation_code, is_locked, default_options_id, enable_chat, enable_dice) "
    "VALUES (?, ?, ?, 0, ?, 1, 1)",
    (ROOM_NAME, USER_A_ID, f"invite-p27-{TS}", LOC_OPT_ID)
)
db.commit()
ROOM_ID = db.execute("SELECT id FROM room WHERE name=?", (ROOM_NAME,)).fetchone()[0]
check(bool(ROOM_ID), f"Create test room via DB (room_id={ROOM_ID})")

# Create a scene via REST (as User A)
s, r, _ = http("POST", "/api/v1/scenes", {"name": "P27 Test Scene", "room_id": ROOM_ID}, key=KEY_A)
check_status("Create scene (as User A) → 201", s, 201)
SCENE_UUID = jget(r, "data", "uuid")
if SCENE_UUID:
    check(True, f"Scene UUID: {SCENE_UUID}")
else:
    check(False, f"Get scene UUID - ABORTING (response: {r})")
    sys.exit(1)

# Create a token with HP in User A's scene
s, r, _ = http(
    "POST", f"/api/v1/scenes/{SCENE_UUID}/tokens",
    {"name": "TestToken", "x": 100, "y": 100, "hp": 20, "hp_max": 20, "faction": "neutral"},
    key=KEY_A
)
check_status("Create token with HP in scene (as User A) → 201", s, 201)
TOKEN_UUID = jget(r, "data", "uuid")
if TOKEN_UUID:
    check(True, f"Token UUID: {TOKEN_UUID}")
else:
    check(False, "Could not create test token - ABORTING")
    print(f"    Response: {r}")
    sys.exit(1)

print()

# ============================================================
# BUG 2 — quick endpoints: missing per-token ownership check
# ============================================================
print("--- BUG 2: Missing per-token ownership check (User B accesses User A's token) ---")

# POST /api/v1/quick/damage  (as User B, User A's token)
s, r, _ = http(
    "POST", "/api/v1/quick/damage",
    {"token_id": TOKEN_UUID, "amount": 5},
    key=KEY_B
)
check_status(
    "POST /quick/damage (as User B, User A's token) → 403 (Bug 2: apply_damage cross-DM isolation)",
    s, 403
)

# POST /api/v1/quick/heal  (as User B, User A's token)
s, r, _ = http(
    "POST", "/api/v1/quick/heal",
    {"token_id": TOKEN_UUID, "amount": 3},
    key=KEY_B
)
check_status(
    "POST /quick/heal (as User B, User A's token) → 403 (Bug 2: apply_heal cross-DM isolation)",
    s, 403
)

# POST /api/v1/quick/move  (as User B, User A's token)
s, r, _ = http(
    "POST", "/api/v1/quick/move",
    {"token_id": TOKEN_UUID, "x": 200, "y": 200},
    key=KEY_B
)
check_status(
    "POST /quick/move (as User B, User A's token) → 403 (Bug 2: move_token cross-DM isolation)",
    s, 403
)

# POST /api/v1/quick/condition  (as User B, User A's token)
s, r, _ = http(
    "POST", "/api/v1/quick/condition",
    {"token_id": TOKEN_UUID, "condition": "poisoned", "action": "add"},
    key=KEY_B
)
check_status(
    "POST /quick/condition (as User B, User A's token) → 403 (Bug 2: update_condition cross-DM isolation)",
    s, 403
)

# POST /api/v1/quick/kill  (as User B, User A's token)
s, r, _ = http(
    "POST", "/api/v1/quick/kill",
    {"token_id": TOKEN_UUID},
    key=KEY_B
)
check_status(
    "POST /quick/kill (as User B, User A's token) → 403 (Bug 2: kill_token cross-DM isolation)",
    s, 403
)

print()

# ============================================================
# REGRESSION — All 5 quick endpoints work for User A (owner)
# ============================================================
print("--- REGRESSION: All 5 quick endpoints work for User A (owner) ---")

# POST /api/v1/quick/damage  (as User A)
s, r, _ = http(
    "POST", "/api/v1/quick/damage",
    {"token_id": TOKEN_UUID, "amount": 5},
    key=KEY_A
)
check_status("POST /quick/damage (as User A, owner) → 200", s, 200)
check(jget(r, "data", "damage") == 5, "  response.data.damage == 5")

# HP is now 15, verify
current_hp = jget(r, "data", "new_hp")

# POST /api/v1/quick/heal  (as User A)
s, r, _ = http(
    "POST", "/api/v1/quick/heal",
    {"token_id": TOKEN_UUID, "amount": 3},
    key=KEY_A
)
check_status("POST /quick/heal (as User A, owner) → 200", s, 200)
check(jget(r, "data", "healed") == 3, "  response.data.healed == 3")

# POST /api/v1/quick/move  (as User A)
s, r, _ = http(
    "POST", "/api/v1/quick/move",
    {"token_id": TOKEN_UUID, "x": 300, "y": 400},
    key=KEY_A
)
check_status("POST /quick/move (as User A, owner) → 200", s, 200)
check(jget(r, "data", "new_position", "x") == 300, "  response.data.new_position.x == 300")

# POST /api/v1/quick/condition  (as User A)
s, r, _ = http(
    "POST", "/api/v1/quick/condition",
    {"token_id": TOKEN_UUID, "condition": "blinded", "action": "add"},
    key=KEY_A
)
check_status("POST /quick/condition (as User A, owner) → 200", s, 200)
check("blinded" in jget(r, "data", "conditions", default=[]), "  'blinded' in response.data.conditions")

# POST /api/v1/quick/kill  (as User A)
s, r, _ = http(
    "POST", "/api/v1/quick/kill",
    {"token_id": TOKEN_UUID},
    key=KEY_A
)
check_status("POST /quick/kill (as User A, owner) → 200", s, 200)
check(jget(r, "data", "old_hp") is not None, "  response.data.old_hp present")

print()

# ============================================================
# REGRESSION — Phase 26 access control still holds
# ============================================================
print("--- REGRESSION (Phase 26 smoke: tokens/combats/actions access control) ---")

# tokens.py — invalid UUID → 400
s, r, _ = http("GET", "/api/v1/scenes/not-an-int/tokens", key=KEY_A)
check_status("GET /scenes/not-an-int/tokens → 400 (Phase 26 Bug 1 regression)", s, 400)

# combats.py — cross-DM isolation → 403
s, r, _ = http("GET", f"/api/v1/scenes/{SCENE_UUID}/combats/active", key=KEY_B)
check_status("GET /scenes/{uuid}/combats/active (as User B) → 403 (Phase 26 Bug 2 regression)", s, 403)

# actions.py — cross-DM isolation → 403
s, r, _ = http("GET", f"/api/v1/scenes/{SCENE_UUID}/actions", key=KEY_B)
check_status("GET /scenes/{uuid}/actions (as User B) → 403 (Phase 26 Bug 2 regression)", s, 403)

# Phase 23 Bug 1: non-int player ID → 400
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
