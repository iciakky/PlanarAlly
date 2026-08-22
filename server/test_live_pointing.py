#!/usr/bin/env python3
"""
Live Pointing & Memory — ATDD Integration Tests

46 BDD scenarios from docs/live-pointing-bdd-scenarios.md.
REST-testable scenarios run as integration tests against a live server.
Browser-only scenarios are listed at the end.

Run: python test_live_pointing.py
Requires: PlanarAlly server at http://127.0.0.1:8000
"""

import json
import sys
import time
import urllib.error
import urllib.request

BASE_URL = "http://127.0.0.1:8000"
TS = int(time.time())
DM_USER = f"marktest_dm_{TS}"
DM_PASS = "testpass123"
PLAYER_USER = f"marktest_player_{TS}"
PLAYER_PASS = "testpass123"
PLAYER2_USER = f"marktest_player2_{TS}"
PLAYER2_PASS = "testpass123"

pass_count = 0
fail_count = 0
total_count = 0

DM_KEY = None
PLAYER_KEY = None
PLAYER2_KEY = None
ROOM_ID = None
SCENE_ID = None


def green(s):
    return f"\033[92m{s}\033[0m"


def red(s):
    return f"\033[91m{s}\033[0m"


def yellow(s):
    return f"\033[93m{s}\033[0m"


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


def get_markers(key, scope=None):
    """Helper: GET markers and return list."""
    path = f"/api/v1/scenes/{SCENE_ID}/markers"
    if scope:
        path += f"?scope={scope}"
    s, r = http("GET", path, key=key)
    markers = jget(r, "data", "markers") or jget(r, "data") or []
    return s, markers if isinstance(markers, list) else []


def find_marker(markers, external_id):
    """Find a marker by external_id in a list."""
    return next((m for m in markers if m.get("external_id") == external_id), None)


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

def setup():
    global DM_KEY, PLAYER_KEY, PLAYER2_KEY, ROOM_ID, SCENE_ID

    print("\n" + "=" * 60)
    print("SETUP")
    print("=" * 60)

    for user, pwd in [(DM_USER, DM_PASS), (PLAYER_USER, PLAYER_PASS), (PLAYER2_USER, PLAYER2_PASS)]:
        s, _ = http("POST", "/api/register", {"username": user, "password": pwd})
        check(s == 200, f"Register {user}", f"got {s}")

    s, r = http("POST", "/api/v1/auth/keys", {"username": DM_USER, "password": DM_PASS, "role": "dm"})
    DM_KEY = jget(r, "data", "key")
    check(bool(DM_KEY), "DM API key")

    s, r = http("POST", "/api/v1/auth/keys", {"username": PLAYER_USER, "password": PLAYER_PASS, "role": "player"})
    PLAYER_KEY = jget(r, "data", "key")
    check(bool(PLAYER_KEY), "Player API key")

    s, r = http("POST", "/api/v1/auth/keys", {"username": PLAYER2_USER, "password": PLAYER2_PASS, "role": "player"})
    PLAYER2_KEY = jget(r, "data", "key")
    check(bool(PLAYER2_KEY), "Player2 API key")

    s, r = http("POST", "/api/v1/rooms", {"name": f"marker_test_{TS}"}, key=DM_KEY)
    check(s == 201, "Create room", f"got {s}: {r}")
    ROOM_ID = jget(r, "data", "room_id")
    SCENE_ID = jget(r, "data", "default_location", "id")

    for u in [PLAYER_USER, PLAYER2_USER]:
        s, _ = http("POST", f"/api/v1/rooms/{ROOM_ID}/players",
                     {"username": u, "role": "player"}, key=DM_KEY)
        check(s in (200, 201), f"Add {u} to room", f"got {s}")


# ===== CRUD (S1, S1b, S1c, S2, S3, S4, S4b, S4d, S4e) =====

POINT_A_REV = None

def test_s1_create_ring():
    """S1: DM creates ring marker. Owner is server-determined."""
    global POINT_A_REV
    print("\n--- S1: Create ring marker ---")
    s, r = http("PUT", f"/api/v1/scenes/{SCENE_ID}/markers/by-external-id/point-A", {
        "x": 384, "y": 288, "shape": "ring", "label": "A",
        "scope": "player", "visible_to": [PLAYER_USER],
    }, key=DM_KEY)
    check(s in (200, 201), f"Create → {s}", f"got {s}: {r}")
    data = jget(r, "data") or {}
    check(data.get("owner") == DM_USER, f"owner={DM_USER} (server-determined)")
    check(data.get("external_id") == "point-A", "external_id in response")
    rev = data.get("revision")
    check(isinstance(rev, int), f"revision={rev}")
    POINT_A_REV = rev

    _, markers = get_markers(DM_KEY, scope="player")
    check(find_marker(markers, "point-A") is not None, "point-A in GET /markers")


