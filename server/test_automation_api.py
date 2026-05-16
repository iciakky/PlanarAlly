#!/usr/bin/env python3
"""
TDD integration tests for Automation API endpoints.

Requires a running PlanarAlly server at 127.0.0.1:8000.
Tests follow the v2 proposal implementation order:
1. POST /rooms
2. POST /rooms/{id}/players
3. POST /scenes/{id}/shapes (generic shape creation)
4. PUT /scenes/{id}/shapes/by-external-id/{eid} (upsert)
5. PATCH /shapes/{id}/access
6. PATCH /scenes/{id}/options
7. GET /scenes/{id}/diagnostics
8. GET /scenes/{id}/visibility
"""

import json
import sys
import time
import urllib.request
import urllib.error

BASE_URL = "http://127.0.0.1:8000"
TS = int(time.time())
DM_USER = f"autotest_dm_{TS}"
DM_PASS = "testpass123"
PLAYER_USER = f"autotest_player_{TS}"
PLAYER_PASS = "testpass123"

pass_count = 0
fail_count = 0
total_count = 0

DM_KEY = None
PLAYER_KEY = None
ROOM_ID = None
SCENE_ID = None


def green(s): return f"\033[0;32m{s}\033[0m"
def red(s): return f"\033[0;31m{s}\033[0m"


def check(condition, name, detail=""):
    global pass_count, fail_count, total_count
    total_count += 1
    if condition:
        pass_count += 1
        print(f"  {green('PASS')} {name}")
    else:
        fail_count += 1
        print(f"  {red('FAIL')} {name}" + (f" — {detail}" if detail else ""))


def http(method, path, body=None, key=None):
    url = f"{BASE_URL}{path}"
    data = json.dumps(body).encode() if body else None
    headers = {"Content-Type": "application/json"}
    if key:
        headers["X-API-Key"] = key
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        resp = urllib.request.urlopen(req)
        body_text = resp.read().decode()
        try:
            return resp.status, json.loads(body_text)
        except (json.JSONDecodeError, ValueError):
            return resp.status, {"_raw": body_text}
    except urllib.error.HTTPError as e:
        body_text = e.read().decode()
        try:
            return e.code, json.loads(body_text)
        except (json.JSONDecodeError, ValueError):
            return e.code, {"_raw": body_text}


def jget(obj, *keys):
    for k in keys:
        if isinstance(obj, dict):
            obj = obj.get(k)
        else:
            return None
    return obj


# ============================================================
print("=" * 60)
print("Automation API — Integration Tests")
print("=" * 60)

# --- SETUP ---
print("\n--- SETUP ---")

s, r = http("POST", "/api/register", {"username": DM_USER, "password": DM_PASS})
check(s == 200, f"Register DM user ({DM_USER})")

s, r = http("POST", "/api/v1/auth/keys", {"username": DM_USER, "password": DM_PASS, "role": "dm"})
DM_KEY = jget(r, "data", "key")
check(bool(DM_KEY), "Create DM API key")

s, r = http("POST", "/api/register", {"username": PLAYER_USER, "password": PLAYER_PASS})
check(s == 200, f"Register player user ({PLAYER_USER})")

# --- 1. POST /rooms ---
print("\n--- POST /rooms ---")

s, r = http("POST", "/api/v1/rooms", {"name": f"test_room_{TS}"}, key=DM_KEY)
check(s == 201, f"Create room → 201", f"got {s}: {r}")
ROOM_ID = jget(r, "data", "room_id")
check(ROOM_ID is not None, f"Room ID returned: {ROOM_ID}")

default_loc = jget(r, "data", "default_location")
check(default_loc is not None, "Default location returned")
SCENE_ID = jget(default_loc, "id") if default_loc else None
check(SCENE_ID is not None, f"Default scene ID: {SCENE_ID}")

s2, r2 = http("POST", "/api/v1/rooms", {"name": f"test_room_{TS}"}, key=DM_KEY)
check(s2 == 409, f"Duplicate room name → 409", f"got {s2}")

