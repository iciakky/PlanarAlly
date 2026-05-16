# Automation API — Implementation Notes

本文件記錄 v2 spec (`automation_api_proposal.md`) 與實際實作之間的差異，以及實作過程中發現的限制。

---

## Spec 差異

### 1. `getVisibleShapes()` 改為 async

Spec 描述為同步函數。實作改為 `async`，因為需要透過 socket 向 server 查詢 external_id mapping。

```js
// Spec 寫法（同步）
const shapes = window.planarallyAutomation.getVisibleShapes()

// 實際用法（async）
const shapes = await window.planarallyAutomation.getVisibleShapes()
```

在 Playwright/agent-browser 中使用 `page.evaluate` 或 `eval --json` 時，Promise 會自動 await，對 caller 幾乎透明。

### 2. `getVisibleShapes()` 的 reason enum

Spec 定義四種 reason：`visible`, `not_in_vision`, `hidden_layer`, `not_sent_to_client`。

實作只有兩種：`visible`, `not_in_vision`。

原因：PA server 不送 DM-only layer shapes 給 player client。這些 shapes 根本不在 player 的 `idMap` 裡，所以不會出現在 `getVisibleShapes()` 結果中。不存在的 shape 不需要 reason。

**驗證方式：** Player 的 `getVisibleShapes()` 結果中不會出現 DM-only layer 的 shape UUID。可以對比 DM 和 Player 的結果來確認資訊隔離。

### 3. `setView()` 內部實作

Spec 描述為「讀寫 `window.state.position`」。實作使用 PA 的 `positionSystem.setPan()` 和 `positionSystem.setZoomDisplay()`。

**對 caller 無影響**——API 介面 `setView({panX, panY, zoom})` 不變。Zoom 值範圍 0-1（0=最遠，1=最近）。

### 4. Diagnostics `SHAPE_VISIBLE_NO_ACCESS` 已移除

Code review 確認此 check 概念錯誤：PA 送 player-visible layer 上**所有** shapes 給 player，不管 access 設定。Access 只影響 client UI 互動（名稱顯示為 `?`、不能移動等），不影響資料傳輸。

目前 diagnostics 只檢查 `MISSING_LOCATION_USER_OPTION`。Spec 中提到的 `SECRET_ON_PLAYER_VISIBLE_LAYER` 未實作。

---

## 額外功能（Spec 未涵蓋）

### `reloadLocation()`

```js
await window.planarallyAutomation.reloadLocation()
```

強制 server 重新送出完整的 board 資料。用途：PA 有 auth race condition（見下方），首次載入可能不完整。呼叫此方法可修復。

**建議用法：** 在 `ready()` resolve 後，如果 board 明顯不完整（例如 `getVisibleShapes()` 回傳空陣列但 scene 預期有 shapes），呼叫 `reloadLocation()` 再 await 其回傳值。注意：空陣列也可能是正確結果（空 scene 或 player 在 DM-only scene）。

```js
await pa.ready({ timeout: 60000 });
const shapes = await pa.getVisibleShapes();
if (shapes.length === 0 && expectedShapeCount > 0) {
    await pa.reloadLocation(); // returns a new ready promise
}
```

---

## 已知限制

### 1. Headless browser 首次載入延遲（~20-30 秒）

PA 的 Vue router `beforeRouteEnter` 在 component mount 前就建立 socket 連線。首次載入 game URL 時，auth check 可能在 socket 連線後才完成，導致頁面 redirect 再回來。

**對 caller 的影響：** `ready()` 需要等 ~20-30 秒才 resolve。設定 `timeout ≥ 60000` 即可。

**確認：** `ready()` 在所有 board data 送達且處理完後才 resolve。不需要額外 sleep。

### 2. Shape options 格式

`options` 欄位在 PA 的 DB 中儲存為 entries array 格式（如 `"[]"` 或 `"[[\"preFogShape\",true]]"`）。

REST API 接受 dict 輸入（如 `{"preFogShape": true}`）並自動轉換。Caller 不需要手動轉格式。

### 3. Revision counter 和 epoch 機制

Server restart 後 revision 從 0 開始。Client 端維護 `epoch` counter，每次 socket reconnect 時 epoch +1。

**Reconnect 時的行為：**
- `lastProcessedRevision` 重置為 0
- 所有 pending `waitForSync` waiters 被 **reject**（`Error: Connection lost (reconnect #N). Revision epoch changed.`）
- `ready()` promise 被 reject 並重建（需要重新 await `ready()`）
- `reconnectCount` 和 `epoch` 遞增

**Cross-epoch 保護：** `waitForSync` 記錄建立時的 epoch。如果 epoch 改變，waiter 不會被新 epoch 的 revision 滿足。

**Caller 偵測 reconnect（完整範例）：**
```js
const pa = window.planarallyAutomation;
const epochBefore = pa.epoch;
try {
    await pa.waitForSync({ revision: r });
} catch (e) {
    if (pa.epoch !== epochBefore) {
        // reconnect happened — must re-initialize
        await pa.ready({ timeout: 60000 });
        // caller should re-run the mutation or abort
        throw new Error("Reconnect during sync: " + e.message);
    }
    throw e; // timeout or other error — re-throw
}
```

**重要：** epoch guard 需要配合 try/catch。如果 `waitForSync` reject 後沒有 catch，epoch check 不會執行。

**重要：** 不要將 `pa.ready()` 的回傳值存到變數中重複使用。每次需要等 ready 時，直接呼叫 `pa.ready()`。舊的 resolved promise 在 reconnect 後仍然回傳 `true`，不反映新狀態。

**重要：** 在 Playwright/agent-browser 的 `page.evaluate` 中，未 catch 的 rejection 可能被靜默吞掉（evaluate 回傳 `undefined`）。所有 automation API 呼叫都應該在 try/catch 中執行。

### 4. `waitForSync` timeout 和 `ready()` timeout

```js
// ready() 預設 60 秒 timeout，可自訂
await pa.ready();                      // 60s default
await pa.ready({ timeout: 120000 });   // 120s

// waitForSync 預設 30 秒 timeout，可自訂
await pa.waitForSync({ revision: 42 });              // 30s default
await pa.waitForSync({ revision: 42, timeout: 10000 }); // 10s
```

兩個 waiting function 都有 default timeout，不會永遠 hang。

Timeout error 包含診斷資訊：`"waitForSync timed out: requested=42, current=5, epoch=2"`。

### 4. `getVisibleShapes()` 使用 center point 判斷

大形狀或長牆的 center 可能不在 vision 範圍內但邊緣可見。對 token-sized shapes（半徑 < 50）幾乎沒有影響。

### 5. `setView()` 注意事項

- 必須在 `ready()` resolve 後才能呼叫，否則會 throw `"board not ready"`
- `zoom` 值範圍 0-1。**0 = 最近（zoomed in），1 = 最遠（zoomed out）**。超出範圍會被 clamp。
- 另有 `setViewToBounds({x, y, width, height, padding?})` 可自動計算 zoom 以 fit 指定區域。

### 6. Wall/door 建議放在 `map` layer

Spec 範例使用 `"layer": "tokens"`。建議改用 `"map"` layer：

| Shape 類型 | 建議 Layer | 原因 |
|-----------|-----------|------|
| 牆壁 (line + vision_obstruction) | `map` | 靜態地形，不可被玩家選取/移動 |
| 門 (rect + is_door) | `tokens` | 互動式物件，DM 需要可選取 |
| PC/NPC tokens | `tokens` | 主要互動層 |
| DM 秘密 | `dm` | Data-level 隔離（不送給 player） |
| Fog reveal polygons | `fow` | Fog of war 系統 |
