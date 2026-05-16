#!/bin/bash
# Phase 22: Full Integration Test Script
# Tests complete DM CLI workflow end-to-end via curl

BASE_URL="http://localhost:8000"
TS=$(date +%s)
DM_USER="inttest_dm_$TS"
DM_PASS="testpass123"
PLAYER_USER="inttest_player_$TS"
PLAYER_PASS="testpass456"
DB_PATH="/d/repo/PlanarAlly/server/data/planar.sqlite"

PASS=0
FAIL=0
TOTAL=0

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

pass() {
    echo -e "  ${GREEN}✓ $1${NC}"
    PASS=$((PASS + 1))
    TOTAL=$((TOTAL + 1))
}

fail() {
    echo -e "  ${RED}✗ $1${NC}"
    FAIL=$((FAIL + 1))
    TOTAL=$((TOTAL + 1))
}

check_http() {
    local expected="$1"
    local actual="$2"
    local name="$3"
    if [ "$actual" = "$expected" ]; then
        pass "$name → HTTP $actual"
    else
        fail "$name (expected $expected, got $actual)"
    fi
}

# Parse JSON field using python3
jq_field() {
    local json="$1"
    local expr="$2"
    echo "$json" | python3 -c "import sys,json; d=json.load(sys.stdin); print($expr)" 2>/dev/null
}

echo "============================================================"
echo "PlanarAlly REST API - Phase 22 Integration Test"
echo "============================================================"
echo "DM user: $DM_USER"
echo "Timestamp: $TS"
echo ""

# ==============================================================
# SETUP: Register users, create API keys, create test room
# ==============================================================
echo "--- SETUP ---"

# 1. Register DM user
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE_URL/api/register" \
  -H "Content-Type: application/json" \
  -d "{\"username\": \"$DM_USER\", \"password\": \"$DM_PASS\"}")
check_http "200" "$STATUS" "Register DM user ($DM_USER)"

# 2. Create DM API key (credential-based)
BODY=$(curl -s -X POST "$BASE_URL/api/v1/auth/keys" \
  -H "Content-Type: application/json" \
  -d "{\"username\": \"$DM_USER\", \"password\": \"$DM_PASS\", \"role\": \"dm\"}")
DM_KEY=$(jq_field "$BODY" "d['data']['key']")
DM_KEY_ID=$(jq_field "$BODY" "d['data']['id']")
if [ -n "$DM_KEY" ]; then
    pass "Create DM API key (credential-based)"
    echo "    Key: $DM_KEY"
else
    fail "Create DM API key - aborting"
    echo "    Response: $BODY"
    exit 1
fi

# 3. Register player user
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE_URL/api/register" \
  -H "Content-Type: application/json" \
  -d "{\"username\": \"$PLAYER_USER\", \"password\": \"$PLAYER_PASS\"}")
check_http "200" "$STATUS" "Register player user ($PLAYER_USER)"

# 4. Create player API key (using DM key to create for another user)
BODY=$(curl -s -X POST "$BASE_URL/api/v1/auth/keys" \
  -H "X-API-Key: $DM_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"username\": \"$PLAYER_USER\", \"role\": \"player\"}")
PLAYER_KEY=$(jq_field "$BODY" "d['data']['key']")
if [ -n "$PLAYER_KEY" ]; then
    pass "Create player API key (via DM key)"
else
    fail "Create player API key"
    echo "    Response: $BODY"
fi

# 5. Get DM user ID from DB and create a test room
DM_USER_ID=$(sqlite3 "$DB_PATH" "SELECT id FROM user WHERE name='$DM_USER';")
[ -n "$DM_USER_ID" ] && pass "Get DM user ID: $DM_USER_ID" || { fail "Get DM user ID - aborting"; exit 1; }

ROOM_NAME="IntTest_Room_$TS"
# Create location_options entry first (required FK for room)
sqlite3 "$DB_PATH" "INSERT INTO location_options (spawn_locations) VALUES ('[]');"
LOC_OPT_ID=$(sqlite3 "$DB_PATH" "SELECT last_insert_rowid();")
sqlite3 "$DB_PATH" "INSERT INTO room (name, creator_id, invitation_code, is_locked, default_options_id, enable_chat, enable_dice) VALUES ('$ROOM_NAME', $DM_USER_ID, 'invite-$TS', 0, $LOC_OPT_ID, 1, 1);"
ROOM_ID=$(sqlite3 "$DB_PATH" "SELECT id FROM room WHERE name='$ROOM_NAME';")
[ -n "$ROOM_ID" ] && pass "Create test room via DB (room_id=$ROOM_ID)" || { fail "Create test room - aborting"; exit 1; }

echo ""

# ==============================================================
# AUTH ENDPOINT TESTS
# ==============================================================
echo "--- AUTH ---"

STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/api/v1/auth/keys")
check_http "401" "$STATUS" "No auth header → 401"

STATUS=$(curl -s -o /dev/null -w "%{http_code}" -H "X-API-Key: dm-invalid-key-xyz" "$BASE_URL/api/v1/auth/keys")
check_http "401" "$STATUS" "Invalid key → 401"

BODY=$(curl -s -H "X-API-Key: $DM_KEY" "$BASE_URL/api/v1/auth/keys")
KEY_COUNT=$(jq_field "$BODY" "len(d['data']['keys'])")
[ -n "$KEY_COUNT" ] && pass "List API keys → found $KEY_COUNT keys" || fail "List API keys failed"

# Player cannot list keys (DM-only)
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -H "X-API-Key: $PLAYER_KEY" "$BASE_URL/api/v1/auth/keys")
check_http "403" "$STATUS" "Player cannot list keys → 403"

# Wrong credentials
BODY=$(curl -s -X POST "$BASE_URL/api/v1/auth/keys" \
  -H "Content-Type: application/json" \
  -d "{\"username\": \"$DM_USER\", \"password\": \"wrongpassword\", \"role\": \"dm\"}")
SUCCESS=$(jq_field "$BODY" "str(d['success'])")
[ "$SUCCESS" = "False" ] && pass "Wrong credentials → rejected" || fail "Wrong credentials not rejected"

echo ""

# ==============================================================
# SCENE CRUD TESTS
# ==============================================================
echo "--- SCENES ---"

# Create scene
BODY=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/api/v1/scenes" \
  -H "X-API-Key: $DM_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"name\": \"IntTest Scene\", \"room_id\": $ROOM_ID}")
STATUS=$(echo "$BODY" | tail -1)
RESP=$(echo "$BODY" | head -n -1)
check_http "201" "$STATUS" "Create scene"
SCENE_UUID=$(jq_field "$RESP" "d['data']['uuid']")
[ -n "$SCENE_UUID" ] && pass "Scene UUID: $SCENE_UUID" || { fail "Get scene UUID - aborting"; echo "Response: $RESP"; exit 1; }

