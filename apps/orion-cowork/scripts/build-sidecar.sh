#!/usr/bin/env bash
# Build sidecar single-binary via PyInstaller — Phase 31-W。
#
# 從 repo root 跑 uv run pyinstaller,輸出落 apps/orion-cowork/dist/sidecar/。
# electron-builder.yml 的 extraResources 會把 binary 抓進 .app/.exe/.AppImage。
#
# Cross-arch:跟著 host(macOS arm64 build arm64 binary,intel host 出 x64)。
# Cross-platform 要去對應 OS 上 build(目前沒 CI,只支援開發機 host arch)。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COWORK_DIR="$(dirname "$SCRIPT_DIR")"
REPO_ROOT="$(cd "$COWORK_DIR/../.." && pwd)"

cd "$REPO_ROOT"

# pyinstaller 在 sidecar 的 dev group;確保裝了
if ! uv run --package orion-cowork-sidecar pyinstaller --version >/dev/null 2>&1; then
  echo "[build-sidecar] pyinstaller not installed — uv sync --group dev"
  uv sync --group dev
fi

# Clean old artifacts
rm -rf "$COWORK_DIR/build/pyinstaller" "$COWORK_DIR/dist/sidecar"

echo "[build-sidecar] running pyinstaller (this takes 1-2 min)..."
uv run --package orion-cowork-sidecar pyinstaller \
  --clean --noconfirm \
  --distpath "$COWORK_DIR/dist/sidecar" \
  --workpath "$COWORK_DIR/build/pyinstaller" \
  "$COWORK_DIR/sidecar/pyinstaller.spec"

BIN="$COWORK_DIR/dist/sidecar/orion-cowork-sidecar"
if [[ "$(uname -s)" == "MINGW"* || "$(uname -s)" == "CYGWIN"* ]]; then
  BIN="${BIN}.exe"
fi

if [[ ! -f "$BIN" ]]; then
  echo "[build-sidecar] ERROR: binary not found at $BIN"
  exit 1
fi

SIZE=$(du -h "$BIN" | cut -f1)
echo "[build-sidecar] ✓ built: $BIN ($SIZE)"
