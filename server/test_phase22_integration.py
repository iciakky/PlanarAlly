#!/usr/bin/env python3
"""
Phase 22: Full Integration Test Script
Tests complete DM CLI workflow end-to-end using Python's urllib.
"""

import json
import sqlite3
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime

BASE_URL = "http://localhost:8000"
TS = int(time.time())
DM_USER = f"inttest_dm_{TS}"
DM_PASS = "testpass123"
PLAYER_USER = f"inttest_player_{TS}"
PLAYER_PASS = "testpass456"
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


def http(method, path, body=None, headers=None, key=None, expect_status=None):
    """Make HTTP request, return (status, response_body)."""
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
            try:
                resp_body = json.loads(raw)
            except Exception:
                resp_body = {"_raw": raw.decode("utf-8", errors="replace")}
            return status, resp_body
    except urllib.error.HTTPError as e:
        status = e.code
        try:
            raw = e.read()
            try:
                resp_body = json.loads(raw)
            except Exception:
                resp_body = {"_raw": raw.decode("utf-8", errors="replace")}
        except Exception:
            resp_body = {}
        return status, resp_body
    except Exception as e:
        return 0, {"error": str(e)}


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
print("PlanarAlly REST API - Phase 22 Integration Test")
print("=" * 60)
print(f"DM user: {DM_USER}")
print(f"Timestamp: {TS}")
print()

# ============================================================
# SETUP
# ============================================================
print("--- SETUP ---")

# Register DM user
s, r = http("POST", "/api/register", {"username": DM_USER, "password": DM_PASS})
check_status("Register DM user", s, 200)

# Create DM API key (credential-based)
s, r = http("POST", "/api/v1/auth/keys", {"username": DM_USER, "password": DM_PASS, "role": "dm"})
DM_KEY = jget(r, "data", "key")
DM_KEY_ID = jget(r, "data", "id")
if DM_KEY:
    check(True, f"Create DM API key (credential-based)")
    print(f"    Key: {DM_KEY[:20]}...")
else:
    check(False, "Create DM API key - ABORTING")
    print(f"    Response: {r}")
    sys.exit(1)

# Register player user
s, r = http("POST", "/api/register", {"username": PLAYER_USER, "password": PLAYER_PASS})
check_status("Register player user", s, 200)

# Create player API key (via DM key)
s, r = http("POST", "/api/v1/auth/keys", {"username": PLAYER_USER, "role": "player"}, key=DM_KEY)
PLAYER_KEY = jget(r, "data", "key")
check(bool(PLAYER_KEY), "Create player API key (via DM key)")

# Get DM user ID from DB + create test room
db = sqlite3.connect(DB_PATH)
DM_USER_ID = db.execute(f"SELECT id FROM user WHERE name='{DM_USER}'").fetchone()
if DM_USER_ID:
    DM_USER_ID = DM_USER_ID[0]
    check(True, f"Got DM user ID: {DM_USER_ID}")
else:
    check(False, "Get DM user ID - ABORTING")
    sys.exit(1)

ROOM_NAME = f"IntTest_Room_{TS}"
db.execute("INSERT INTO location_options (spawn_locations) VALUES ('[]')")
LOC_OPT_ID = db.execute("SELECT last_insert_rowid()").fetchone()[0]
db.execute(
    "INSERT INTO room (name, creator_id, invitation_code, is_locked, default_options_id, enable_chat, enable_dice) "
    f"VALUES ('{ROOM_NAME}', {DM_USER_ID}, 'invite-{TS}', 0, {LOC_OPT_ID}, 1, 1)"
)
db.commit()
ROOM_ID = db.execute(f"SELECT id FROM room WHERE name='{ROOM_NAME}'").fetchone()[0]
check(bool(ROOM_ID), f"Create test room via DB (room_id={ROOM_ID})")

print()

# ============================================================
# AUTH TESTS
# ============================================================
print("--- AUTH ---")

s, r = http("GET", "/api/v1/auth/keys")
check_status("No auth → 401", s, 401)

s, r = http("GET", "/api/v1/auth/keys", headers={"X-API-Key": "dm-invalid-key-xyz"})
check_status("Invalid key → 401", s, 401)

s, r = http("GET", "/api/v1/auth/keys", key=DM_KEY)
check_status("List API keys → 200", s, 200)
keys = jget(r, "data", "keys", default=[])
check(len(keys) >= 1, f"List keys → {len(keys)} keys found")

s, r = http("GET", "/api/v1/auth/keys", key=PLAYER_KEY)
check_status("Player cannot list keys → 403", s, 403)

s, r = http("POST", "/api/v1/auth/keys", {"username": DM_USER, "password": "wrongpass", "role": "dm"})
check(not jget(r, "success", default=True), "Wrong credentials → rejected")

print()

