# Roadmap

未來方向 + 過去做過什麼。

## 結構

- **[plans/](./plans/)** — 未實作的 phase plan(forward-looking spec)
- **[done.md](./done.md)** — 已完成的 phase 一句話列表(git log 對照)

## 寫新 plan

新 plan 文件放 [`plans/`](./plans/),命名格式 `<NN>-<short-name>.md`,起手用 9 節範本:

1. **速覽** — 時程、依賴、交付物
2. **目標與動機** — 為什麼做、解決什麼
3. **任務拆解** — 可勾選清單
4. **模組架構與檔案** — 目錄樹
5. **API surface / 範例** — caller 看到什麼
6. **設計決策與取捨**
7. **驗收標準** — 自動測試 + 手動驗證 + 整合
8. **常見踩雷**
9. **參考資料**

範例見現有 plan(如 [`plans/7c-helm-chart.md`](./plans/7c-helm-chart.md))。

## 完工後

plan 實作完成後:

1. **不要**把 plan 文件改寫成 completion 報告 — 完工事實看 `git log`
2. 把這份 plan 從 `plans/` 移除(`git rm`)
3. 在 [`done.md`](./done.md) 加一行:`- Phase NN — <name>(<short commit>):一句話`
4. 如果這個 plan 引入新 feature/architecture decision,記得 update [`../features/`](../features/) 或 [`../architecture/design-decisions.md`](../architecture/design-decisions.md)

## 不寫完工日誌

過去 orion-agent docs 有大量 `phase-NN-completion.md`,事後證明價值低 — 真實狀態看 git log 跟 code,文件只會 stale。新規矩:**plan 入,doc 出**(更新 features / architecture)。
