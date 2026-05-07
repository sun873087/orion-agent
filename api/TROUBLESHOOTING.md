# Troubleshooting

## `ModuleNotFoundError: No module named 'orion_agent'`

**症狀**:跑 `uv run orion ...` 或 `uv run pytest` 時出現此錯。
但前一秒明明 `make install` 看起來正常。

**根因**(macOS 環境特定):

`~/Desktop` 與 `~/Documents` **被 iCloud Drive 自動同步**(macOS 預設啟用)。
`uv pip install --reinstall` 在寫 `.venv/.../site-packages/orion_agent-0.1.0.dist-info/`
時,iCloud 偶發看到 file lock / hash 衝突,**自動 rename 新檔案加 " 2"、" 3" 後綴**。

結果:
- `dist-info/` 內塞滿 `RECORD 2`、`METADATA 5`、`uv_cache 7.json` 等 dupe
- 真正的 `RECORD` 可能被覆蓋或失效
- Python import system 看到 dist-info 但找不到對應 source → 報 ModuleNotFoundError

確認方式:
```bash
ls .venv/lib/python3.12/site-packages/orion_agent-0.1.0.dist-info/ | grep " [2-9]"
```
若有任何輸出 → 確認被 iCloud 污染。

---

## 解法

### 立即救援(已被污染的 .venv)

```bash
make fix-install
```

會清掉 `.venv` 內所有 `* 2` / `* 3` 等 iCloud 殘檔,然後重灌。

或更暴力:
```bash
make clean-venv && make install
```

### 根本解法(三選一)

#### 1. 把專案搬出 Desktop / Documents(推薦)

```bash
mv ~/Desktop/claude-code-source-main ~/code/
```

`~/code/` 不被 iCloud 同步,從此沒問題。

#### 2. 關 iCloud Desktop & Documents Sync

System Settings → Apple Account → iCloud → Drive → Options → 取消 "Desktop & Documents Folders"。
**注意**:這會把現有檔案搬回本機(可能要等同步)。

#### 3. 用 `.nosync` 後綴排除 .venv

macOS 的 iCloud 不同步以 `.nosync` 結尾的檔案 / 目錄。可以:

```bash
mv .venv .venv.nosync
ln -s .venv.nosync .venv
```

但 uv / pytest 看到 symlink 可能行為不一致,**最不推薦**。

---

## 為何 Makefile 的 `install` 連跑兩步?

```makefile
install:
	uv sync
	uv pip install -e . --reinstall
```

`uv sync` 應該已含 editable install。但 iCloud 偶發 rename 會讓 sync 留下半成品。
第二步 `uv pip install -e . --reinstall` 是 belt-and-suspenders — 確保 `.pth` 真的存在。

正常環境(非 Desktop)第二步是 no-op 級別,不影響。
