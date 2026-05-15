# Phase 22:DXT(Anthropic Desktop Extensions)Plugin Format

## 速覽

- **預計時程**:3-5 天
- **前置 Phase**:Phase 8(plugin 系統)、Phase 14(SecureStorage)
- **本文件目的**:從 `docs/phases/14-distribution-sync.md` § 5.5 拆出來。
  Phase 14 完工後 DXT format 沒做(範圍偏 plugin 主題,不是 sync / secure),升級為獨立 phase。
- **主要交付物**:
  - DXT zip 格式 install / export
  - DXT manifest 解析(`plugin.json`)
  - 整合 Phase 8 plugin discover 路徑
  - 簽名驗證 hook(可選,future)

## 為何另開 phase?

Phase 14 spec § 5.5 已標明 DXT 是「**輕量,可選**」的章節。實際做下來:

1. DXT 跟「跨機 sync」「secureStorage」沒共同主題
2. DXT install 邏輯 90% 是 zip 解壓 → 套用 Phase 8 plugin loader,放 plugin 系統較合理
3. Phase 14 已把 web chat 必要的 sync(REST CRUD)+ SecureStorage 做完,DXT 純粹是 plugin marketplace 場景才需要

依 user 規則(completion 不寫 TODO),從 Phase 14 拆出。

## TS 對應

`src/utils/dxt/`(目錄)— DXT 格式的 zip / manifest 處理。

## 任務拆解

- [ ] 1. `plugins/dxt.py`:`install_dxt(dxt_path, plugins_dir)` + `export_dxt(plugin_dir, output_path)`
- [ ] 2. manifest schema(name / version / description / entry / hooks / permissions)
- [ ] 3. 整合 Phase 8 plugin discover(install 後 plugins_dir 已可見)
- [ ] 4. 簽名驗證 placeholder(spec § 9 踩雷 #4)
- [ ] 5. CLI / REST 入口(可選):`/plugins/install` upload .dxt
- [ ] 6. 測試 + Phase 22 心得

## 依賴

- Phase 8 `plugins/` 系統(plugin loader / discover)
- Phase 14 `storage/secure.py`(若 plugin 內含敏感 token,從 secure store 讀)

## 驗收標準

```bash
pytest tests/unit/plugins/test_dxt.py -v
```

關鍵測試:install 後 plugin 出現在 list,export 後 zip 內含原檔。

## 完成後寫

`orion-agent/docs/phase-22-completion.md`(zh-tw、含驗證指令、無 TODO)。