s3, r3 = http("POST", "/api/v1/rooms", {}, key=DM_KEY)
check(s3 == 400, "Missing name → 400", f"got {s3}")

# --- 2. POST /rooms/{id}/players ---
print("\n--- POST /rooms/{id}/players ---")

s, r = http("POST", f"/api/v1/rooms/{ROOM_ID}/players",
            {"username": PLAYER_USER, "role": "player"}, key=DM_KEY)
check(s == 201, f"Add player to room → 201", f"got {s}: {r}")
check(jget(r, "data", "username") == PLAYER_USER, "Player username in response")
luo_created = jget(r, "data", "location_user_options_created")
check(isinstance(luo_created, list) and len(luo_created) > 0,
      f"LocationUserOption auto-created: {luo_created}")

s2, r2 = http("POST", f"/api/v1/rooms/{ROOM_ID}/players",
              {"username": PLAYER_USER, "role": "player"}, key=DM_KEY)
check(s2 == 409, "Duplicate player → 409", f"got {s2}")

s3, r3 = http("POST", f"/api/v1/rooms/{ROOM_ID}/players",
              {"username": "nonexistent_user_xyz", "role": "player"}, key=DM_KEY)
check(s3 == 404, "Nonexistent user → 404", f"got {s3}")

# --- 3. POST /scenes/{id}/shapes (generic) ---
print("\n--- POST /scenes/{id}/shapes ---")

# Create wall (line + vision_obstruction=1)
s, r = http("POST", f"/api/v1/scenes/{SCENE_ID}/shapes", {
    "type": "line",
    "external_id": "north-wall",
    "layer": "map",
    "x": 100, "y": 100,
    "x2": 500, "y2": 100,
    "line_width": 2,
    "vision_obstruction": 1,
    "stroke_colour": "rgba(0,0,0,1)",
}, key=DM_KEY)
check(s == 201, f"Create wall (line) → 201", f"got {s}: {r}")
wall_uuid = jget(r, "data", "uuid")
check(wall_uuid is not None, f"Wall UUID: {wall_uuid}")
check(jget(r, "data", "external_id") == "north-wall", "External ID in response")

# Create door (rect + is_door)
s, r = http("POST", f"/api/v1/scenes/{SCENE_ID}/shapes", {
    "type": "rect",
    "external_id": "door-1",
    "layer": "tokens",
    "x": 300, "y": 95,
    "width": 30, "height": 10,
    "is_door": True,
    "vision_obstruction": 1,
    "fill_colour": "rgba(139,69,19,1)",
}, key=DM_KEY)
check(s == 201, "Create door (rect) → 201", f"got {s}: {r}")
door_uuid = jget(r, "data", "uuid")
check(door_uuid is not None, f"Door UUID: {door_uuid}")

# Create PC token
s, r = http("POST", f"/api/v1/scenes/{SCENE_ID}/shapes", {
    "type": "circulartoken",
    "external_id": "kannon",
    "layer": "tokens",
    "x": 430, "y": 360,
    "radius": 28,
    "text": "PC",
    "name": "Kannon",
}, key=DM_KEY)
check(s == 201, "Create PC token (circulartoken) → 201", f"got {s}: {r}")
pc_uuid = jget(r, "data", "uuid")
check(pc_uuid is not None, f"PC UUID: {pc_uuid}")

# Create polygon (fog reveal)
s, r = http("POST", f"/api/v1/scenes/{SCENE_ID}/shapes", {
    "type": "polygon",
    "external_id": "room-fog",
    "layer": "fow",
    "x": 0, "y": 0,
    "vertices": [[100, 100], [500, 100], [500, 400], [100, 400]],
    "line_width": 0,
    "open_polygon": False,
}, key=DM_KEY)
check(s == 201, "Create polygon (fog) → 201", f"got {s}: {r}")

