# Phase 31-B:Cowork signing + auto-update

## 速覽

- **預計時程**:1 週工作 + 申請開發者帳號的等待(Apple 1-2 天、Microsoft 數小時)
- **前置 Phase**:31-A(packaging)
- **狀態**:📝 spec only,**未實作**
- **目標**:end-user 雙擊安裝**不被 OS 警告 "unidentified developer"**,並支援自動更新。

## 1. 為何需要

無簽章 app 在 macOS / Windows 都會被擋:

- **macOS**:Gatekeeper 顯示 "cannot be opened because the developer cannot be verified",user 要右鍵 Open + 在 System Preferences 額外授權
- **Windows**:SmartScreen 顯示 "Windows protected your PC",有 "More info → Run anyway" 選項但會嚇退一般 user
- **Linux**:.AppImage 本身不需要簽章

簽章 + notarization 解決這些。

## 2. macOS

### 2.1 申請

- Apple Developer Program $99/year
- 申請 "Developer ID Application" 跟 "Developer ID Installer" certificate
- 在 Apple Developer portal 啟用 App-specific password(用於 notarytool 上傳)

### 2.2 流程

`electron-builder` 內建支援:

```yaml
# electron-builder.yml
mac:
  hardenedRuntime: true
  entitlements: build/entitlements.mac.plist
  notarize:
    teamId: ${env.APPLE_TEAM_ID}
afterSign: scripts/notarize.js  # 如果 electron-builder 內建 notarize 不夠
```

簽章 cert 從 macOS Keychain 載入。CI 環境用 `electron-builder` 的 `CSC_LINK` + `CSC_KEY_PASSWORD` env vars 載 .p12。

### 2.3 entitlements

Cowork 需要的:

```xml
<key>com.apple.security.cs.allow-jit</key><true/>             <!-- Electron V8 JIT -->
<key>com.apple.security.cs.allow-unsigned-executable-memory</key><true/>
<key>com.apple.security.cs.disable-library-validation</key><true/>  <!-- PyInstaller sidecar -->
<key>com.apple.security.files.user-selected.read-write</key><true/>  <!-- Read tool -->
<key>com.apple.security.network.client</key><true/>            <!-- HTTP to API providers -->
```

### 2.4 任務

- [ ] 申請 Apple Developer Program
- [ ] 下載 Developer ID certificate
- [ ] 寫 `apps/orion-cowork/build/entitlements.mac.plist`
- [ ] electron-builder.yml 加 mac.notarize 設定
- [ ] 設 env vars `APPLE_ID` / `APPLE_APP_SPECIFIC_PASSWORD` / `APPLE_TEAM_ID`
- [ ] CI(若有)新增 macOS runner + Keychain 解鎖步驟
- [ ] 驗證:打包出來的 .dmg 在乾淨 macOS 雙擊安裝 → 開 app 無警告

## 3. Windows

### 3.1 申請

- EV Code Signing Certificate(DigiCert / Sectigo / GlobalSign),約 $300-700/year
- EV cert 才能立即過 SmartScreen reputation(普通 cert 要累積 install 數)
- 或退而求其次:Self-signed + 走 user manually trust(不推薦給 production)

### 3.2 流程

```yaml
win:
  certificateFile: build/certificate.pfx
  certificatePassword: ${env.WIN_CERT_PASSWORD}
  signingHashAlgorithms: [sha256]
  publisherName: "Your Org"
```

### 3.3 任務

- [ ] 採購 EV Code Signing Cert(常需要實體 USB token,影響 CI)
- [ ] electron-builder.yml 加 Windows signing 設定
- [ ] 驗證:乾淨 Windows 機器 install → SmartScreen 不再警告

## 4. Auto-update(electron-updater)

### 4.1 設計

- App 啟動時檢查 update server,有新版下載 + 通知 user
- electron-builder 跟 electron-updater 整合,publish 設定 GitHub Releases 或自架 S3:

```yaml
publish:
  - provider: github
    owner: <org>
    repo: orion-agent
```

### 4.2 流程

1. CI build → 上傳 .dmg / .exe / .AppImage + `latest-mac.yml` / `latest.yml` / `latest-linux.yml` 到 GitHub Release
2. App 開機 → fetch `latest-*.yml` 比版本 → 通知 user
3. 點 install → 下載差量 / 完整新版 → 重啟 app

### 4.3 任務

- [ ] `apps/orion-cowork/package.json` 加 `electron-updater` deps
- [ ] electron/main.ts 加 update check init
- [ ] renderer 加 "有新版可用" notification 元件
- [ ] 確認簽章後的 update package 才能被 electron-updater 接受
- [ ] 設 GitHub Release(或自架 S3 / nginx)當 update channel

## 5. 風險

| 風險 | 緩解 |
|---|---|
| Apple notarization 排隊 1-2 天 | 預留 buffer;同期可做 Windows / Linux |
| EV cert 採購需要法人實體 | 個人專案可 fallback 一般 cert + 承受 SmartScreen warning |
| Update package 整顆下載太慢 | electron-updater 支援差量 update,但需 build server 多保留歷史版本 |
| 中國地區 GitHub 下載慢 | 自架 mirror 或用 CDN |
| 簽章 cert 過期 | 一年要 renew + rebuild,記事項 |

## 6. 驗收

- [ ] macOS:乾淨機器 .dmg install → 雙擊 .app 無 Gatekeeper 警告
- [ ] Windows:乾淨機器 .exe install → 無 SmartScreen 警告
- [ ] App 開啟 → 偵測新版 → user 點 install → 自動更新到新版
- [ ] Update 過程不破壞既有 sidecar 進程 / 對話資料

## 7. 完成後

Phase 31-B 完成 = Cowork **真正可以給外部 user**。
