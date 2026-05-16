#!/bin/bash
# Phase 21 RBAC Verification Smoke Test
# All tests should PASS

DM_RESP=$(curl -s -X POST http://localhost:8000/api/v1/auth/keys \
  -H "Content-Type: application/json" \
  -d "{\"username\": \"smoketest_vision\", \"password\": \"test123\", \"role\": \"dm\"}")
DM_KEY=$(echo "$DM_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['data']['key'] if d.get('success') else 'ERR:'+str(d))")

PLAYER_RESP=$(curl -s -X POST http://localhost:8000/api/v1/auth/keys \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $DM_KEY" \
  -d "{\"username\": \"rbactest\", \"role\": \"player\"}")
PLAYER_KEY=$(echo "$PLAYER_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['data']['key'] if d.get('success') else 'ERR:'+str(d))")

SCENE_UUID="2"
PASS=0
FAIL=0

check() {
  local label="$1"
  local expected="$2"
  local actual="$3"
  if [ "$actual" = "$expected" ]; then
    echo "PASS: $label (got $actual)"
    PASS=$((PASS+1))
  else
    echo "FAIL: $label (expected $expected, got $actual)"
    FAIL=$((FAIL+1))
  fi
}

echo "=== Setup ==="
echo "DM Key: $DM_KEY"
echo "Player Key: $PLAYER_KEY"

echo ""
echo "=== Baseline Tests ==="
check "no-auth->401" "401" "$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/v1/scenes)"
check "dm-auth->200" "200" "$(curl -s -o /dev/null -w "%{http_code}" -H "X-API-Key: $DM_KEY" http://localhost:8000/api/v1/auth/keys)"
check "dm-list-scenes->200" "200" "$(curl -s -o /dev/null -w "%{http_code}" -H "X-API-Key: $DM_KEY" http://localhost:8000/api/v1/scenes)"

echo ""
echo "=== DM-Only Endpoints (player should get 403) ==="

check "player-CANNOT-start-combat->403" "403" "$(curl -s -o /dev/null -w "%{http_code}" -X POST "http://localhost:8000/api/v1/scenes/${SCENE_UUID}/combats" -H "Content-Type: application/json" -H "X-API-Key: $PLAYER_KEY" -d '{"combatants":[]}')"

check "player-CANNOT-review-action->403" "403" "$(curl -s -o /dev/null -w "%{http_code}" -X PATCH http://localhost:8000/api/v1/actions/dummy-uuid -H "Content-Type: application/json" -H "X-API-Key: $PLAYER_KEY" -d '{"status":"accepted"}')"

check "player-CANNOT-quick-damage->403" "403" "$(curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8000/api/v1/quick/damage -H "Content-Type: application/json" -H "X-API-Key: $PLAYER_KEY" -d '{"token_id":"x","amount":5}')"

check "player-CANNOT-quick-heal->403" "403" "$(curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8000/api/v1/quick/heal -H "Content-Type: application/json" -H "X-API-Key: $PLAYER_KEY" -d '{"token_id":"x","amount":3}')"

check "player-CANNOT-quick-move->403" "403" "$(curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8000/api/v1/quick/move -H "Content-Type: application/json" -H "X-API-Key: $PLAYER_KEY" -d '{"token_id":"x","x":0,"y":0}')"

check "player-CANNOT-quick-condition->403" "403" "$(curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8000/api/v1/quick/condition -H "Content-Type: application/json" -H "X-API-Key: $PLAYER_KEY" -d '{"token_id":"x","condition":"poisoned"}')"

check "player-CANNOT-quick-kill->403" "403" "$(curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8000/api/v1/quick/kill -H "Content-Type: application/json" -H "X-API-Key: $PLAYER_KEY" -d '{"token_id":"x"}')"

check "player-CANNOT-fog-reveal->403" "403" "$(curl -s -o /dev/null -w "%{http_code}" -X POST "http://localhost:8000/api/v1/scenes/${SCENE_UUID}/fog/reveal" -H "Content-Type: application/json" -H "X-API-Key: $PLAYER_KEY" -d '{"type":"rect","x":0,"y":0,"width":100,"height":100}')"

check "player-CANNOT-fog-hide->403" "403" "$(curl -s -o /dev/null -w "%{http_code}" -X POST "http://localhost:8000/api/v1/scenes/${SCENE_UUID}/fog/hide" -H "Content-Type: application/json" -H "X-API-Key: $PLAYER_KEY" -d '{"shape_id":"dummy"}')"

check "player-CANNOT-create-scene->403" "403" "$(curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8000/api/v1/scenes -H "Content-Type: application/json" -H "X-API-Key: $PLAYER_KEY" -d '{"name":"Test","room_id":1}')"

check "player-CANNOT-delete-scene->403" "403" "$(curl -s -o /dev/null -w "%{http_code}" -X DELETE "http://localhost:8000/api/v1/scenes/${SCENE_UUID}" -H "X-API-Key: $PLAYER_KEY")"

check "player-CANNOT-create-token->403" "403" "$(curl -s -o /dev/null -w "%{http_code}" -X POST "http://localhost:8000/api/v1/scenes/${SCENE_UUID}/tokens" -H "Content-Type: application/json" -H "X-API-Key: $PLAYER_KEY" -d '{"name":"Tok","x":100,"y":100,"hp":10,"hp_max":10,"ac":12}')"