# Create gm_secret on DM layer
s, r = http("POST", f"/api/v1/scenes/{SCENE_ID}/shapes", {
    "type": "circulartoken",
    "external_id": "smuggler-a",
    "layer": "dm",
    "x": 600, "y": 200,
    "radius": 28,
    "text": "??",
    "name": "Smuggler",
}, key=DM_KEY)
check(s == 201, "Create gm_secret token on dm layer → 201", f"got {s}: {r}")

# Invalid type
s, r = http("POST", f"/api/v1/scenes/{SCENE_ID}/shapes", {
    "type": "invalid_type", "x": 0, "y": 0,
}, key=DM_KEY)
check(s == 400, "Invalid shape type → 400", f"got {s}")

# Missing required field for line
s, r = http("POST", f"/api/v1/scenes/{SCENE_ID}/shapes", {
    "type": "line", "x": 0, "y": 0,
}, key=DM_KEY)
check(s == 400, "Line missing x2/y2 → 400", f"got {s}")

# --- 4. External ID upsert ---
print("\n--- PUT /shapes/by-external-id ---")

s, r = http("PUT", f"/api/v1/scenes/{SCENE_ID}/shapes/by-external-id/kannon", {
    "type": "circulartoken",
    "x": 450, "y": 370,
    "radius": 28,
    "text": "PC",
    "name": "Kannon Updated",
}, key=DM_KEY)
check(s == 200, "Upsert existing shape → 200 (update)", f"got {s}: {r}")
check(jget(r, "data", "uuid") == pc_uuid, "UUID preserved on update")

s, r = http("PUT", f"/api/v1/scenes/{SCENE_ID}/shapes/by-external-id/new-marker", {
    "type": "rect",
    "x": 200, "y": 200,
    "width": 50, "height": 50,
    "name": "Marker",
}, key=DM_KEY)
check(s == 201, "Upsert new shape → 201 (create)", f"got {s}: {r}")
check(jget(r, "data", "external_id") == "new-marker", "External ID in upsert response")

# Type mismatch
s, r = http("PUT", f"/api/v1/scenes/{SCENE_ID}/shapes/by-external-id/kannon", {
    "type": "line", "x": 0, "y": 0, "x2": 100, "y2": 100, "line_width": 2,
}, key=DM_KEY)
check(s == 409, "Upsert type mismatch → 409", f"got {s}: {r}")

# Query by external_id
s, r = http("GET", f"/api/v1/scenes/{SCENE_ID}/shapes?external_id=kannon", key=DM_KEY)
check(s == 200, "Query by external_id → 200", f"got {s}")
check(jget(r, "data", "uuid") == pc_uuid, "Correct shape returned by external_id")

# --- 5. PATCH /shapes/{id}/access ---
print("\n--- PATCH /shapes/{id}/access ---")

s, r = http("PATCH", f"/api/v1/shapes/{pc_uuid}/access", {
    "players": {PLAYER_USER: {"vision": True, "movement": True, "edit": False}},
    "default_vision": False,
    "default_movement": False,
}, key=DM_KEY)
check(s == 200, "Set shape access → 200", f"got {s}: {r}")

# --- 5.5 PATCH /tokens/{id}/vision ---
print("\n--- PATCH /tokens/{id}/vision ---")

# Set vision without specifying colour — should default to transparent warm
s, r = http("PATCH", f"/api/v1/tokens/{pc_uuid}/vision", {
    "has_vision": True,
    "range": 60,
}, key=DM_KEY)
check(s == 200, "Set token vision → 200", f"got {s}: {r}")
default_colour = jget(r, "data", "colour")
check(default_colour == "rgba(255, 244, 210, 0.10)",
      f"Default vision colour is transparent warm",
      f"got colour={default_colour}")