# ============================================================
# SCENE TESTS
# ============================================================
print("--- SCENES ---")

s, r = http("POST", "/api/v1/scenes", {"name": "IntTest Scene", "room_id": ROOM_ID}, key=DM_KEY)
check_status("Create scene → 201", s, 201)
SCENE_UUID = jget(r, "data", "uuid")
if SCENE_UUID:
    check(True, f"Scene UUID: {SCENE_UUID}")
else:
    check(False, f"Get scene UUID - ABORTING (response: {r})")
    sys.exit(1)

s, r = http("GET", "/api/v1/scenes", key=DM_KEY)
check_status("List scenes → 200", s, 200)
scenes = jget(r, "data", "scenes", default=[])
check(len(scenes) >= 1, f"List scenes → {len(scenes)} scene(s)")

s, r = http("GET", f"/api/v1/scenes/{SCENE_UUID}", key=DM_KEY)
check_status("Get scene → 200", s, 200)

s, r = http("PUT", f"/api/v1/scenes/{SCENE_UUID}", {"name": "Updated IntTest Scene"}, key=DM_KEY)
check_status("Update scene name → 200", s, 200)

s, r = http("GET", f"/api/v1/scenes/{SCENE_UUID}", key=DM_KEY)
name = jget(r, "data", "name")
check(name == "Updated IntTest Scene", f"Scene name updated", f"got '{name}'")

s, r = http("GET", f"/api/v1/scenes/{SCENE_UUID}/state", key=DM_KEY)
check_status("Get scene state (empty) → 200", s, 200)

s, r = http("GET", "/api/v1/scenes/99999", key=DM_KEY)
check_status("Non-existent scene → 404", s, 404)

s, r = http("GET", "/api/v1/scenes/not-a-number", key=DM_KEY)
check_status("String scene UUID → 404", s, 404)

print()

# ============================================================
# TOKEN TESTS
# ============================================================
print("--- TOKENS ---")

s, r = http("POST", f"/api/v1/scenes/{SCENE_UUID}/tokens",
            {"name": "Warrior", "x": 100, "y": 100, "hp": 45, "hp_max": 45, "ac": 18, "faction": "friendly"},
            key=DM_KEY)
check_status("Create Warrior token → 201", s, 201)
WARRIOR_UUID = jget(r, "data", "uuid")
if WARRIOR_UUID:
    check(True, f"Warrior UUID: {WARRIOR_UUID}")
else:
    check(False, f"Get Warrior UUID - ABORTING (response: {r})")
    sys.exit(1)

s, r = http("POST", f"/api/v1/scenes/{SCENE_UUID}/tokens",
            {"name": "Rogue", "x": 200, "y": 100, "hp": 32, "hp_max": 32, "ac": 15, "faction": "friendly"},
            key=DM_KEY)
check_status("Create Rogue token → 201", s, 201)
ROGUE_UUID = jget(r, "data", "uuid")
check(bool(ROGUE_UUID), f"Rogue UUID: {ROGUE_UUID}")

s, r = http("POST", f"/api/v1/scenes/{SCENE_UUID}/tokens",
            {"name": "Goblin", "x": 500, "y": 300, "hp": 7, "hp_max": 7, "ac": 13, "faction": "hostile"},
            key=DM_KEY)
check_status("Create Goblin token → 201", s, 201)
GOBLIN_UUID = jget(r, "data", "uuid")
check(bool(GOBLIN_UUID), f"Goblin UUID: {GOBLIN_UUID}")

s, r = http("GET", f"/api/v1/scenes/{SCENE_UUID}/tokens", key=DM_KEY)
check_status("List tokens → 200", s, 200)
count = jget(r, "data", "count", default=0)
check(count == 3, f"Token count = 3", f"got {count}")

s, r = http("GET", f"/api/v1/tokens/{WARRIOR_UUID}", key=DM_KEY)
check_status("Get Warrior token → 200", s, 200)
hp = jget(r, "data", "hp")
# hp is returned as {"value": N, "max": M} dict
hp_val = hp["value"] if isinstance(hp, dict) else hp
check(hp_val == 45, f"Warrior HP value=45", f"got hp={hp}")

s, r = http("PATCH", f"/api/v1/tokens/{WARRIOR_UUID}", {"hp": 38, "conditions": ["prone"]}, key=DM_KEY)
check_status("Update Warrior HP→38 + prone → 200", s, 200)

s, r = http("GET", f"/api/v1/tokens/{WARRIOR_UUID}", key=DM_KEY)
hp = jget(r, "data", "hp")
hp_val = hp["value"] if isinstance(hp, dict) else hp
check(hp_val == 38, f"Warrior HP updated to 38", f"got hp={hp}")

