"""Output styles。Phase 13。

對應 TS Claude Code `src/outputStyles/loadOutputStylesDir.ts`(輕量)。

User 自訂 agent 回應風格(simple / verbose / formal / 等)。每個 style 是一份
markdown 檔(frontmatter + body)。本 phase 範圍:loader + lookup,沒做 cache。

`load_all_output_styles()` 從以下位置匯總:
  1. `$ORION_HOME/output-styles/`(全域)
  2. `<cwd>/.orion/output-styles/`(per-project)

caller(Conversation)用 style name 透過 `find_output_style()` 取對應 prompt。
"""

from orion_sdk.output_styles.loader import (
    OutputStyle,
    find_output_style,
    list_output_style_names,
    load_all_output_styles,
    load_output_styles_dir,
)

__all__ = [
    "OutputStyle",
    "find_output_style",
    "list_output_style_names",
    "load_all_output_styles",
    "load_output_styles_dir",
]
