# Phase 31-A:Cowork packaging

## 速覽

- **預計時程**:1 週
- **前置 Phase**:Phase 30-E(Cowork PoC 跑通)
- **狀態**:📝 spec only,**未實作**
- **目標**:把 Cowork 從「需要 dev 環境跑 `uv run` + `npm run dev`」變成「end-user 雙擊就開」。不含簽章 / notarization(下個 sub-phase B 處理)。

## 1. 兩個打包工具

### 1.1 PyInstaller — 把 Python sidecar 包成 single binary

`apps/orion-cowork/sidecar/` 目前需要 `uv run` 才能跑(吃 workspace venv)。end-user 機器沒有 uv 也沒有 SDK 安裝。

PyInstaller 把 Python interpreter + `orion-sdk` + `orion-model` + 所有 deps 全部打包成單一 `orion-cowork-sidecar`(macOS / Linux)或 `orion-cowork-sidecar.exe`(Windows)。

### 1.2 electron-builder — 把 Electron renderer + main + sidecar 打包成 app

- macOS:`.app` bundle(內含 `Contents/Resources/sidecar/orion-cowork-sidecar`)
- Linux:`.AppImage`(self-contained portable)
- Windows:`.exe`(NSIS installer)

## 2. 任務拆解

### 2.1 PyInstaller sidecar build

- [ ] `apps/orion-cowork/sidecar/` 加 `pyinstaller.spec` 設定:
  - Entry:`src/orion_cowork_sidecar/__main__.py`
  - `--onefile` 模式
  - hidden imports:`sqlalchemy.dialects.sqlite`、`anthropic`、`openai` 等 dynamic-import deps
  - data files:`packages/orion-sdk/src/orion_sdk/skills/bundled/*`、`packages/orion-model/src/orion_model/models.json`
- [ ] Makefile 加 `build-sidecar`:`pyinstaller apps/orion-cowork/sidecar/pyinstaller.spec`
- [ ] 測試:打包後 binary 拿到沒裝 Python 的機器跑 `echo '{"id":"1","method":"ping"}' | ./orion-cowork-sidecar` → 拿到 pong

### 2.2 electron-builder

- [ ] `apps/orion-cowork/package.json` 加 `electron-builder` 為 devDep
- [ ] 寫 `apps/orion-cowork/electron-builder.yml`:
  ```yaml
  appId: dev.orion-agent.cowork
  productName: Orion Cowork
  directories:
    output: dist/installers
  files:
    - dist/electron/**
    - dist/renderer/**
  extraResources:
    - from: ../../dist/sidecar/orion-cowork-sidecar
      to: sidecar/orion-cowork-sidecar
  mac:
    target: [{ target: dmg, arch: [arm64, x64] }]
  win:
    target: [{ target: nsis, arch: [x64] }]
  linux:
    target: [{ target: AppImage, arch: [x64] }]
  ```
- [ ] Makefile 加 `build-cowork`:`build-sidecar && npm run build -w @orion/cowork && npm run dist -w @orion/cowork`

### 2.3 Electron main 改為 production sidecar 路徑

`electron/sidecar.ts:start()` 目前 spawn `uv run --package orion-cowork-sidecar python -m orion_cowork_sidecar`。Production 改為直接 spawn `process.resourcesPath/sidecar/orion-cowork-sidecar`(no Python required)。

```typescript
const sidecarPath = app.isPackaged
  ? path.join(process.resourcesPath, 'sidecar', process.platform === 'win32' ? 'orion-cowork-sidecar.exe' : 'orion-cowork-sidecar')
  : null

if (sidecarPath) {
  proc = spawn(sidecarPath, [], { env: { PYTHONUNBUFFERED: '1' } })
} else {
  // dev mode: spawn uv run as before
  proc = spawn('uv', ['run', '--package', 'orion-cowork-sidecar', ...], { cwd: repoRoot })
}
```

### 2.4 跨平台驗證

- [ ] macOS arm64:dmg install → 開 app → 跑對話
- [ ] macOS x64:同上(若有 Intel Mac)
- [ ] Linux x64(Ubuntu 22.04 VM):AppImage → 雙擊 → 開 app → 跑對話
- [ ] Windows x64:NSIS install → 開 app → 跑對話

## 3. 風險

| 風險 | 緩解 |
|---|---|
| PyInstaller hidden imports 漏(sqlalchemy / anthropic dynamic load) | `.spec` 內顯式 `hiddenimports=[...]`;打包後執行先測 happy path |
| Cross-arch:Mac M1 build 不能 run on Intel | 兩個 arch 各打一次,或 universal2(慢) |
| Sidecar binary 太肥(~150-200MB) | 預期值,無解。.dmg 內壓縮後 ~60-80MB |
| Windows path 跟 `\r\n` | sidecar 內 stdout 強制 `\n`(已做);Windows file path 走 Node `path.join` |
| ANTHROPIC_API_KEY / .env 怎麼進 production | App 加設定畫面讓 user 填 + 存 OS keychain(`keyring`),sidecar 啟動讀 |

## 4. 驗收

- [ ] `make build-cowork` 跑出 3 個 platform 的 installer
- [ ] 拿到沒裝 Python / uv / Node 的機器:雙擊 installer → 開啟 → renderer 顯示 chat UI → 輸入 prompt → streaming 回應正常
- [ ] Sidecar process 不洩漏(close app → `ps` 無 `orion-cowork-sidecar` 殘留)
- [ ] App size 合理(<= 200MB on macOS,<= 150MB AppImage / NSIS)

## 4.5 已知 ship-tooling 痛點(實作中發現)

`npm install` 從 root workspace 跑時,**electron-builder 的 native helper
`app-builder-bin` 沒被裝下來**(可能跟 npm workspaces hoist + optional dep
互動有關)。`npm run dist:mac` 跑時報:

```
spawn .../node_modules/app-builder-bin/mac/app-builder_arm64 ENOENT
```

可能解法(後續驗證):

1. cowork/ 加 `.npmrc` 設 `install-strategy=nested`(npm 9+)
2. 改用 pnpm 取代 npm workspaces(原生支援 nohoist)
3. 在 cowork/ 內 `npm install electron-builder app-builder-bin --no-workspaces`
   強制 local 裝
4. CI build 時改用 `electron-builder` Docker image,繞過 host npm hoist

選擇之前先用 minimal repro 驗,別盲試。Phase 31-A scope 視為「sidecar binary
+ Electron production path 抓取」完成;ship 真正 .dmg / .exe 出貨留下一輪。

## 5. 完成後

Phase 31-A 完成 = Cowork **無簽章版本**可以給內部 / dev 用。要 ship 給外部 user 還缺簽章 → 進 Phase 31-B。
