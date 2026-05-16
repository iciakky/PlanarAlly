# PlanarAlly Automation API — 交付報告

## 交付內容

一個修改過的 PlanarAlly docker image，新增了 REST API 和 frontend automation bridge，讓你可以用程式設定場景、驗證 GM/Player 資訊隔離、並透過 headless browser 截圖。

---

## 如何開始

### 1. 取得 image

你會收到一個 docker image（`planarally-automation:latest`）。載入方式：

```bash
docker load < planarally-automation.tar
```

### 2. 啟動 container

把你原本跑官方 image 的指令中的 image name 換掉即可。其他參數（port、volume）完全相容。

```bash
# 原本
docker run -d -p 8000:8000 kruptein/planarally:latest

# 改成
docker run -d -p 8000:8000 planarally-automation:latest
```

### 3. 註冊使用者 + 建 API key

```bash
# 註冊
curl http://localhost:8000/api/register \
  -H "Content-Type: application/json" \
  -d '{"username":"myuser","password":"mypass"}'

# 建 DM API key
curl http://localhost:8000/api/v1/auth/keys \
  -H "Content-Type: application/json" \
  -d '{"username":"myuser","password":"mypass","role":"dm"}'
# → {"data": {"key": "dm-xxxx..."}}
```

之後所有 REST API 呼叫都用 `X-API-Key: dm-xxxx...` header。

---

## REST API 一覽

所有 endpoint 都在 `/api/v1/` 下，需要 `X-API-Key` header。

| Endpoint | 方法 | 用途 |
|----------|------|------|
| `/rooms` | POST | 建立 room（自動建 location + floor + layers） |
| `/rooms/{id}/players` | POST | 加 player 到 room（自動建 LocationUserOption） |
| `/assets` | POST | 上傳圖片資產（回傳 asset_id, asset_hash, entry_id, width_px, height_px） |
| `/scenes/{id}/shapes` | POST | 建 shape（支援 assetrect, circulartoken, line, polygon, rect） |
| `/scenes/{id}/shapes` | GET | 用 `?external_id=xxx` 查詢 shape |
| `/scenes/{id}/shapes/by-external-id/{eid}` | PUT | Upsert（存在就 update，不存在就 create） |
| `/shapes/{uuid}/access` | PATCH | 設定 per-player vision/movement/edit |
| `/scenes/{id}/options` | PATCH | 設定場景選項（fog, LOS, grid, ambient light） |
| `/scenes/{id}/diagnostics` | GET | 檢查場景 invariants |
| `/scenes/{id}/visibility?player=xxx` | GET | Server-side visibility check |

每個 mutation endpoint 都回傳 `revision` number，用於 `waitForSync`。

---

## Frontend Automation Bridge

在 browser 開啟 game URL 加上 `?automation=1&hideUi=1`：

```
http://localhost:8000/game/{creator}/{room}?automation=1&hideUi=1
```

所有方法在 `window.planarallyAutomation` 上：

### `ready({timeout?})`

等待 board 完全載入。Default timeout 60 秒。

```js
await window.planarallyAutomation.ready(); // 60s default
await window.planarallyAutomation.ready({ timeout: 120000 }); // 120s
```

### `readyStable({timeout?, maxRetries?})`

`ready()` 的穩定版——自動重試 reconnect rejection（headless browser auth dance 會觸發一次 reconnect）。

```js
await window.planarallyAutomation.readyStable(); // 60s timeout, 3 retries
```

建議在 headless 環境用 `readyStable()` 取代 `ready()`。

### `waitForSync({revision, timeout?})`

等待 REST API mutation 同步到 client。Default timeout 30 秒。

```js
const resp = await fetch('/api/v1/scenes/1/shapes', { method: 'POST', ... });
const { data: { revision } } = await resp.json();
await window.planarallyAutomation.waitForSync({ revision });
// 現在 canvas 已經畫好了，可以截圖或查詢 visibility
```

### `getVisibleShapes()`

回傳 client 端所有 shapes 的 visibility 狀態。**Async**。

```js
const shapes = await window.planarallyAutomation.getVisibleShapes();
// [
//   { uuid: "...", external_id: "kannon", layer: "tokens", visible: true, reason: "visible" },
//   { uuid: "...", external_id: "north-wall", layer: "map", visible: true, reason: "visible" },
//   ...
// ]
```

- `external_id`：你在 REST API 建 shape 時指定的 ID，null 表示未指定
- `reason`：`visible`（在 vision 範圍內）或 `not_in_vision`（被 fog/LOS/牆壁擋住）
- DM-only layer（如 `dm`）的 shapes **不會出現在 player client 的結果中**

### `setView({panX, panY, zoom})`

設定視角。必須在 `ready()` 後呼叫。Zoom 範圍 0-1，超出會被 clamp。

```js
window.planarallyAutomation.setView({ panX: 400, panY: 300, zoom: 0.5 });
```