s, r = http("GET", "/api/v1/tokens/00000000-0000-0000-0000-000000000000", key=DM_KEY)
check_status("Non-existent token → 404", s, 404)

s, r = http("POST", f"/api/v1/scenes/{SCENE_UUID}/tokens", {"x": 0, "y": 0}, key=DM_KEY)
check_status("Token missing name → 400", s, 400)

print()

# ============================================================
# BATCH OPERATIONS
# ============================================================
print("--- BATCH OPERATIONS ---")

s, r = http("POST", f"/api/v1/scenes/{SCENE_UUID}/tokens/batch", {
    "operations": [
        {"op": "create", "data": {"name": "Orc", "x": 600, "y": 300, "hp": 15, "hp_max": 15, "ac": 14, "faction": "hostile"}},
        {"op": "create", "data": {"name": "Troll", "x": 700, "y": 300, "hp": 84, "hp_max": 84, "ac": 15, "faction": "hostile"}}
    ]
}, key=DM_KEY)
check_status("Batch create Orc + Troll → 200", s, 200)
success_count = jget(r, "data", "success_count", default=0)
check(success_count == 2, f"Batch success_count=2", f"got {success_count}")
results = jget(r, "data", "results", default=[])
ok_results = [x for x in results if x.get("status") == "ok"]
ORC_UUID = ok_results[0]["id"] if len(ok_results) > 0 else None
TROLL_UUID = ok_results[1]["id"] if len(ok_results) > 1 else None
check(bool(ORC_UUID), f"Orc UUID: {ORC_UUID}")
check(bool(TROLL_UUID), f"Troll UUID: {TROLL_UUID}")

if not ORC_UUID or not TROLL_UUID:
    check(False, "Get Orc/Troll UUIDs - ABORTING")
    sys.exit(1)

s, r = http("GET", f"/api/v1/scenes/{SCENE_UUID}/tokens", key=DM_KEY)
count = jget(r, "data", "count", default=0)
check(count == 5, f"Token count = 5 after batch", f"got {count}")

# Dry run
s, r = http("POST", f"/api/v1/scenes/{SCENE_UUID}/tokens/batch", {
    "dry_run": True,
    "operations": [{"op": "create", "data": {"name": "DryRunToken", "x": 0, "y": 0, "hp": 1, "hp_max": 1, "ac": 10}}]
}, key=DM_KEY)
check_status("Batch dry_run → 200", s, 200)
is_dry = jget(r, "data", "dry_run")
check(is_dry == True, "dry_run=True confirmed", f"got {is_dry}")

s, r = http("GET", f"/api/v1/scenes/{SCENE_UUID}/tokens", key=DM_KEY)
count = jget(r, "data", "count", default=0)
check(count == 5, f"Token count still 5 after dry_run", f"got {count}")

# Batch update
s, r = http("POST", f"/api/v1/scenes/{SCENE_UUID}/tokens/batch", {
    "operations": [{"op": "update", "id": ROGUE_UUID, "data": {"hp": 28, "name": "Shadow Rogue"}}]
}, key=DM_KEY)
check_status("Batch update Rogue → 200", s, 200)
sc = jget(r, "data", "success_count", default=0)
check(sc == 1, f"Batch update success_count=1", f"got {sc}")

print()

# ============================================================
# FOG OF WAR TESTS
# ============================================================
print("--- FOG OF WAR ---")

s, r = http("GET", f"/api/v1/scenes/{SCENE_UUID}/fog", key=DM_KEY)
check_status("Get fog state (empty) → 200", s, 200)
fog_shapes = jget(r, "data", "fog_shapes", default=[])
check(len(fog_shapes) == 0, f"No fog shapes initially", f"got {len(fog_shapes)}")

s, r = http("POST", f"/api/v1/scenes/{SCENE_UUID}/fog/reveal",
            {"type": "rect", "x": 0, "y": 0, "width": 400, "height": 400}, key=DM_KEY)
check_status("Reveal rectangular fog → 200", s, 200)
FOG_RECT_UUID = jget(r, "data", "shape_id")
check(bool(FOG_RECT_UUID), f"Fog rect shape_id: {FOG_RECT_UUID}")

s, r = http("POST", f"/api/v1/scenes/{SCENE_UUID}/fog/reveal",
            {"type": "polygon", "vertices": [[400, 0], [700, 0], [700, 400], [400, 400]]}, key=DM_KEY)
check_status("Reveal polygon fog → 200", s, 200)
FOG_POLY_UUID = jget(r, "data", "shape_id")
check(bool(FOG_POLY_UUID), f"Fog polygon shape_id: {FOG_POLY_UUID}")

s, r = http("GET", f"/api/v1/scenes/{SCENE_UUID}/fog", key=DM_KEY)
fog_count = len(jget(r, "data", "fog_shapes", default=[]))
check(fog_count == 2, f"Fog count=2 after reveals", f"got {fog_count}")