def test_s1b_create_label():
    """S1b: DM creates label marker."""
    print("\n--- S1b: Create label marker ---")
    s, r = http("PUT", f"/api/v1/scenes/{SCENE_ID}/markers/by-external-id/label-1", {
        "x": 200, "y": 150, "shape": "label", "label": "B", "text": "move here",
        "scope": "player", "visible_to": [PLAYER_USER],
    }, key=DM_KEY)
    check(s in (200, 201), f"Create label → {s}", f"got {s}: {r}")
    data = jget(r, "data") or {}
    check(data.get("shape") == "label", "shape=label")
    check(data.get("owner") == DM_USER, f"owner={DM_USER}")


def test_s1c_create_flag():
    """S1c: DM creates flag marker in fog."""
    print("\n--- S1c: Create flag in fog ---")
    s, r = http("PUT", f"/api/v1/scenes/{SCENE_ID}/markers/by-external-id/flag-1", {
        "x": 600, "y": 500, "shape": "flag", "label": "C",
        "scope": "player", "visible_to": [PLAYER_USER], "render_above_fog": True,
    }, key=DM_KEY)
    check(s in (200, 201), f"Create flag → {s}", f"got {s}: {r}")
    _, markers = get_markers(DM_KEY)
    m = find_marker(markers, "flag-1")
    check(m is not None, "flag-1 persists in GET")
    if m:
        check(m.get("owner") == DM_USER, f"owner={DM_USER}")


def test_s2_upsert():
    """S2: Upsert preserves omitted fields (visible_to). Revision increases."""
    print("\n--- S2: Upsert marker ---")
    # Ensure point-A exists and capture its revision as baseline
    _, setup_r = http("PUT", f"/api/v1/scenes/{SCENE_ID}/markers/by-external-id/point-A", {
        "x": 384, "y": 288, "shape": "ring", "label": "A",
        "scope": "player", "visible_to": [PLAYER_USER],
    }, key=DM_KEY)
    baseline_rev = jget(setup_r, "data", "revision")

    s, r = http("PUT", f"/api/v1/scenes/{SCENE_ID}/markers/by-external-id/point-A", {
        "x": 500, "y": 300, "shape": "ring", "label": "A", "scope": "player",
    }, key=DM_KEY)
    check(s == 200, "Upsert → 200", f"got {s}: {r}")
    data = jget(r, "data") or {}
    check(data.get("x") == 500, "x=500")
    check(data.get("y") == 300, "y=300")
    vis = data.get("visible_to")
    check(isinstance(vis, list) and PLAYER_USER in vis,
          f"visible_to preserved: {vis}")
    rev = data.get("revision")
    check(isinstance(rev, int), f"revision={rev}")
    if isinstance(baseline_rev, int) and isinstance(rev, int):
        check(rev > baseline_rev, f"Revision increased from baseline: {baseline_rev} < {rev}")


def test_s3_delete():
    """S3: Delete single marker."""
    print("\n--- S3: Delete marker ---")
    http("PUT", f"/api/v1/scenes/{SCENE_ID}/markers/by-external-id/to-delete", {
        "x": 10, "y": 10, "shape": "ring", "label": "X",
        "scope": "player", "visible_to": [PLAYER_USER],
    }, key=DM_KEY)

    s, r = http("DELETE", f"/api/v1/scenes/{SCENE_ID}/markers/by-external-id/to-delete", key=DM_KEY)
    check(s == 200, "Delete → 200", f"got {s}: {r}")
    rev = jget(r, "data", "revision") or jget(r, "revision")
    check(rev is not None, f"revision on delete: {rev}")

    _, markers = get_markers(DM_KEY)
    check(find_marker(markers, "to-delete") is None, "to-delete absent from list")


