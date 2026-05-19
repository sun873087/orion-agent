# Building Orion Cowork for distribution

Phase 31-W — PyInstaller sidecar binary + electron-builder cross-platform installers
(`.dmg` / `.exe` / `.AppImage`)。

> **狀態:macOS .dmg unsigned 可 build。Windows / Linux 需在對應 OS 上 build
> (沒 CI 跨平台);notarization / code signing 等下一個 phase。**

## TL;DR

```bash
# 從 repo root,跑一次 build 全套(sidecar binary + renderer + electron + .dmg)
cd apps/orion-cowork
pnpm dist:mac        # 產 .dmg 進 dist/installers/
```

第一次跑 ~2-3 分鐘:PyInstaller 90s + Vite build 2s + electron-builder 30s。

## 兩段式架構

```
1. PyInstaller         打包 Python sidecar 成 single binary
   sidecar/  ──────────►  dist/sidecar/orion-cowork-sidecar  (~90 MB)
                          (90 MB 主要是 anthropic / openai SDK + sqlalchemy 等)

2. electron-builder    用 binary + renderer dist + electron main → installer
   ├── extraResources picks dist/sidecar/orion-cowork-sidecar
   └── 包進 dist/installers/Orion Cowork-x.y.z-{arch}.dmg
```

## 開發 vs Production sidecar 啟動

`apps/orion-cowork/electron/main.ts:packagedSidecarPath()` 偵測:

```ts
if (app.isPackaged) {
  // Production:Contents/Resources/sidecar/orion-cowork-sidecar
  return resolve(process.resourcesPath, 'sidecar', 'orion-cowork-sidecar')
}
return null  // dev → SidecarClient 走 `uv run python -m ...`
```

Dev 流程完全不變(`pnpm dev` 還是 uv);production .app 直接呼 binary,
**user 不需要裝 Python / uv**。

## Build 細節

### A. Sidecar binary

```bash
pnpm build:sidecar
# = bash scripts/build-sidecar.sh
# = uv run pyinstaller apps/orion-cowork/sidecar/pyinstaller.spec
```

`pyinstaller.spec` 重點:
- **`collect_submodules('orion_sdk', 'orion_model')`** — SDK 內有大量字串動態 import
  (plugin loader / skill / DB dialects),靜態 graph 抓不到全
- **Hidden imports**:`sqlalchemy.dialects.{sqlite,postgresql}.{aiosqlite,asyncpg}` /
  `anthropic._streaming` / `openai._streaming`
- **`collect_data_files('orion_sdk')`** 把 bundled skills(`.md`)+ pricing
  (`.json`)+ prompt template 包進 binary
- **`console=True`** — sidecar 走 stdin/stdout JSON-RPC,**不能** windowed mode
- **`target_arch=None`** — 跟著 host CPU。arm64 機器只能 build arm64;intel 機器
  build x64。**沒 universal2 / Rosetta cross-build**(PyInstaller 限制)

Cross-arch:要 build x64 binary 在 arm64 機器上,只能在 x64 機器上跑 spec。
electron-builder 跑 `--mac` 會嘗試兩種 arch,但 sidecar 只有一個 binary(host arch),
所以另一個 arch 的 .dmg 內 sidecar binary 其實是 host arch,跑不起來。
**短期解**:只發 host arch 的 .dmg。
**長期解**:GitHub Actions matrix(macos-13 x64 + macos-14 arm64),分別 build
再 collect。

### B. Renderer + electron main

```bash
pnpm build:renderer    # vite build → dist/renderer/
pnpm build:electron    # tsc → dist/electron/
```

Renderer 走 Vite production build(minify + tree-shake)。Bundle ~720 KB
(gzip 213 KB),主要是 lucide-react icons + react-markdown 引擎。

### C. electron-builder

```bash
pnpm dist:mac          # build:all + electron-builder --mac
```

`electron-builder.yml` 重點:
- **`electronVersion: 33.4.11`** — npm workspaces hoist 到 root,builder
  introspection 找不到,顯式指定
- **`extraResources`** — sidecar binary 進 `Contents/Resources/sidecar/`
- **`files`** — 只進 `dist/electron/**` + `dist/renderer/**` + `package.json`,
  不打包 src
- **macOS**:DMG installer,arm64 + x64;`hardenedRuntime: true` 給未來 notarize
  鋪路
- **Windows**:NSIS .exe x64
- **Linux**:AppImage x64

輸出:`apps/orion-cowork/dist/installers/Orion Cowork-{version}-{arch}.{ext}`。

## Build matrix(目前手動)

| Platform | 本機 build? | Cross-arch? | 備註 |
|---|---|---|---|
| macOS arm64 (.dmg) | ✓ Apple Silicon 機跑 | sidecar 只有 host arch | 主力 |
| macOS x64 (.dmg) | ✓ Intel Mac 跑 | 同上 | 已 unsigned + unnotarized |
| Windows x64 (.exe) | ✗ 需要 Windows 機 / VM | n/a | 沒測過 |
| Linux x64 (.AppImage) | ✗ 需要 Linux 機 / Docker | n/a | 沒測過 |

CI matrix(下一個 phase)會把這四個自動跑出來。

## 已知問題 / 限制

- **DMG unsigned** — macOS Gatekeeper 第一次開要 user 「右鍵 → 開啟」繞過警告。
  Notarization 是獨立 wishlist item(Phase 31-X)
- **90 MB sidecar binary 偏大** — 主因:anthropic / openai SDK 內 metadata + sqlalchemy
  driver。Optimize 方向:`--strip` + `excludes` 精煉 + 拆 plugin lazy load(>= 1 day)
- **DMG 比 user 想像的大**(arm64 ~187 MB)— Electron runtime 150 MB + sidecar 90 MB
  + renderer / preload < 5 MB
- **Renderer chunk > 500 KB warning** — Vite 提醒。先 ignore,真要小走 dynamic
  `import()` 切 code split,但要重寫 lazy import 邏輯

## Verify the build locally

```bash
# 1. 確認 sidecar binary 能 emit sidecar.ready
apps/orion-cowork/dist/sidecar/orion-cowork-sidecar < /dev/null
# 約 7s 後印出 {"event": "sidecar.ready"} 然後因 stdin EOF 退出

# 2. Mount DMG 拖 .app 進 Applications
open "apps/orion-cowork/dist/installers/Orion Cowork-0.1.0-arm64.dmg"
```

第一次開新 .app 會被 Gatekeeper 警告(unsigned)— 右鍵 → 開啟 → 確認。

## 相關檔

- `apps/orion-cowork/scripts/build-sidecar.sh`     PyInstaller wrapper
- `apps/orion-cowork/sidecar/pyinstaller.spec`     PyInstaller config
- `apps/orion-cowork/electron-builder.yml`         electron-builder config
- `apps/orion-cowork/electron/main.ts:packagedSidecarPath()`  dev vs prod path
- `apps/orion-cowork/electron/sidecar.ts:start()`  spawn binary vs `uv run`
