#!/usr/bin/env bash
# Dev 用 — 改 node_modules/electron/dist/Electron.app 的 CFBundleName / CFBundleDisplayName
# 為 "Orion Cowork",讓 dock hover / cmd-tab 顯正確 app 名,不再是 "Electron"。
#
# Production build 由 electron-builder 處理,不會經過這個 script。
# npm install / reinstall 後 plist 會還原,所以 dev:electron 每次都跑一次。
set -e

APP_NAME="Orion Cowork"

# 找最近的 node_modules/electron/dist/Electron.app — monorepo hoist 可能放
# 在 cowork 自己的 node_modules,也可能放在 repo root。
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CANDIDATES=(
  "$SCRIPT_DIR/../node_modules/electron/dist/Electron.app"
  "$SCRIPT_DIR/../../../node_modules/electron/dist/Electron.app"
  "$SCRIPT_DIR/../../node_modules/electron/dist/Electron.app"
)

APP_PATH=""
for c in "${CANDIDATES[@]}"; do
  if [ -d "$c" ]; then
    APP_PATH="$c"
    break
  fi
done

if [ -z "$APP_PATH" ]; then
  echo "[dev-brand-electron] Electron.app not found; skipping (production build unaffected)."
  exit 0
fi

PLIST="$APP_PATH/Contents/Info.plist"
if [ ! -f "$PLIST" ]; then
  echo "[dev-brand-electron] Info.plist not found at $PLIST; skipping."
  exit 0
fi

CURRENT=$(/usr/libexec/PlistBuddy -c "Print :CFBundleName" "$PLIST" 2>/dev/null || echo "")
if [ "$CURRENT" = "$APP_NAME" ]; then
  exit 0
fi

/usr/libexec/PlistBuddy -c "Set :CFBundleName $APP_NAME" "$PLIST"
/usr/libexec/PlistBuddy -c "Set :CFBundleDisplayName $APP_NAME" "$PLIST" 2>/dev/null || \
  /usr/libexec/PlistBuddy -c "Add :CFBundleDisplayName string $APP_NAME" "$PLIST"

# touch app 讓 LaunchServices 重 cache(否則 dock 還是舊名)
touch "$APP_PATH"

echo "[dev-brand-electron] renamed Electron.app → \"$APP_NAME\""
