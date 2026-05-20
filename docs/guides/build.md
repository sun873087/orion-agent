# Building Cowork for distribution

PyInstaller sidecar binary + electron-builder cross-platform installer。

## Prerequisites

- Python ≥ 3.11
- Node ≥ 20 + pnpm
- PyInstaller(via dev deps:`uv sync`)
- electron + electron-builder(via `pnpm install`)
- macOS:`xcode-select --install`(arm64 build 用)
- Windows:Visual Studio Build Tools(NSIS 生成用)
- Linux:`fuse` for AppImage

## 一鍵 build all

```bash
cd apps/orion-cowork
pnpm dist
# = build:sidecar(PyInstaller)+ build:renderer(Vite)+ build:electron(tsc)+ electron-builder pack
```

平台輸出:`dist/installers/`

- macOS:`Orion Cowork-<ver>-arm64.dmg` + `-x64.dmg`(各約 200 MB)
- Windows:`Orion Cowork-<ver>-x64.exe`(NSIS installer)
- Linux:`Orion Cowork-<ver>.AppImage`

## 各步驟拆解

### 1. Sidecar(PyInstaller)

```bash
pnpm build:sidecar
# = bash scripts/build-sidecar.sh
# → dist/sidecar/orion-cowork-sidecar  (90 MB single binary)
```

包含 Python interpreter + orion-sdk + 全 deps。Cold start 比 dev mode 快(沒 uv resolve)。

### 2. Renderer + Electron

```bash
pnpm build:renderer    # Vite build → dist/renderer/
pnpm build:electron    # tsc → dist/electron/
```

Vite 設 `base: './'` 讓 Electron `file://` protocol 能讀 assets。

### 3. Pack

```bash
pnpm build && electron-builder --config electron-builder.yml [--mac|--win|--linux]
```

`electron-builder.yml`:
- `files`:dist/electron + dist/renderer
- `extraResources`:`dist/sidecar/orion-cowork-sidecar` → `Resources/sidecar/`
- 平台:DMG / NSIS / AppImage

## Code signing(production)

macOS:

```bash
export CSC_LINK=base64-encoded-or-path-to-.p12
export CSC_KEY_PASSWORD=<p12-password>
export APPLE_ID=<apple-id-email>
export APPLE_APP_SPECIFIC_PASSWORD=<app-specific-pwd>
export APPLE_TEAM_ID=<team-id>

pnpm dist:mac
# electron-builder 自動跑 codesign + notarytool
```

Windows:

```bash
export WIN_CSC_LINK=path-to-.pfx
export WIN_CSC_KEY_PASSWORD=<pwd>

pnpm dist:win
```

沒設這些 env → unsigned build,user 機要手動 bypass Gatekeeper / SmartScreen。

## 自動發布(GitHub Releases + Auto-update)

`electron-builder.yml` 內 `publish: github`(已設好)。流程:

```bash
# 在 main branch
npm version patch  # 0.1.0 → 0.1.1
git push --tags

# Build + 上傳到 GitHub Release
GH_TOKEN=ghp_... pnpm dist
# electron-builder 自動建 GitHub Release(draft)+ upload DMG / EXE / AppImage + latest.yml

# 到 GitHub UI 把 draft release publish
```

User 開現有 Cowork → electron-updater check `latest.yml` → 偵測新版 → 下載 → 推 toast。

## CI/CD(建議)

GitHub Actions 設 workflow:

```yaml
on:
  push:
    tags: ['v*']

jobs:
  build-mac:
    runs-on: macos-latest
    steps:
      # ... checkout + uv sync + pnpm install ...
      - run: pnpm dist:mac
        env:
          CSC_LINK: ${{ secrets.CSC_LINK }}
          APPLE_ID: ${{ secrets.APPLE_ID }}
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

3 個 platform(mac / win / linux)平行跑,各自 upload 到同一 release。

## 看完繼續

- [`../features/cowork.md`](../features/cowork.md) — Cowork 結構
- [troubleshooting.md](./troubleshooting.md) — build 失敗排查