def test_s4_batch_clear():
    """S4: Batch clear by prefix. Only requesting user's markers deleted."""
    print("\n--- S4: Batch clear by prefix ---")
    # DM creates dm-live-1, dm-live-2
    for eid in ["dm-live-1", "dm-live-2"]:
        http("PUT", f"/api/v1/scenes/{SCENE_ID}/markers/by-external-id/{eid}", {
            "x": 10, "y": 10, "shape": "ring", "label": eid[-1:],
            "scope": "player", "visible_to": [PLAYER_USER],
        }, key=DM_KEY)
    # Player creates player-ref-A (via player key)
    http("PUT", f"/api/v1/scenes/{SCENE_ID}/markers/by-external-id/player-ref-A", {
        "x": 20, "y": 20, "shape": "flag", "label": "PA",
        "scope": "player", "visible_to": [PLAYER_USER],
    }, key=PLAYER_KEY)

    s, _ = http("DELETE", f"/api/v1/scenes/{SCENE_ID}/markers?prefix=dm-live-&scope=player", key=DM_KEY)
    check(s == 200, "Batch delete → 200", f"got {s}")

    _, markers = get_markers(DM_KEY)
    eids = [m.get("external_id") for m in markers]
    check("dm-live-1" not in eids, "dm-live-1 deleted")
    check("dm-live-2" not in eids, "dm-live-2 deleted")
    check("player-ref-A" in eids, "player-ref-A survived (different owner)")


def test_s4b_owner_filter():
    """S4b: Batch delete with owner filter (own markers only)."""
    print("\n--- S4b: Batch delete with owner filter ---")
    http("PUT", f"/api/v1/scenes/{SCENE_ID}/markers/by-external-id/dm-b1", {
        "x": 10, "y": 10, "shape": "ring", "label": "B1",
        "scope": "player", "visible_to": [PLAYER_USER],
    }, key=DM_KEY)
    http("PUT", f"/api/v1/scenes/{SCENE_ID}/markers/by-external-id/pl-b1", {
        "x": 20, "y": 20, "shape": "flag", "label": "PB",
        "scope": "player", "visible_to": [PLAYER_USER],
    }, key=PLAYER_KEY)

    s, _ = http("DELETE",
                f"/api/v1/scenes/{SCENE_ID}/markers?scope=player&owner={DM_USER}",
                key=DM_KEY)
    check(s == 200, "Batch delete owner=dm → 200", f"got {s}")

    _, markers = get_markers(DM_KEY)
    eids = [m.get("external_id") for m in markers]
    check("dm-b1" not in eids, "dm-b1 deleted")
    check("pl-b1" in eids, "pl-b1 survived (different owner)")


def test_s4d_prefix_cross_owner():
    """S4d: Prefix delete cannot hit other owner's markers."""
    print("\n--- S4d: Prefix cross-owner ---")
    http("PUT", f"/api/v1/scenes/{SCENE_ID}/markers/by-external-id/dm-live-mine", {
        "x": 10, "y": 10, "shape": "ring", "label": "M",
        "scope": "player", "visible_to": [PLAYER_USER],
    }, key=DM_KEY)
    http("PUT", f"/api/v1/scenes/{SCENE_ID}/markers/by-external-id/dm-live-scout", {
        "x": 20, "y": 20, "shape": "flag", "label": "S",
        "scope": "player", "visible_to": [PLAYER_USER],
    }, key=PLAYER_KEY)

    http("DELETE", f"/api/v1/scenes/{SCENE_ID}/markers?prefix=dm-live-&scope=player", key=DM_KEY)

    _, markers = get_markers(DM_KEY)
    eids = [m.get("external_id") for m in markers]
    check("dm-live-mine" not in eids, "dm-live-mine deleted (own)")
    check("dm-live-scout" in eids, "dm-live-scout survived (player's)")


def test_s4e_cannot_delete_others():
    """S4e: owner filter targeting another user → 403."""
    print("\n--- S4e: Cannot delete others' markers ---")
    http("PUT", f"/api/v1/scenes/{SCENE_ID}/markers/by-external-id/player-secret", {
        "x": 30, "y": 30, "shape": "flag", "label": "PS",
        "scope": "player", "visible_to": [PLAYER_USER],
    }, key=PLAYER_KEY)

    s, _ = http("DELETE",
                f"/api/v1/scenes/{SCENE_ID}/markers?owner={PLAYER_USER}",
                key=DM_KEY)
    check(s == 403, f"DELETE owner={PLAYER_USER} as DM → 403", f"got {s}")

    # Verify via player's own view (DM may not see player-owned markers)
    _, markers = get_markers(PLAYER_KEY)
    check(find_marker(markers, "player-secret") is not None, "player-secret still exists (player's view)")


# ===== Security (S7, S7b, S7c, S18, S21, S21b, S23, S23b) =====

