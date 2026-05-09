# Phase 11 — Input Pipeline 完工記錄

**完成日期**:2026-05-07
**Plan doc**:`docs/phases/11-input-pipeline.md`(範圍 A:spec 推薦 web-chat 精簡版 —
slash registry + 2 內建 + image + upload + token_estimation;**不含** !shell /
@file ref / 6 個 CLI 內建,留 Phase 11c。)
**狀態**:✅ `make check` 全綠 — **558 unit tests passed, 0 skipped**(17s),
ruff clean,mypy --strict 169 files clean。

---

## 交付清單

### 新增模組

```
src/orion_agent/
├── commands/                             [全新,5 檔]
│   ├── __init__.py
│   ├── types.py                          Command Protocol + CommandResult
│   ├── registry.py                       全域 registry + register_builtins()
│   └── builtin/
│       ├── __init__.py
│       ├── help.py                       /help — 列已註冊命令
│       └── model.py                      /model — 顯示 / 切換 / list 模型
├── input/                                [全新,5 檔]
│   ├── __init__.py
│   ├── slash.py                          is_slash_command + parse_slash
│   ├── process_input.py                  主協調器(yield UserMessage / CommandResult /
│   │                                       CommandInject / Error events)+ RawInput +
│   │                                       ImageAttachment + FileUploadRef dataclasses
│   ├── image.py                          base64 + media_type + decode_data_url +
│   │                                       to_content_block(無 PIL)
│   └── upload.py                         UploadStore — save / read / read_text /
│                                          delete / list,per-user 隔離 + size limit
├── services/token_estimation.py          [新] rough(CJK 1 char/tok / Latin 4 char/tok)+
│                                          rough_messages_token_count + 兩階段
│                                          estimate_with_two_phase
└── api/routes/uploads.py                 [新] POST /uploads(multipart)+ GET /uploads +
                                          DELETE /uploads/{id}
```

### 修改既有檔

```
src/orion_agent/api/app.py                lifespan 加 register_builtins() + 註冊 uploads_router
```

### Tests(全新,7 檔,共 59 案例)

```
tests/unit/commands/
├── test_registry.py               6 tests(register / dup / 空名 / list 排序 / idempotent / Protocol check)
└── test_builtin.py                6 tests(/help 列出 / 空 / /model 顯示 / list / switch / no provider)
tests/unit/input/
├── test_slash.py                  9 tests(基本 / 雙斜線 / 空 / 數字開頭 / 連字 / parse / 多字 / strip)
├── test_process_input.py          10 tests(plain / empty / unknown slash / execute / crash /
│                                            inject / new_user_message / image / upload / pure text)
├── test_image.py                  8 tests(media_type / encode / size / file / data URL / invalid / block)
└── test_upload.py                 10 tests(save+read / text / 隔離 / size limit / sanitize /
                                            delete / unknown / list / invalid id / no dir)
tests/unit/services/
└── test_token_estimation.py       10 tests(empty / Latin / CJK / messages / 兩階段四種路徑)
```

---

## 設計決策

### 1. Web-chat 場景大幅精簡(spec 推薦)

對應 spec § ⚠️ Web Chat 場景大幅精簡:

| TS 設計 | Phase 11 對應 |
|---|---|
| `/clear` `/compact` `/init` `/memory` `/cost` `/history` | ❌ 由前端 UI 取代(有需要再 Phase 11c 補) |
| `/model` `/help` | ✅ 保留(Phase 11 內建) |
| `@file` ref | ✅ 改 file upload(`/uploads` REST + ContentBlock 注入) |
| `!shell` 直接執行 | ❌ SaaS 危險 — 不做(Phase 11c 加 ORION_ALLOW_SHELL_INPUT 升旗才開) |

只保留 2 個內建命令 — `/model` `/help`。其餘 6 個 spec 推薦由前端側欄 / 按鈕取代。

### 2. CommandResult 三條輸出路徑

```python
@dataclass
class CommandResult:
    text: str | None              # UI 顯示但不送 API
    new_user_message: str | None  # 轉成 user message 進 query loop(/init 模式)
    inject_into_prompt: str | None # 注入下次 system prompt(/memory 模式)
    side_effect: str | None       # 純描述(已執行的動作)
```

caller(process_user_input)依路徑 yield 對應 event。

### 3. process_user_input 4 種輸出 event

```
UserMessageEvent      ← 真正進 query loop
CommandResultEvent    ← UI 顯示 / 不送 API
CommandInjectEvent    ← 注入下次 system prompt
InputErrorEvent       ← 處理失敗(未知命令、空輸入、execute crash)
```

模仿 Phase 6 WebSocket event union 設計。

### 4. RawInput vs str — 多型 input

純文字直接傳 str(便利);多 metadata(images / uploads)用 `RawInput` dataclass。
process_user_input 兩種都吃。Image / upload attachment 自動轉 ContentBlock list:

```python
[
  {"type": "text", "text": "describe + [Attached file: x.py (id: abc123)]"},
  {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "..."}},
]
```

直接餵 Anthropic vision API 格式。

### 5. file upload 取代 `@file` ref

`/uploads` POST(multipart/form-data)→ 存 `~/.orion/uploads/<user_id>/<id>.<ext>`,
回 `{upload_id, filename, size}`。Agent 用 `read_upload(user_id, upload_id)` 讀內容。