# List scenes - should include the new scene
BODY=$(curl -s -H "X-API-Key: $DM_KEY" "$BASE_URL/api/v1/scenes")
SCENE_COUNT=$(jq_field "$BODY" "len(d['data']['scenes'])")
[ "$SCENE_COUNT" -ge "1" ] 2>/dev/null && pass "List scenes → $SCENE_COUNT scene(s)" || fail "List scenes: expected ≥1, got $SCENE_COUNT"

# Get scene
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -H "X-API-Key: $DM_KEY" "$BASE_URL/api/v1/scenes/$SCENE_UUID")
check_http "200" "$STATUS" "Get scene by UUID"

# Update scene name
BODY=$(curl -s -w "\n%{http_code}" -X PUT "$BASE_URL/api/v1/scenes/$SCENE_UUID" \
  -H "X-API-Key: $DM_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name": "Updated IntTest Scene"}')
STATUS=$(echo "$BODY" | tail -1)
check_http "200" "$STATUS" "Update scene name"

# Verify name change
BODY=$(curl -s -H "X-API-Key: $DM_KEY" "$BASE_URL/api/v1/scenes/$SCENE_UUID")
SCENE_NAME=$(jq_field "$BODY" "d['data']['name']")
[ "$SCENE_NAME" = "Updated IntTest Scene" ] && pass "Scene name updated correctly" || fail "Scene name expected 'Updated IntTest Scene', got '$SCENE_NAME'"

# Get scene state (empty)
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -H "X-API-Key: $DM_KEY" "$BASE_URL/api/v1/scenes/$SCENE_UUID/state")
check_http "200" "$STATUS" "Get scene state (empty)"

# Non-existent scene
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -H "X-API-Key: $DM_KEY" "$BASE_URL/api/v1/scenes/99999")
check_http "404" "$STATUS" "Non-existent scene → 404"

# Invalid scene UUID (string)
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -H "X-API-Key: $DM_KEY" "$BASE_URL/api/v1/scenes/not-a-number")
check_http "404" "$STATUS" "String scene UUID → 404"

echo ""

# ==============================================================
# TOKEN CRUD TESTS
# ==============================================================
echo "--- TOKENS ---"

# Create Warrior token
BODY=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/api/v1/scenes/$SCENE_UUID/tokens" \
  -H "X-API-Key: $DM_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name": "Warrior", "x": 100, "y": 100, "hp": 45, "hp_max": 45, "ac": 18, "faction": "friendly"}')
STATUS=$(echo "$BODY" | tail -1)
RESP=$(echo "$BODY" | head -n -1)
check_http "201" "$STATUS" "Create Warrior token"
WARRIOR_UUID=$(jq_field "$RESP" "d['data']['uuid']")
[ -n "$WARRIOR_UUID" ] && pass "Warrior UUID: $WARRIOR_UUID" || { fail "Get Warrior UUID - aborting"; exit 1; }

# Create Rogue token
BODY=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/api/v1/scenes/$SCENE_UUID/tokens" \
  -H "X-API-Key: $DM_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name": "Rogue", "x": 200, "y": 100, "hp": 32, "hp_max": 32, "ac": 15, "faction": "friendly"}')
STATUS=$(echo "$BODY" | tail -1)
RESP=$(echo "$BODY" | head -n -1)
check_http "201" "$STATUS" "Create Rogue token"
ROGUE_UUID=$(jq_field "$RESP" "d['data']['uuid']")
[ -n "$ROGUE_UUID" ] && pass "Rogue UUID: $ROGUE_UUID" || { fail "Get Rogue UUID - aborting"; exit 1; }

# Create Goblin enemy
BODY=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/api/v1/scenes/$SCENE_UUID/tokens" \
  -H "X-API-Key: $DM_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name": "Goblin", "x": 500, "y": 300, "hp": 7, "hp_max": 7, "ac": 13, "faction": "hostile"}')
STATUS=$(echo "$BODY" | tail -1)
RESP=$(echo "$BODY" | head -n -1)
check_http "201" "$STATUS" "Create Goblin token"
GOBLIN_UUID=$(jq_field "$RESP" "d['data']['uuid']")
[ -n "$GOBLIN_UUID" ] && pass "Goblin UUID: $GOBLIN_UUID" || { fail "Get Goblin UUID - aborting"; exit 1; }

# List tokens - expect 3
BODY=$(curl -s -H "X-API-Key: $DM_KEY" "$BASE_URL/api/v1/scenes/$SCENE_UUID/tokens")
TOKEN_COUNT=$(jq_field "$BODY" "d['data']['count']")
[ "$TOKEN_COUNT" = "3" ] && pass "List tokens → count=3" || fail "Expected 3 tokens, got $TOKEN_COUNT"

# Get single token
BODY=$(curl -s -w "\n%{http_code}" -H "X-API-Key: $DM_KEY" "$BASE_URL/api/v1/tokens/$WARRIOR_UUID")
STATUS=$(echo "$BODY" | tail -1)
RESP=$(echo "$BODY" | head -n -1)
check_http "200" "$STATUS" "Get Warrior token"
WARRIOR_HP=$(jq_field "$RESP" "d['data']['hp']")
[ "$WARRIOR_HP" = "45" ] && pass "Warrior HP=45 (correct)" || fail "Expected HP=45, got $WARRIOR_HP"

# Update Warrior: reduce HP and add condition
BODY=$(curl -s -w "\n%{http_code}" -X PATCH "$BASE_URL/api/v1/tokens/$WARRIOR_UUID" \
  -H "X-API-Key: $DM_KEY" \
  -H "Content-Type: application/json" \
  -d '{"hp": 38, "conditions": ["prone"]}')
STATUS=$(echo "$BODY" | tail -1)
check_http "200" "$STATUS" "Update Warrior HP→38, add prone"

# Verify update
BODY=$(curl -s -H "X-API-Key: $DM_KEY" "$BASE_URL/api/v1/tokens/$WARRIOR_UUID")
HP=$(jq_field "$BODY" "d['data']['hp']")
[ "$HP" = "38" ] && pass "Warrior HP updated to 38" || fail "Expected HP=38, got $HP"

# 404 for non-existent token
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -H "X-API-Key: $DM_KEY" "$BASE_URL/api/v1/tokens/00000000-0000-0000-0000-000000000000")
check_http "404" "$STATUS" "Non-existent token → 404"

# Duplicate/missing fields validation
BODY=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/api/v1/scenes/$SCENE_UUID/tokens" \
  -H "X-API-Key: $DM_KEY" \
  -H "Content-Type: application/json" \
  -d '{"x": 0, "y": 0}')
STATUS=$(echo "$BODY" | tail -1)
check_http "400" "$STATUS" "Create token missing name → 400"

echo ""

# ==============================================================
# BATCH TOKEN OPERATIONS
# ==============================================================
echo "--- BATCH OPERATIONS ---"

