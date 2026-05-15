# Phase 31-C:Cowork UI complete

## 速覽

- **預計時程**:2 週
- **前置 Phase**:31-B(signing 完成,UI 開發 / 改動可即時打包驗證)
- **狀態**:📝 spec only,**未實作**
- **目標**:取代 Phase 30-E 的 PoC renderer 為**產線級 UI**。範圍嚴格守住「取代 PoC,不擴張」。

## 1. PoC 現況 vs 目標

| | Phase 30-E PoC | Phase 31-C target |
|---|---|---|
| 訊息列表 | 純 `<div>` 列出 role + text | MessageBubble 元件 + 分 user/assistant/tool/system 樣式 |
| Streaming text | 直接覆蓋最後 message | 同 + cursor blink + auto-scroll-to-bottom |
| 工具呼叫 | 只在 tool_result 顯示一行 | 工具 panel:tool name + input → 進度 → result(可 collapse) |
| Abort | 無 UI | Cancel 按鈕 + Ctrl-C 快捷鍵 |
| 設定 | 寫死 anthropic + claude-sonnet-4-6 | Settings panel:provider / model / API key |
| 對話 | 一次性,關 app 就丟 | 訊息列表 + "New chat" 按鈕(實際持久化 Phase 31-D 做) |
| 主題 | 系統預設 | 明暗主題切換(可選) |

## 2. 任務拆解

### 2.1 元件 inventory

從 chat/web 抽**結構 reference**(但不複用 code,renderer 自己重寫):

- MessageBubble(role + content + timestamp + token usage)
- MessageList(virtualized scroll for long history)
- InputBox(textarea + send + abort button + token estimate)
- ToolCallPanel(展示 tool name + input → progress events → result,可摺疊)
- ModelPicker(下拉選 provider + model)
- SettingsPanel(API key、temperature 等)
- TitleBar(新對話 / 切換)

Cowork **獨立寫**(不複用 chat/web 元件,見 design-decisions §4)。可參考 visual style。

### 2.2 State 管理

引入 `zustand`(同 chat/web 的選擇),`apps/orion-cowork/renderer/src/store/`:

- `useAgentStore`:current session_id、messages、busy state、abort
- `useSettingsStore`:provider / model / API keys / theme

### 2.3 Abort UI

```typescript
async function handleAbort() {
  if (sessionId) {
    await window.agent.call('conversation.abort', { session_id: sessionId }, () => {})
  }
}
```

- Cancel 按鈕在 InputBox 旁,只在 `busy` 時顯示
- Ctrl-C / Cmd-K 快捷鍵透過 `useKeyboard` hook 綁

### 2.4 Tool progress 顯示

Renderer 收 `tool_progress` event:

```typescript
{ event: "tool_progress", data: { tool_name: "Bash", tool_use_id: "...", progress: { stage: "starting" } } }
```

→ 在對應 ToolCallPanel 顯示 inline progress bar / status text。tool_result 抵達後 panel 內容換成 result(可摺疊預設摺疊)。

### 2.5 Settings panel

```typescript
// renderer/src/components/SettingsPanel.tsx
<div>
  <ProviderPicker />
  <ModelPicker />
  <Field label="ANTHROPIC_API_KEY" type="password" onChange={save} />
  <Field label="OPENAI_API_KEY" type="password" onChange={save} />
</div>
```

API key 存:

- macOS:Keychain(透過 sidecar 的 `keyring` 模組)
- Windows:Credential Manager
- Linux:Secret Service

Sidecar 啟動時讀 keyring → 設環境變數給 orion-model SDK。

Renderer 透過新 RPC method `settings.get` / `settings.set` 操作 sidecar 端 keyring。

### 2.6 對話列表(不含持久化)

UI 上看得到「對話 A / 對話 B / ...」可切換,但實際資料在 sidecar 記憶體 + 關 app 丟失。持久化進 Phase 31-D。

- `New chat` 按鈕 → 呼叫 `conversation.create` → 新增 session_id 進列表
- 點對話 → 切到對應 session_id
- 刪對話 → 呼叫 `conversation.delete`(新 RPC)+ 從列表移除

### 2.7 樣式 / 視覺

Cowork 預設使用 **Tailwind**(同 chat/web,但獨立 config)。深色主題優先(桌機 app 常用),明色主題 toggle。

## 3. 新增的 RPC methods

| Method | 用途 |
|---|---|
| `conversation.list` | 列當前 sidecar 內的 sessions |
| `conversation.delete` | 刪 session |
| `settings.get(key)` | 從 keyring 讀 |
| `settings.set(key, value)` | 寫 keyring |

## 4. 風險

| 風險 | 緩解 |
|---|---|
| UI scope creep(想加更多 feature) | 嚴格守住「取代 PoC」清單,新功能進 Phase 32 |
| 跨 OS keyring 行為不一致 | `keyring` Python 庫已抽象,實測 3 個 OS 驗證 |
| 大 tool result(>100KB)阻塞 UI 渲染 | UI 預設 collapse,點開才完整 render;virtualized scroll |
| Streaming text 性能(高頻 setState) | 用 useDeferredValue 或 batch update(每 50ms flush 一次)|

## 5. 驗收

- [ ] 開 app → 看到完整 chat UI(非 PoC 醜樣)
- [ ] 輸入 prompt → streaming text 字字浮現,流暢
- [ ] LLM 呼叫工具 → 看到 ToolCallPanel,progress / result 都顯示
- [ ] Cancel 按鈕能中止 in-flight turn
- [ ] Settings panel:換 model + 填 API key → save → 下次對話用新設定
- [ ] 多個 conversation 可切換
- [ ] 明暗主題切換正常

## 6. 完成後

Phase 31-C 完成 = Cowork 看起來像「成品」。但關 app 還是丟對話 → Phase 31-D 補本機持久化。