### `setViewToBounds({x, y, width, height, padding?})`

自動計算 pan/zoom 讓指定區域 fit 在畫面中。

```js
// 讓 (0,0)-(1056,768) 的地圖區域填滿畫面
window.planarallyAutomation.setViewToBounds({x: 0, y: 0, width: 1056, height: 768, padding: 20});
```

### `reloadLocation()`

強制 server 重新送出 board 資料。用於首次載入不完整時的 workaround。

```js
await window.planarallyAutomation.reloadLocation();
```

### `epoch` / `reconnectCount` / `lastRevision`

連線狀態 getter。`epoch` 在每次 socket reconnect 時遞增。

---

## 完整工作流程範例

```python
import requests
import json

BASE = "http://localhost:8000"
KEY = "dm-xxxx..."  # 從 /api/v1/auth/keys 取得
H = {"Content-Type": "application/json", "X-API-Key": KEY}

# 1. 建 room
r = requests.post(f"{BASE}/api/v1/rooms", json={"name": "dungeon"}, headers=H)
room_id = r.json()["data"]["room_id"]
scene_id = r.json()["data"]["default_location"]["id"]

# 2. 加 player
requests.post(f"{BASE}/api/v1/rooms/{room_id}/players",
    json={"username": "player1", "role": "player"}, headers=H)

# 3. 設場景選項
requests.patch(f"{BASE}/api/v1/scenes/{scene_id}/options",
    json={"full_fow": True, "fowLos": True, "fowOpacity": 0.7}, headers=H)

# 3.5 上傳地圖背景 + 放置為 assetrect
import base64
with open("assets/ash-lantern-kiln-background.png", "rb") as f:
    png_b64 = base64.b64encode(f.read()).decode()
r = requests.post(f"{BASE}/api/v1/assets", json={
    "name": "ash-lantern-kiln-background.png",
    "mime_type": "image/png",
    "content_base64": png_b64,
}, headers=H)
asset = r.json()["data"]
# asset = {"asset_id": 1, "asset_hash": "...", "entry_id": 2, "width_px": 2112, "height_px": 1536}

requests.post(f"{BASE}/api/v1/scenes/{scene_id}/shapes", json={
    "type": "assetrect",
    "external_id": "map-background",
    "layer": "map",
    "x": 0, "y": 0,
    "width": 1056, "height": 768,  # 2x 圖放在 1x 座標
    "assetId": asset["asset_id"],
    "assetHash": asset["asset_hash"],
    "is_locked": True,
    "default_vision_access": True,
    "default_edit_access": False,
}, headers=H)

# 4. 建牆壁
requests.post(f"{BASE}/api/v1/scenes/{scene_id}/shapes", json={
    "type": "line", "external_id": "north-wall", "layer": "map",
    "x": 100, "y": 100, "x2": 500, "y2": 100,
    "line_width": 4, "vision_obstruction": 1,
    "stroke_colour": "rgba(0,0,0,1)"
}, headers=H)

# 5. 建 PC token
r = requests.post(f"{BASE}/api/v1/scenes/{scene_id}/shapes", json={
    "type": "circulartoken", "external_id": "kannon",
    "layer": "tokens", "x": 400, "y": 300, "radius": 28,
    "text": "PC", "name": "Kannon"
}, headers=H)
pc_uuid = r.json()["data"]["uuid"]
last_rev = r.json()["data"]["revision"]

# 6. 給 player vision access
requests.patch(f"{BASE}/api/v1/shapes/{pc_uuid}/access", json={
    "players": {"player1": {"vision": True, "movement": True}},
    "default_vision": False
}, headers=H)

# 7. 建 DM secret（player 看不到）
requests.post(f"{BASE}/api/v1/scenes/{scene_id}/shapes", json={
    "type": "circulartoken", "external_id": "hidden-boss",
    "layer": "dm", "x": 600, "y": 200, "radius": 28,
    "text": "??", "name": "Boss"
}, headers=H)

# 8. 驗證 (server-side)
diag = requests.get(f"{BASE}/api/v1/scenes/{scene_id}/diagnostics", headers=H).json()
assert diag["data"]["ok"] == True

vis = requests.get(f"{BASE}/api/v1/scenes/{scene_id}/visibility?player=player1", headers=H).json()
for s in vis["data"]["shapes"]:
    if s["external_id"] == "hidden-boss":
        assert s["sent_to_client"] == False  # DM-only layer, not sent to player

# 9. 開 browser 驗證 (client-side)
# 用 Playwright / agent-browser / Puppeteer：
# - 登入 player1
# - 開啟 /game/{dm_user}/dungeon?automation=1&hideUi=1
# - await ready()
# - shapes = await getVisibleShapes()
# - assert "hidden-boss" not in [s.external_id for s in shapes]
# - 截圖
```

---

## 重要注意事項

### Shape options 格式

REST API 接受 dict 格式的 `options`（如 `{"preFogShape": true}`），會自動轉換為內部格式。

