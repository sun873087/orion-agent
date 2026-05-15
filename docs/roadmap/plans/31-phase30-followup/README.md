# Phase 31 — Phase 30 follow-up:Cowork ship + test infra + SDK polish

## 速覽

- **預計時程**:全職 6-8 週 / 業餘 16-20 週
- **前置 Phase**:Phase 30(monorepo 重構)完成
- **狀態**:📝 spec only,**未實作**
- **觸發來源**:Phase 30 在 monorepo 結構 + Cowork PoC 收尾,但留下三組 follow-up 工作:
  1. Cowork 從 PoC 到 ship-ready
  2. e2e test infra(chat-api + Cowork)
  3. SDK polish(memory anti-bloat Layer 3+4、MCP supervisor、cross-machine resume)
- 本 Phase 31 把這三組整合成可平行的 3 條 track,各有 sub-phase 標號 A-H。

## 1. 三條 Track

| Track | sub-phase | 內容 | 估時 |
|---|---|---|---|
| **1. Cowork ship-readiness** | A-D | PyInstaller + electron-builder + 簽章 + 完整 UI + 本機持久化 + MCP | 4-5 週 |
| **2. Test infra** | E, F | chat-api e2e + Cowork e2e | 1-2 週 |
| **3. SDK polish** | G, H | memory anti-bloat L3+4 + MCP supervisor + cross-machine resume | 1-2 週 |

**Track 間獨立可平行**(不同人 / 不同 session)。Track 內部有依賴順序(A → B → C → D)。

## 2. Sub-phase 列表

### Track 1:Cowork ship-readiness

- **[A. Cowork packaging](./A-cowork-packaging.md)** — PyInstaller 把 sidecar 包成 single binary;electron-builder 打包 .app / .exe / .AppImage(無簽章)。1 週。
- **[B. Cowork signing + auto-update](./B-cowork-signing-update.md)** — macOS notarization、Windows code signing、electron-updater integration。1 週(+ 申請開發者帳號的等待)。
- **[C. Cowork UI complete](./C-cowork-ui-complete.md)** — 取代 PoC renderer 為產線級 UI:訊息泡泡 / 工具 progress / abort UI / 設定畫面。2 週。
- **[D. Cowork local persistence + MCP](./D-cowork-persistence-mcp.md)** — 本機 SQLite session 持久化、MCP server 整合、多 provider / model 切換。1 週。

### Track 2:Test infra

- **[E. Chat-api e2e infra](./E-chat-api-e2e.md)** — Postgres testcontainer + WS client + 完整 happy-path e2e。1 週。
- **[F. Cowork e2e infra](./F-cowork-e2e.md)** — headless Electron + Playwright Electron + xvfb CI 環境。1 週。

### Track 3:SDK polish

- **[G. Memory Layer 3+4](./G-memory-layer-3-4.md)** — usage tracking sidecar log + quota / merge suggest。1 週。
- **[H. MCP supervisor + cross-machine resume](./H-mcp-supervisor-resume.md)** — MCP server crash auto-restart、Postgres-backed cross-machine session resume。1 週。

## 3. 依賴圖

```
       A (packaging)
       │
       ▼
       B (signing)
       │
       ▼
       C (UI complete) ──┐
       │                 │
       ▼                 │
       D (persistence)   │
                         │
       E (chat-api e2e)  │
                         │
       F (cowork e2e) ◀──┘
                         (F 需 D 完成,因為要測完整 UI flow)
       G (memory L3+4)
       H (MCP+resume)
```

**Track 2 的 F 依賴 Track 1 的 D 完成**(e2e 要測完整 UI flow)。其他 sub-phase 之間獨立。

## 4. 不在 scope 內

明確**不做**的事:

| 範疇 | 為何不做 |
|---|---|
| Cowork iOS / Android port | 桌機優先,行動端另開 |
| Plugin marketplace UI(plan 8c) | Plugin 生態系尚未成形 |
| Helm chart(plan 7c) | Phase 31 不動 deployment,docker-compose 已夠 dev / staging |
| Grafana stack(plan 9d) | observability 等 production 部署有實際 traffic 再加 |
| TS port of SDK | Phase 30 設計決策已明確不做 |

## 5. 整體驗收

Phase 31 全部完成時:

- [ ] `make build-cowork-production` 跑出 macOS .app + Windows .exe + Linux .AppImage(都有簽章 + notarized)
- [ ] end-user 雙擊安裝即可開,**不需要本機裝 Python / uv / Node**
- [ ] Cowork 完整 chat UI 不再被叫 "PoC"
- [ ] `make test-e2e-chat` 通過(完整 chat-api stack e2e,含 Postgres)
- [ ] `make test-e2e-cowork` 通過(headless Electron + sidecar 完整對話)
- [ ] Memory Layer 3+4 預設啟用,Layer 4 在 UI 顯示「建議合併」標記
- [ ] MCP server crash 自動重啟(指數 backoff,3 次後 give up)
- [ ] chat-api 用 Postgres 模式,跨機器 resume 整段對話可用

## 6. 風險清單

| 風險 | 嚴重度 | 緩解 |
|---|---|---|
| macOS notarization 流程卡 Apple 審核 | 高 | 平行做 — A 先 ship 無簽章版本給 dev / 內部測試,B 處理簽章不 block 其他 track |
| Cowork UI scope creep | 高 | C 嚴格守住「取代 PoC」目標,新功能進 Phase 32+ |
| PyInstaller sidecar 跨平台問題(尤其 Windows) | 中 | A 階段優先 macOS / Linux,Windows 留後 |
| headless Electron CI 不穩 | 中 | F 階段先確認 local 跑得起來再上 CI |
| Memory L3+4 對既有 user 行為改變 | 中 | 預設 opt-in flag,觀察一陣子才預設 on |
| Cross-machine resume 大 transcript 載入慢 | 中 | H 階段內含 lazy load / streaming load 設計 |

## 7. 進入下一步

1. 讀完本 README 對整體方向有概念
2. 挑 track + 第一個 sub-phase 進去詳讀(從 A 或 E 或 G 切入皆可)
3. 每個 sub-phase 完工 → 從 `plans/31-phase30-followup/` 移除該檔 + 在 `../../done.md` 加一行
4. 全 Phase 31 完工 → 整個 `31-phase30-followup/` 目錄刪除(已包含進 `done.md`)
