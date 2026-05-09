# Phase 11:Input Pipeline(使用者輸入管線)

## 速覽

- **預計時程**:1-2 週
- **前置 Phase**:Phase 1(Conversation)、Phase 4(system prompt)、Phase 6(FastAPI)
- **本文件目的**:補 Phase 1-10 漏掉的「使用者輸入到 prompt 的中間處理層」
- **主要交付物**:
  - Slash 命令系統(基礎 8-10 個必要命令)
  - `processUserInput`(slash 展開 / `!shell` / `@file` ref / paste)
  - Image input 鏈路(paste base64 → ContentBlock)
  - Token estimation(rough + precise 兩階段)

## ⚠️ Web Chat 場景大幅精簡

> **TS 原設計**(CLI):103 個 slash 命令、`@file` ref 讀本機檔、`!cmd` 直接 shell。
>
> **Web chat 改為**:
>
> | TS 設計 | Web chat 對應 |
> |---|---|
> | `/clear` | ❌ 用前端「New Chat」按鈕取代 |
> | `/compact` | ❌ 後端自動觸發即可,不需 user 手動 |
> | `/init` | ❌ web chat 沒「project」概念 |
> | `/memory` | ❌ 用側欄 UI(列 / 改 / 刪 memory) |
> | `/cost` | ❌ 用側欄顯示用量 |
> | `/history` | ❌ 用側欄 conversation list |
> | `/model` | ✅ 保留(或前端 dropdown) |
> | `/help` | ✅ 保留 |
> | `@file` ref | ❌ 改「附件上傳」UI 元件,前端 base64 上傳 |
> | `!shell` | ❌ **拿掉**(SaaS 危險);user 用正常 prompt 走 BashTool 即可 |
>
> **Phase 11 大幅精簡**:slash registry 仍要做(因為 plugin 可加自訂 slash),但內建只做 `/model` `/help`。`@file` 換成檔案上傳機制。`!shell` 完全不做。

## 1. 為何需要本 phase?

Phase 1 的 `Conversation.submit_message(prompt: str)` **直接把字串送 query loop**。漏了原專案有的中間層:

```
原專案:
  使用者打字 ─▶ processUserInput ─▶ 解析 / 展開 ─▶ Conversation
                    ↓
                  ├─ /slash 命令
                  ├─ !shell 命令
                  ├─ @file ref(自動讀檔)
                  └─ 圖片 paste

Phase 1-10 之前:
  使用者打字 ─▶ 直接送 ─▶ Conversation
                          (chat UI 體驗陽春)
```

**對應 TS 源碼**:
- `src/utils/processUserInput/`(4 檔,共 1765 行!)
- `src/commands.ts` + `src/commands/`(103 個 slash 命令)
- `src/services/tokenEstimation.ts`

## 2. TS 源檔映射

| Python 模組 | 對應 TS 源檔 | 行數 | 注意 |
|---|---|---|---|
| `src/input/process_input.py` | `src/utils/processUserInput/processUserInput.ts` | 605 | 主協調 |
| `src/input/slash.py` | `src/utils/processUserInput/processSlashCommand.tsx` | 921 | Slash 解析展開 |
| `src/input/shell.py` | `src/utils/processUserInput/processBashCommand.tsx` | 139 | `!cmd` 直接執行 |
| `src/input/text.py` | `src/utils/processUserInput/processTextPrompt.ts` | 100 | `@file` 自動讀 |
| `src/input/image.py` | (散落)| — | base64 paste |
| `src/commands/registry.py` | `src/commands.ts` | 25 KB | Command 介面 + 註冊 |
| `src/commands/builtin/*.py` | `src/commands/<name>/` 子目錄 | 各 | 每個 slash 命令 |
| `src/services/token_estimation.py` | `src/services/tokenEstimation.ts` | — | 兩階段 token count |

## 3. 任務拆解

### Web Chat 精簡版任務拆解(1 週)

- [ ] 1.1 `commands/types.py`:`Command` Protocol(plugin 可註冊新 slash)
- [ ] 1.2 `commands/registry.py`:registry(主要給 plugin 用)
- [ ] 1.3 **2 個內建命令**:
  - [ ] `model.py` — 切模型(也可前端 dropdown 取代)
  - [ ] `help.py` — 列命令清單
