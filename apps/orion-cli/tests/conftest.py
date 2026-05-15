"""orion-cli tests conftest。

共用 fixtures 透過 pytest_plugins 從 orion-sdk 拉進來。
"""

pytest_plugins = ["orion_sdk._testing"]