# Batch create 2 enemy tokens
BODY=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/api/v1/scenes/$SCENE_UUID/tokens/batch" \
  -H "X-API-Key: $DM_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "operations": [
      {"op": "create", "data": {"name": "Orc", "x": 600, "y": 300, "hp": 15, "hp_max": 15, "ac": 14, "faction": "hostile"}},
      {"op": "create", "data": {"name": "Troll", "x": 700, "y": 300, "hp": 84, "hp_max": 84, "ac": 15, "faction": "hostile"}}
    ]
  }')
STATUS=$(echo "$BODY" | tail -1)
RESP=$(echo "$BODY" | head -n -1)
check_http "200" "$STATUS" "Batch create Orc + Troll"
SUCCESS_COUNT=$(jq_field "$RESP" "d['data']['success_count']")
[ "$SUCCESS_COUNT" = "2" ] && pass "Batch success_count=2" || fail "Expected success_count=2, got $SUCCESS_COUNT"
ORC_UUID=$(jq_field "$RESP" "[r for r in d['data']['results'] if r.get('status')=='ok'][0]['id']")
TROLL_UUID=$(jq_field "$RESP" "[r for r in d['data']['results'] if r.get('status')=='ok'][1]['id']")
[ -n "$ORC_UUID" ] && pass "Orc UUID: $ORC_UUID" || { fail "Get Orc UUID - aborting"; exit 1; }
[ -n "$TROLL_UUID" ] && pass "Troll UUID: $TROLL_UUID" || { fail "Get Troll UUID - aborting"; exit 1; }

# Verify token count is now 5
BODY=$(curl -s -H "X-API-Key: $DM_KEY" "$BASE_URL/api/v1/scenes/$SCENE_UUID/tokens")
TOKEN_COUNT=$(jq_field "$BODY" "d['data']['count']")
[ "$TOKEN_COUNT" = "5" ] && pass "Token count = 5 after batch" || fail "Expected 5 tokens, got $TOKEN_COUNT"

# Dry run test
BODY=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/api/v1/scenes/$SCENE_UUID/tokens/batch" \
  -H "X-API-Key: $DM_KEY" \
  -H "Content-Type: application/json" \
  -d '{"dry_run": true, "operations": [{"op": "create", "data": {"name": "DryRunToken", "x": 0, "y": 0, "hp": 1, "hp_max": 1, "ac": 10}}]}')
STATUS=$(echo "$BODY" | tail -1)
RESP=$(echo "$BODY" | head -n -1)
check_http "200" "$STATUS" "Batch dry_run mode"
IS_DRY=$(jq_field "$RESP" "str(d['data']['dry_run'])")
[ "$IS_DRY" = "True" ] && pass "dry_run=True confirmed" || fail "Expected dry_run=True, got $IS_DRY"

# Dry run should not add token - still 5
BODY=$(curl -s -H "X-API-Key: $DM_KEY" "$BASE_URL/api/v1/scenes/$SCENE_UUID/tokens")
TOKEN_COUNT=$(jq_field "$BODY" "d['data']['count']")
[ "$TOKEN_COUNT" = "5" ] && pass "Token count still 5 after dry_run" || fail "Expected 5 tokens after dry_run, got $TOKEN_COUNT"

# Batch update + delete
BODY=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/api/v1/scenes/$SCENE_UUID/tokens/batch" \
  -H "X-API-Key: $DM_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"operations\": [
    {\"op\": \"update\", \"id\": \"$ROGUE_UUID\", \"data\": {\"hp\": 28, \"name\": \"Shadow Rogue\"}}
  ]}")
STATUS=$(echo "$BODY" | tail -1)
RESP=$(echo "$BODY" | head -n -1)
check_http "200" "$STATUS" "Batch update Rogue name+HP"
SC=$(jq_field "$RESP" "d['data']['success_count']")
[ "$SC" = "1" ] && pass "Batch update success" || fail "Expected success_count=1, got $SC"

echo ""

# ==============================================================
# FOG OF WAR TESTS
# ==============================================================
echo "--- FOG OF WAR ---"

# Get empty fog state
BODY=$(curl -s -w "\n%{http_code}" -H "X-API-Key: $DM_KEY" "$BASE_URL/api/v1/scenes/$SCENE_UUID/fog")
STATUS=$(echo "$BODY" | tail -1)
RESP=$(echo "$BODY" | head -n -1)
check_http "200" "$STATUS" "Get fog state (initially empty)"
FOG_COUNT=$(jq_field "$RESP" "len(d['data']['fog_shapes'])")
[ "$FOG_COUNT" = "0" ] && pass "No fog shapes initially" || fail "Expected 0 fog shapes, got $FOG_COUNT"

# Reveal rectangle
BODY=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/api/v1/scenes/$SCENE_UUID/fog/reveal" \
  -H "X-API-Key: $DM_KEY" \
  -H "Content-Type: application/json" \
  -d '{"type": "rect", "x": 0, "y": 0, "width": 400, "height": 400}')
STATUS=$(echo "$BODY" | tail -1)
RESP=$(echo "$BODY" | head -n -1)
check_http "200" "$STATUS" "Reveal rectangular fog area"
FOG_RECT_UUID=$(jq_field "$RESP" "d['data']['shape_id']")
[ -n "$FOG_RECT_UUID" ] && pass "Fog rect shape_id: $FOG_RECT_UUID" || fail "Get fog rect shape_id"

# Reveal polygon
BODY=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/api/v1/scenes/$SCENE_UUID/fog/reveal" \
  -H "X-API-Key: $DM_KEY" \
  -H "Content-Type: application/json" \
  -d '{"type": "polygon", "vertices": [[400, 0], [700, 0], [700, 400], [400, 400]]}')
STATUS=$(echo "$BODY" | tail -1)
RESP=$(echo "$BODY" | head -n -1)
check_http "200" "$STATUS" "Reveal polygon fog area"
FOG_POLY_UUID=$(jq_field "$RESP" "d['data']['shape_id']")
[ -n "$FOG_POLY_UUID" ] && pass "Fog polygon shape_id: $FOG_POLY_UUID" || fail "Get fog polygon shape_id"

# Get fog state - should have 2 shapes
BODY=$(curl -s -H "X-API-Key: $DM_KEY" "$BASE_URL/api/v1/scenes/$SCENE_UUID/fog")
FOG_COUNT=$(jq_field "$BODY" "len(d['data']['fog_shapes'])")
[ "$FOG_COUNT" = "2" ] && pass "Fog count=2 after reveals" || fail "Expected 2 fog shapes, got $FOG_COUNT"

# Hide polygon shape
BODY=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/api/v1/scenes/$SCENE_UUID/fog/hide" \
  -H "X-API-Key: $DM_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"shape_id\": \"$FOG_POLY_UUID\"}")
STATUS=$(echo "$BODY" | tail -1)
check_http "200" "$STATUS" "Hide polygon fog shape"

# Verify fog count = 1
BODY=$(curl -s -H "X-API-Key: $DM_KEY" "$BASE_URL/api/v1/scenes/$SCENE_UUID/fog")
FOG_COUNT=$(jq_field "$BODY" "len(d['data']['fog_shapes'])")
[ "$FOG_COUNT" = "1" ] && pass "Fog count=1 after hide" || fail "Expected 1 fog shape, got $FOG_COUNT"

