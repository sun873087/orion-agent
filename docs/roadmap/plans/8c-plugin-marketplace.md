# Phase 8c — Plugin Marketplace + 安裝管線 + Plugin 沙盒

**狀態**:📋 Plan(等實質 plugin 生態 / curated registry server 上線)
**前置**:Phase 8 完成(PluginManifest、loader、enable/disable)
**估時**:1 週

## 動機

Phase 8 範圍 C 已交付 plugin **discovery / load**:讀本機目錄的 `plugin.json`、註冊
hook + skill + MCP server。**沒有**:
- 從 registry 拉 plugin metadata 列表
- 下載 zip / dxt bundle 安裝到本機
- 簽章驗證(SHA-256 / Ed25519)
- plugin 沙盒(限制 hook 能 import / 做哪些事)

production deploy 真要 expose plugin 給 user 加,需要這層。本 phase 補完。

## 範圍

### 做

| 項目 | 說明 |
|---|---|
| **PluginRegistry client** | 從 server-side `plugins.json` 讀 metadata 清單 |
| **install_from_registry** | 下載 zip(或 dxt)→ 驗 signature → 解壓到 `~/.orion/plugins/<user>/<plugin_id>/` |
| **uninstall** | 移除 plugin dir |
| **REST endpoint** | `GET /plugins` 列已安裝、`POST /plugins/install/<id>`、`DELETE /plugins/<id>` |
| **Plugin sandbox**(基礎) | webhook hook 預設 `web_only` 模式;shell hook 走 user 的 sandbox(Phase 7 SandboxBackend)而非 host |
| **CLI** | `orion plugin install <id>` / `orion plugin list` / `orion plugin enable <name>` |
| **Server-side `plugins.json`** | repo 下範例(`docs/plugin-registry/plugins.json`),你 host 在 CDN |

### 不做(留更後)

- Plugin DSL / 編譯(讓 user 寫 Python plugin 而非 manifest)→ Phase 9+
- 自動更新 / version pin → Phase 9+
- Plugin 互相依賴解析 → Phase 9+
- Per-tenant plugin 隔離(K8s namespace)→ Phase 11+

## 檔案結構

```
src/orion_agent/plugins/
├── marketplace.py                       [新] PluginRegistry + install_from_registry +
│                                              uninstall + verify_signature
└── ... (Phase 8 既有)

src/orion_agent/api/routes/
└── plugins.py                           [新] /plugins/* REST endpoints

src/orion_agent/main.py                  [改] orion plugin install / list / enable / disable

deploy/plugin-registry/                  [新] 部署範例
├── plugins.json                         server-side metadata
└── README.md                            CDN host + signing 流程
```

## 實作順序(8 步)

| Step | 工作 |
|---|---|
| 1 | `plugins/marketplace.py`:`RegistryEntry` + `PluginRegistry.list_available / get` |
| 2 | `install_from_registry(plugin_id, user_id, registry, install_dir)`:download + verify + extract |
| 3 | `uninstall(plugin_id, user_id, install_dir)` |
| 4 | unit test:mock httpx + tmp zip |
| 5 | `api/routes/plugins.py`:`GET / POST install / DELETE`(JWT auth) |
| 6 | unit test for routes |
| 7 | CLI:`orion plugin install / list / enable / disable` |
| 8 | docs/phases/plan/8c-plugin-marketplace.md 完工 + `deploy/plugin-registry/plugins.json` 範例 |

## 簽章驗證

最簡 SHA-256:registry `plugins.json` 內每筆有 `signature`,client 下完 zip 算 SHA,
不符就拒絕安裝。

進階 Ed25519(可選):registry 用私鑰簽 manifest,client 帶 public key 驗證。

## Verification

```bash
# 1. 建一個範例 plugin zip(skill + plugin.json)
mkdir -p /tmp/p1 && cat > /tmp/p1/plugin.json <<'EOF'
{"name": "demo", "version": "0.1.0", "skills": []}
EOF
cd /tmp && zip -r p1.zip p1/

# 2. host 到 local server(模擬 CDN)
python3 -m http.server 8888 &

# 3. 寫 plugins.json 給本機 registry
cat > /tmp/plugins.json <<EOF
{"plugins":[{"plugin_id":"demo@0.1.0","name":"demo","version":"0.1.0",
"description":"demo","source":"verified",
"download_url":"http://localhost:8888/p1.zip",
"signature":"$(shasum -a 256 /tmp/p1.zip | awk '{print $1}')"}]}
EOF

# 4. CLI install
ORION_REGISTRY_URL="file:///tmp/plugins.json" \
  uv run orion plugin install demo@0.1.0
# 預期:download → verify SHA → 解壓 ~/.orion/plugins/<user>/demo_0.1.0/

uv run orion plugin enable demo
uv run orion plugin list
# 預期:列出 demo 已 enabled
```

## 風險

| 風險 | 緩解 |
|---|---|
| 惡意 plugin 拿 shell hook 跑 `rm -rf /` | sandbox 預設 `web_only`(只 webhook),shell hook 需顯式 `--allow-shell-hooks` |
| zip slip(`../` path)→ 解到別人目錄 | 解壓前 normalize path,reject `..` |
| 巨大 zip 撐爆 disk | size limit(10 MB)+ 解壓後 quota |
| Registry server compromise → 假 plugin metadata | Ed25519 簽章(進階) + pinned public key |
| Network 失敗中途 | 暫存到 `/tmp/orion-plugin-staging/`,完整下完 + verified 才 atomic mv |
| Plugin 升級 broke | 保留舊版本目錄,fallback;Phase 9 加 version pin / lockfile |

## Plugin Server 部署提示

```
你 host:
  https://orion-cdn.example/plugins.json    # registry metadata
  https://orion-cdn.example/p/<id>.zip      # plugin bundle

Plugin 提交流程(內部 / 認證):
  1. plugin 作者開 PR 加 plugin source 到 your monorepo / submission repo
  2. CI build zip + 算 SHA-256 + 簽 Ed25519
  3. 你 review → merge → CI 上 CDN + 更新 plugins.json
```

## 完成 Phase 8c 後

進 Phase 9(worktree + telemetry)或 Phase 10(tools performance)。
