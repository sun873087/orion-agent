"""MCP OAuth — stub。

對應 spec § 5.5 oauth.py(本機 callback,Phase 5 範圍)+ § 5.5b oauth_web.py
(server-side,Phase 6 / 7)。

設計取捨:
- Phase 5 的 CLI 模式可實作本機 callback port,但實際 MCP server 多用內建 token /
  公開 read-only,**OAuth 不是 stdio servers 的常見需求**(filesystem / git / etc.
  都不需要)。
- 真正需要 OAuth 的 server(GitHub / Slack / Notion)在 web 模式下用 server-side OAuth
  比較合理(Phase 6 / 7 整合 FastAPI + secureStorage)。

所以 Phase 5 兩個都 stub,保留接口 + raise NotImplementedError 指引。
"""

from __future__ import annotations


def start_local_oauth_flow(server_name: str, authorize_url: str) -> str:  # noqa: ARG001
    """本機 callback OAuth — Phase 5 不實作。

    若 user 真的需要,可手動取 token 透過環境變數注入 stdio config 的 env field。
    """
    raise NotImplementedError(
        f"Local OAuth callback for MCP server {server_name!r} deferred to Phase 5b. "
        "Workaround: pass auth tokens via the `env` field in mcp.json's stdio config."
    )


def start_web_oauth_flow(server_name: str, user_id: str) -> str:  # noqa: ARG001
    """Server-side OAuth — Phase 6/7。"""
    raise NotImplementedError(
        f"Web OAuth flow for MCP server {server_name!r} requires Phase 6 (FastAPI) + "
        "Phase 7 (secureStorage) integration."
    )
