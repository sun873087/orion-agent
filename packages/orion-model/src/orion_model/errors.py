"""Provider-side 上游 HTTP error 的友善包裝。

Native httpx provider(Google Gemini / Ollama / 未來別的)raise 這個,
sidecar `_format_send_error` 識別後抽 `status_code` 直接給 UI 用。
SDK-based provider(OpenAI / Anthropic / OpenRouter via openai SDK)用
SDK 自己的 `RateLimitError` / `AuthenticationError` 等 — 不用這 class。
"""

from __future__ import annotations


class ProviderHTTPError(RuntimeError):
    """Provider 上游 HTTP 4xx/5xx 的 typed exception。

    Attributes:
        provider: e.g. "google", "ollama"
        status_code: HTTP status
        upstream_message: 從 upstream body parse 出來的 error.message(若有)
        body: raw response body(截 1KB)
    """

    def __init__(
        self,
        *,
        provider: str,
        status_code: int,
        upstream_message: str = "",
        body: str = "",
    ) -> None:
        self.provider = provider
        self.status_code = status_code
        self.upstream_message = upstream_message
        self.body = body[:1000]
        super().__init__(self._compose())

    def _compose(self) -> str:
        prov = self.provider.capitalize()
        sc = self.status_code
        umsg = (self.upstream_message or "").strip()
        if sc == 429:
            if self.provider == "google":
                return (
                    "Gemini 配額用完(free tier RPM≈15 / RPD≈50)。"
                    "等 1 分鐘再試,或在 aistudio.google.com 啟用 paid billing"
                )
            return f"{prov} 速率限制 / quota 用完,稍候再試"
        if sc == 401:
            return f"{prov} API key 無效 — 檢查環境變數設定"
        if sc == 403:
            return f"{prov} API key 沒權限(可能已 revoke 或未 enable API)"
        if sc == 402:
            return f"{prov} 餘額不足 / billing 未啟用"
        if sc == 404:
            if umsg:
                return f"{prov} 找不到資源:{umsg[:200]}"
            return f"{prov} 404 — model 名稱可能拼錯或無權使用"
        if sc == 400:
            if umsg:
                return f"{prov} 拒此 request:{umsg[:300]}"
            return f"{prov} 400 — request 格式錯"
        if sc >= 500:
            tail = f":{umsg[:200]}" if umsg else ""
            return f"{prov} 上游 {sc} 錯誤,稍候再試{tail}"
        if umsg:
            return f"{prov} HTTP {sc}:{umsg[:300]}"
        return f"{prov} HTTP {sc}"


__all__ = ["ProviderHTTPError"]