# Set vision with explicit colour — should use caller's colour
s, r = http("PATCH", f"/api/v1/tokens/{pc_uuid}/vision", {
    "has_vision": True,
    "range": 60,
    "colour": "rgba(0, 255, 0, 0.5)",
}, key=DM_KEY)
check(s == 200, "Set token vision with custom colour → 200", f"got {s}: {r}")
custom_colour = jget(r, "data", "colour")
check(custom_colour == "rgba(0, 255, 0, 0.5)",
      f"Custom vision colour preserved",
      f"got colour={custom_colour}")

# --- 6. PATCH /scenes/{id}/options ---
print("\n--- PATCH /scenes/{id}/options ---")

s, r = http("PATCH", f"/api/v1/scenes/{SCENE_ID}/options", {
    "full_fow": True,
    "fowLos": True,
    "fowOpacity": 0.7,
    "unitSize": 5,
    "unitSizeUnit": "ft",
}, key=DM_KEY)
check(s == 200, "Set scene options → 200", f"got {s}: {r}")
eff = jget(r, "data", "effective_options")
check(eff is not None, "Effective options returned")

# --- 7. GET /scenes/{id}/diagnostics ---
print("\n--- GET /scenes/{id}/diagnostics ---")

s, r = http("GET", f"/api/v1/scenes/{SCENE_ID}/diagnostics", key=DM_KEY)
check(s == 200, "Diagnostics → 200", f"got {s}: {r}")
diag_data = jget(r, "data") or {}
check("ok" in diag_data, "Has 'ok' field")
issues = diag_data.get("issues") or []
check(isinstance(issues, list), f"Issues is a list (count: {len(issues)})")

# --- 8. GET /scenes/{id}/visibility ---
print("\n--- GET /scenes/{id}/visibility ---")

s, r = http("GET", f"/api/v1/scenes/{SCENE_ID}/visibility?player={PLAYER_USER}", key=DM_KEY)
check(s == 200, "Visibility → 200", f"got {s}: {r}")
shapes_vis = jget(r, "data", "shapes") or []
check(isinstance(shapes_vis, list), f"Shapes list returned (count: {len(shapes_vis)})")

# Check gm_secret is not sent to client
smuggler = next((s for s in shapes_vis if s.get("external_id") == "smuggler-a"), None)
check(smuggler is not None, "Smuggler in visibility list")
if smuggler:
    check(smuggler.get("sent_to_client") is False, "Smuggler not sent to client (gm_secret)",
          f"got sent_to_client={smuggler.get('sent_to_client')}")
    check(smuggler.get("reason") == "not_sent_to_client", "Smuggler reason=not_sent_to_client",
          f"got reason={smuggler.get('reason')}")

# PC should be visible (sent to client)
pc_vis = next((s for s in shapes_vis if s.get("external_id") == "kannon"), None)
check(pc_vis is not None, "Kannon in visibility list")
if pc_vis:
    check(pc_vis.get("sent_to_client") is True, "Kannon sent to client")

# --- 9. Mutation revision counter ---
print("\n--- REVISION COUNTER ---")

# Create shape and check for revision in response
s, r = http("POST", f"/api/v1/scenes/{SCENE_ID}/shapes", {
    "type": "rect", "external_id": "rev-test-1",
    "x": 0, "y": 0, "width": 10, "height": 10,
}, key=DM_KEY)
rev1 = jget(r, "data", "revision")
check(rev1 is not None and isinstance(rev1, int), f"Create shape returns revision: {rev1}")

# Second mutation should have higher revision
s, r = http("POST", f"/api/v1/scenes/{SCENE_ID}/shapes", {
    "type": "rect", "external_id": "rev-test-2",
    "x": 10, "y": 10, "width": 10, "height": 10,
}, key=DM_KEY)
rev2 = jget(r, "data", "revision")
check(rev2 is not None and rev2 > (rev1 or 0), f"Revision monotonically increasing: {rev1} < {rev2}")