s, r = http("POST", f"/api/v1/scenes/{SCENE_UUID}/fog/hide",
            {"shape_id": FOG_POLY_UUID}, key=DM_KEY)
check_status("Hide polygon fog → 200", s, 200)

s, r = http("GET", f"/api/v1/scenes/{SCENE_UUID}/fog", key=DM_KEY)
fog_count = len(jget(r, "data", "fog_shapes", default=[]))
check(fog_count == 1, f"Fog count=1 after hide", f"got {fog_count}")

s, r = http("POST", f"/api/v1/scenes/{SCENE_UUID}/fog/reveal",
            {"type": "circle", "x": 0, "y": 0}, key=DM_KEY)
check_status("Invalid fog type → 400", s, 400)

s, r = http("POST", f"/api/v1/scenes/{SCENE_UUID}/fog/reveal",
            {"type": "rect", "x": 0, "y": 0, "width": 100, "height": 100}, key=PLAYER_KEY)
check_status("Player cannot reveal fog → 403", s, 403)

print()

# ============================================================
# TOKEN VISION TESTS
# ============================================================
print("--- TOKEN VISION ---")

s, r = http("PATCH", f"/api/v1/tokens/{WARRIOR_UUID}/vision", {"has_vision": True, "range": 60}, key=DM_KEY)
check_status("Set Warrior vision (range=60) → 200", s, 200)

s, r = http("PATCH", f"/api/v1/tokens/{WARRIOR_UUID}/vision", {"has_vision": True, "range": 30, "dim": 30}, key=DM_KEY)
check_status("Update Warrior vision (range=30, dim=30) → 200", s, 200)

s, r = http("PATCH", f"/api/v1/tokens/{WARRIOR_UUID}/vision", {"has_vision": False}, key=DM_KEY)
check_status("Remove Warrior vision → 200", s, 200)

print()

# ============================================================
# DICE ROLL TESTS
# ============================================================
print("--- DICE ROLLS ---")

s, r = http("POST", "/api/v1/rolls", {"notation": "1d20+5", "note": "Initiative roll"}, key=DM_KEY)
check_status("Roll 1d20+5 → 201", s, 201)
ROLL_UUID = jget(r, "data", "uuid")
ROLL_TOTAL = jget(r, "data", "total")
check(bool(ROLL_UUID), f"Roll UUID obtained, total={ROLL_TOTAL}")
check(ROLL_TOTAL is not None and 6 <= ROLL_TOTAL <= 25, f"Roll total {ROLL_TOTAL} in range [6,25]", f"got {ROLL_TOTAL}")

s, r = http("GET", f"/api/v1/rolls/{ROLL_UUID}", key=DM_KEY)
check_status("Get roll by UUID → 200", s, 200)

s, r = http("POST", "/api/v1/rolls",
            {"notation": "1d20+3", "advantage": True, "scene_id": int(SCENE_UUID),
             "actor_id": WARRIOR_UUID, "note": "Attack with advantage"},
            key=DM_KEY)
check_status("Roll 1d20+3 with advantage → 201", s, 201)

s, r = http("POST", "/api/v1/rolls",
            {"notation": "1d20", "disadvantage": True, "note": "Saving throw disadvantage"},
            key=DM_KEY)
check_status("Roll 1d20 with disadvantage → 201", s, 201)

s, r = http("POST", "/api/v1/rolls", {"notation": "2d6+3", "secret": True, "note": "Secret damage"}, key=DM_KEY)
check_status("Secret roll 2d6+3 → 201", s, 201)

s, r = http("POST", "/api/v1/rolls", {"notation": "2d8+1d6+4", "note": "Heavy attack"}, key=DM_KEY)
check_status("Compound roll 2d8+1d6+4 → 201", s, 201)
compound_total = jget(r, "data", "total")
check(compound_total is not None and compound_total >= 7, f"Compound total={compound_total} ≥7", f"got {compound_total}")

s, r = http("POST", "/api/v1/rolls", {"notation": "4d6kh3", "note": "Ability score"}, key=DM_KEY)
check_status("Roll 4d6kh3 (keep highest 3) → 201", s, 201)

s, r = http("POST", "/api/v1/rolls", {"notation": "not-valid-dice"}, key=DM_KEY)
check_status("Invalid dice notation → 400", s, 400)

s, r = http("GET", "/api/v1/rolls?limit=20", key=DM_KEY)
check_status("List rolls → 200", s, 200)
rolls = jget(r, "data", "rolls", default=[])
check(len(rolls) >= 5, f"List rolls → {len(rolls)} rolls (≥5)")

s, r = http("POST", "/api/v1/rolls", {"notation": "1d20", "note": "Player roll"}, key=PLAYER_KEY)
check_status("Player can roll dice → 201", s, 201)