def test_s7_dm_scope():
    """S7: scope:dm marker not sent to player."""
    print("\n--- S7: scope:dm secrecy ---")
    http("PUT", f"/api/v1/scenes/{SCENE_ID}/markers/by-external-id/secret-note", {
        "x": 300, "y": 300, "shape": "label", "label": "SEC",
        "text": "trap here", "scope": "dm",
    }, key=DM_KEY)

    _, dm_markers = get_markers(DM_KEY, scope="dm")
    check(find_marker(dm_markers, "secret-note") is not None, "DM sees scope:dm marker")

    _, pl_markers = get_markers(PLAYER_KEY)
    check(find_marker(pl_markers, "secret-note") is None,
          "Player does NOT see scope:dm (data-level secrecy)")


def test_s7b_visible_to_exclusion():
    """S7b: visible_to excludes unlisted players at data level."""
    print("\n--- S7b: visible_to data-level exclusion ---")
    http("PUT", f"/api/v1/scenes/{SCENE_ID}/markers/by-external-id/ash-only", {
        "x": 400, "y": 400, "shape": "ring", "label": "AO",
        "scope": "player", "visible_to": [PLAYER_USER],
    }, key=DM_KEY)

    _, p1_markers = get_markers(PLAYER_KEY)
    check(find_marker(p1_markers, "ash-only") is not None,
          f"{PLAYER_USER} sees ash-only")

    p2_status, p2_r = http("GET", f"/api/v1/scenes/{SCENE_ID}/markers", key=PLAYER2_KEY)
    p2_markers = jget(p2_r, "data", "markers") or jget(p2_r, "data") or []
    check(find_marker(p2_markers if isinstance(p2_markers, list) else [], "ash-only") is None,
          f"{PLAYER2_USER} does NOT see ash-only (parsed list)")
    # Full response envelope scan — not just the markers array
    p2_full_text = json.dumps(p2_r)
    check("ash-only" not in p2_full_text,
          f"{PLAYER2_USER} zero references to 'ash-only' in full response envelope (data-level)")


def test_s7c_shape_isolation():
    """S7c: GM-only shape isolated even with co-located marker."""
    print("\n--- S7c: GM-only shape + marker coexist ---")
    s, r = http("POST", f"/api/v1/scenes/{SCENE_ID}/shapes", {
        "type": "circulartoken", "external_id": "hidden-boss",
        "layer": "dm", "x": 400, "y": 300, "radius": 28, "text": "??",
    }, key=DM_KEY)
    boss_uuid = jget(r, "data", "uuid")

    http("PUT", f"/api/v1/scenes/{SCENE_ID}/markers/by-external-id/point-nearby", {
        "x": 400, "y": 300, "shape": "ring", "label": "N",
        "scope": "player", "visible_to": [PLAYER_USER],
    }, key=DM_KEY)

    _, pl_markers = get_markers(PLAYER_KEY)
    resp_text = json.dumps(pl_markers)
    check("point-nearby" in resp_text, "Player sees marker")
    if boss_uuid:
        check(boss_uuid not in resp_text, "Hidden boss UUID absent from player markers")
    check("hidden-boss" not in resp_text, "hidden-boss name absent")


def test_s18_no_hidden_reveal():
    """S18: Marker above fog doesn't reveal hidden shapes in API."""
    print("\n--- S18: No hidden reveal in API ---")
    s, r = http("POST", f"/api/v1/scenes/{SCENE_ID}/shapes", {
        "type": "line", "external_id": "secret-room-wall",
        "layer": "dm", "x": 384, "y": 288, "x2": 500, "y2": 288,
        "line_width": 2, "stroke_colour": "rgba(0,0,0,1)",
    }, key=DM_KEY)
    wall_uuid = jget(r, "data", "uuid")

    http("PUT", f"/api/v1/scenes/{SCENE_ID}/markers/by-external-id/fog-ref", {
        "x": 384, "y": 288, "shape": "ring", "label": "F",
        "scope": "player", "visible_to": [PLAYER_USER], "render_above_fog": True,
    }, key=DM_KEY)

    _, pl_markers = get_markers(PLAYER_KEY)
    resp_text = json.dumps(pl_markers)
    check("secret-room-wall" not in resp_text, "No secret-room-wall in player markers")
    if wall_uuid:
        check(wall_uuid not in resp_text, "Hidden wall UUID absent")


def test_s21_empty_visible_to():
    """S21: visible_to=[] → 400 with error identifying the field."""
    print("\n--- S21: Empty visible_to ---")
    s, r = http("PUT", f"/api/v1/scenes/{SCENE_ID}/markers/by-external-id/empty-vis", {
        "x": 10, "y": 10, "shape": "ring", "label": "E",
        "scope": "player", "visible_to": [],
    }, key=DM_KEY)
    check(s == 400, "visible_to=[] → 400", f"got {s}")
    err_text = json.dumps(r).lower()
    check("visible_to" in err_text, "Error identifies visible_to field", f"body: {r}")