# Upsert update should also return revision
s, r = http("PUT", f"/api/v1/scenes/{SCENE_ID}/shapes/by-external-id/rev-test-1", {
    "type": "rect", "x": 5, "y": 5, "width": 10, "height": 10,
}, key=DM_KEY)
rev3 = jget(r, "data", "revision")
check(rev3 is not None and rev3 > (rev2 or 0), f"Upsert update returns revision: {rev3}")

# Shape access should return revision
s, r = http("PATCH", f"/api/v1/shapes/{pc_uuid}/access", {
    "default_vision": True,
}, key=DM_KEY)
rev4 = jget(r, "data", "revision")
check(rev4 is not None and rev4 > (rev3 or 0), f"Access update returns revision: {rev4}")

# Scene options should return revision
s, r = http("PATCH", f"/api/v1/scenes/{SCENE_ID}/options", {
    "fowOpacity": 0.5,
}, key=DM_KEY)
rev5 = jget(r, "data", "revision")
check(rev5 is not None and rev5 > (rev4 or 0), f"Options update returns revision: {rev5}")

# --- 10. Asset upload ---
print("\n--- POST /assets ---")

# Create a tiny 1x1 PNG (smallest valid PNG)
import base64
PNG_1x1 = base64.b64encode(
    b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01'
    b'\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00'
    b'\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00'
    b'\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82'
).decode()

s, r = http("POST", "/api/v1/assets", {
    "name": "test-bg.png",
    "mime_type": "image/png",
    "content_base64": PNG_1x1,
}, key=DM_KEY)
check(s == 201, f"Upload asset → 201", f"got {s}: {r}")
ASSET_ID = jget(r, "data", "asset_id")
ASSET_HASH = jget(r, "data", "asset_hash")
check(ASSET_ID is not None, f"Asset ID returned: {ASSET_ID}")
check(ASSET_HASH is not None and len(ASSET_HASH) == 40, f"Asset hash (SHA-1): {ASSET_HASH}")
ENTRY_ID = jget(r, "data", "entry_id")
check(ENTRY_ID is not None, f"Entry ID returned: {ENTRY_ID}")
check(jget(r, "data", "width_px") == 1, f"Image width_px detected: {jget(r, 'data', 'width_px')}")
check(jget(r, "data", "height_px") == 1, f"Image height_px detected: {jget(r, 'data', 'height_px')}")

# Upload same file again — should succeed (dedup) with same hash
s2, r2 = http("POST", "/api/v1/assets", {
    "name": "test-bg-copy.png",
    "mime_type": "image/png",
    "content_base64": PNG_1x1,
}, key=DM_KEY)
check(s2 == 201, "Upload duplicate asset → 201 (dedup)")
check(jget(r2, "data", "asset_hash") == ASSET_HASH, "Same hash for same content")

# Missing content
s3, r3 = http("POST", "/api/v1/assets", {
    "name": "empty.png",
}, key=DM_KEY)
check(s3 == 400, "Missing content → 400", f"got {s3}")

# --- 11. Assetrect shape creation ---
print("\n--- POST /scenes/{id}/shapes (assetrect) ---")

s, r = http("POST", f"/api/v1/scenes/{SCENE_ID}/shapes", {
    "type": "assetrect",
    "external_id": "map-background",
    "layer": "map",
    "x": 0, "y": 0,
    "width": 1056, "height": 768,
    "assetId": ASSET_ID,
    "assetHash": ASSET_HASH,
    "is_locked": True,
    "default_edit_access": False,
    "default_vision_access": True,
}, key=DM_KEY)
check(s == 201, f"Create assetrect → 201", f"got {s}: {r}")
bg_uuid = jget(r, "data", "uuid")
check(bg_uuid is not None, f"Background UUID: {bg_uuid}")
check(jget(r, "data", "external_id") == "map-background", "External ID in response")
check(jget(r, "data", "revision") is not None, "Revision in response")