- [ ] 1.4 `input/process_input.py`:主協調器(slash + 上傳檔 + 圖片)
- [ ] 1.5 `input/slash.py`:檢測 `/cmd args`(plugin 加的命令在這 dispatch)
- [ ] 1.6 ❌ ~~`input/shell.py`(`!cmd` 不做,SaaS 不該預設開)~~
- [ ] 1.7 `input/upload.py`:**檔案上傳**(取代 TS `@file` ref)
  - 前端 multipart upload 或 base64 → 後端存 `tool-results/uploads/<id>.<ext>`
  - 注入到 prompt:`[Attached file: filename.py - id: <upload_id>]`
  - Tool 透過 `read_upload(upload_id)` 取內容
- [ ] 1.8 `input/image.py`:base64 image → ContentBlock 格式(同 Phase 11 原設計)
- [ ] 1.9 `services/token_estimation.py`:兩階段(原設計不變)
- [ ] 1.10 整合到 Phase 6 WebSocket:訊息有 `attachments`(uploads / images)欄位
- [ ] 1.11 (進階)PromptSuggestion 簡化版

### TS 原版的 8 個 slash 命令對應到前端 UI

| TS slash 命令 | Web chat UI 元件 |
|---|---|
| `/clear` | 「New Chat」按鈕(POST /sessions 開新 session) |
| `/compact` | 自動觸發,前端不暴露(或 admin 設定) |
| `/init` | 不適用(無 project 概念) |
| `/memory` | 側欄「Memory」分頁(GET / PUT /memories) |
| `/cost` | 側欄「Usage」顯示(GET /sessions/{id}/cost) |
| `/history` | 側欄「History」conversation list |
| `/model` | header dropdown 或 `/model` slash |
| `/help` | help 按鈕或 `/help` slash |
- [ ] 2.8 **(可選)PromptSuggestion 簡化版**:對應 TS `services/PromptSuggestion/`(1514 行)
   - `suggestions/predictor.py`:user 打字時,後端用 Haiku 預測 next prompt
   - WebSocket 推 `suggestions` event 給前端顯示 autocomplete
   - 完整 speculative execution 留 [OPTIONAL § 4](./OPTIONAL.md)

## 4. 模組架構

```
src/claude_agent_py/
├── commands/
│   ├── __init__.py
│   ├── types.py                        # ◀ Command Protocol
│   ├── registry.py                     # ◀ 全域註冊
│   └── builtin/
│       ├── clear.py
│       ├── compact.py
│       ├── init.py
│       ├── memory.py
│       ├── cost.py
│       ├── model.py
│       ├── help.py
│       └── history.py
│
├── input/
│   ├── __init__.py
│   ├── process_input.py                # ◀ 主協調
│   ├── slash.py                        # ◀ /cmd 解析展開
│   ├── shell.py                        # ◀ !cmd 直接執行
│   ├── text.py                         # ◀ @file ref + paste
│   └── image.py                        # ◀ base64 image
│
└── services/
    └── token_estimation.py             # ◀ 兩階段 token count
```

## 5. Python Skeleton

### 5.1 `commands/types.py`

```python
"""Command Protocol。對應 TS Command interface(commands.ts)。"""
from __future__ import annotations
from typing import Protocol, runtime_checkable, AsyncIterator
from pydantic import BaseModel

from claude_agent_py.core.state import AgentContext


class CommandResult(BaseModel):
    """命令執行結果。可能是純文字 / 修改 conversation state / 結束 session。"""
    text: str | None = None
    """要顯示給使用者的文字。"""

    inject_into_prompt: str | None = None
    """要注入到下一輪 system prompt 的內容(例 /memory 把記憶塞進去)。"""

    new_user_message: str | None = None
    """轉換成 user message 進 conversation(例 !cmd 結果)。"""

    side_effect: str | None = None
    """side effect 描述(已執行的動作)。"""


@runtime_checkable
class Command(Protocol):
    name: str
    """命令名稱(不含 / 前綴)。"""

    description: str
    """help 顯示用。"""

    async def execute(
        self,
        args: str,
        ctx: AgentContext,
        conversation,
    ) -> CommandResult:
        ...
```

### 5.2 `commands/registry.py`