print()

# ============================================================
# COMBAT TESTS
# ============================================================
print("--- COMBAT ---")

s, r = http("GET", f"/api/v1/scenes/{SCENE_UUID}/combats/active", key=DM_KEY)
check_status("No active combat before start → 404", s, 404)

s, r = http("POST", f"/api/v1/scenes/{SCENE_UUID}/combats", {
    "combatants": [
        {"actor_id": WARRIOR_UUID, "initiative": 18},
        {"actor_id": ROGUE_UUID, "initiative": 15},
        {"actor_id": GOBLIN_UUID, "initiative": 12},
        {"actor_id": ORC_UUID, "initiative": 8},
        {"actor_id": TROLL_UUID, "initiative": 5},
    ],
    "auto_sort": True
}, key=DM_KEY)
check_status("Start combat with 5 → 201", s, 201)
COMBAT_UUID = jget(r, "data", "uuid")
if COMBAT_UUID:
    check(True, f"Combat UUID: {COMBAT_UUID}")
else:
    check(False, f"Get combat UUID - ABORTING (response: {r})")
    sys.exit(1)

s, r = http("POST", f"/api/v1/scenes/{SCENE_UUID}/combats",
            {"combatants": [{"actor_id": WARRIOR_UUID, "initiative": 10}]}, key=DM_KEY)
check_status("Duplicate combat → 409", s, 409)

s, r = http("GET", f"/api/v1/scenes/{SCENE_UUID}/combats/active", key=DM_KEY)
check_status("Get active combat → 200", s, 200)

s, r = http("GET", f"/api/v1/combats/{COMBAT_UUID}", key=DM_KEY)
combatants = jget(r, "data", "combatants", default=[])
check(len(combatants) == 5, f"Combat has 5 combatants", f"got {len(combatants)}")

s, r = http("GET", f"/api/v1/combats/{COMBAT_UUID}/round", key=DM_KEY)
check_status("Get round info → 200", s, 200)
round_num = jget(r, "data", "round")
turn_num = jget(r, "data", "turn")
check(round_num == 0, f"Round=0 at start", f"got {round_num}")
check(turn_num == 0, f"Turn=0 at start", f"got {turn_num}")

# Advance 3 turns
for i in range(1, 4):
    s, r = http("PATCH", f"/api/v1/combats/{COMBAT_UUID}/next", key=DM_KEY)
    check_status(f"Advance turn #{i} → 200", s, 200)

s, r = http("GET", f"/api/v1/combats/{COMBAT_UUID}/round", key=DM_KEY)
turn_num = jget(r, "data", "turn")
check(turn_num == 3, f"Turn=3 after 3 advances", f"got {turn_num}")

# Advance 2 more (wrap around: 5 combatants, turn 4 wraps to 0, round++
for i in range(4, 6):
    s, r = http("PATCH", f"/api/v1/combats/{COMBAT_UUID}/next", key=DM_KEY)
    check_status(f"Advance turn #{i} (wrap-around) → 200", s, 200)

s, r = http("GET", f"/api/v1/combats/{COMBAT_UUID}/round", key=DM_KEY)
round_num = jget(r, "data", "round")
turn_num = jget(r, "data", "turn")
check(round_num == 1, f"Round=1 after wrap-around", f"got {round_num}")
check(turn_num == 0, f"Turn=0 after wrap-around", f"got {turn_num}")

s, r = http("PATCH", f"/api/v1/combats/{COMBAT_UUID}/initiative",
            {"actor_id": GOBLIN_UUID, "initiative": 20}, key=DM_KEY)
check_status("Modify Goblin initiative → 200", s, 200)

s, r = http("DELETE", f"/api/v1/combats/{COMBAT_UUID}/remove/{ORC_UUID}", key=DM_KEY)
check_status("Remove Orc from combat → 200", s, 200)

s, r = http("GET", f"/api/v1/combats/{COMBAT_UUID}", key=DM_KEY)
combatants = jget(r, "data", "combatants", default=[])
check(len(combatants) == 4, f"Combatants=4 after Orc removal", f"got {len(combatants)}")

s, r = http("POST", f"/api/v1/scenes/{SCENE_UUID}/combats",
            {"combatants": [{"actor_id": WARRIOR_UUID, "initiative": 10}]}, key=PLAYER_KEY)
check_status("Player cannot start combat → 403", s, 403)

print()

# ============================================================
# QUICK COMMANDS
# ============================================================
print("--- QUICK COMMANDS ---")

s, r = http("POST", "/api/v1/quick/damage",
            {"token_id": GOBLIN_UUID, "amount": 5, "note": "Warrior sword strike"}, key=DM_KEY)
