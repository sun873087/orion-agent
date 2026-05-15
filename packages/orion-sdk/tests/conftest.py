"""orion-sdk tests conftest。

共用 fixtures (isolate_sessions_dir / tmp_ctx / sample_text_file / mock_provider)
都搬到 `orion_sdk._testing` 模組,以便 orion-chat-api / orion-cli 等下游 package
也能透過 `pytest_plugins` 重用。
"""

pytest_plugins = ["orion_sdk._testing"]