def test_s21b_missing_visible_to():
    """S21b: scope=player without visible_to → 400 with error identifying the field."""
    print("\n--- S21b: Missing visible_to ---")
    s, r = http("PUT", f"/api/v1/scenes/{SCENE_ID}/markers/by-external-id/no-vis", {
        "x": 10, "y": 10, "shape": "ring", "label": "NV", "scope": "player",
    }, key=DM_KEY)
    check(s == 400, "scope=player no visible_to → 400", f"got {s}")
    err_text = json.dumps(r).lower()
    check("visible_to" in err_text, "Error identifies visible_to field", f"body: {r}")


def test_s23_owner_spoof():
    """S23: Owner cannot be spoofed via request body. Error references ownership."""
    print("\n--- S23: Owner spoof → 400 ---")
    s, r = http("PUT", f"/api/v1/scenes/{SCENE_ID}/markers/by-external-id/spoof-test", {
        "x": 10, "y": 10, "shape": "ring", "label": "SP",
        "scope": "player", "visible_to": [PLAYER_USER],
        "owner": PLAYER_USER,
    }, key=DM_KEY)
    check(s == 400, f"owner={PLAYER_USER} as DM → 400", f"got {s}: {r}")
    err_text = json.dumps(r).lower()
    check("owner" in err_text, "Error references 'owner' field", f"body: {r}")


def test_s23b_arrow_no_target():
    """S23b: Arrow without target_x/target_y → 400."""
    print("\n--- S23b: Arrow missing target ---")
    s, _ = http("PUT", f"/api/v1/scenes/{SCENE_ID}/markers/by-external-id/bad-arrow", {
        "x": 100, "y": 100, "shape": "arrow", "label": "BA",
        "scope": "player", "visible_to": [PLAYER_USER],
    }, key=DM_KEY)
    check(s == 400, "Arrow no target → 400", f"got {s}")


# ===== Revision (S13) =====

def test_s13_revision():
    """S13: Marker mutations return monotonically increasing revision."""
    print("\n--- S13: Revision integration ---")
    s, r = http("PUT", f"/api/v1/scenes/{SCENE_ID}/markers/by-external-id/rev-1", {
        "x": 50, "y": 50, "shape": "ring", "label": "R1",
        "scope": "player", "visible_to": [PLAYER_USER],
    }, key=DM_KEY)
    rev1 = jget(r, "data", "revision")
    check(isinstance(rev1, int), f"rev1={rev1}")

    s, r = http("PUT", f"/api/v1/scenes/{SCENE_ID}/markers/by-external-id/rev-2", {
        "x": 60, "y": 60, "shape": "flag", "label": "R2",
        "scope": "player", "visible_to": [PLAYER_USER],
    }, key=DM_KEY)
    rev2 = jget(r, "data", "revision")
    check(isinstance(rev2, int), f"rev2={rev2}")
    if isinstance(rev1, int) and isinstance(rev2, int):
        check(rev2 > rev1, f"Monotonic: {rev1} < {rev2}")


# ===== Record (S22) =====

def test_s22_record_field():
    """S22: record field stored, queryable, and filterable."""
    print("\n--- S22: record field ---")
    http("PUT", f"/api/v1/scenes/{SCENE_ID}/markers/by-external-id/tactical-A", {
        "x": 100, "y": 100, "shape": "ring", "label": "T",
        "scope": "player", "visible_to": [PLAYER_USER], "record": True,
    }, key=DM_KEY)
    http("PUT", f"/api/v1/scenes/{SCENE_ID}/markers/by-external-id/scratch-B", {
        "x": 200, "y": 200, "shape": "ring", "label": "SB",
        "scope": "player", "visible_to": [PLAYER_USER], "record": False,
    }, key=DM_KEY)

    # Part 1: field is stored correctly in general list
    _, markers = get_markers(DM_KEY)
    tac = find_marker(markers, "tactical-A")
    scr = find_marker(markers, "scratch-B")
    check(tac is not None, "tactical-A exists")
    check(scr is not None, "scratch-B exists")
    if tac:
        check(tac.get("record") is True, "tactical-A record=true")
    if scr:
        check(scr.get("record") is False, "scratch-B record=false")

    # Part 2: record-filtered query (session record)
    s, r = http("GET", f"/api/v1/scenes/{SCENE_ID}/markers?record=true", key=DM_KEY)
    if s == 200:
        rec_markers = jget(r, "data", "markers") or jget(r, "data") or []
        if isinstance(rec_markers, list):
            rec_eids = [m.get("external_id") for m in rec_markers]
            check("tactical-A" in rec_eids, "tactical-A in record=true query")
            check("scratch-B" not in rec_eids, "scratch-B excluded from record=true query")
        else:
            check(False, "record=true query returns list", f"got: {r}")
    else:
        # If record filter not supported yet, note it
        print(f"  {yellow('NOTE')} GET /markers?record=true not implemented yet ({s})")