```python
"""Command 註冊表。"""
from __future__ import annotations
from claude_agent_py.commands.types import Command


_registry: dict[str, Command] = {}


def register(cmd: Command) -> None:
    if cmd.name in _registry:
        raise ValueError(f"Command {cmd.name} already registered")
    _registry[cmd.name] = cmd


def get(name: str) -> Command | None:
    return _registry.get(name)


def list_all() -> list[Command]:
    return list(_registry.values())


def register_builtins() -> None:
    """啟動時呼叫一次。"""
    from claude_agent_py.commands.builtin import (
        clear, compact, init, memory, cost, model, help as help_cmd, history,
    )
    register(clear.ClearCommand())
    register(compact.CompactCommand())
    register(init.InitCommand())
    register(memory.MemoryCommand())
    register(cost.CostCommand())
    register(model.ModelCommand())
    register(help_cmd.HelpCommand())
    register(history.HistoryCommand())
```

### 5.3 `commands/builtin/clear.py`(範例)

```python
"""/clear — 清訊息 + clear section cache。"""
from __future__ import annotations
from claude_agent_py.commands.types import CommandResult
from claude_agent_py.prompt.sections import clear_system_prompt_sections


class ClearCommand:
    name = "clear"
    description = "Clear conversation messages and reset section cache."

    async def execute(self, args, ctx, conversation) -> CommandResult:
        conversation.mutable_messages.clear()
        conversation.permission_denials.clear()
        clear_system_prompt_sections()
        return CommandResult(text="Conversation cleared.")
```

### 5.4 `commands/builtin/compact.py`

```python
"""/compact — 手動觸發 compaction。"""
from claude_agent_py.commands.types import CommandResult
from claude_agent_py.compact.auto import auto_compact


class CompactCommand:
    name = "compact"
    description = "Manually compact conversation history."

    async def execute(self, args, ctx, conversation) -> CommandResult:
        new_messages = await auto_compact(conversation.mutable_messages, ctx, force=True)
        if new_messages is None:
            return CommandResult(text="Nothing to compact.")
        conversation.mutable_messages = new_messages
        return CommandResult(text=f"Compacted to {len(new_messages)} messages.")
```

### 5.5 `commands/builtin/init.py`

```python
"""/init — 自動產生 CLAUDE.md。

對應 TS commands/init/。讓 agent 自己 explore + 寫 CLAUDE.md。
"""
from claude_agent_py.commands.types import CommandResult


INIT_PROMPT = """Analyze this codebase and write a CLAUDE.md file at the project root.

Include:
1. Project structure overview
2. Build / test / run commands
3. Key conventions
4. Important context for future Claude sessions

Use Read / Glob / Grep tools to explore. Then Write the file."""


class InitCommand:
    name = "init"
    description = "Auto-generate CLAUDE.md by analyzing the codebase."

    async def execute(self, args, ctx, conversation) -> CommandResult:
        # /init 是把 prompt 注入主對話,不是直接修改 state
        return CommandResult(new_user_message=INIT_PROMPT)
```

### 5.6 `input/process_input.py`(主協調)