check_status("Quick damage Goblin -5 HP → 200", s, 200)
new_hp = jget(r, "data", "new_hp")
check(new_hp == 2, f"Goblin HP 7→2 (damage=5)", f"got {new_hp}")

s, r = http("POST", "/api/v1/quick/heal",
            {"token_id": WARRIOR_UUID, "amount": 3, "note": "Potion of Healing"}, key=DM_KEY)
check_status("Quick heal Warrior +3 HP → 200", s, 200)
new_hp = jget(r, "data", "new_hp")
check(new_hp == 41, f"Warrior HP 38→41 (heal=3)", f"got {new_hp}")

# Overcap test
s, r = http("POST", "/api/v1/quick/heal",
            {"token_id": WARRIOR_UUID, "amount": 100}, key=DM_KEY)
new_hp = jget(r, "data", "new_hp")
check(new_hp == 45, f"Heal overcap: Warrior capped at 45/45", f"got {new_hp}")

s, r = http("POST", "/api/v1/quick/move",
            {"token_id": ROGUE_UUID, "x": 350, "y": 250, "note": "Flanking move"}, key=DM_KEY)
check_status("Quick move Rogue to (350,250) → 200", s, 200)
new_x = jget(r, "data", "new_position", "x")
check(new_x == 350, f"Rogue x=350 confirmed", f"got {new_x}")

s, r = http("POST", "/api/v1/quick/condition",
            {"token_id": WARRIOR_UUID, "condition": "frightened", "action": "add"}, key=DM_KEY)
check_status("Quick condition: add frightened → 200", s, 200)
conditions = jget(r, "data", "conditions", default=[])
check("frightened" in conditions, f"frightened in conditions: {conditions}")

s, r = http("POST", "/api/v1/quick/condition",
            {"token_id": WARRIOR_UUID, "condition": "frightened", "action": "remove"}, key=DM_KEY)
check_status("Quick condition: remove frightened → 200", s, 200)

s, r = http("POST", "/api/v1/quick/condition",
            {"token_id": WARRIOR_UUID, "condition": "poisoned", "action": "toggle"}, key=DM_KEY)
check_status("Invalid condition action → 400", s, 400)

s, r = http("POST", "/api/v1/quick/kill",
            {"token_id": GOBLIN_UUID, "note": "Final blow"}, key=DM_KEY)
check_status("Quick kill Goblin → 200", s, 200)
old_hp = jget(r, "data", "old_hp")
removed = jget(r, "data", "removed_from_combat")
check(old_hp == 2, f"Goblin old_hp=2", f"got {old_hp}")
check(removed == True, f"Goblin removed_from_combat=True", f"got {removed}")

s, r = http("POST", "/api/v1/quick/damage",
            {"token_id": WARRIOR_UUID, "amount": 5}, key=PLAYER_KEY)
check_status("Player cannot use quick/damage → 403", s, 403)

print()

# ============================================================
# ACTION DECLARATIONS
# ============================================================
print("--- ACTIONS ---")

s, r = http("POST", f"/api/v1/scenes/{SCENE_UUID}/actions", {
    "actor_id": WARRIOR_UUID,
    "action_type": "attack",
    "description": "Warrior attacks Troll with longsword",
    "targets": [{"uuid": TROLL_UUID, "type": "enemy"}]
}, key=DM_KEY)
check_status("Submit attack action → 201", s, 201)
ACTION_UUID = jget(r, "data", "uuid")
check(bool(ACTION_UUID), f"Action UUID: {ACTION_UUID}")

s, r = http("GET", f"/api/v1/scenes/{SCENE_UUID}/actions", key=DM_KEY)
check_status("List actions → 200", s, 200)

s, r = http("GET", f"/api/v1/actions/{ACTION_UUID}", key=DM_KEY)
check_status("Get action by UUID → 200", s, 200)

s, r = http("GET", f"/api/v1/scenes/{SCENE_UUID}/actions?status=pending", key=DM_KEY)
pending = jget(r, "data", "actions", default=[])
check(len(pending) >= 1, f"Pending actions ≥1 ({len(pending)} found)")

s, r = http("PATCH", f"/api/v1/actions/{ACTION_UUID}",
            {"status": "accepted", "dm_note": "Great tactical choice!"}, key=DM_KEY)
check_status("Review action - accept → 200", s, 200)

s, r = http("POST", f"/api/v1/scenes/{SCENE_UUID}/actions", {
    "actor_id": ROGUE_UUID,
    "action_type": "spell",
    "description": "Rogue tries to cast Fireball"
}, key=DM_KEY)
ACTION2_UUID = jget(r, "data", "uuid")
if ACTION2_UUID:
    s, r = http("PATCH", f"/api/v1/actions/{ACTION2_UUID}",
                {"status": "rejected", "dm_note": "Rogues cannot cast Fireball!"}, key=DM_KEY)
    check_status("Review action - reject → 200", s, 200)