# Invalid fog type
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE_URL/api/v1/scenes/$SCENE_UUID/fog/reveal" \
  -H "X-API-Key: $DM_KEY" \
  -H "Content-Type: application/json" \
  -d '{"type": "circle", "x": 0, "y": 0}')
check_http "400" "$STATUS" "Invalid fog type → 400"

# Player cannot reveal fog (DM-only)
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE_URL/api/v1/scenes/$SCENE_UUID/fog/reveal" \
  -H "X-API-Key: $PLAYER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"type": "rect", "x": 0, "y": 0, "width": 100, "height": 100}')
check_http "403" "$STATUS" "Player cannot reveal fog → 403"

echo ""

# ==============================================================
# TOKEN VISION TESTS
# ==============================================================
echo "--- TOKEN VISION ---"

# Set vision
BODY=$(curl -s -w "\n%{http_code}" -X PATCH "$BASE_URL/api/v1/tokens/$WARRIOR_UUID/vision" \
  -H "X-API-Key: $DM_KEY" \
  -H "Content-Type: application/json" \
  -d '{"has_vision": true, "range": 60}')
STATUS=$(echo "$BODY" | tail -1)
check_http "200" "$STATUS" "Set Warrior vision (range=60)"

# Update vision
BODY=$(curl -s -w "\n%{http_code}" -X PATCH "$BASE_URL/api/v1/tokens/$WARRIOR_UUID/vision" \
  -H "X-API-Key: $DM_KEY" \
  -H "Content-Type: application/json" \
  -d '{"has_vision": true, "range": 30, "dim": 30}')
STATUS=$(echo "$BODY" | tail -1)
check_http "200" "$STATUS" "Update Warrior vision (range=30, dim=30)"

# Remove vision
BODY=$(curl -s -w "\n%{http_code}" -X PATCH "$BASE_URL/api/v1/tokens/$WARRIOR_UUID/vision" \
  -H "X-API-Key: $DM_KEY" \
  -H "Content-Type: application/json" \
  -d '{"has_vision": false}')
STATUS=$(echo "$BODY" | tail -1)
check_http "200" "$STATUS" "Remove Warrior vision"

echo ""

# ==============================================================
# DICE ROLL TESTS
# ==============================================================
echo "--- DICE ROLLS ---"

# Basic roll
BODY=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/api/v1/rolls" \
  -H "X-API-Key: $DM_KEY" \
  -H "Content-Type: application/json" \
  -d '{"notation": "1d20+5", "note": "Initiative roll"}')
STATUS=$(echo "$BODY" | tail -1)
RESP=$(echo "$BODY" | head -n -1)
check_http "201" "$STATUS" "Roll 1d20+5"
ROLL_UUID=$(jq_field "$RESP" "d['data']['uuid']")
ROLL_TOTAL=$(jq_field "$RESP" "d['data']['total']")
[ -n "$ROLL_UUID" ] && pass "Roll UUID obtained, total=$ROLL_TOTAL" || fail "Get roll UUID"

# Verify total in valid range (1d20+5 = 6 to 25)
if [ -n "$ROLL_TOTAL" ] && [ "$ROLL_TOTAL" -ge "6" ] 2>/dev/null && [ "$ROLL_TOTAL" -le "25" ] 2>/dev/null; then
    pass "Roll total $ROLL_TOTAL is in valid range [6,25]"
else
    fail "Roll total $ROLL_TOTAL not in valid range [6,25]"
fi

# Get roll by UUID
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -H "X-API-Key: $DM_KEY" "$BASE_URL/api/v1/rolls/$ROLL_UUID")
check_http "200" "$STATUS" "Get roll by UUID"

# Roll with advantage
BODY=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/api/v1/rolls" \
  -H "X-API-Key: $DM_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"notation\": \"1d20+3\", \"advantage\": true, \"scene_id\": $SCENE_UUID, \"actor_id\": \"$WARRIOR_UUID\", \"note\": \"Attack with advantage\"}")
STATUS=$(echo "$BODY" | tail -1)
check_http "201" "$STATUS" "Roll 1d20+3 with advantage"

# Roll with disadvantage
BODY=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/api/v1/rolls" \
  -H "X-API-Key: $DM_KEY" \
  -H "Content-Type: application/json" \
  -d '{"notation": "1d20", "disadvantage": true, "note": "Saving throw disadvantage"}')
STATUS=$(echo "$BODY" | tail -1)
check_http "201" "$STATUS" "Roll 1d20 with disadvantage"

# Secret roll (DM-only)
BODY=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/api/v1/rolls" \
  -H "X-API-Key: $DM_KEY" \
  -H "Content-Type: application/json" \
  -d '{"notation": "2d6+3", "secret": true, "note": "Secret monster damage"}')
STATUS=$(echo "$BODY" | tail -1)
check_http "201" "$STATUS" "Secret roll 2d6+3"

# Compound roll
BODY=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/api/v1/rolls" \
  -H "X-API-Key: $DM_KEY" \
  -H "Content-Type: application/json" \
  -d '{"notation": "2d8+1d6+4", "note": "Heavy attack roll"}')
STATUS=$(echo "$BODY" | tail -1)
RESP=$(echo "$BODY" | head -n -1)
check_http "201" "$STATUS" "Compound roll 2d8+1d6+4"
COMPOUND_TOTAL=$(jq_field "$RESP" "d['data']['total']")
[ -n "$COMPOUND_TOTAL" ] && [ "$COMPOUND_TOTAL" -ge "7" ] 2>/dev/null && pass "Compound roll total=$COMPOUND_TOTAL (≥7 min)" || fail "Compound roll total invalid: $COMPOUND_TOTAL"

# Keep highest (ability score roll)
BODY=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/api/v1/rolls" \
  -H "X-API-Key: $DM_KEY" \
  -H "Content-Type: application/json" \
  -d '{"notation": "4d6kh3", "note": "Ability score generation"}')
STATUS=$(echo "$BODY" | tail -1)
check_http "201" "$STATUS" "Roll 4d6kh3 (keep highest 3)"

# Invalid notation
BODY=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/api/v1/rolls" \
  -H "X-API-Key: $DM_KEY" \
  -H "Content-Type: application/json" \
  -d '{"notation": "not-valid-dice"}')
STATUS=$(echo "$BODY" | tail -1)
check_http "400" "$STATUS" "Invalid dice notation → 400"

# List rolls
BODY=$(curl -s -H "X-API-Key: $DM_KEY" "$BASE_URL/api/v1/rolls?limit=20")
ROLL_COUNT=$(jq_field "$BODY" "len(d['data']['rolls'])")
[ "$ROLL_COUNT" -ge "5" ] 2>/dev/null && pass "List rolls → $ROLL_COUNT rolls (≥5)" || fail "Expected ≥5 rolls, got $ROLL_COUNT"