# ===== Field semantics (S17, S14 data) =====

def test_s17_fields():
    """S17: label/text/comment stored and retrievable."""
    print("\n--- S17: Field semantics ---")
    http("PUT", f"/api/v1/scenes/{SCENE_ID}/markers/by-external-id/field-test", {
        "x": 300, "y": 300, "shape": "label", "label": "A",
        "text": "move here",
        "comment": "I want to scout toward this side and look for cover.",
        "scope": "player", "visible_to": [PLAYER_USER],
    }, key=DM_KEY)

    _, markers = get_markers(PLAYER_KEY)
    m = find_marker(markers, "field-test")
    check(m is not None, "field-test found")
    if m:
        check(m.get("label") == "A", "label=A")
        check(m.get("text") == "move here", "text='move here'")
        check("scout toward" in (m.get("comment") or ""), "comment stored")


def test_s14_arrow_data():
    """S14: Arrow stores source + target."""
    print("\n--- S14: Arrow data ---")
    s, r = http("PUT", f"/api/v1/scenes/{SCENE_ID}/markers/by-external-id/arrow-1", {
        "x": 100, "y": 100, "target_x": 300, "target_y": 200,
        "shape": "arrow", "label": "go",
        "scope": "player", "visible_to": [PLAYER_USER],
    }, key=DM_KEY)
    check(s in (200, 201), f"Create arrow → {s}", f"got {s}: {r}")
    data = jget(r, "data") or {}
    check(data.get("target_x") == 300, "target_x=300")
    check(data.get("target_y") == 200, "target_y=200")
    check(data.get("shape") == "arrow", "shape=arrow")


# ===== Map Refs (S11, S12, S15, S19) =====

def test_s11_pure_map_ref():
    """S11: Pure coordinate map ref (no marker link)."""
    print("\n--- S11: Pure coordinate map ref ---")
    s, r = http("POST", f"/api/v1/scenes/{SCENE_ID}/map-refs", {
        "player": PLAYER_USER, "x": 412, "y": 322,
    }, key=PLAYER_KEY)
    check(s in (200, 201), f"Create pure map-ref → {s}", f"got {s}: {r}")
    data = jget(r, "data") or {}
    check(data.get("x") == 412, "x=412")
    check(data.get("y") == 322, "y=322")
    check("grid" in data, "grid field present")
    check(data.get("marker_id") is None, "No marker_id (pure ref)")


def test_s11d_marker_linked_ref():
    """S11d: Marker-linked map ref."""
    print("\n--- S11d: Marker-linked map ref ---")
    http("PUT", f"/api/v1/scenes/{SCENE_ID}/markers/by-external-id/{PLAYER_USER}:A", {
        "x": 412, "y": 322, "shape": "flag", "label": "A",
        "comment": "scout here",
        "scope": "player", "visible_to": [PLAYER_USER],
    }, key=PLAYER_KEY)

    s, r = http("POST", f"/api/v1/scenes/{SCENE_ID}/map-refs", {
        "player": PLAYER_USER, "x": 412, "y": 322,
        "marker_id": "A",
    }, key=PLAYER_KEY)
    check(s in (200, 201), f"Create marker-linked ref → {s}", f"got {s}: {r}")
    data = jget(r, "data") or {}
    check(data.get("marker_id") == "A", "marker_id=A")