s, r = http("PATCH", f"/api/v1/actions/{ACTION_UUID}", {"status": "invalid_status"}, key=DM_KEY)
check_status("Invalid action status → 400", s, 400)

if ACTION_UUID and PLAYER_KEY:
    s, r = http("PATCH", f"/api/v1/actions/{ACTION_UUID}", {"status": "accepted"}, key=PLAYER_KEY)
    check_status("Player cannot review actions → 403", s, 403)

print()

# ============================================================
# PLAYER MANAGEMENT
# ============================================================
print("--- PLAYERS ---")

s, r = http("GET", "/api/v1/players", key=DM_KEY)
check_status("List players → 200", s, 200)
online_count = jget(r, "data", "online_count", default=-1)
print(f"    Online players: {online_count} (expect 0 in automated test)")

s, r = http("GET", f"/api/v1/players/{DM_USER_ID}/tokens", key=DM_KEY)
check_status("Get DM player tokens → 200", s, 200)

s, r = http("POST", f"/api/v1/players/{DM_USER_ID}/message",
            {"text": "Your turn is coming up!", "private": False}, key=DM_KEY)
check_status("Send message to offline player → 200", s, 200)
delivered = jget(r, "data", "delivered")
check(delivered == False, f"delivered=False (offline)", f"got {delivered}")

print()

# ============================================================
# EVENT LOG
# ============================================================
print("--- EVENTS ---")

s, r = http("GET", "/api/v1/events?limit=100", key=DM_KEY)
check_status("Query all events → 200", s, 200)
all_events = jget(r, "data", "events", default=[])
print(f"    Total events logged: {len(all_events)}")
check(len(all_events) >= 20, f"Events logged ≥20 (good coverage)", f"got {len(all_events)}")

s, r = http("GET", f"/api/v1/events?scene_id={SCENE_UUID}&limit=50", key=DM_KEY)
scene_events = jget(r, "data", "events", default=[])
print(f"    Scene events: {len(scene_events)}")
check(len(scene_events) >= 5, f"Scene events ≥5", f"got {len(scene_events)}")

s, r = http("GET", "/api/v1/events?type=damage_applied", key=DM_KEY)
check_status("Filter events by type=damage_applied → 200", s, 200)

s, r = http("POST", "/api/v1/events/note",
            {"note": "Session notes: Warrior nearly died fighting Troll", "scene_id": int(SCENE_UUID)},
            key=DM_KEY)
check_status("Create DM note → 201", s, 201)

s, r = http("GET", "/api/v1/events?limit=5", key=PLAYER_KEY)
check_status("Player can query events → 200", s, 200)

s, r = http("POST", "/api/v1/events/note", {"text": "Player note attempt"}, key=PLAYER_KEY)
check_status("Player cannot create DM notes → 403", s, 403)

s, r = http("GET", "/api/v1/events/export?format=json", key=DM_KEY)
check_status("Export events as JSON → 200", s, 200)
exported = jget(r, "exported_events")
print(f"    Exported events: {exported}")

s, r = http("GET", "/api/v1/events/export?format=txt", key=DM_KEY)
check_status("Export events as TXT → 200", s, 200)

s, r = http("GET", f"/api/v1/events/export?format=json&scene_id={SCENE_UUID}", key=DM_KEY)
check_status("Export events filtered by scene → 200", s, 200)

s, r = http("GET", "/api/v1/events/export?format=csv", key=DM_KEY)
check_status("Export invalid format → 400", s, 400)

# SSE stream brief test
print("    Testing SSE stream connection...")
import socket
try:
    sock = socket.create_connection(("localhost", 8000), timeout=2)
    sock.sendall(f"GET /api/v1/events/stream HTTP/1.1\r\nHost: localhost:8000\r\nX-API-Key: {DM_KEY}\r\nAccept: text/event-stream\r\n\r\n".encode())
    sock.settimeout(3)
    data = sock.recv(1024).decode("utf-8", errors="ignore")
    sock.close()
    check("200 OK" in data, "SSE stream → HTTP 200 OK", data[:100])
except Exception as e:
    check(False, f"SSE stream connection failed: {e}")

print()

# ============================================================
# SCENE SNAPSHOTS
# ============================================================
print("--- SCENE SNAPSHOTS ---")

s, r = http("POST", f"/api/v1/scenes/{SCENE_UUID}/snapshot",
            {"name": "After Round 1"}, key=DM_KEY)
check_status("Create scene snapshot → 201", s, 201)
SNAP_UUID = jget(r, "data", "uuid")
SNAP_TOKEN_COUNT = jget(r, "data", "token_count", default=0)
check(bool(SNAP_UUID), f"Snapshot UUID: {SNAP_UUID} (tokens={SNAP_TOKEN_COUNT})")