# Player can roll dice
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE_URL/api/v1/rolls" \
  -H "X-API-Key: $PLAYER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"notation": "1d20", "note": "Player roll"}')
check_http "201" "$STATUS" "Player can roll dice → 201"

echo ""

# ==============================================================
# COMBAT TESTS
# ==============================================================
echo "--- COMBAT ---"

# No active combat before starting
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -H "X-API-Key: $DM_KEY" "$BASE_URL/api/v1/scenes/$SCENE_UUID/combats/active")
check_http "404" "$STATUS" "No active combat before start → 404"

# Start combat with 5 tokens
BODY=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/api/v1/scenes/$SCENE_UUID/combats" \
  -H "X-API-Key: $DM_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"combatants\": [
      {\"actor_id\": \"$WARRIOR_UUID\", \"initiative\": 18},
      {\"actor_id\": \"$ROGUE_UUID\", \"initiative\": 15},
      {\"actor_id\": \"$GOBLIN_UUID\", \"initiative\": 12},
      {\"actor_id\": \"$ORC_UUID\", \"initiative\": 8},
      {\"actor_id\": \"$TROLL_UUID\", \"initiative\": 5}
    ],
    \"auto_sort\": true
  }")
STATUS=$(echo "$BODY" | tail -1)
RESP=$(echo "$BODY" | head -n -1)
check_http "200" "$STATUS" "Start combat with 5 combatants"
COMBAT_UUID=$(jq_field "$RESP" "d['data']['uuid']")
[ -n "$COMBAT_UUID" ] && pass "Combat UUID: $COMBAT_UUID" || { fail "Get combat UUID - aborting"; echo "Response: $RESP"; exit 1; }

# Duplicate combat → 409
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE_URL/api/v1/scenes/$SCENE_UUID/combats" \
  -H "X-API-Key: $DM_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"combatants\": [{\"actor_id\": \"$WARRIOR_UUID\", \"initiative\": 10}]}")
check_http "409" "$STATUS" "Start duplicate combat → 409"

# Get active combat
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -H "X-API-Key: $DM_KEY" "$BASE_URL/api/v1/scenes/$SCENE_UUID/combats/active")
check_http "200" "$STATUS" "Get active combat"

# Get combat by UUID
BODY=$(curl -s -H "X-API-Key: $DM_KEY" "$BASE_URL/api/v1/combats/$COMBAT_UUID")
C_COUNT=$(jq_field "$BODY" "len(d['data']['combatants'])")
[ "$C_COUNT" = "5" ] && pass "Combat has 5 combatants" || fail "Expected 5 combatants, got $C_COUNT"

# Round info at start (round=0, turn=0)
BODY=$(curl -s -H "X-API-Key: $DM_KEY" "$BASE_URL/api/v1/combats/$COMBAT_UUID/round")
ROUND=$(jq_field "$BODY" "d['data']['round']")
TURN=$(jq_field "$BODY" "d['data']['turn']")
[ "$ROUND" = "0" ] && pass "Round=0 at combat start" || fail "Expected round=0, got $ROUND"
[ "$TURN" = "0" ] && pass "Turn=0 at combat start" || fail "Expected turn=0, got $TURN"

# Advance 3 turns
for i in 1 2 3; do
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X PATCH "$BASE_URL/api/v1/combats/$COMBAT_UUID/next" \
      -H "X-API-Key: $DM_KEY")
    check_http "200" "$STATUS" "Advance turn #$i"
done

# Verify turn=3 after 3 advances
BODY=$(curl -s -H "X-API-Key: $DM_KEY" "$BASE_URL/api/v1/combats/$COMBAT_UUID/round")
TURN=$(jq_field "$BODY" "d['data']['turn']")
[ "$TURN" = "3" ] && pass "Turn=3 after 3 advances" || fail "Expected turn=3, got $TURN"

# Advance 2 more turns (should wrap: turn 4→0, round 0→1)
for i in 4 5; do
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X PATCH "$BASE_URL/api/v1/combats/$COMBAT_UUID/next" \
      -H "X-API-Key: $DM_KEY")
    check_http "200" "$STATUS" "Advance turn #$i (wrap-around)"
done

BODY=$(curl -s -H "X-API-Key: $DM_KEY" "$BASE_URL/api/v1/combats/$COMBAT_UUID/round")
ROUND=$(jq_field "$BODY" "d['data']['round']")
TURN=$(jq_field "$BODY" "d['data']['turn']")
[ "$ROUND" = "1" ] && pass "Round=1 after wrap-around" || fail "Expected round=1, got $ROUND"
[ "$TURN" = "0" ] && pass "Turn=0 after wrap-around" || fail "Expected turn=0, got $TURN"

# Modify initiative
BODY=$(curl -s -w "\n%{http_code}" -X PATCH "$BASE_URL/api/v1/combats/$COMBAT_UUID/initiative" \
  -H "X-API-Key: $DM_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"actor_id\": \"$GOBLIN_UUID\", \"initiative\": 20}")
STATUS=$(echo "$BODY" | tail -1)
check_http "200" "$STATUS" "Modify Goblin initiative to 20"

# Remove combatant (Orc)
BODY=$(curl -s -w "\n%{http_code}" -X DELETE "$BASE_URL/api/v1/combats/$COMBAT_UUID/remove/$ORC_UUID" \
  -H "X-API-Key: $DM_KEY")
STATUS=$(echo "$BODY" | tail -1)
check_http "200" "$STATUS" "Remove Orc from combat"

# Verify combatant count dropped to 4
BODY=$(curl -s -H "X-API-Key: $DM_KEY" "$BASE_URL/api/v1/combats/$COMBAT_UUID")
C_COUNT=$(jq_field "$BODY" "len(d['data']['combatants'])")
[ "$C_COUNT" = "4" ] && pass "Combatants=4 after Orc removal" || fail "Expected 4 combatants, got $C_COUNT"

# Player cannot start combat
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE_URL/api/v1/scenes/$SCENE_UUID/combats" \
  -H "X-API-Key: $PLAYER_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"combatants\": [{\"actor_id\": \"$WARRIOR_UUID\", \"initiative\": 10}]}")
check_http "403" "$STATUS" "Player cannot start combat → 403"

echo ""

# ==============================================================
# QUICK COMMANDS
# ==============================================================
echo "--- QUICK COMMANDS ---"

# Damage Goblin (-5 HP: 7→2)
BODY=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/api/v1/quick/damage" \
  -H "X-API-Key: $DM_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"token_id\": \"$GOBLIN_UUID\", \"amount\": 5, \"note\": \"Warrior sword strike\"}")
STATUS=$(echo "$BODY" | tail -1)
RESP=$(echo "$BODY" | head -n -1)
check_http "200" "$STATUS" "Quick damage Goblin -5 HP"
NEW_HP=$(jq_field "$RESP" "d['data']['new_hp']")
[ "$NEW_HP" = "2" ] && pass "Goblin HP 7→2 (damage=5)" || fail "Expected Goblin HP=2, got $NEW_HP"

