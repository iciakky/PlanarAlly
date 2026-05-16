#!/bin/bash
# Quick test of actions endpoint

DM_RESP=$(curl -s -X POST http://localhost:8000/api/v1/auth/keys \
  -H "Content-Type: application/json" \
  -d "{\"username\": \"smoketest_vision\", \"password\": \"test123\", \"role\": \"dm\"}")
DM_KEY=$(echo "$DM_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['data']['key'] if d.get('success') else 'ERR:'+str(d))")
echo "DM Key: $DM_KEY"

echo ""
echo "Scene 2 actions (DM):"
curl -s -H "X-API-Key: $DM_KEY" "http://localhost:8000/api/v1/scenes/2/actions"

echo ""
echo "Scene 3 actions (DM):"
curl -s -H "X-API-Key: $DM_KEY" "http://localhost:8000/api/v1/scenes/3/actions"

PLAYER_RESP=$(curl -s -X POST http://localhost:8000/api/v1/auth/keys \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $DM_KEY" \
  -d "{\"username\": \"rbactest\", \"role\": \"player\"}")
PLAYER_KEY=$(echo "$PLAYER_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['data']['key'] if d.get('success') else 'ERR:'+str(d))")
echo ""
echo "Player Key: $PLAYER_KEY"

echo ""
echo "Scene 2 actions (Player - expects 403 or 200 with empty list):"
curl -s -H "X-API-Key: $PLAYER_KEY" "http://localhost:8000/api/v1/scenes/2/actions"