s, r = http("GET", f"/api/v1/scenes/{SCENE_UUID}/snapshots", key=DM_KEY)
snap_count = jget(r, "data", "count", default=0)
check(snap_count == 1, f"Snapshot count=1", f"got {snap_count}")

# Delete Troll token
http("DELETE", f"/api/v1/tokens/{TROLL_UUID}", key=DM_KEY)
s, r = http("GET", f"/api/v1/scenes/{SCENE_UUID}/tokens", key=DM_KEY)
before_restore = jget(r, "data", "count", default=0)
print(f"    Token count before restore: {before_restore}")

# Restore snapshot
s, r = http("POST", f"/api/v1/scenes/{SCENE_UUID}/restore/{SNAP_UUID}", key=DM_KEY)
check_status("Restore scene snapshot → 200", s, 200)
tokens_restored = jget(r, "data", "tokens_restored", default=0)
print(f"    Tokens restored: {tokens_restored}")

s, r = http("GET", f"/api/v1/scenes/{SCENE_UUID}/tokens", key=DM_KEY)
after_restore = jget(r, "data", "count", default=0)
check(after_restore == SNAP_TOKEN_COUNT, f"Token count restored to {SNAP_TOKEN_COUNT}", f"got {after_restore}")

s, r = http("POST", f"/api/v1/scenes/{SCENE_UUID}/restore/00000000-0000-0000-0000-000000000000", key=DM_KEY)
check_status("Non-existent snapshot → 404", s, 404)

print()

# ============================================================
# COMBAT END
# ============================================================
print("--- END COMBAT ---")

s, r = http("POST", f"/api/v1/combats/{COMBAT_UUID}/end", key=DM_KEY)
check_status("End combat → 200", s, 200)

s, r = http("GET", f"/api/v1/scenes/{SCENE_UUID}/combats/active", key=DM_KEY)
check_status("No active combat after end → 404", s, 404)

s, r = http("PATCH", f"/api/v1/combats/{COMBAT_UUID}/next", key=DM_KEY)
check_status("Advance turn after end → 400 (combat inactive)", s, 400)

print()

# ============================================================
# KEY MANAGEMENT
# ============================================================
print("--- KEY MANAGEMENT ---")

s, r = http("POST", "/api/v1/auth/keys", {"username": DM_USER, "role": "player"}, key=DM_KEY)
check_status("Create temp key → 201", s, 201)
TEMP_KEY_UUID = jget(r, "data", "id")
TEMP_KEY_VAL = jget(r, "data", "key")

if TEMP_KEY_UUID and TEMP_KEY_VAL:
    s, r = http("GET", "/api/v1/test/player", key=TEMP_KEY_VAL)
    check_status("Temp key works before revoke → 200", s, 200)

    s, r = http("DELETE", f"/api/v1/auth/keys/{TEMP_KEY_UUID}", key=DM_KEY)
    check_status("Revoke temporary key → 200", s, 200)

    s, r = http("GET", "/api/v1/test/player", key=TEMP_KEY_VAL)
    check_status("Revoked key → 401", s, 401)

s, r = http("DELETE", "/api/v1/auth/keys/00000000-0000-0000-0000-000000000000", key=DM_KEY)
check_status("Revoke non-existent key → 404", s, 404)

print()

# ============================================================
# CLEANUP
# ============================================================
print("--- CLEANUP ---")

s, r = http("DELETE", f"/api/v1/scenes/{SCENE_UUID}", key=DM_KEY)
check_status("Delete test scene → 200", s, 200)

s, r = http("GET", f"/api/v1/scenes/{SCENE_UUID}", key=DM_KEY)
check_status("Deleted scene → 404", s, 404)

# Clean up DB
try:
    db.execute(f"DELETE FROM room WHERE name='{ROOM_NAME}'")
    db.execute(f"DELETE FROM location_options WHERE id={LOC_OPT_ID}")
    db.execute(f"DELETE FROM api_key WHERE user_id IN (SELECT id FROM user WHERE name='{DM_USER}' OR name='{PLAYER_USER}')")
    db.execute(f"DELETE FROM user WHERE name='{DM_USER}' OR name='{PLAYER_USER}'")
    db.commit()
    db.close()
    check(True, "Cleaned up test data from DB")
except Exception as e:
    check(False, f"Cleanup failed: {e}")

print()

# ============================================================
# FINAL SUMMARY
# ============================================================
print("=" * 60)
print(f"RESULTS: {pass_count} passed, {fail_count} failed, {total_count} total")
print("=" * 60)
if fail_count == 0:
    print(f"\033[0;32m✅ All tests passed!\033[0m")
    sys.exit(0)
else:
    print(f"\033[0;31m❌ {fail_count} test(s) failed\033[0m")
    sys.exit(1)