filename **sanitize**(只留字母 / 數字 / `.`-`_`,擋 path traversal),size limit 10 MB。
per-user 隔離(`/uploads/<user_id>/` 子目錄)。`ORION_HOME` 可換目錄。

對應 spec § Phase 11 § 1.7。

### 6. CJK-aware rough token count

```
- 純拉丁(英 / 程式碼)→ chars / 4
- 含 CJK / 全形 → chars × 1(保守高估)
```

對應 GPT / Claude tokenizer 對中日韓字元 1:1 的近似。

### 7. 兩階段 estimate

```
rough ≤ threshold * 0.5    → 確定不超(便宜路徑,跳過 precise)
rough > threshold          → 確定超(便宜路徑)
threshold * 0.5 < rough <= threshold → 灰色 → 呼 precise_counter callback
```

caller 不需強制提供 precise_counter;沒提供時用 rough fallback。對應 TS
`MCP_TOKEN_COUNT_THRESHOLD_FACTOR = 0.5`。

### 8. 不依賴外部 tokenizer

`token_estimation` 模組**沒有**直接 import Anthropic SDK;caller(typically
Phase 3 memory selector / Phase 5 mcpValidation / Phase 11 input)自己提供
`precise_counter: async (msgs) -> int`,本檔保持 no-dep 純 Python 實作。

---

## REST API 變更

新 endpoint:

```
POST   /uploads            multipart file → 回 {upload_id, filename, size}
GET    /uploads            回 list of UploadSummary(只看 user 自己的)
DELETE /uploads/{id}       刪除單一 upload
```

JWT-protected(`current_user` dep)。size limit 10 MB,filename auto-sanitize。

---

## 環境變數

| Env | 用途 |
|---|---|
| `ORION_HOME` | settings + uploads 目錄(預設 `~/.orion`)。Phase 10 `ConfigTool` 同 env。 |

---

## Verification

```bash
cd orion-agent/api/

make check
# → ruff All checks passed!
# → mypy --strict: 169 files, 0 issues
# → pytest: 558 passed, 0 skipped(17s)

# upload demo
ORION_HOME=/tmp/orion-up uv run orion serve --port 8765 &
TOKEN=$(curl -s -X POST http://127.0.0.1:8765/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"alice","password":""}' | jq -r .token)
curl -s -X POST http://127.0.0.1:8765/uploads \
  -H "Authorization: Bearer $TOKEN" \
  -F file=@README.md
# 預期:{ "upload_id": "...", "filename": "README.md", "size": 123 }

curl -s http://127.0.0.1:8765/uploads -H "Authorization: Bearer $TOKEN" | jq

# slash 命令(WebSocket runner 整合留 Phase 11c)
.venv/bin/python -c "
import asyncio
from orion_agent.commands.registry import register_builtins
from orion_agent.commands.builtin.help import HelpCommand
register_builtins()
print(asyncio.run(HelpCommand().execute('', None, None)).text)
"
```

---

## Phase 11 故意先不做(都已開新 phase plan)

| 項目 | 留給 |
|---|---|
| `!shell` 直接執行(走 Phase 7 sandbox + ORION_ALLOW_SHELL_INPUT 升旗) | Phase 11c(`docs/phases/11c-extra-slash-and-shell.md`) |
| `@file` ref(自動讀檔注入)— 改用 upload | Phase 11c(若仍想保留 CLI 體驗) |
| 6 個 CLI 內建(/clear / /compact / /init / /memory / /cost / /history) | Phase 11c |
| WebSocket UserMessageEvent.attachments 欄位整合(目前 /uploads 用 separate REST)| Phase 11c |
| Image 壓縮(超 5 MB / 2048px 自動 PIL thumbnail) | Phase 11c |
| Plugin 註冊 slash 命令(對應 Phase 8 plugin manifest 加 commands 欄位) | Phase 11c |
| PromptSuggestion(speculative execution + Haiku 預測 next prompt) | OPTIONAL § 4 |

---

## 風險與已緩解

| 風險 | 緩解 |
|---|---|
| Slash 命令 typo(`/clr` 寫錯)→ silent ignore | parse 偵測 → unknown 命令回 InputErrorEvent(不 crash 對話) |
| Upload path traversal(`../../etc/passwd`) | filename 用 basename + 字元 whitelist,絕不可能逃出 user 目錄 |
| Upload 巨大檔案撐爆 disk | save_upload size limit(預設 10 MB);超過 raise UploadTooLargeError |
| Slash 命令 execute crash 影響 WebSocket session | process_user_input try/except 包,失敗 yield InputErrorEvent |
| CJK token 估算誤差(rough 高估) | 設計上保守,寧願多算（避免 truncate 太晚)。若 production 證明高估太多,Phase 11c 改更精細 char class |
| upload_id 碰撞(uuid hex[:16]) | 16 hex char ≈ 64 bits,機率極低;Phase 11c 可加 collision check + retry |
| process_user_input WebSocket 整合未做 | 文件清楚標示 Phase 11c;`/uploads` 已可獨立用 |

---

## Tests 摘要

| Suite | 數量 | 說明 |
|---|---|---|
| Phase 0–10 既有 | 499 | 全綠不動 |
| **Phase 11 commands**(registry / 內建) | 12 | |
| **Phase 11 input**(slash / process / image / upload) | 37 | |
| **Phase 11 services**(token_estimation) | 10 | |
| **總計** | **558** | mypy --strict 169 files / ruff 全綠 |