# Heal Warrior (+3 HP: 38→41)
BODY=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/api/v1/quick/heal" \
  -H "X-API-Key: $DM_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"token_id\": \"$WARRIOR_UUID\", \"amount\": 3, \"note\": \"Potion of Healing\"}")
STATUS=$(echo "$BODY" | tail -1)
RESP=$(echo "$BODY" | head -n -1)
check_http "200" "$STATUS" "Quick heal Warrior +3 HP"
NEW_HP=$(jq_field "$RESP" "d['data']['new_hp']")
[ "$NEW_HP" = "41" ] && pass "Warrior HP 38→41 (heal=3)" || fail "Expected Warrior HP=41, got $NEW_HP"

# Heal overcap test: Warrior has 41/45 HP, heal 100 → should cap at 45
BODY=$(curl -s -X POST "$BASE_URL/api/v1/quick/heal" \
  -H "X-API-Key: $DM_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"token_id\": \"$WARRIOR_UUID\", \"amount\": 100}")
NEW_HP=$(jq_field "$BODY" "d['data']['new_hp']")
[ "$NEW_HP" = "45" ] && pass "Heal overcap: Warrior capped at 45/45" || fail "Expected HP cap at 45, got $NEW_HP"

# Move Rogue
BODY=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/api/v1/quick/move" \
  -H "X-API-Key: $DM_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"token_id\": \"$ROGUE_UUID\", \"x\": 350, \"y\": 250, \"note\": \"Flanking move\"}")
STATUS=$(echo "$BODY" | tail -1)
RESP=$(echo "$BODY" | head -n -1)
check_http "200" "$STATUS" "Quick move Rogue to (350,250)"
NEW_X=$(jq_field "$RESP" "d['data']['new_position']['x']")
[ "$NEW_X" = "350" ] && pass "Rogue x=350 confirmed" || fail "Expected x=350, got $NEW_X"

# Add condition
BODY=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/api/v1/quick/condition" \
  -H "X-API-Key: $DM_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"token_id\": \"$WARRIOR_UUID\", \"condition\": \"frightened\", \"action\": \"add\"}")
STATUS=$(echo "$BODY" | tail -1)
RESP=$(echo "$BODY" | head -n -1)
check_http "200" "$STATUS" "Quick condition: add frightened to Warrior"
CONDITIONS=$(jq_field "$RESP" "str('frightened' in d['data']['conditions'])")
[ "$CONDITIONS" = "True" ] && pass "frightened in conditions" || fail "frightened not in conditions"

# Remove condition
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE_URL/api/v1/quick/condition" \
  -H "X-API-Key: $DM_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"token_id\": \"$WARRIOR_UUID\", \"condition\": \"frightened\", \"action\": \"remove\"}")
check_http "200" "$STATUS" "Quick condition: remove frightened"

# Invalid action
BODY=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/api/v1/quick/condition" \
  -H "X-API-Key: $DM_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"token_id\": \"$WARRIOR_UUID\", \"condition\": \"poisoned\", \"action\": \"toggle\"}")
STATUS=$(echo "$BODY" | tail -1)
check_http "400" "$STATUS" "Invalid condition action → 400"

# Kill Goblin (HP 2 → 0, remove from combat)
BODY=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/api/v1/quick/kill" \
  -H "X-API-Key: $DM_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"token_id\": \"$GOBLIN_UUID\", \"note\": \"Final blow from Warrior\"}")
STATUS=$(echo "$BODY" | tail -1)
RESP=$(echo "$BODY" | head -n -1)
check_http "200" "$STATUS" "Quick kill Goblin"
OLD_HP=$(jq_field "$RESP" "d['data']['old_hp']")
REMOVED=$(jq_field "$RESP" "str(d['data']['removed_from_combat'])")
[ "$OLD_HP" = "2" ] && pass "Goblin old_hp=2 confirmed" || fail "Expected old_hp=2, got $OLD_HP"
[ "$REMOVED" = "True" ] && pass "Goblin removed_from_combat=True" || fail "Expected removed_from_combat=True, got $REMOVED"

# Player cannot use quick commands
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE_URL/api/v1/quick/damage" \
  -H "X-API-Key: $PLAYER_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"token_id\": \"$WARRIOR_UUID\", \"amount\": 5}")
check_http "403" "$STATUS" "Player cannot use quick/damage → 403"

echo ""

# ==============================================================
# ACTION DECLARATIONS
# ==============================================================
echo "--- ACTIONS ---"

# Player cannot submit actions without owning the token
# (They need to be a PlayerRoom member, and own the token)
# DM submitting action for Warrior
BODY=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/api/v1/scenes/$SCENE_UUID/actions" \
  -H "X-API-Key: $DM_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"actor_id\": \"$WARRIOR_UUID\",
    \"action_type\": \"attack\",
    \"description\": \"Warrior attacks Troll with longsword\",
    \"targets\": [{\"uuid\": \"$TROLL_UUID\", \"type\": \"enemy\"}]
  }")
STATUS=$(echo "$BODY" | tail -1)
RESP=$(echo "$BODY" | head -n -1)
check_http "200" "$STATUS" "Submit attack action"
ACTION_UUID=$(jq_field "$RESP" "d['data']['uuid']")
[ -n "$ACTION_UUID" ] && pass "Action UUID: $ACTION_UUID" || fail "Get action UUID"

# List actions
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -H "X-API-Key: $DM_KEY" "$BASE_URL/api/v1/scenes/$SCENE_UUID/actions")
check_http "200" "$STATUS" "List actions"

# Get action by UUID
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -H "X-API-Key: $DM_KEY" "$BASE_URL/api/v1/actions/$ACTION_UUID")
check_http "200" "$STATUS" "Get action by UUID"

# List pending actions filter
BODY=$(curl -s -H "X-API-Key: $DM_KEY" "$BASE_URL/api/v1/scenes/$SCENE_UUID/actions?status=pending")
PENDING_COUNT=$(jq_field "$BODY" "len(d['data']['actions'])")
[ "$PENDING_COUNT" -ge "1" ] 2>/dev/null && pass "Pending actions ≥1" || fail "Expected ≥1 pending actions, got $PENDING_COUNT"

# Accept action
BODY=$(curl -s -w "\n%{http_code}" -X PATCH "$BASE_URL/api/v1/actions/$ACTION_UUID" \
  -H "X-API-Key: $DM_KEY" \
  -H "Content-Type: application/json" \
  -d '{"status": "accepted", "dm_note": "Great tactical choice!"}')
STATUS=$(echo "$BODY" | tail -1)
check_http "200" "$STATUS" "Review action - accept"

# Submit another action for rejection
BODY=$(curl -s -X POST "$BASE_URL/api/v1/scenes/$SCENE_UUID/actions" \
  -H "X-API-Key: $DM_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"actor_id\": \"$ROGUE_UUID\", \"action_type\": \"spell\", \"description\": \"Rogue tries to cast Fireball\"}")