```python
"""Input pipeline 主協調。對應 TS processUserInput.ts。"""
from __future__ import annotations
from typing import AsyncIterator

from claude_agent_py.commands.registry import get as get_command
from claude_agent_py.commands.types import CommandResult
from claude_agent_py.core.state import AgentContext
from claude_agent_py.input.slash import is_slash_command, parse_slash
from claude_agent_py.input.shell import is_shell_command, exec_shell
from claude_agent_py.input.text import expand_file_refs, extract_attachments


async def process_user_input(
    raw: str | dict,  # str 或 {text, images} 含圖
    ctx: AgentContext,
    conversation,
) -> AsyncIterator[dict]:
    """把 raw input 轉為 Conversation 可消化的 message events。

    yield 一個或多個事件:
      - {type: "user_message", content: ...}     ← 進 query loop
      - {type: "command_result", text: ...}      ← UI 顯示但不送 API
      - {type: "command_inject", prompt: ...}    ← 注入到 system prompt
      - {type: "shell_result", content: ...}     ← shell 結果
    """
    text = raw if isinstance(raw, str) else raw.get("text", "")
    images = raw.get("images", []) if isinstance(raw, dict) else []

    # 1. Slash 命令
    if is_slash_command(text):
        cmd_name, args = parse_slash(text)
        cmd = get_command(cmd_name)
        if cmd is None:
            yield {"type": "error", "text": f"Unknown command: /{cmd_name}"}
            return

        result = await cmd.execute(args, ctx, conversation)
        if result.text:
            yield {"type": "command_result", "text": result.text}
        if result.new_user_message:
            yield {"type": "user_message", "content": result.new_user_message}
        if result.inject_into_prompt:
            ctx.feature_flags["pending_prompt_injection"] = result.inject_into_prompt
        return

    # 2. Shell 命令(! 開頭)
    if is_shell_command(text):
        result_text = await exec_shell(text[1:], ctx)  # 去掉 !
        # shell 結果包成 user message,讓模型可以參考
        yield {
            "type": "user_message",
            "content": f"[Shell command output for: {text}]\n```\n{result_text}\n```",
        }
        return

    # 3. 一般文字 + @file refs + 圖片
    expanded_text = await expand_file_refs(text, ctx)
    attachments = extract_attachments(text, images)

    if attachments:
        # 包成 ContentBlock list(含 text + image)
        content_blocks = [{"type": "text", "text": expanded_text}]
        for img in attachments:
            content_blocks.append({
                "type": "image",
                "source": {"type": "base64", "media_type": img["mime"], "data": img["data"]},
            })
        yield {"type": "user_message", "content": content_blocks}
    else:
        yield {"type": "user_message", "content": expanded_text}
```

### 5.7 `input/slash.py`

```python
"""Slash 命令解析。對應 TS processSlashCommand.tsx。"""
from __future__ import annotations
import re


SLASH_PATTERN = re.compile(r"^/([\w-]+)\b\s*(.*)$", re.DOTALL)


def is_slash_command(text: str) -> bool:
    """是否 / 開頭。需排除 // 路徑與獨立 /。"""
    if not text or not text.startswith("/"):
        return False
    if text.startswith("//"):
        return False
    if len(text) < 2:
        return False
    return SLASH_PATTERN.match(text) is not None


def parse_slash(text: str) -> tuple[str, str]:
    """解析 /cmd args → (cmd_name, args_str)。"""
    match = SLASH_PATTERN.match(text)
    if not match:
        raise ValueError(f"Not a slash command: {text}")
    return match.group(1), match.group(2).strip()
```

### 5.8 `input/shell.py`

```python
"""!cmd 直接 shell 命令。對應 TS processBashCommand.tsx。"""
from __future__ import annotations

from claude_agent_py.tools.shell.bash import BashTool, BashInput


def is_shell_command(text: str) -> bool:
    return text.startswith("!") and not text.startswith("!!")


async def exec_shell(command: str, ctx) -> str:
    """直接用 BashTool 跑命令,返回輸出文字。"""
    tool = BashTool()
    input_obj = BashInput(command=command, timeout=30_000)
    output_parts = []
    async for event in tool.call(input_obj, ctx):
        if hasattr(event, "text"):
            output_parts.append(event.text)
        elif hasattr(event, "message"):  # ErrorEvent
            output_parts.append(f"[error] {event.message}")
    return "\n".join(output_parts)
```

### 5.9 `input/text.py`

```python
"""文字輸入處理:@file ref、attachments。對應 TS processTextPrompt.ts。"""
from __future__ import annotations
import re
from pathlib import Path


FILE_REF_PATTERN = re.compile(r"@(\S+)")


async def expand_file_refs(text: str, ctx) -> str:
    """把 @file.py 自動展開成附 file 內容。

    對應 TS 的 nestedMemoryAttachmentTriggers + 一般 @file ref 機制。
    """
    matches = list(FILE_REF_PATTERN.finditer(text))
    if not matches:
        return text

    expanded = text
    for m in reversed(matches):  # 從後往前替換不影響 indices
        ref = m.group(1)
        path = ctx.cwd / ref if not Path(ref).is_absolute() else Path(ref)
        if path.exists() and path.is_file():
            try:
                content = path.read_text(encoding="utf-8")
                # 在原位插入 file 標記;具體 prompt 內容會在 query_loop 時當 attachment 注入
                expanded = (
                    expanded[:m.start()]
                    + f"@{ref} (loaded as attachment)"
                    + expanded[m.end():]
                )
                # 把實際內容加到 ctx 的 pending attachments
                if not hasattr(ctx, "pending_attachments"):
                    ctx.pending_attachments = []
                ctx.pending_attachments.append({
                    "path": str(path),
                    "content": content,
                })
            except Exception:
                pass

    return expanded


def extract_attachments(text: str, images: list) -> list[dict]:
    """從輸入抽出 attachments(目前只處理圖片,未來可加 PDF / file)。"""
    return [
        {"type": "image", "mime": img.get("mime", "image/png"), "data": img["data"]}
        for img in images
    ]
```