# Query back to verify coordinates and fields stored correctly
s, r = http("GET", f"/api/v1/scenes/{SCENE_ID}/shapes?external_id=map-background", key=DM_KEY)
check(s == 200, "Query assetrect by external_id → 200", f"got {s}")
check(jget(r, "data", "uuid") == bg_uuid, "Correct assetrect returned")
check(jget(r, "data", "x") == 0, "x coordinate stored correctly", f"got x={jget(r, 'data', 'x')}")
check(jget(r, "data", "y") == 0, "y coordinate stored correctly", f"got y={jget(r, 'data', 'y')}")
check(jget(r, "data", "is_locked") is True, "is_locked stored correctly",
      f"got is_locked={jget(r, 'data', 'is_locked')}")
check(jget(r, "data", "default_edit_access") is False, "default_edit_access stored correctly",
      f"got={jget(r, 'data', 'default_edit_access')}")
check(jget(r, "data", "default_vision_access") is True, "default_vision_access stored correctly",
      f"got={jget(r, 'data', 'default_vision_access')}")
check(jget(r, "data", "width") == 1056, "width stored correctly",
      f"got width={jget(r, 'data', 'width')}")
check(jget(r, "data", "height") == 768, "height stored correctly",
      f"got height={jget(r, 'data', 'height')}")
check(jget(r, "data", "assetId") == ASSET_ID, "assetId stored correctly",
      f"got assetId={jget(r, 'data', 'assetId')}")
check(jget(r, "data", "assetHash") == ASSET_HASH, "assetHash stored correctly",
      f"got assetHash={jget(r, 'data', 'assetHash')}")

# Verify uploaded asset is servable (binary, not JSON)
asset_url = f"{BASE_URL}/static/assets/{ASSET_HASH[:2]}/{ASSET_HASH[2:4]}/{ASSET_HASH}"
try:
    req = urllib.request.Request(asset_url)
    resp = urllib.request.urlopen(req)
    s_serve = resp.status
    served_bytes = resp.read()
except urllib.error.HTTPError as e:
    s_serve = e.code
    served_bytes = b""
check(s_serve == 200, "Uploaded asset is servable via static URL",
      f"got {s_serve} for {asset_url}")
check(len(served_bytes) > 0, f"Served file has content ({len(served_bytes)} bytes)")

# Upsert assetrect — change position only, verify is_locked preserved
s, r = http("PUT", f"/api/v1/scenes/{SCENE_ID}/shapes/by-external-id/map-background", {
    "type": "assetrect",
    "x": 10, "y": 10,
    "width": 1056, "height": 768,
    "assetId": ASSET_ID,
    "assetHash": ASSET_HASH,
}, key=DM_KEY)
check(s == 200, "Upsert assetrect → 200", f"got {s}: {r}")
check(jget(r, "data", "uuid") == bg_uuid, "UUID preserved on upsert")

# Verify is_locked preserved after upsert (upsert didn't send is_locked)
s, r = http("GET", f"/api/v1/scenes/{SCENE_ID}/shapes?external_id=map-background", key=DM_KEY)
check(s == 200, "Query after upsert → 200", f"got {s}")
check(jget(r, "data", "x") == 10, "x updated by upsert", f"got x={jget(r, 'data', 'x')}")
check(jget(r, "data", "is_locked") is True, "is_locked preserved after upsert",
      f"got is_locked={jget(r, 'data', 'is_locked')}")

# Upload a second asset (different content)
PNG_2x1 = base64.b64encode(
    b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x02'
    b'\x00\x00\x00\x01\x08\x02\x00\x00\x00\xfdM\xc4\xbf\x00'
    b'\x00\x00\x10IDATx\x9cc\xfc\xff\xff?\x03\x10\x00\x00'
    b'\xff\xff\x03\x00\x06\x00\x01\x02\xde_\x15\x00\x00\x00'
    b'\x00IEND\xaeB`\x82'
).decode()
s, r = http("POST", "/api/v1/assets", {
    "name": "test-bg-v2.png",
    "mime_type": "image/png",
    "content_base64": PNG_2x1,
}, key=DM_KEY)
ASSET_ID_2 = jget(r, "data", "asset_id")
ASSET_HASH_2 = jget(r, "data", "asset_hash")
check(s == 201 and ASSET_HASH_2 != ASSET_HASH, "Upload second asset (different hash)",
      f"got s={s}, hash={ASSET_HASH_2}")