ACTION2_UUID=$(jq_field "$BODY" "d['data']['uuid']")
if [ -n "$ACTION2_UUID" ]; then
    BODY=$(curl -s -w "\n%{http_code}" -X PATCH "$BASE_URL/api/v1/actions/$ACTION2_UUID" \
      -H "X-API-Key: $DM_KEY" \
      -H "Content-Type: application/json" \
      -d '{"status": "rejected", "dm_note": "Rogues cannot cast Fireball!"}')
    STATUS=$(echo "$BODY" | tail -1)
    check_http "200" "$STATUS" "Review action - reject"
fi

# Invalid status
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X PATCH "$BASE_URL/api/v1/actions/$ACTION_UUID" \
  -H "X-API-Key: $DM_KEY" \
  -H "Content-Type: application/json" \
  -d '{"status": "invalid_status"}')
check_http "400" "$STATUS" "Invalid action status → 400"

# Player cannot review actions
if [ -n "$ACTION_UUID" ]; then
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X PATCH "$BASE_URL/api/v1/actions/$ACTION_UUID" \
      -H "X-API-Key: $PLAYER_KEY" \
      -H "Content-Type: application/json" \
      -d '{"status": "accepted"}')
    check_http "403" "$STATUS" "Player cannot review actions → 403"
fi

echo ""

# ==============================================================
# PLAYER MANAGEMENT
# ==============================================================
echo "--- PLAYERS ---"

# List players (none connected)
BODY=$(curl -s -w "\n%{http_code}" -H "X-API-Key: $DM_KEY" "$BASE_URL/api/v1/players")
STATUS=$(echo "$BODY" | tail -1)
RESP=$(echo "$BODY" | head -n -1)
check_http "200" "$STATUS" "List players"
ONLINE_COUNT=$(jq_field "$RESP" "d['data']['online_count']")
echo "    Online players: $ONLINE_COUNT (expect 0 in automated test)"

# Get player tokens by user ID
BODY=$(curl -s -w "\n%{http_code}" -H "X-API-Key: $DM_KEY" "$BASE_URL/api/v1/players/$DM_USER_ID/tokens")
STATUS=$(echo "$BODY" | tail -1)
check_http "200" "$STATUS" "Get DM player tokens"

# Send message (offline → delivered=false)
BODY=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/api/v1/players/$DM_USER_ID/message" \
  -H "X-API-Key: $DM_KEY" \
  -H "Content-Type: application/json" \
  -d '{"text": "Your turn is coming up!", "private": false}')
STATUS=$(echo "$BODY" | tail -1)
RESP=$(echo "$BODY" | head -n -1)
check_http "200" "$STATUS" "Send message to offline player"
DELIVERED=$(jq_field "$RESP" "str(d['data']['delivered'])")
[ "$DELIVERED" = "False" ] && pass "delivered=False (offline player)" || fail "Expected delivered=False, got $DELIVERED"

echo ""

# ==============================================================
# EVENT LOG
# ==============================================================
echo "--- EVENTS ---"

# Query all events
BODY=$(curl -s -H "X-API-Key: $DM_KEY" "$BASE_URL/api/v1/events?limit=100")
ALL_EVENTS=$(jq_field "$BODY" "len(d['data']['events'])")
echo "    Total events logged: $ALL_EVENTS"
[ "$ALL_EVENTS" -ge "20" ] 2>/dev/null && pass "Events logged ≥20 (good coverage)" || fail "Expected ≥20 events, got $ALL_EVENTS"

# Filter by scene
BODY=$(curl -s -H "X-API-Key: $DM_KEY" "$BASE_URL/api/v1/events?scene_id=$SCENE_UUID&limit=50")
SCENE_EVENTS=$(jq_field "$BODY" "len(d['data']['events'])")
echo "    Scene events: $SCENE_EVENTS"
[ "$SCENE_EVENTS" -ge "5" ] 2>/dev/null && pass "Scene events ≥5" || fail "Expected ≥5 scene events, got $SCENE_EVENTS"

# Filter by type
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -H "X-API-Key: $DM_KEY" "$BASE_URL/api/v1/events?type=damage_applied")
check_http "200" "$STATUS" "Filter events by type=damage_applied"

# Create DM note
BODY=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/api/v1/events/note" \
  -H "X-API-Key: $DM_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"text\": \"Session notes: Warrior nearly died fighting Troll\", \"scene_id\": $SCENE_UUID}")
STATUS=$(echo "$BODY" | tail -1)
check_http "201" "$STATUS" "Create DM note"

# Player can query events
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -H "X-API-Key: $PLAYER_KEY" "$BASE_URL/api/v1/events?limit=5")
check_http "200" "$STATUS" "Player can query events"

# Player cannot create DM notes
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE_URL/api/v1/events/note" \
  -H "X-API-Key: $PLAYER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"text": "Player note attempt"}')
check_http "403" "$STATUS" "Player cannot create DM notes → 403"

# Export as JSON
BODY=$(curl -s -w "\n%{http_code}" -H "X-API-Key: $DM_KEY" "$BASE_URL/api/v1/events/export?format=json")
STATUS=$(echo "$BODY" | tail -1)
RESP=$(echo "$BODY" | head -n -1)
check_http "200" "$STATUS" "Export events as JSON"
EXPORTED=$(jq_field "$RESP" "d['exported_events']")
echo "    Exported events: $EXPORTED"

# Export as TXT
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -H "X-API-Key: $DM_KEY" "$BASE_URL/api/v1/events/export?format=txt")
check_http "200" "$STATUS" "Export events as TXT"

# Export filtered by scene
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -H "X-API-Key: $DM_KEY" "$BASE_URL/api/v1/events/export?format=json&scene_id=$SCENE_UUID")
check_http "200" "$STATUS" "Export events filtered by scene"

# Export invalid format
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -H "X-API-Key: $DM_KEY" "$BASE_URL/api/v1/events/export?format=csv")
check_http "400" "$STATUS" "Export invalid format → 400"

# SSE stream - brief connection test
echo "    Testing SSE stream (3s timeout)..."
SSE_DATA=$(timeout 3 curl -s -N -H "X-API-Key: $DM_KEY" "$BASE_URL/api/v1/events/stream" 2>/dev/null | head -c 200)
if echo "$SSE_DATA" | grep -q "data:\|keepalive" 2>/dev/null; then
    pass "SSE stream connected and receiving data"
else
    # Try once more - just check if we can connect
    SSE_STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 2 -H "X-API-Key: $DM_KEY" "$BASE_URL/api/v1/events/stream" 2>/dev/null)
    [ "$SSE_STATUS" = "200" ] && pass "SSE stream endpoint responds 200" || fail "SSE stream connection failed (HTTP $SSE_STATUS)"
fi

echo ""

# ==============================================================
# SCENE SNAPSHOTS
# ==============================================================
echo "--- SCENE SNAPSHOTS ---"

# Create snapshot
BODY=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/api/v1/scenes/$SCENE_UUID/snapshot" \
  -H "X-API-Key: $DM_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name": "After Round 1"}')
