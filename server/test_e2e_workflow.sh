#!/bin/bash
# E2E Integration Test for PlanarAlly REST API
# Tests complete workflow from user registration to REST API usage

set -e  # Exit on error

# Configuration
API_URL="http://localhost:8000"
USERNAME="testdm_$(date +%s)"  # Unique username with timestamp
PASSWORD="test123"
ROLE="dm"

echo "========================================="
echo "PlanarAlly REST API - E2E Test"
echo "========================================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Step 1: Register user via PA's existing endpoint
echo -e "${YELLOW}[Step 1] Registering user: $USERNAME${NC}"
REGISTER_RESPONSE=$(curl -s -X POST "$API_URL/api/register" \
  -H "Content-Type: application/json" \
  -d "{\"username\": \"$USERNAME\", \"password\": \"$PASSWORD\"}" \
  -w "\n%{http_code}")

HTTP_CODE=$(echo "$REGISTER_RESPONSE" | tail -n1)
REGISTER_BODY=$(echo "$REGISTER_RESPONSE" | head -n-1)

if [ "$HTTP_CODE" != "200" ]; then
    echo -e "${RED}❌ Failed to register user (HTTP $HTTP_CODE)${NC}"
    echo "$REGISTER_BODY"
    exit 1
fi

echo -e "${GREEN}✓ User registered successfully${NC}"
echo ""

# Step 2: Create API key with credentials (NEW feature from Phase 11.5)
echo -e "${YELLOW}[Step 2] Creating API key with credentials${NC}"
KEY_RESPONSE=$(curl -s -X POST "$API_URL/api/v1/auth/keys" \
  -H "Content-Type: application/json" \
  -d "{\"username\": \"$USERNAME\", \"password\": \"$PASSWORD\", \"role\": \"$ROLE\"}" \
  -w "\n%{http_code}")

HTTP_CODE=$(echo "$KEY_RESPONSE" | tail -n1)
KEY_BODY=$(echo "$KEY_RESPONSE" | head -n-1)

if [ "$HTTP_CODE" != "201" ]; then
    echo -e "${RED}❌ Failed to create API key (HTTP $HTTP_CODE)${NC}"
    echo "$KEY_BODY"
    exit 1
fi

# Extract API key from response
API_KEY=$(echo "$KEY_BODY" | grep -o '"key": "[^"]*"' | cut -d'"' -f4)

if [ -z "$API_KEY" ]; then
    echo -e "${RED}❌ Failed to extract API key from response${NC}"
    echo "$KEY_BODY"
    exit 1
fi

echo -e "${GREEN}✓ API key created successfully${NC}"
echo "  Key: $API_KEY"
echo ""

# Step 3: Test API key authentication - Health check
echo -e "${YELLOW}[Step 3] Testing API key authentication${NC}"
HEALTH_RESPONSE=$(curl -s -X GET "$API_URL/api/v1/health" \
  -H "X-API-Key: $API_KEY" \
  -w "\n%{http_code}")

HTTP_CODE=$(echo "$HEALTH_RESPONSE" | tail -n1)
HEALTH_BODY=$(echo "$HEALTH_RESPONSE" | head -n-1)

if [ "$HTTP_CODE" != "200" ]; then
    echo -e "${RED}❌ Health check failed (HTTP $HTTP_CODE)${NC}"
    echo "$HEALTH_BODY"
    exit 1
fi

echo -e "${GREEN}✓ API key authentication successful${NC}"
echo ""

# Step 4: List API keys (should see our new key)
echo -e "${YELLOW}[Step 4] Listing API keys${NC}"
LIST_RESPONSE=$(curl -s -X GET "$API_URL/api/v1/auth/keys" \
  -H "X-API-Key: $API_KEY" \
  -w "\n%{http_code}")

HTTP_CODE=$(echo "$LIST_RESPONSE" | tail -n1)
LIST_BODY=$(echo "$LIST_RESPONSE" | head -n-1)

if [ "$HTTP_CODE" != "200" ]; then
    echo -e "${RED}❌ Failed to list keys (HTTP $HTTP_CODE)${NC}"
    echo "$LIST_BODY"
    exit 1
