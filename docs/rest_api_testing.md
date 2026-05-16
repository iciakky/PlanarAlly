# REST API E2E Testing Guide

## Overview

Phase 11.5 added credential-based API key creation, enabling complete end-to-end testing of the REST API using only curl commands, without needing to log in via the web UI.

## Authentication Modes

The `POST /api/v1/auth/keys` endpoint now supports three authentication modes (checked in priority order):

1. **Credential-based** (NEW in Phase 11.5)
   - Provide `username` + `password` in request body
   - System verifies credentials via bcrypt
   - Creates API key for authenticated user
   - **Use case:** E2E testing, automated key generation

2. **Bootstrap mode** (Original)
   - Allows first key creation without authentication
   - Only works when NO API keys exist in database
   - **Use case:** Initial system setup

3. **API key authentication** (Original)
   - Requires existing DM API key in X-API-Key header
   - **Use case:** Creating additional keys after bootstrap

## E2E Testing Workflow

### Prerequisites

1. PlanarAlly server running (dev mode recommended):
   ```bash
   cd server
   PYTHONPATH=. uv run python -m src.planarserver dev
   ```

2. No existing API keys in database (or use credentials mode)

### Automated Test Script

Run the comprehensive E2E test:

```bash
cd server
bash test_e2e_workflow.sh
```

This script automatically:
1. ✅ Registers a unique test user
2. ✅ Creates API key using credentials
3. ✅ Tests authentication (health check)
4. ✅ Tests dice rolling
5. ✅ Tests event logging
6. ✅ Tests invalid key rejection
7. ✅ Tests invalid credentials rejection
8. ✅ Lists API keys

**Expected output:**
```
=========================================
PlanarAlly REST API - E2E Test
=========================================

[Step 1] Registering user: testdm_1234567890
✓ User registered successfully

[Step 2] Creating API key with credentials
✓ API key created successfully
  Key: dm-abc123...

[Step 3] Testing API key authentication
✓ API key authentication successful

[Step 4] Listing API keys
✓ API keys listed successfully

[Step 5] Testing dice roll endpoint
✓ Dice roll successful
  Roll result: 1d20+5 = 18

[Step 6] Testing event log endpoint
✓ Event log queried successfully
  Total events: 1

[Step 7] Testing invalid API key rejection
✓ Invalid API key correctly rejected (401)

[Step 8] Testing invalid credentials rejection
✓ Invalid credentials correctly rejected (401)

=========================================
✅ All E2E tests passed!
=========================================
```

### Manual Testing

#### 1. Register User

```bash
curl -X POST http://localhost:8000/api/register \
  -H "Content-Type: application/json" \
  -d '{"username": "testdm", "password": "test123"}'
```

#### 2. Create API Key (Credential-based)

```bash
curl -X POST http://localhost:8000/api/v1/auth/keys \
  -H "Content-Type: application/json" \
  -d '{"username": "testdm", "password": "test123", "role": "dm"}' \
  | jq -r '.data.key' > api_key.txt

API_KEY=$(cat api_key.txt)
echo "API Key: $API_KEY"
```

#### 3. Test REST Endpoints

**Health check:**
```bash
curl -H "X-API-Key: $API_KEY" http://localhost:8000/api/v1/health
```

**List scenes:**
```bash
curl -H "X-API-Key: $API_KEY" http://localhost:8000/api/v1/scenes
```

**Roll dice:**
```bash
curl -X POST http://localhost:8000/api/v1/rolls \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"notation": "1d20+5", "note": "Attack roll"}'
```

**Query events:**
```bash
curl -H "X-API-Key: $API_KEY" "http://localhost:8000/api/v1/events?limit=10"
```

## Request Format: POST /api/v1/auth/keys

### Credential-based Authentication (NEW)

```json
POST /api/v1/auth/keys
Content-Type: application/json

{
  "username": "testdm",      // PA username
  "password": "test123",     // PA password
  "role": "dm"               // "dm" or "player"
}
```

**Response (201 Created):**
```json
{
  "success": true,
  "data": {
    "id": "uuid",
    "key": "dm-abc123...",   // ⚠️ Only returned once!
    "user_id": "1",
    "username": "testdm",
    "role": "dm",
    "created_at": "2026-02-11T12:00:00Z"
  }
}
```

**Error (401 Unauthorized):**
```json
{
  "success": false,
  "error": {
    "code": "UNAUTHORIZED",
    "message": "Invalid password"
  }
}
```

### Bootstrap Mode (Original)

```json
POST /api/v1/auth/keys
Content-Type: application/json

{
  "username": "admin",    // Note: "username" or "user" both work
  "role": "dm"
}
```

Only works when database has ZERO API keys.

### API Key Authentication (Original)

```json
POST /api/v1/auth/keys
X-API-Key: dm-existing-key-here
Content-Type: application/json

{
  "username": "newuser",
  "role": "player"
}
```

Requires existing DM API key. DM keys can create new keys for any user.

## Security Considerations

### Production Deployment

**⚠️ IMPORTANT:** The credential-based authentication mode is designed for **testing and development** purposes. For production:

1. **Option A: Disable credential auth**
   - Comment out credential check in `auth.py`
   - Force bootstrap or API key auth only

2. **Option B: Rate limiting**
   - Add rate limiting to prevent brute force attacks
   - Implement account lockout after N failed attempts

3. **Option C: Separate admin endpoint**
   - Move credential auth to admin-only endpoint
   - Require additional authorization token

### Best Practices

1. **Never log API keys** - They appear in responses only once
2. **Rotate keys regularly** - Use `DELETE /api/v1/auth/keys/{id}` to revoke
3. **Use role="player" for players** - Limit DM capabilities
4. **Monitor event log** - Review `/api/v1/events` for suspicious activity

## Troubleshooting

### "404: Not Found" on /api/v1/*

**Cause:** Server started before REST API changes were made

**Solution:** Restart the server:
```bash
# Stop server (Ctrl+C or kill process)
cd server
PYTHONPATH=. uv run python -m src.planarserver dev
```

### "Invalid password" but password is correct

**Cause:** User might not exist or username is wrong

**Solution:** Verify user exists:
```bash
sqlite3 server/data/planar.sqlite "SELECT name FROM user;"
```

### "No keys exist" message but bootstrap fails

**Cause:** API keys table might not be created

**Solution:** Check database migration:
```bash
cd server
PYTHONPATH=. uv run python -m src.planarserver  # This creates tables
```

## Development Notes

### Code Location

- **Authentication logic:** `server/src/api/rest/auth.py`
- **E2E test script:** `server/test_e2e_workflow.sh`
- **Middleware:** `server/src/api/rest/middleware.py`

### Testing Against Clean Database

To test bootstrap mode:

```bash
# Backup existing database
cp server/data/planar.sqlite server/data/planar.sqlite.backup

# Clear API keys
sqlite3 server/data/planar.sqlite "DELETE FROM api_key;"

# Run test
cd server && bash test_e2e_workflow.sh

# Restore if needed
mv server/data/planar.sqlite.backup server/data/planar.sqlite
```

## Next Steps

After Phase 11.5, continue with:

- **Phase 12:** Fog of War Control (fog reveal/hide endpoints)
- **Phase 13:** Token Vision (vision range updates)
- **Phase 14:** SSE Event Stream (real-time monitoring)

See `task_plan.md` for complete roadmap.
