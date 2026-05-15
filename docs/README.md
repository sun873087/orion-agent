# orion-agent docs

四個區、各管一件事。

| 區 | 目的 | 何時讀 |
|---|---|---|
| **[architecture/](./architecture/)** | 專案結構、package 拆分、依賴規則 | 想知道「東西長什麼樣」 |
| **[features/](./features/)** | 各 feature 設計與行為(agent loop、tools、memory、MCP、...) | 想知道「X 怎麼運作」 |
| **[guides/](./guides/)** | 操作手冊(setup、跑測試、手動驗證、排錯) | 想動手做某件事 |
| **[roadmap/](./roadmap/)** | 還沒實作的 plan 跟未來方向 | 想看「下一步是什麼」 |

---

## 新人路徑

1. [`architecture/README.md`](./architecture/README.md) — 整體拓樸,15 分鐘掃完
2. [`guides/setup.md`](./guides/setup.md) — 5 個 package 跑通本機
3. [`features/README.md`](./features/README.md) — 挑感興趣的 feature 進去讀
4. [`roadmap/README.md`](./roadmap/README.md) — 看下一步要做什麼

---

## Quick links

| 我要... | 去哪 |
|---|---|
| 第一次安裝跑起來 | [`guides/setup.md`](./guides/setup.md) |
| 跑測試 | [`guides/run-tests.md`](./guides/run-tests.md) |
| 看 5 個 package 各自做什麼 | [`architecture/packages.md`](./architecture/packages.md) |
| 看 runtime 資料/設定在哪個目錄 | [`architecture/runtime-layout.md`](./architecture/runtime-layout.md) |
| 看 agent loop 怎麼跑 | [`features/agent-loop.md`](./features/agent-loop.md) |
| 看內建工具集 | [`features/tools.md`](./features/tools.md) |
| 看 memory 系統 | [`features/memory.md`](./features/memory.md) |
| 卡關 | [`guides/troubleshooting.md`](./guides/troubleshooting.md) |

---

## 寫文件原則

新增文件先判斷它屬於哪一區:

- **architecture/** — 描述「東西怎麼長」(static structure)
- **features/** — 描述「某個 feature 怎麼運作」(behavior)
- **guides/** — 描述「如何做某件事」(action)
- **roadmap/plans/** — 描述「打算做某件事」(intent)

判別不出 → 通常是混了兩件事,拆兩份。

### 其他規則

- 不寫「我們」、「剛剛改了 X」、「最近」這類時間相對詞
- 不寫實作日誌(完工的事直接看 git log)
- Reference 性質的事實(套件名、env var)隨 code 同步更新
- 過期文件直接刪,不要留 "deprecated" 標籤拖