fi

echo -e "${GREEN}✓ API keys listed successfully${NC}"
echo "$LIST_BODY" | head -c 200
echo "..."
echo ""

# Step 5: Test dice rolling endpoint
echo -e "${YELLOW}[Step 5] Testing dice roll endpoint${NC}"
ROLL_RESPONSE=$(curl -s -X POST "$API_URL/api/v1/rolls" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"notation": "1d20+5", "note": "E2E test roll"}' \
  -w "\n%{http_code}")

HTTP_CODE=$(echo "$ROLL_RESPONSE" | tail -n1)
ROLL_BODY=$(echo "$ROLL_RESPONSE" | head -n-1)

if [ "$HTTP_CODE" != "201" ]; then
    echo -e "${RED}❌ Failed to create roll (HTTP $HTTP_CODE)${NC}"
    echo "$ROLL_BODY"
    exit 1
fi

echo -e "${GREEN}✓ Dice roll successful${NC}"
ROLL_TOTAL=$(echo "$ROLL_BODY" | grep -o '"total":[0-9]*' | cut -d':' -f2)
echo "  Roll result: 1d20+5 = $ROLL_TOTAL"
echo ""

# Step 6: Test event log
echo -e "${YELLOW}[Step 6] Testing event log endpoint${NC}"
EVENTS_RESPONSE=$(curl -s -X GET "$API_URL/api/v1/events?limit=5" \
  -H "X-API-Key: $API_KEY" \
  -w "\n%{http_code}")

HTTP_CODE=$(echo "$EVENTS_RESPONSE" | tail -n1)
EVENTS_BODY=$(echo "$EVENTS_RESPONSE" | head -n-1)

if [ "$HTTP_CODE" != "200" ]; then
    echo -e "${RED}❌ Failed to query events (HTTP $HTTP_CODE)${NC}"
    echo "$EVENTS_BODY"
    exit 1
fi

echo -e "${GREEN}✓ Event log queried successfully${NC}"
EVENT_COUNT=$(echo "$EVENTS_BODY" | grep -o '"total_count":[0-9]*' | cut -d':' -f2)
echo "  Total events: $EVENT_COUNT"
echo ""

# Step 7: Test invalid API key (should fail)
echo -e "${YELLOW}[Step 7] Testing invalid API key rejection${NC}"
INVALID_RESPONSE=$(curl -s -X GET "$API_URL/api/v1/health" \
  -H "X-API-Key: invalid-key-12345" \
  -w "\n%{http_code}")

HTTP_CODE=$(echo "$INVALID_RESPONSE" | tail -n1)

if [ "$HTTP_CODE" = "401" ]; then
    echo -e "${GREEN}✓ Invalid API key correctly rejected (401)${NC}"
else
    echo -e "${RED}❌ Expected 401, got HTTP $HTTP_CODE${NC}"
    exit 1
fi
echo ""

# Step 8: Test credential-based auth failure (wrong password)
echo -e "${YELLOW}[Step 8] Testing invalid credentials rejection${NC}"
INVALID_CRED_RESPONSE=$(curl -s -X POST "$API_URL/api/v1/auth/keys" \
  -H "Content-Type: application/json" \
  -d "{\"username\": \"$USERNAME\", \"password\": \"wrongpassword\", \"role\": \"dm\"}" \
  -w "\n%{http_code}")

HTTP_CODE=$(echo "$INVALID_CRED_RESPONSE" | tail -n1)

if [ "$HTTP_CODE" = "401" ]; then
    echo -e "${GREEN}✓ Invalid credentials correctly rejected (401)${NC}"
else
    echo -e "${RED}❌ Expected 401, got HTTP $HTTP_CODE${NC}"
    exit 1
fi
echo ""

# Summary
echo "========================================="
echo -e "${GREEN}✅ All E2E tests passed!${NC}"
echo "========================================="
echo ""
echo "Test user: $USERNAME"
echo "API key: $API_KEY"
echo ""
echo "You can now test other REST endpoints with this API key:"
echo "  curl -H \"X-API-Key: $API_KEY\" $API_URL/api/v1/..."
echo ""
