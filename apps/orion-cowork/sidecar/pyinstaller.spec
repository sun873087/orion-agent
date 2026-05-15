# PyInstaller spec — Cowork sidecar single-binary build.
#
# Build (從 repo root):
#   uv pip install pyinstaller --group dev    # 先確保有 pyinstaller
#   make build-sidecar                          # 跑 pyinstaller apps/orion-cowork/sidecar/pyinstaller.spec
#
# 輸出:dist/sidecar/orion-cowork-sidecar (Linux/macOS) 或
#       dist/sidecar/orion-cowork-sidecar.exe (Windows)

# ruff: noqa
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

REPO_ROOT = Path(SPECPATH).resolve().parents[2]  # spec @ apps/orion-cowork/sidecar/

# Hidden imports — PyInstaller 靜態分析抓不到的動態 import。
HIDDEN = []

# orion-sdk 內某些子 module 透過字串動態 import(plugin / skill loader、
# storage/db dialects)。最保險:把整個 orion_sdk 跟 orion_model 都掃進來。
HIDDEN += collect_submodules("orion_sdk")
HIDDEN += collect_submodules("orion_model")

# DB driver dialects(sqlalchemy 動態 load)
HIDDEN += [
    "sqlalchemy.dialects.sqlite",
    "sqlalchemy.dialects.sqlite.aiosqlite",
    "sqlalchemy.dialects.postgresql",
    "sqlalchemy.dialects.postgresql.asyncpg",
    "aiosqlite",
    "asyncpg",
]

# Anthropic / OpenAI SDK 內部動態 module
HIDDEN += [
    "anthropic._streaming",
    "openai._streaming",
]

# Resource files — bundled skills、prompt templates、models.json 等。
DATAS = []
DATAS += collect_data_files("orion_sdk", includes=["**/*.md", "**/*.json", "**/*.yaml"])
DATAS += collect_data_files("orion_model", includes=["**/*.json"])

block_cipher = None

a = Analysis(
    [str(REPO_ROOT / "apps/orion-cowork/sidecar/src/orion_cowork_sidecar/__main__.py")],
    pathex=[
        str(REPO_ROOT / "apps/orion-cowork/sidecar/src"),
        str(REPO_ROOT / "packages/orion-sdk/src"),
        str(REPO_ROOT / "packages/orion-model/src"),
    ],
    binaries=[],
    datas=DATAS,
    hiddenimports=HIDDEN,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # 不需要進 sidecar 的東西
        "tkinter",
        "test",
        "unittest",
        "pytest",
        "ipython",
        "jupyter",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="orion-cowork-sidecar",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # sidecar 需要 stdin/stdout
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,  # 跟著 host arch;cross-arch 另起一次 build
    codesign_identity=None,
    entitlements_file=None,
)