# Upsert to replace asset reference
s, r = http("PUT", f"/api/v1/scenes/{SCENE_ID}/shapes/by-external-id/map-background", {
    "type": "assetrect",
    "x": 10, "y": 10,
    "width": 2000, "height": 1500,
    "assetId": ASSET_ID_2,
    "assetHash": ASSET_HASH_2,
}, key=DM_KEY)
check(s == 200, "Upsert assetrect with new asset → 200", f"got {s}: {r}")

# Verify new asset and dimensions are stored
s, r = http("GET", f"/api/v1/scenes/{SCENE_ID}/shapes?external_id=map-background", key=DM_KEY)
check(jget(r, "data", "assetId") == ASSET_ID_2, "assetId updated by upsert",
      f"got assetId={jget(r, 'data', 'assetId')}")
check(jget(r, "data", "width") == 2000, "width updated by upsert",
      f"got width={jget(r, 'data', 'width')}")

# Upsert with mismatched assetId/assetHash (should reject)
s, r = http("PUT", f"/api/v1/scenes/{SCENE_ID}/shapes/by-external-id/map-background", {
    "type": "assetrect",
    "x": 10, "y": 10,
    "width": 1056, "height": 768,
    "assetId": ASSET_ID,
    "assetHash": "0000000000000000000000000000000000000000",
}, key=DM_KEY)
check(s == 400, "Upsert with mismatched assetHash → 400", f"got {s}: {r}")

# Verify assetHash after valid swap
s, r = http("GET", f"/api/v1/scenes/{SCENE_ID}/shapes?external_id=map-background", key=DM_KEY)
check(jget(r, "data", "assetHash") == ASSET_HASH_2, "assetHash matches after swap",
      f"got assetHash={jget(r, 'data', 'assetHash')}")

# Mismatched assetId/assetHash pair (create path)
s, r = http("POST", f"/api/v1/scenes/{SCENE_ID}/shapes", {
    "type": "assetrect",
    "x": 0, "y": 0, "width": 100, "height": 100,
    "assetId": ASSET_ID,
    "assetHash": "0000000000000000000000000000000000000000",
}, key=DM_KEY)
check(s == 400, "Mismatched assetId/assetHash → 400", f"got {s}: {r}")

# Auto-detect dimensions (omit width/height)
s, r = http("POST", f"/api/v1/scenes/{SCENE_ID}/shapes", {
    "type": "assetrect",
    "external_id": "auto-sized",
    "layer": "map",
    "x": 0, "y": 0,
    "assetId": ASSET_ID,
    "assetHash": ASSET_HASH,
}, key=DM_KEY)
check(s == 201, "Assetrect auto-detect dimensions → 201", f"got {s}: {r}")

s, r = http("GET", f"/api/v1/scenes/{SCENE_ID}/shapes?external_id=auto-sized", key=DM_KEY)
check(jget(r, "data", "width") == 1, "Auto-detected width matches image (1px)",
      f"got width={jget(r, 'data', 'width')}")
check(jget(r, "data", "height") == 1, "Auto-detected height matches image (1px)",
      f"got height={jget(r, 'data', 'height')}")

# strict_aspect_ratio — matching ratio (should pass)
s, r = http("POST", f"/api/v1/scenes/{SCENE_ID}/shapes", {
    "type": "assetrect",
    "external_id": "strict-ok",
    "layer": "map",
    "x": 0, "y": 0,
    "width": 2, "height": 2,
    "assetId": ASSET_ID,
    "assetHash": ASSET_HASH,
    "strict_aspect_ratio": True,
}, key=DM_KEY)
check(s == 201, "strict_aspect_ratio matching ratio → 201", f"got {s}: {r}")