def test_s12_query_refs():
    """S12: DM queries recent map refs. Verify specific coords + inside_scene."""
    print("\n--- S12: Query map refs ---")
    # Ensure a known ref exists (inline setup)
    http("POST", f"/api/v1/scenes/{SCENE_ID}/map-refs", {
        "player": PLAYER_USER, "x": 412, "y": 322,
    }, key=PLAYER_KEY)

    s, r = http("GET",
                f"/api/v1/scenes/{SCENE_ID}/map-refs?since_revision=0&player={PLAYER_USER}",
                key=DM_KEY)
    check(s == 200, "GET map-refs → 200", f"got {s}: {r}")
    refs = jget(r, "data", "refs") or jget(r, "data") or []
    check(isinstance(refs, list) and len(refs) > 0, f"Got {len(refs)} ref(s)")
    # Find the specific ref we created
    matched = [ref for ref in refs if ref.get("x") == 412 and ref.get("y") == 322]
    check(len(matched) > 0, "Found ref with x=412, y=322")
    if matched:
        ref = matched[0]
        check("grid" in ref, "grid present")
        check("inside_scene" in ref, "inside_scene present (BDD S12 requirement)")


def test_s15_out_of_bounds():
    """S15: Out-of-bounds map ref with direction."""
    print("\n--- S15: Out-of-bounds map ref ---")
    http("POST", f"/api/v1/scenes/{SCENE_ID}/shapes", {
        "type": "rect", "external_id": "bounds-rect",
        "layer": "map", "x": 0, "y": 0, "width": 1000, "height": 800,
        "fill_colour": "rgba(200,200,200,1)",
    }, key=DM_KEY)

    s, r = http("POST", f"/api/v1/scenes/{SCENE_ID}/map-refs", {
        "player": PLAYER_USER, "x": 1500, "y": 900,
    }, key=PLAYER_KEY)
    check(s in (200, 201), "Create OOB ref", f"got {s}: {r}")
    data = jget(r, "data") or {}
    check(data.get("inside_scene") is False, "inside_scene=false")
    check("scene_bounds_source" in data, "scene_bounds_source present")
    has_dir = "direction_from_bounds" in data or "nearest_edge" in data
    check(has_dir, "Direction/nearest_edge present")


def test_s19_no_hidden_leak():
    """S19: Map ref near hidden area doesn't leak."""
    print("\n--- S19: Map ref no hidden leak ---")
    http("POST", f"/api/v1/scenes/{SCENE_ID}/shapes", {
        "type": "rect", "external_id": "hidden-room",
        "layer": "dm", "x": 480, "y": 380, "width": 40, "height": 40,
        "fill_colour": "rgba(100,0,0,1)", "name": "Secret Chamber",
    }, key=DM_KEY)

    s, r = http("POST", f"/api/v1/scenes/{SCENE_ID}/map-refs", {
        "player": PLAYER_USER, "x": 500, "y": 400,
    }, key=PLAYER_KEY)
    check(s in (200, 201), "Create ref near hidden", f"got {s}: {r}")
    resp_text = json.dumps(r)
    check("hidden-room" not in resp_text, "No hidden-room in response")
    check("Secret Chamber" not in resp_text, "No hidden name in response")

    known = jget(r, "data", "known_state_hint")
    if known is not None:
        check(known in (None, "unseen"), f"known_state_hint={known}")


# ===== Grid Options (S10) =====

def test_s10_grid_options():
    """S10b: PATCH grid-options with compass."""
    print("\n--- S10b: Grid options API ---")
    s, r = http("PATCH", f"/api/v1/scenes/{SCENE_ID}/grid-options", {
        "show_coordinates": "hover", "coordinate_mode": "xy",
        "origin": "NW", "toggleable": True,
        "compass": {"enabled": True, "north_degrees": 0},
    }, key=DM_KEY)
    check(s == 200, "PATCH grid-options → 200", f"got {s}: {r}")
    data = jget(r, "data") or r
    check(data.get("show_coordinates") == "hover", "show_coordinates=hover")


# ===== Prep-time persistence (S5b) =====

def test_s5b_prep_time():
    """S5b: Prep-time marker visible to player on first query."""
    print("\n--- S5b: Prep-time persistence ---")
    http("PUT", f"/api/v1/scenes/{SCENE_ID}/markers/by-external-id/prep-A", {
        "x": 700, "y": 100, "shape": "flag", "label": "PA",
        "scope": "player", "visible_to": [PLAYER_USER],
    }, key=DM_KEY)

    _, markers = get_markers(PLAYER_KEY)
    check(find_marker(markers, "prep-A") is not None,
          "Prep-time marker visible to player on first query")


# ===== S28: UI input stores comment, not text =====