### 5.10 `input/image.py`

```python
"""Image input 處理。"""
from __future__ import annotations
import base64
from pathlib import Path


def encode_image_to_base64(path: Path) -> dict:
    """檔案 → base64 + mime → API 格式。"""
    mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".gif": "image/gif", ".webp": "image/webp"}
    mime = mime_map.get(path.suffix.lower(), "image/png")
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return {"mime": mime, "data": data}


def encode_image_bytes(image_bytes: bytes, mime: str) -> dict:
    """raw bytes → base64。"""
    return {"mime": mime, "data": base64.b64encode(image_bytes).decode("ascii")}


def compress_image_if_needed(
    image_bytes: bytes,
    *,
    max_size: int = 5 * 1024 * 1024,  # 5 MB
    max_dimension: int = 2048,
) -> bytes:
    """太大時用 PIL 壓縮(取代 Phase 5 的 mcpValidation 圖片壓縮)。"""
    if len(image_bytes) <= max_size:
        return image_bytes

    from io import BytesIO
    from PIL import Image

    img = Image.open(BytesIO(image_bytes))
    if max(img.size) > max_dimension:
        img.thumbnail((max_dimension, max_dimension), Image.LANCZOS)

    out = BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()
```

### 5.11 `services/token_estimation.py`

```python
"""Token estimation。對應 TS services/tokenEstimation.ts。

兩階段策略:
  1. rough_token_count:字元 / 4(快、粗)
  2. precise_token_count:呼叫 anthropic count_tokens API(精準、慢)
應用:memory selector(見 Phase 3)、compact 觸發判斷
"""
from __future__ import annotations
import anthropic


def rough_token_count(text: str) -> int:
    """估算 token 數,字元 / 4。"""
    return len(text) // 4


async def precise_token_count(
    messages: list,
    *,
    model: str = "claude-sonnet-4-6",
) -> int:
    """精準 token count,透過 anthropic count_tokens API。"""
    client = anthropic.AsyncAnthropic()
    response = await client.messages.count_tokens(
        model=model,
        messages=messages,
    )
    return response.input_tokens


async def estimate_with_two_phase(
    content,
    *,
    threshold: int,
    factor: float = 0.5,
) -> bool:
    """兩階段判斷是否超 threshold。

    對應 TS mcpContentNeedsTruncation 的兩階段檢查模式:
      ① rough 估值 ≤ threshold * 0.5 → 確定不超(便宜路徑)
      ② 否則用精確 count
    """
    text = content if isinstance(content, str) else str(content)
    rough = rough_token_count(text)
    if rough <= threshold * factor:
        return False  # 確定不超

    # 才呼叫精準
    precise = await precise_token_count([{"role": "user", "content": text}])
    return precise > threshold
```

## 6. 整合到 Conversation

```python
# core/conversation.py 改造

class Conversation:
    async def submit_raw_input(self, raw: str | dict) -> AsyncIterator:
        """新進入點:接受 raw input(可能是 slash 命令 / shell / 圖片 / 一般文字)。

        Phase 11 加。原 submit_message 改成內部 helper。
        """
        from claude_agent_py.input.process_input import process_user_input

        async for event in process_user_input(raw, self.ctx, self):
            if event["type"] == "user_message":
                # 真正進 query_loop
                async for msg in self._submit_message(event["content"]):
                    yield msg
            elif event["type"] == "command_result":
                # UI 顯示但不送 API
                yield {"type": "system_text", "content": event["text"]}
            elif event["type"] == "command_inject":
                # 標記下一輪 system prompt 注入(這是給特殊 command 用)
                pass
```

