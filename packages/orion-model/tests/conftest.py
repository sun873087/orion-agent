"""orion-model tests conftest。

orion-model 沒有 sessions / AgentContext 等概念,不需要 SDK 的 fixtures。
僅載入 .env(integration tests 才會用到真 API keys)。
"""

from dotenv import load_dotenv

load_dotenv()
