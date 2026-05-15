"""orion-chat-api tests conftest。

共用 fixtures (isolate_sessions_dir / tmp_ctx / MockProvider 等)從 orion-sdk
透過 pytest_plugins 拉進來,避免重複定義。
"""

pytest_plugins = ["orion_sdk._testing"]