## 7. 設計決策

### 為何 slash 不只是 alias?

`/clear` 不只是「執行某個內建函式」,還會 mutate session state(清訊息、reset cache)。這跟「展開成 prompt 送模型」不同層次。

對應 TS:`Command.handler` 可以**直接修改 conversation state**,不一定要走模型。

### 為何 `!cmd` 結果包成 user message?

兩種設計:
- **方式 A**:直接執行,結果只給 user 看(不進對話歷史)
- **方式 B(採用)**:執行後包成 user message 進對話,**模型看得到**

選 B 的理由:
- User 跑 `!ls` 後問「這裡有 .py 檔嗎?」,模型有上下文
- 對應 TS `processBashCommand` 也是包成 message

### 為何 `@file` 不直接塞進 prompt 字串?

直接塞會讓 prompt 巨大(若檔案 100KB)。改成 attachment 機制:
- 文字保留 `@filename`(讓模型知道有引用)
- 實際內容在 query_loop 組訊息時當 attachment 加在前綴
- 模型看到 attachment 區塊獨立於 user prompt

對應 TS `attachments.ts` 的設計。

### 為何 token estimation 兩階段?

精準 count 要呼叫 Anthropic API(~50ms)。每次都呼叫太貴。

策略:
- 字元 / 4 估值 ≤ threshold × 0.5 → 確定不超(省 API call)
- 估值接近 threshold → 才呼叫精準 API

對應 TS `MCP_TOKEN_COUNT_THRESHOLD_FACTOR = 0.5`。

## 8. 驗收標準

```bash
pytest tests/commands/ tests/input/ -v
```

關鍵測試:

- `test_slash_clear.py` — /clear 後 messages 為空
- `test_slash_compact.py` — /compact 觸發、無事可壓回 "Nothing"
- `test_shell_redirect.py` — !ls 結果進 user message
- `test_file_ref_expand.py` — @file.py 正確讀檔 + attachment
- `test_image_paste.py` — base64 image 正確包成 ContentBlock
- `test_token_two_phase.py` — rough < 50% 不呼 API,> 50% 才呼

### 手動驗證

```bash
> /help                       # 列命令
> /init                       # 自動生 CLAUDE.md
> !ls                         # shell 命令
> 解釋 @main.py 的 main 函式  # @file ref
> /clear                      # 清訊息
> /memory                     # 看 / 改 MEMORY.md
> /cost                       # 用量
```

## 9. 常見踩雷

### 踩雷 1:slash 命令名衝突 / typo

`/clr` 是 typo,該怎麼 handle?Phase 11 直接報錯。進階版可加 fuzzy matching 提示「Did you mean /clear?」。

### 踩雷 2:`!cmd` 跨 sandbox

Phase 7 後 Bash 在 sandbox 內跑。`!cmd` 也應該走 sandbox(否則繞過安全)。但 user 可能期望 `!ls` 看的是自己的 fs(Phase 7 前)。明確設計決策後寫進文件。

### 踩雷 3:`@file` 路徑遍歷

`@/etc/passwd` 會讓模型看到敏感檔。要限制:
- 只允許 cwd 內檔案
- 或 sandbox 內(Phase 7 後)

### 踩雷 4:Image base64 太大

Anthropic API 對 image 有大小限制(5 MB)。要在 send 前壓縮(skeleton 5.10)。

### 踩雷 5:Token count API 慢拖累 input pipeline

雖然兩階段省了大多數呼叫,但 `precise_token_count` 在主路徑會卡。可加 timeout:

```python
try:
    return await asyncio.wait_for(precise_token_count(...), timeout=2.0)
except asyncio.TimeoutError:
    return rough * 1.5  # 保守估
```

## 10. 完成清單

- [ ] `Command` Protocol + registry
- [ ] 8 個必要命令(/clear /compact /init /memory /cost /model /help /history)
- [ ] `process_user_input` 主協調
- [ ] Slash 解析展開
- [ ] `!shell` 命令
- [ ] `@file` ref + attachment
- [ ] Image input 鏈路
- [ ] Token estimation 兩階段
- [ ] FastAPI 整合(WebSocket 收到的訊息走 input pipeline)
- [ ] 寫 Phase 11 心得