STATUS=$(echo "$BODY" | tail -1)
RESP=$(echo "$BODY" | head -n -1)
check_http "201" "$STATUS" "Create scene snapshot"
SNAP_UUID=$(jq_field "$RESP" "d['data']['uuid']")
SNAP_TOKEN_COUNT=$(jq_field "$RESP" "d['data']['token_count']")
[ -n "$SNAP_UUID" ] && pass "Snapshot UUID: $SNAP_UUID (tokens=$SNAP_TOKEN_COUNT)" || fail "Get snapshot UUID"

# List snapshots
BODY=$(curl -s -H "X-API-Key: $DM_KEY" "$BASE_URL/api/v1/scenes/$SCENE_UUID/snapshots")
SNAP_COUNT=$(jq_field "$BODY" "d['data']['count']")
[ "$SNAP_COUNT" = "1" ] && pass "Snapshot count=1" || fail "Expected 1 snapshot, got $SNAP_COUNT"

# Delete Troll token (snapshot should restore it)
curl -s -o /dev/null -X DELETE "$BASE_URL/api/v1/tokens/$TROLL_UUID" -H "X-API-Key: $DM_KEY"
BODY=$(curl -s -H "X-API-Key: $DM_KEY" "$BASE_URL/api/v1/scenes/$SCENE_UUID/tokens")
BEFORE_RESTORE=$(jq_field "$BODY" "d['data']['count']")
echo "    Token count before restore: $BEFORE_RESTORE"

# Restore snapshot
BODY=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/api/v1/scenes/$SCENE_UUID/restore/$SNAP_UUID" \
  -H "X-API-Key: $DM_KEY")
STATUS=$(echo "$BODY" | tail -1)
RESP=$(echo "$BODY" | head -n -1)
check_http "200" "$STATUS" "Restore scene snapshot"
TOKENS_RESTORED=$(jq_field "$RESP" "d['data']['tokens_restored']")
echo "    Tokens restored: $TOKENS_RESTORED"

# Verify tokens after restore
BODY=$(curl -s -H "X-API-Key: $DM_KEY" "$BASE_URL/api/v1/scenes/$SCENE_UUID/tokens")
AFTER_RESTORE=$(jq_field "$BODY" "d['data']['count']")
[ "$AFTER_RESTORE" = "$SNAP_TOKEN_COUNT" ] && pass "Token count restored to $AFTER_RESTORE" || fail "Expected $SNAP_TOKEN_COUNT tokens, got $AFTER_RESTORE"

# Non-existent snapshot
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE_URL/api/v1/scenes/$SCENE_UUID/restore/00000000-0000-0000-0000-000000000000" \
  -H "X-API-Key: $DM_KEY")
check_http "404" "$STATUS" "Non-existent snapshot → 404"

echo ""

# ==============================================================
# COMBAT END
# ==============================================================
echo "--- END COMBAT ---"

# End combat
BODY=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/api/v1/combats/$COMBAT_UUID/end" \
  -H "X-API-Key: $DM_KEY")
STATUS=$(echo "$BODY" | tail -1)
check_http "200" "$STATUS" "End combat"

# No active combat after end
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -H "X-API-Key: $DM_KEY" "$BASE_URL/api/v1/scenes/$SCENE_UUID/combats/active")
check_http "404" "$STATUS" "No active combat after end → 404"

# Advance turn fails (combat ended)
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X PATCH "$BASE_URL/api/v1/combats/$COMBAT_UUID/next" \
  -H "X-API-Key: $DM_KEY")
check_http "400" "$STATUS" "Advance turn after end → 400 (combat inactive)"

echo ""

# ==============================================================
# AUTH KEY MANAGEMENT
# ==============================================================
echo "--- KEY MANAGEMENT ---"

# Create temporary key to revoke
BODY=$(curl -s -X POST "$BASE_URL/api/v1/auth/keys" \
  -H "X-API-Key: $DM_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"username\": \"$DM_USER\", \"role\": \"player\"}")
TEMP_KEY_UUID=$(jq_field "$BODY" "d['data']['id']")
TEMP_KEY_VAL=$(jq_field "$BODY" "d['data']['key']")
if [ -n "$TEMP_KEY_UUID" ]; then
    # Verify temp key works
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" -H "X-API-Key: $TEMP_KEY_VAL" "$BASE_URL/api/v1/test/player")
    check_http "200" "$STATUS" "Temporary key works before revoke"

    # Revoke it
    BODY=$(curl -s -w "\n%{http_code}" -X DELETE "$BASE_URL/api/v1/auth/keys/$TEMP_KEY_UUID" \
      -H "X-API-Key: $DM_KEY")
    STATUS=$(echo "$BODY" | tail -1)
    check_http "200" "$STATUS" "Revoke temporary key"

    # Verify it no longer works
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" -H "X-API-Key: $TEMP_KEY_VAL" "$BASE_URL/api/v1/test/player")
    check_http "401" "$STATUS" "Revoked key → 401"
fi

# Revoke non-existent key
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X DELETE "$BASE_URL/api/v1/auth/keys/00000000-0000-0000-0000-000000000000" \
  -H "X-API-Key: $DM_KEY")
check_http "404" "$STATUS" "Revoke non-existent key → 404"

echo ""

# ==============================================================
# CLEANUP
# ==============================================================
echo "--- CLEANUP ---"

# Delete test scene
BODY=$(curl -s -w "\n%{http_code}" -X DELETE "$BASE_URL/api/v1/scenes/$SCENE_UUID" \
  -H "X-API-Key: $DM_KEY")
STATUS=$(echo "$BODY" | tail -1)
check_http "200" "$STATUS" "Delete test scene"

# Verify scene deleted
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -H "X-API-Key: $DM_KEY" "$BASE_URL/api/v1/scenes/$SCENE_UUID")
check_http "404" "$STATUS" "Deleted scene → 404"

# Clean up DB
sqlite3 "$DB_PATH" "DELETE FROM room WHERE name='$ROOM_NAME';"
pass "Cleaned up test room from DB"

# Revoke test keys
curl -s -o /dev/null -X DELETE "$BASE_URL/api/v1/auth/keys/$DM_KEY_ID" -H "X-API-Key: $DM_KEY" 2>/dev/null || true
sqlite3 "$DB_PATH" "DELETE FROM api_key WHERE user_id IN (SELECT id FROM user WHERE name='$DM_USER' OR name='$PLAYER_USER');"
sqlite3 "$DB_PATH" "DELETE FROM user WHERE name='$DM_USER' OR name='$PLAYER_USER';"
pass "Cleaned up test users and keys"

echo ""

# ==============================================================
# FINAL SUMMARY
# ==============================================================
echo "============================================================"
echo "RESULTS: $PASS passed, $FAIL failed, $TOTAL total"
echo "============================================================"
if [ $FAIL -eq 0 ]; then
    echo -e "${GREEN}✅ All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}❌ $FAIL test(s) failed${NC}"
    exit 1
fi