### 建議的 layer 分配

| Shape 類型 | Layer | 原因 |
|-----------|-------|------|
| 地圖背景 (assetrect + is_locked) | `map` | 鎖定的底圖，不可被拖移 |
| 牆壁 (line + vision_obstruction) | `map` | 靜態地形，不可被玩家選取 |
| 門 (rect + is_door) | `tokens` | 互動式，DM 需可選取 |
| PC/NPC tokens | `tokens` | 主要互動層 |
| DM 秘密 | `dm` | Data-level 隔離（不送給 player） |
| Fog reveal polygons | `fow` | Fog of war 系統 |

### Headless browser 首次載入

PA 有 auth race condition，首次載入 game URL 時 `ready()` 可能需要 20-30 秒才 resolve。不需要額外 sleep——`ready()` 在 board 完全載入後才 resolve。設定 timeout >= 60 秒即可。

如果 `ready()` 後 `getVisibleShapes()` 回傳空但場景有 shapes，呼叫 `reloadLocation()` 再等 `ready()`。

### Reconnect 處理

所有 async 方法（`ready`, `waitForSync`, `getVisibleShapes`）在 socket reconnect 時會 **reject**，不是 resolve。必須用 try/catch：

```js
const pa = window.planarallyAutomation;
const epochBefore = pa.epoch;
try {
    await pa.waitForSync({ revision: r });
} catch (e) {
    if (pa.epoch !== epochBefore) {
        // reconnect 發生了，重新初始化
        await pa.ready({ timeout: 60000 });
        throw new Error("Reconnect during sync: " + e.message);
    }
    throw e; // timeout 或其他錯誤
}
```

### Vision colour

`PATCH /api/v1/tokens/{uuid}/vision` 不指定 `colour` 時，預設為 `rgba(255, 244, 210, 0.10)`（透明暖色），不會遮蓋地圖。如需自訂，傳 `colour` 參數。

### `setView` zoom 方向

`zoom` 值範圍 0-1。**0 = 最近（zoomed in），1 = 最遠（zoomed out）**。建議用 `setViewToBounds` 避免手動計算。

### `getVisibleShapes()` 精度

使用 shape center point 判斷 visibility。Token-sized shapes 沒問題，超大形狀或長牆的 center 可能不在 vision 範圍。

### Asset upload + assetrect

- Upload response 回傳 `width_px`/`height_px`（PNG/JPEG 自動偵測）
- `assetrect` 不指定 width/height 時自動用圖片原始尺寸
- 明確指定 width/height 時不會被覆蓋（支援 2x hi-res 底圖）
- `strict_aspect_ratio: true` 在 create 和 upsert 都生效：比例差 >1% → 400 error
- 不帶 `strict_aspect_ratio` 時，比例差 >1% → response 含 `aspect_ratio_warning` 欄位

### Revision counter

In-memory，server restart 後重置。Client 在 reconnect 時也會重置。Cross-epoch 的 revision 會被自動 reject，不會 false positive。

---

## 驗證結果

### Server-side（107/107 integration tests pass）
- Room 建立 + player 加入 + LocationUserOption 自動建立
- Asset 上傳（dedup、dimension detection、servability）
- Shape 建立（5 types 含 assetrect）+ external_id upsert + query
- Assetrect: auto-detect dimensions, strict_aspect_ratio check, upsert asset swap
- Shape access + scene options + diagnostics + visibility
- Mutation revision counter monotonically increasing
- Vision colour default: transparent warm (not opaque white)

### Browser-side（DM + Player 實測通過）

| 測試 | DM | Player |
|------|----|----|
| `ready()` resolve | ✅ | ✅ |
| `getVisibleShapes()` shape count | 6（含 dm layer） | 5（dm layer filtered） |
| `external_id` 回傳 | ✅ 正確 | ✅ 正確 |
| `hidden-enemy`（dm layer）出現 | ✅ 是 | ✅ 不出現 |
| assetrect 渲染（cleric-token.png） | ✅ 正確顯示 | — |
| `readyStable()` | ✅ resolve 成功 | — |
| `setViewToBounds()` | ✅ viewport 調整正確 | — |
| `waitForSync` end-to-end | ✅ REST→sync→idMap 增加 | — |
| `setView` pan/zoom | ✅ 值正確改變 | — |
| `epoch` / `reconnectCount` | ✅ 可讀 | — |

### Code-review-only（未經 runtime 驗證）
- `reloadLocation()` — 邏輯正確但未 browser-tested
- Reconnect 行為（epoch increment, waiter rejection）— 需要 server restart 才能觸發
- Timeout reject — 需要 server 不回應的條件

---

## 文件

- `docs/automation_api_proposal.md` — 完整 API spec（含所有 endpoint 的 request/response 格式）
- `docs/automation_api_implementation_notes.md` — Spec 與實作之間的差異、已知限制

有問題直接問。