check "player-CANNOT-list-keys->403" "403" "$(curl -s -o /dev/null -w "%{http_code}" -H "X-API-Key: $PLAYER_KEY" http://localhost:8000/api/v1/auth/keys)"

check "player-CANNOT-create-note->403" "403" "$(curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8000/api/v1/events/note -H "Content-Type: application/json" -H "X-API-Key: $PLAYER_KEY" -d '{"note":"test"}')"

check "player-CANNOT-advance-combat->403" "403" "$(curl -s -o /dev/null -w "%{http_code}" -X PATCH http://localhost:8000/api/v1/combats/dummy/next -H "X-API-Key: $PLAYER_KEY")"

# DM-only scene management
check "player-CANNOT-update-scene->403" "403" "$(curl -s -o /dev/null -w "%{http_code}" -X PUT "http://localhost:8000/api/v1/scenes/${SCENE_UUID}" -H "Content-Type: application/json" -H "X-API-Key: $PLAYER_KEY" -d '{"name":"Hacked"}')"

echo ""
echo "=== DM+Player Endpoints (player should succeed) ==="

check "player-CAN-GET-rolls->200" "200" "$(curl -s -o /dev/null -w "%{http_code}" -H "X-API-Key: $PLAYER_KEY" http://localhost:8000/api/v1/rolls)"

# POST /rolls - use python to create proper JSON
ROLL_CODE=$(python3 -c "
import urllib.request, json, sys
req = urllib.request.Request(
    'http://localhost:8000/api/v1/rolls',
    data=json.dumps({'notation': '1d20'}).encode(),
    headers={'Content-Type': 'application/json', 'X-API-Key': '${PLAYER_KEY}'},
    method='POST'
)
try:
    resp = urllib.request.urlopen(req)
    print(resp.status)
except urllib.error.HTTPError as e:
    print(e.code)
")
check "player-CAN-POST-rolls->201" "201" "$ROLL_CODE"

check "player-CAN-GET-events->200" "200" "$(curl -s -o /dev/null -w "%{http_code}" -H "X-API-Key: $PLAYER_KEY" http://localhost:8000/api/v1/events)"

check "player-CAN-export-events->200" "200" "$(curl -s -o /dev/null -w "%{http_code}" -H "X-API-Key: $PLAYER_KEY" "http://localhost:8000/api/v1/events/export?format=json")"

# GET /scenes is DM only (players don't list scenes, they join rooms)
check "player-CANNOT-list-scenes->403" "403" "$(curl -s -o /dev/null -w "%{http_code}" -H "X-API-Key: $PLAYER_KEY" http://localhost:8000/api/v1/scenes)"

# GET /scenes/{uuid}/state - player access to scenes (allowed)
check "player-CAN-GET-scene-state->200" "200" "$(curl -s -o /dev/null -w "%{http_code}" -H "X-API-Key: $PLAYER_KEY" "http://localhost:8000/api/v1/scenes/${SCENE_UUID}/state")"

# GET /scenes/{uuid}/actions - player can list (sees only their own actions)
# rbactest is not in room 1, but the endpoint should succeed (empty list or 403 at scene access level)
ACTIONS_CODE=$(curl -s -o /dev/null -w "%{http_code}" -H "X-API-Key: $PLAYER_KEY" "http://localhost:8000/api/v1/scenes/${SCENE_UUID}/actions")
if [ "$ACTIONS_CODE" != "500" ]; then
  echo "PASS: player-GET-actions-no-500 (got $ACTIONS_CODE - no server error)"
  PASS=$((PASS+1))
else
  echo "FAIL: player-GET-actions-no-500 (got 500 - server error)"
  FAIL=$((FAIL+1))
fi

# POST /scenes/{uuid}/actions - player can submit (RBAC allows, resource validation determines result)
SUBMIT_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "http://localhost:8000/api/v1/scenes/${SCENE_UUID}/actions" \
  -H "Content-Type: application/json" -H "X-API-Key: $PLAYER_KEY" \
  -d '{"actor_id":"non-existent","action_type":"attack"}')
if [ "$SUBMIT_CODE" != "403" ]; then
  echo "PASS: player-submit-action-RBAC-ok (got $SUBMIT_CODE - RBAC allows players to submit)"
  PASS=$((PASS+1))
else
  echo "FAIL: player-submit-action-RBAC-ok (got 403 - should be allowed by RBAC)"
  FAIL=$((FAIL+1))
fi

# GET /scenes/{uuid}/tokens - player CANNOT access tokens in scenes they haven't joined
# (scene-level PlayerRoom membership check, not RBAC decorator - this is correct behavior)
check "player-CANNOT-GET-tokens-in-unjoined-scene->403" "403" "$(curl -s -o /dev/null -w "%{http_code}" -H "X-API-Key: $PLAYER_KEY" "http://localhost:8000/api/v1/scenes/${SCENE_UUID}/tokens")"

echo ""
echo "=== Results ==="
echo "PASS: $PASS  FAIL: $FAIL  TOTAL: $((PASS+FAIL))"