# strict_aspect_ratio — mismatched ratio (should fail)
s, r = http("POST", f"/api/v1/scenes/{SCENE_ID}/shapes", {
    "type": "assetrect",
    "external_id": "strict-fail",
    "layer": "map",
    "x": 0, "y": 0,
    "width": 200, "height": 300,
    "assetId": ASSET_ID,
    "assetHash": ASSET_HASH,
    "strict_aspect_ratio": True,
}, key=DM_KEY)
check(s == 400, "strict_aspect_ratio mismatched ratio → 400", f"got {s}: {r}")
check("Aspect ratio mismatch" in str(jget(r, "error", "message") or ""),
      "Error message includes aspect ratio details")

# Non-strict mismatched ratio — should return warning (not error)
s, r = http("POST", f"/api/v1/scenes/{SCENE_ID}/shapes", {
    "type": "assetrect",
    "external_id": "warn-ratio",
    "layer": "map",
    "x": 0, "y": 0,
    "width": 200, "height": 300,
    "assetId": ASSET_ID,
    "assetHash": ASSET_HASH,
}, key=DM_KEY)
check(s == 201, "Non-strict mismatched ratio → 201 with warning", f"got {s}")
check(jget(r, "data", "aspect_ratio_warning") is not None,
      "Warning included in response", f"got {r}")

# Upsert asset swap — auto-detect dimensions when width/height omitted
s, r = http("PUT", f"/api/v1/scenes/{SCENE_ID}/shapes/by-external-id/map-background", {
    "type": "assetrect",
    "x": 0, "y": 0,
    "assetId": ASSET_ID,
    "assetHash": ASSET_HASH,
}, key=DM_KEY)
check(s == 200, "Upsert swap asset without dimensions → 200", f"got {s}: {r}")
s, r = http("GET", f"/api/v1/scenes/{SCENE_ID}/shapes?external_id=map-background", key=DM_KEY)
check(jget(r, "data", "width") == 1, "Dimensions auto-detected from new asset (width=1)",
      f"got width={jget(r, 'data', 'width')}")
check(jget(r, "data", "height") == 1, "Dimensions auto-detected from new asset (height=1)",
      f"got height={jget(r, 'data', 'height')}")

# Upsert non-strict warning response
s, r = http("PUT", f"/api/v1/scenes/{SCENE_ID}/shapes/by-external-id/map-background", {
    "type": "assetrect",
    "x": 0, "y": 0,
    "width": 200, "height": 300,
    "assetId": ASSET_ID,
    "assetHash": ASSET_HASH,
}, key=DM_KEY)
check(s == 200, "Upsert non-strict mismatched ratio → 200", f"got {s}")
check(jget(r, "data", "aspect_ratio_warning") is not None,
      "Upsert warning in response", f"got {r}")

# Upsert with strict_aspect_ratio — mismatched (should fail)
s, r = http("PUT", f"/api/v1/scenes/{SCENE_ID}/shapes/by-external-id/map-background", {
    "type": "assetrect",
    "x": 10, "y": 10,
    "width": 200, "height": 300,
    "assetId": ASSET_ID_2,
    "assetHash": ASSET_HASH_2,
    "strict_aspect_ratio": True,
}, key=DM_KEY)
check(s == 400, "Upsert strict_aspect_ratio mismatched → 400", f"got {s}: {r}")

# Missing assetId
s, r = http("POST", f"/api/v1/scenes/{SCENE_ID}/shapes", {
    "type": "assetrect",
    "x": 0, "y": 0, "width": 100, "height": 100,
}, key=DM_KEY)
check(s == 400, "Assetrect missing assetId → 400", f"got {s}")

# ============================================================
print("\n" + "=" * 60)
print(f"RESULTS: {pass_count} passed, {fail_count} failed, {total_count} total")
print("=" * 60)
if fail_count > 0:
    sys.exit(1)