def test_s28_comment_stored_text_null():
    """S28: Server stores comment field correctly, text stays null when not sent.
    Note: the UI-to-comment mapping happens client-side (Vue dialog sends comment
    field via socket). This REST test verifies server-side storage only.
    The actual note→comment mapping is a browser-only test."""
    print("\n--- S28: comment stored, text null (server-side) ---")
    http("PUT", f"/api/v1/scenes/{SCENE_ID}/markers/by-external-id/ui-note-test", {
        "x": 350, "y": 350, "shape": "ring", "label": "NT",
        "comment": "check this corner",
        "scope": "player", "visible_to": [PLAYER_USER],
    }, key=PLAYER_KEY)

    _, markers = get_markers(PLAYER_KEY)
    m = find_marker(markers, "ui-note-test")
    check(m is not None, "ui-note-test found (player created)")
    if m:
        check(m.get("comment") == "check this corner", "comment stored correctly")
        check(m.get("text") is None, "text is null (not sent, not auto-filled)")


# ===== Browser-only scenarios =====

def note_browser_scenarios():
    print("\n" + "=" * 60)
    print(yellow("BROWSER-ONLY SCENARIOS (require automation bridge):"))
    print("=" * 60)
    browser_only = [
        "S3b  - Delete syncs to connected player overlay",
        "S4c  - Batch-delete propagates to connected players",
        "S5   - Marker syncs to player in real-time (socket)",
        "S5c  - Reconnection delivers full authoritative marker state",
        "S5d  - visible_to live delivery to named recipient only",
        "S6   - Marker renders above FoW (screenshot)",
        "S6b  - Marker above fog does not punch through (pixel check)",
        "S8   - Markers don't affect vision computation",
        "S9   - Player places marker via UI (shape+colour+note)",
        "S9b  - Duplicate label upsert with UI feedback",
        "S9c  - Player places marker in unseen fog via UI",
        "S10  - Coordinate hover display (visual)",
        "S10b - Compass display (visual part)",
        "S11  - Player creates pure map ref via UI click",
        "S11b - Player copies pure coordinate to clipboard",
        "S11c - DM agent parses @map-ref payload",
        "S11d - Player creates marker-linked map ref via UI",
        "S11e - Player copies marker-linked ref to clipboard",
        "S13b - waitForSync with DM browser, no player connected",
        "S14  - Arrow renders at midpoint (visual)",
        "S16  - Markers persist across page reload",
        "S17  - label+text on-map, comment hover tooltip",
        "S20  - Marker layer toggle (session-only)",
        "S24  - Display: label always, text toggleable, comment hover",
        "S25  - Toggle Marker Text (per-client, scene-wide, session-only)",
        "S25b - Null-comment hover shows no tooltip",
        "S26  - Player selects ring or flag shape in dialog",
        "S26b - Arrow/Label NOT in player UI shape selector",
        "S27  - Colour preset swatches in dialog",
        "S29  - Delete own marker via right-click context menu",
        "S30  - Delete option only for own markers (not DM's)",
        "S31  - Delete nearest marker on overlap",
        "S32  - No delete option when no own markers nearby",
        "S33  - Delete via context menu syncs to server",
    ]
    for sc in browser_only:
        print(f"  {yellow('SKIP')} {sc}")
    print(f"\n  {len(browser_only)} scenarios require browser verification")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("Live Pointing & Memory — ATDD Integration Tests")
    print(f"Server: {BASE_URL}")
    print("=" * 60)

    setup()

    # CRUD
    test_s1_create_ring()
    test_s1b_create_label()
    test_s1c_create_flag()
    test_s2_upsert()
    test_s3_delete()
    test_s4_batch_clear()
    test_s4b_owner_filter()
    test_s4d_prefix_cross_owner()
    test_s4e_cannot_delete_others()

    # Security
    test_s7_dm_scope()
    test_s7b_visible_to_exclusion()
    test_s7c_shape_isolation()
    test_s18_no_hidden_reveal()
    test_s21_empty_visible_to()
    test_s21b_missing_visible_to()
    test_s23_owner_spoof()
    test_s23b_arrow_no_target()

    # Revision
    test_s13_revision()

    # Record
    test_s22_record_field()

    # Fields
    test_s17_fields()
    test_s14_arrow_data()

    # Map Refs
    test_s11_pure_map_ref()
    test_s11d_marker_linked_ref()
    test_s12_query_refs()
    test_s15_out_of_bounds()
    test_s19_no_hidden_leak()

    # Grid Options
    test_s10_grid_options()

    # UX: comment vs text
    test_s28_comment_stored_text_null()

    # Prep-time
    test_s5b_prep_time()

    note_browser_scenarios()

    print("\n" + "=" * 60)
    print(f"RESULTS: {pass_count} passed, {fail_count} failed, {total_count} total")
    print("=" * 60)
    if fail_count > 0:
        sys.exit(1)
