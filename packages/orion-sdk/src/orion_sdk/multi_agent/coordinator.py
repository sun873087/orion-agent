"""Coordinator(Leader-Worker)pattern。Phase 15。

對應 TS Claude Code `src/coordinator/coordinatorMode.ts`。

語意:
  Coordinator(leader)拿到 N 個 TaskAssignment → 並行 spawn N 個 worker 跑各自任務 →
  收集 WorkerReport → caller 自行整合(coordinator 本身只負責 dispatch)。

每個 worker 透過 Phase 12 `services.forked_agent.run_forked_agent` 跑,共享父
prompt cache(若 caller 傳同 system + tools + messages_prefix);個別 worker 失敗
**不影響其他**(回 status="failed" + error message)。

並發控制:`anyio.CapacityLimiter`(預設 max_workers=5)— 防一次 spawn 過多。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import anyio

from orion_sdk.core.state import AgentContext
from orion_model.provider import LLMProvider
from orion_sdk.multi_agent.types import (
    TaskAssignment,
    WorkerReport,
)
from orion_sdk.permissions.decisions import CanUseToolFn, always_allow
from orion_sdk.services.forked_agent import (
    CacheSafeParams,
    ForkedAgentResult,
    run_forked_agent,
)


@dataclass
class CoordinatorResult:
    """Coordinator dispatch 跑完的彙總。"""

    reports: list[WorkerReport]
    total_usage: dict[str, int] = field(default_factory=dict)

    @property
    def succeeded(self) -> list[WorkerReport]:
        return [r for r in self.reports if r.status == "completed"]

    @property
    def failed(self) -> list[WorkerReport]:
        return [r for r in self.reports if r.status == "failed"]


class Coordinator:
    """Leader agent。一個 coordinator,N 個並行 worker。

    Args:
        ctx: 父 AgentContext(每個 worker 透過 fork_context_for_subagent 取獨立 ctx)
        provider: LLMProvider(workers 共用,以省 client config)
        cache_safe_params: 父 prompt cache snapshot — workers 共享 prefix
        max_workers: 同時併發上限(預設 5,>5 raise ValueError 在 dispatch)
        worker_can_use_tool: 給 workers 用的 permission policy(預設 always_allow)
        summary_provider: 若有,worker 完成後用此 provider 產 AgentSummary(通常傳
            Haiku 便宜版);None 跳過 summary
    """

    def __init__(
        self,
        *,
        ctx: AgentContext,
        provider: LLMProvider,
        cache_safe_params: CacheSafeParams,
        max_workers: int = 5,
        worker_can_use_tool: CanUseToolFn = always_allow,
        summary_provider: LLMProvider | None = None,
    ) -> None:
        self.ctx = ctx
        self.provider = provider
        self.cache_safe_params = cache_safe_params
        self.max_workers = max_workers
        self.worker_can_use_tool = worker_can_use_tool
        self.summary_provider = summary_provider

    async def dispatch(
        self,
        assignments: list[TaskAssignment],
    ) -> CoordinatorResult:
        """併行跑 assignments,等所有 worker 完成回 CoordinatorResult。

        Raises:
            ValueError: assignments 超過 max_workers。
        """
        if len(assignments) > self.max_workers:
            raise ValueError(
                f"Too many assignments: {len(assignments)} > "
                f"max_workers={self.max_workers}"
            )

        if not assignments:
            return CoordinatorResult(reports=[])

        limiter = anyio.CapacityLimiter(self.max_workers)
        # holders 預先佔位,確保結果順序與 assignments 對齊
        holders: list[WorkerReport | None] = [None] * len(assignments)

        async def _store(idx: int, assignment: TaskAssignment) -> None:
            async with limiter:
                holders[idx] = await self._run_worker(assignment)

        async with anyio.create_task_group() as tg:
            for i, a in enumerate(assignments):
                tg.start_soon(_store, i, a)

        reports = [r for r in holders if r is not None]
        total = self._aggregate_usage(reports)
        return CoordinatorResult(reports=reports, total_usage=total)

    async def _run_worker(self, assignment: TaskAssignment) -> WorkerReport:
        worker_id = f"worker-{assignment.task_id.hex[:8]}"
        prompt = self._format_worker_prompt(assignment)
        try:
            fork_result: ForkedAgentResult = await run_forked_agent(
                parent_ctx=self.ctx,
                parent_params=self.cache_safe_params,
                user_prompt=prompt,
                provider=self.provider,
                can_use_tool=self.worker_can_use_tool,
                max_turns=assignment.max_turns,
                fork_label=worker_id,
            )
        except Exception as e:  # noqa: BLE001 — 個別 worker 失敗隔離
            return WorkerReport(
                task_id=assignment.task_id,
                worker_id=worker_id,
                status="failed",
                error=f"{type(e).__name__}: {e}",
            )

        summary = ""
        if self.summary_provider is not None:
            summary = await self._maybe_summarize(
                fork_result, agent_name=worker_id,
            )

        return WorkerReport(
            task_id=assignment.task_id,
            worker_id=worker_id,
            status="completed",
            final_text=fork_result.final_text,
            summary=summary,
            total_usage=fork_result.total_usage,
            written_paths=fork_result.written_paths,
        )

    async def _maybe_summarize(
        self,
        fork_result: ForkedAgentResult,
        *,
        agent_name: str,
    ) -> str:
        if self.summary_provider is None:
            return ""
        # 延遲 import 避免循環依賴
        from orion_sdk.multi_agent.agent_summary import generate_agent_summary

        try:
            return await generate_agent_summary(
                fork_result.final_messages,
                provider=self.summary_provider,
                agent_name=agent_name,
            )
        except Exception:  # noqa: BLE001 — 摘要失敗不該影響 dispatch
            return ""

    @staticmethod
    def _format_worker_prompt(assignment: TaskAssignment) -> str:
        ctx_json = ""
        if assignment.context:
            from json import dumps
            ctx_json = (
                "\n\nAdditional context (JSON):\n" + dumps(assignment.context, indent=2)
            )
        fmt_hint = ""
        if assignment.expected_format:
            fmt_hint = f"\n\nExpected output format: {assignment.expected_format}"
        return (
            "You are a worker agent assigned a sub-task by a coordinator.\n\n"
            f"Task: {assignment.description}"
            f"{ctx_json}"
            f"{fmt_hint}\n\n"
            "Complete the task and provide a concise final answer."
        )

    @staticmethod
    def _aggregate_usage(reports: list[WorkerReport]) -> dict[str, int]:
        total = {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0}
        for r in reports:
            for k in total:
                total[k] += r.total_usage.get(k, 0)
        return total


__all__ = ["Coordinator", "CoordinatorResult"]
