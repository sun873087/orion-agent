# Phase 7:Sandbox + Production(沙盒與生產化)

## 速覽

- **預計時程**:3-4 週
- **前置 Phase**:Phase 6(FastAPI 跑通),Phase 2-5(各種狀態與工具)
- **後續 Phase**:Phase 8-10 在 production 基礎上做進階特性
- **主要交付物**:
  - Docker per-session sandbox(Bash / FileWrite 限定容器內)
  - 容器 lifecycle 管理(reuse pool、idle cleanup、resource limits)
  - Postgres 持久化 sessions / messages / transcripts
  - Redis per-user state cache
  - S3 大型工具結果持久化(取代 Phase 2 的本機 fs)
  - Per-user quota(token / cost / 並發 session 數)

## 1. 目標與動機

Phase 1-6 都是**單機 / 信任本機 user** 設計。Phase 7 把它變成**多人 SaaS**。三個關鍵問題要解:

```
1. 安全:不同 user 的工具不能讀寫同一個 fs
2. 持久:重啟 server 不丟對話、可水平擴展
3. 計費:per-user 用量限制
```

**對應 docs**:無直接對應(原 Claude Code 是單機)
- [docs/05](../05-settings-memory-context.md) `services/policyLimits/` 與 `remoteManagedSettings/` 設計可借鑑
- [docs/09](../09-large-tool-results.md) 大結果持久化要從 fs 改 S3

完成本 phase 後,你的服務能 production 上線多人使用。

## 2. TS 源檔映射

| Python 模組 | 對應 TS 源檔 | 注意事項 |
|---|---|---|
| `src/sandbox/docker.py` | (無) | 容器管理 |
| `src/sandbox/pool.py` | (無) | 容器池化 reuse |
| `src/sandbox/proxy_tools.py` | (無) | Bash/FileWrite 改在容器內跑 |
| `src/storage/postgres.py` | `src/utils/sessionStorage.ts`(改 fs → DB) | sessions / messages |
| `src/storage/redis_cache.py` | `src/bootstrap/state.ts`(改 module-state → Redis) | per-user state cache |
| `src/storage/s3_blobs.py` | `src/utils/toolResultStorage.ts`(改 fs → S3) | 大結果 |
| `src/quota/quota_manager.py` | `src/services/api/ultrareviewQuota.ts` | per-user 配額 |
| `src/policy/policy_engine.py` | `src/services/policyLimits/`、`remoteManagedSettings/` | 政策驅動 permission |

## 3. 任務拆解

### Week 1:Docker sandbox

- [ ] 1.1 加入依賴:`docker`(Python SDK)、`asyncpg`、`redis-py`、`boto3`
- [ ] 1.2 `sandbox/docker.py`:`Sandbox` class(spawn 容器、exec 命令、卸載)
- [ ] 1.3 Dockerfile(`docker/sandbox/Dockerfile`):基礎映像 + 必要工具(ripgrep、git、python)
- [ ] 1.4 `sandbox/pool.py`:容器池(idle cleanup、限制總數)
- [ ] 1.5 `sandbox/proxy_tools.py`:把 Phase 1 的 BashTool / FileWriteTool 改成 sandbox 內跑
- [ ] 1.6 整合到 `Conversation`:`ctx.sandbox` 欄位
- [ ] 1.7 測試:Bash / Edit 在 sandbox 內、不影響主機 fs

### Week 2:Postgres + Redis

- [ ] 2.1 `storage/postgres.py`:SQLAlchemy models(User / Session / Message / Replacement)
- [ ] 2.2 Alembic migration scripts(DB schema)— 注意:**settings.json 的版本 migrations 是不同事,見 [Phase 13](./13-resilience.md)**
- [ ] 2.3 取代 Phase 2 的 JSONL transcript:寫 Postgres
- [ ] 2.4 `storage/redis_cache.py`:per-session state(Phase 4 的 system_prompt_cache、Phase 3 的 token_budget 等)
- [ ] 2.5 改造 `SessionManager`:不存 in-memory,query DB
- [ ] 2.6 多 worker(uvicorn workers > 1)互相不干擾測試

### Week 3:S3 + Quota

- [ ] 3.1 `storage/s3_blobs.py`:`upload_blob` / `download_blob` / `signed_url`
- [ ] 3.2 改造 `storage/tool_result.py`:大結果寫 S3 而非本機
- [ ] 3.3 取代 Phase 5 的 mcp 大結果持久化
- [ ] 3.4 `quota/quota_manager.py`:per-user token / cost / session 數限制
- [ ] 3.5 用 Redis 累計 quota(atomic increment)
- [ ] 3.6 quota 超過拋 `QuotaExceededError`,API 回 429

### Week 4:Policy engine + 整合 + 部署

- [ ] 4.1 `policy/policy_engine.py`:基於 yaml 政策決定 permission
- [ ] 4.1b 完整 `permissions/filesystem.py`(對應 TS `utils/permissions/filesystem.ts`):
   - DANGEROUS_DIRECTORIES list(`/`、`~/`、`~/.ssh`、`~/.aws` 等)
   - Memory dir write carve-out(對應 docs/07 §8)
   - Path traversal 檢測(防 `../../../etc/passwd`)
   - Symlink 解析(防符號連結繞過)
- [ ] 4.1c `utils/settings/loader.py` 完整 4 層合併(對應 TS `utils/settings/`):
   - enterprise/managed(server 推送) > local > project > user
   - managed 鎖定欄位(user 不能覆寫)
- [ ] 4.2 改造 Phase 6 的 `make_can_use_tool_for_websocket`:政策決定 default
- [ ] 4.3 監控 + log:Prometheus metrics、structured logging
- [ ] 4.4 Dockerfile + docker-compose.yml(完整 stack)
- [ ] 4.5 端到端整合測試(2 個並發 user 各跑各的)
- [ ] 4.6 寫 Phase 7 心得

## 4. 模組架構與檔案

```
src/claude_agent_py/
├── sandbox/
│   ├── __init__.py
│   ├── docker.py                      # ◀ NEW Docker SDK 包裝
│   ├── pool.py                        # ◀ NEW 容器池
│   └── proxy_tools.py                 # ◀ NEW 工具改走 sandbox
│
├── storage/
│   ├── postgres.py                    # ◀ NEW Postgres SQLAlchemy
│   ├── redis_cache.py                 # ◀ NEW Redis per-session
│   ├── s3_blobs.py                    # ◀ NEW S3 持久化
│   ├── tool_result.py                 # ◀ 改造:fs → S3
│   └── session.py                     # ◀ 改造:JSONL → Postgres
│
├── quota/
│   ├── __init__.py
│   └── quota_manager.py               # ◀ NEW 配額管理
│
├── policy/
│   ├── __init__.py
│   └── policy_engine.py               # ◀ NEW yaml 政策
│
└── api/
    └── permissions.py                 # ◀ 擴充:整合 policy_engine

docker/
├── sandbox/
│   └── Dockerfile                     # ◀ 工具執行容器
├── api/
│   └── Dockerfile                     # ◀ FastAPI 容器
└── docker-compose.yml                 # ◀ 完整 stack(api + postgres + redis + minio)
```

## 5. Python Skeleton

### 5.1 `sandbox/docker.py`

```python
"""Docker sandbox。每 session 一個容器。"""
from __future__ import annotations
import asyncio
import shlex
from dataclasses import dataclass
from pathlib import Path
import docker  # docker SDK


@dataclass
class SandboxConfig:
    image: str = "claude-agent-sandbox:latest"
    memory_limit: str = "2g"
    cpu_quota: int = 100_000  # 1 CPU
    network_mode: str = "bridge"  # 或 "none" 隔離網路
    workspace_size_mb: int = 1024
    timeout_seconds: int = 3600  # idle timeout


class Sandbox:
    """單一容器。每 session 一個。"""

    def __init__(self, container_id: str, workspace: Path):
        self.container_id = container_id
        self.workspace = workspace  # host 端對應路徑(供 Read/Write)
        self._docker = docker.from_env()

    async def exec(
        self,
        command: str,
        *,
        timeout: float = 60.0,
        cwd: str = "/workspace",
    ) -> tuple[int, str]:
        """在容器內執行命令,返回 (returncode, output)。"""
        container = self._docker.containers.get(self.container_id)
        # docker SDK exec 是同步的,用 to_thread 包裝
        def _run():
            result = container.exec_run(
                cmd=command, workdir=cwd, demux=False,
            )
            return result.exit_code, result.output.decode("utf-8", errors="replace")

        return await asyncio.wait_for(
            asyncio.to_thread(_run), timeout=timeout
        )

    async def write_file(self, path: str, content: str) -> None:
        """寫檔到容器內。透過 docker SDK 的 put_archive。"""
        # 細節:用 tarfile 包裝後 put_archive
        ...

    async def read_file(self, path: str) -> str:
        """讀容器內的檔案。"""
        ...

    async def stop(self) -> None:
        try:
            container = self._docker.containers.get(self.container_id)
            container.stop(timeout=5)
            container.remove()
        except Exception:
            pass


async def create_sandbox(config: SandboxConfig, session_id: str) -> Sandbox:
    """建立新 sandbox 容器。"""
    client = docker.from_env()

    workspace = Path(f"/var/lib/claude-agent/sandboxes/{session_id}")
    workspace.mkdir(parents=True, exist_ok=True)

    container = client.containers.run(
        image=config.image,
        detach=True,
        mem_limit=config.memory_limit,
        nano_cpus=config.cpu_quota * 10,
        network_mode=config.network_mode,
        volumes={str(workspace): {"bind": "/workspace", "mode": "rw"}},
        working_dir="/workspace",
        # 防 fork bomb / 過多 process
        ulimits=[docker.types.Ulimit(name="nproc", soft=512, hard=512)],
        # 防容器逃逸
        security_opt=["no-new-privileges"],
        cap_drop=["ALL"],
        cap_add=["DAC_OVERRIDE"],  # 視 workload 調整
        # 保持運行
        command="sleep infinity",
    )

    return Sandbox(container_id=container.id, workspace=workspace)
```

### 5.2 `sandbox/pool.py`

```python
"""容器池化。減少 cold start 延遲。"""
from __future__ import annotations
import time
import anyio
from collections import deque

from claude_agent_py.sandbox.docker import Sandbox, SandboxConfig, create_sandbox


class SandboxPool:
    def __init__(
        self,
        *,
        warm_size: int = 3,
        max_total: int = 50,
        idle_ttl_seconds: float = 600,
    ):
        self.warm_size = warm_size
        self.max_total = max_total
        self.idle_ttl = idle_ttl_seconds
        self._available: deque[tuple[Sandbox, float]] = deque()
        self._in_use: dict[str, Sandbox] = {}  # session_id → sandbox
        self._lock = anyio.Lock()

    async def acquire(self, session_id: str) -> Sandbox:
        """取一個 sandbox 給該 session。"""
        async with self._lock:
            if session_id in self._in_use:
                return self._in_use[session_id]

            # 嘗試從 warm pool 取
            while self._available:
                sandbox, _ = self._available.popleft()
                # check 是否還活著
                self._in_use[session_id] = sandbox
                return sandbox

            if len(self._in_use) >= self.max_total:
                raise RuntimeError("sandbox pool exhausted")

            # 建新的
            sandbox = await create_sandbox(SandboxConfig(), session_id)
            self._in_use[session_id] = sandbox
            return sandbox

    async def release(self, session_id: str) -> None:
        async with self._lock:
            sandbox = self._in_use.pop(session_id, None)
            if sandbox is None:
                return
            # 看是否要回 warm pool 還是 shutdown
            if len(self._available) < self.warm_size:
                self._available.append((sandbox, time.time()))
            else:
                await sandbox.stop()

    async def cleanup_idle(self) -> None:
        """定期跑,清掉超過 idle_ttl 的 warm pool 容器。"""
        async with self._lock:
            now = time.time()
            keep = deque()
            for sandbox, ts in self._available:
                if now - ts > self.idle_ttl:
                    await sandbox.stop()
                else:
                    keep.append((sandbox, ts))
            self._available = keep
```

### 5.3 `sandbox/proxy_tools.py`(改造工具)

```python
"""把工具的 file ops / shell ops proxy 到 sandbox 容器內。"""
from __future__ import annotations
from pathlib import Path
from typing import AsyncIterator

from claude_agent_py.core.tool import Tool, ToolEvent, TextEvent, ErrorEvent
from claude_agent_py.core.state import AgentContext
from claude_agent_py.tools.shell.bash import BashInput


class SandboxedBashTool:
    """Bash 在 sandbox 內跑。"""
    name = "Bash"
    description = "Execute a bash command in sandbox."
    input_schema = BashInput

    def is_concurrency_safe(self, input: BashInput) -> bool:
        # 沿用 Phase 1 的 isReadOnly 邏輯
        return _is_read_only_bash(input.command)

    def is_read_only(self, input: BashInput) -> bool:
        return _is_read_only_bash(input.command)

    async def call(
        self, input: BashInput, ctx: AgentContext,
    ) -> AsyncIterator[ToolEvent]:
        sandbox = ctx.sandbox
        if sandbox is None:
            yield ErrorEvent(message="No sandbox available")
            return

        try:
            rc, output = await sandbox.exec(
                input.command, timeout=input.timeout / 1000,
            )
            if rc == 0:
                yield TextEvent(text=output)
            else:
                yield ErrorEvent(message=f"Bash exit {rc}:\n{output}")
        except TimeoutError:
            yield ErrorEvent(message="Bash timeout")


def _is_read_only_bash(command: str) -> bool:
    # 同 Phase 1 邏輯
    ...
```

### 5.4 `storage/postgres.py`

```python
"""Postgres SQLAlchemy models。"""
from __future__ import annotations
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import String, ForeignKey, Text, JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(primary_key=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    messages: Mapped[list["Message"]] = relationship(back_populates="session")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("sessions.id"))
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[dict | str] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    session: Mapped[Session] = relationship(back_populates="messages")


class ContentReplacement(Base):
    __tablename__ = "content_replacements"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("sessions.id"))
    tool_use_id: Mapped[str] = mapped_column(String(64), index=True)
    replacement: Mapped[str] = mapped_column(Text)
    blob_uri: Mapped[str | None] = mapped_column(String(512))  # S3 URL
```

### 5.5 `storage/s3_blobs.py`

```python
"""S3 大型工具結果持久化。取代 Phase 2 的本機 fs。"""
from __future__ import annotations
import os
from datetime import timedelta
from uuid import UUID
import aioboto3


_session = aioboto3.Session()
BUCKET = os.environ.get("CLAUDE_AGENT_BUCKET", "claude-agent-blobs")


async def upload_blob(
    content: str | bytes,
    *,
    session_id: UUID,
    tool_use_id: str,
    ext: str = "json",
) -> str:
    """上傳 blob,返回 s3 key。"""
    if isinstance(content, str):
        content = content.encode("utf-8")
    key = f"sessions/{session_id}/tool-results/{tool_use_id}.{ext}"
    async with _session.client("s3") as s3:
        await s3.put_object(Bucket=BUCKET, Key=key, Body=content)
    return key


async def download_blob(key: str) -> bytes:
    async with _session.client("s3") as s3:
        response = await s3.get_object(Bucket=BUCKET, Key=key)
        return await response["Body"].read()


async def signed_url(key: str, *, expires: timedelta = timedelta(hours=1)) -> str:
    """產生 pre-signed URL(供模型 Read)。"""
    async with _session.client("s3") as s3:
        return await s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": BUCKET, "Key": key},
            ExpiresIn=int(expires.total_seconds()),
        )
```

### 5.6 `quota/quota_manager.py`

```python
"""Per-user 配額。對應 TS services/api/ultrareviewQuota.ts。"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import timedelta
from redis.asyncio import Redis


@dataclass
class QuotaConfig:
    daily_token_limit: int = 500_000
    monthly_cost_limit_usd: float = 10.0
    max_concurrent_sessions: int = 5


class QuotaExceededError(Exception):
    pass


class QuotaManager:
    def __init__(self, redis: Redis, config: QuotaConfig):
        self.redis = redis
        self.config = config

    async def check_and_consume_tokens(
        self,
        user_id: str,
        tokens: int,
    ) -> None:
        """atomic check + increment。超過拋 QuotaExceededError。"""
        key = f"quota:tokens:{user_id}:daily"
        current = await self.redis.incrby(key, tokens)
        if current == tokens:  # 第一次,設 expire
            await self.redis.expire(key, int(timedelta(days=1).total_seconds()))
        if current > self.config.daily_token_limit:
            await self.redis.decrby(key, tokens)  # rollback
            raise QuotaExceededError(
                f"Daily token limit {self.config.daily_token_limit} exceeded"
            )

    async def acquire_session_slot(self, user_id: str) -> None:
        key = f"quota:sessions:{user_id}"
        current = await self.redis.incr(key)
        if current > self.config.max_concurrent_sessions:
            await self.redis.decr(key)
            raise QuotaExceededError(
                f"Max {self.config.max_concurrent_sessions} concurrent sessions"
            )

    async def release_session_slot(self, user_id: str) -> None:
        key = f"quota:sessions:{user_id}"
        await self.redis.decr(key)
```

### 5.7 `policy/policy_engine.py`

```python
"""Yaml-based policy engine。對應 TS services/policyLimits/。"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import yaml


@dataclass
class PolicyRule:
    tool_name: str
    decision: str  # "allow" / "deny" / "ask"
    conditions: dict | None = None  # 進階:cmd/path 條件


@dataclass
class Policy:
    rules: list[PolicyRule]
    default: str = "ask"

    def evaluate(self, tool_name: str, input_dict: dict) -> str:
        for rule in self.rules:
            if rule.tool_name == tool_name or rule.tool_name == "*":
                if self._match_conditions(rule.conditions, input_dict):
                    return rule.decision
        return self.default

    def _match_conditions(self, conditions, input_dict) -> bool:
        if conditions is None:
            return True
        # 簡單實作:check 每個 key 是否 match
        for k, v in conditions.items():
            if input_dict.get(k) != v:
                return False
        return True


def load_policy(path: Path) -> Policy:
    data = yaml.safe_load(path.read_text())
    rules = [PolicyRule(**r) for r in data.get("rules", [])]
    return Policy(rules=rules, default=data.get("default", "ask"))
```

`policy.yaml` 範例:

```yaml
default: ask
rules:
  - tool_name: Read
    decision: allow
  - tool_name: Grep
    decision: allow
  - tool_name: Bash
    conditions:
      command: "ls *"  # 簡化版
    decision: allow
  - tool_name: Bash
    decision: ask
  - tool_name: Write
    decision: deny  # production 不允許寫主機 fs(走 sandbox 才行)
```

### 5.8 `docker-compose.yml`

```yaml
version: '3.8'

services:
  api:
    build:
      context: .
      dockerfile: docker/api/Dockerfile
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql+asyncpg://claude:claude@postgres:5432/claude_agent
      - REDIS_URL=redis://redis:6379/0
      - S3_ENDPOINT=http://minio:9000
      - CLAUDE_AGENT_BUCKET=claude-agent-blobs
      - DOCKER_HOST=unix:///var/run/docker.sock
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock  # 讓 api 能起 sandbox
    depends_on:
      - postgres
      - redis
      - minio

  postgres:
    image: postgres:16
    environment:
      - POSTGRES_USER=claude
      - POSTGRES_PASSWORD=claude
      - POSTGRES_DB=claude_agent
    volumes:
      - pgdata:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine

  minio:
    image: minio/minio
    command: server /data
    environment:
      - MINIO_ROOT_USER=minioadmin
      - MINIO_ROOT_PASSWORD=minioadmin
    volumes:
      - miniodata:/data

volumes:
  pgdata:
  miniodata:
```

## 6. 設計決策與取捨

### 為何 Docker 而非 firejail / chroot?

- **完整檔案系統隔離**:容器有自己的 fs,沒辦法逃出 mount
- **Resource limits**:CPU / 記憶體 / pid / network 都能限
- **乾淨重置**:容器死了重建,不污染 host
- **跨平台**:Linux / macOS Docker Desktop 都能跑

替代:
- **E2B / Modal / Daytona**:託管,省管理但有費用
- **Firecracker microVM**:更輕量但要自建編排

Phase 7 用 Docker 起步,Phase 9+ 若需要更輕量可換 Firecracker。

### 為何 docker socket mount?

API 容器要能 spawn sandbox 容器 → mount `/var/run/docker.sock`。**這是安全風險**(等於給 API 容器 root)。Production 應改:

- 用 docker-in-docker(DinD)專用容器
- 或用 K8s CRD + custom controller
- 或 Nomad / SystemD-nspawn

Phase 7 簡化版直接 mount socket。

### 為何 Postgres + Redis?

| 資料 | 後端 | 為何 |
|---|---|---|
| User / Session metadata / Message transcript | Postgres | 結構化,需 SQL query(列 user 的 session 等) |
| Token quota counter / session lock / system_prompt cache | Redis | atomic increment、TTL、in-memory 快 |
| Tool result blobs | S3 | 大檔、bandwidth |

對應 TS 在原專案的 `bootstrap/state.ts`(全域可變)、`utils/sessionStorage.ts`(JSONL),Python port 拆成三個職責分明的後端。

### 為何 quota 用 Redis 而非 DB?

- atomic counter:`INCR` 是 O(1) 原子操作
- TTL 自動到期:每日重置不用 cron
- 高頻訪問:每次 API call 都要查,Redis 比 DB 快兩個數量級

quota 對寫入順序不敏感(approximate counter),Redis 偶爾掉資料可接受。**精準計費**(用於收費)應雙寫 DB。

### 為何 yaml policy 而非 hardcoded?

- 不同 user / 不同 deployment 有不同需求
- yaml 易讀,可由 admin 編輯不需 redeploy
- Phase 8 可加 hot reload

對應 TS `services/policyLimits/` 與企業 `remoteManagedSettings/` 的設計理念。

### Phase 7 故意不做的

| 項目 | 留給哪個 phase |
|---|---|
| 自動水平 scaling(K8s HPA)| Phase 9 telemetry 後 |
| 進階 sandbox(Firecracker)| 不做(scope 外) |
| 完整支付 / 訂閱系統 | 不做(scope 外) |
| 進階 RBAC / 多 tenant | 不做(基礎版只分 user) |

## 7. 驗收標準

### 自動測試

```bash
# 啟 docker-compose stack
docker-compose up -d

# 跑測試
pytest tests/sandbox/ tests/storage/ tests/quota/ -v
```

關鍵測試:

- `test_sandbox_isolation.py`:在 sandbox 內 `rm -rf /` 不影響 host
- `test_sandbox_resource_limit.py`:fork bomb 被擋
- `test_pool_reuse.py`:release 後再 acquire 同 session 拿同 sandbox
- `test_postgres_session_crud.py`:CRUD 跨 worker 一致
- `test_redis_quota_atomic.py`:並發 increment 不超 limit
- `test_s3_upload_download.py`:roundtrip
- `test_policy_engine.py`:rules 評估正確

### 手動驗證

開兩個瀏覽器 tab(模擬兩個 user):

- User A 跑「rm -rf /」 → 只影響自己 sandbox,User B 對話無感
- User A 達 daily token limit → API 回 429,User B 不受影響
- 重啟 API server → 對話歷史保留(Postgres)、resume 後 prompt cache 命中
- 大結果 → 看 S3 bucket 有對應 object

### 整合驗證

跑 stress test:50 個並發 user,各跑 10 turn 對話,觀察:

- 容器池上限正確
- DB 連線池正確 size
- Redis quota 不超賣
- 沒有資料 race(同 session 兩個 worker 同時寫不會錯亂)

## 8. 常見踩雷

### 踩雷 1:Docker socket 權限風險

mount `/var/run/docker.sock` 等於給 API container root。一定要:
- API container 不暴露在 internet(放在 reverse proxy 後面)
- 限制 API code 只能呼叫特定 docker API(自建 wrapper,不直接給 docker SDK)
- 或改用 DinD / 專用編排

### 踩雷 2:Sandbox idle 不釋放

容器跑 `sleep infinity` 會永遠存活。必須:
- 加 idle timer:N 分鐘無活動 → release
- pool cleanup 定期跑
- 容器死了要 detect(`container.status` 改變)

否則 5 個 user 跑 100 個 session,主機 OOM。

### 踩雷 3:容器內網路逃逸

預設 `network_mode=bridge` 容器能上網。MCP 工具 / Bash curl 等可能存取內網敏感服務。建議:

- `network_mode=none`(完全切網)+ 透過 API container 代理外部請求
- 或 custom bridge + iptables 阻擋內網 IP 範圍

### 踩雷 4:DB 連線池 vs uvicorn workers

uvicorn workers > 1 → 每個 worker 自己一個連線池。Postgres `max_connections` 預設 100,worker × pool_size 不能超過。

```python
# pool_size=5, max_overflow=10 per worker
# 4 workers × 15 = 60 連線(OK)
```

### 踩雷 5:Redis pub/sub vs polling

若需要跨 worker 通訊(例:tool permission ask 在 worker A,user 點選送到 worker B),要 pub/sub。Phase 7 簡化版假設 sticky session(同 user 永遠連同 worker)。

### 踩雷 6:S3 一致性

S3 read-after-write 有 strong consistency(2020 後)。但**列舉(list)**仍是 eventual。不要用 `list_objects` 確認剛寫的檔案存在。

### 踩雷 7:Quota race

```python
current = await redis.incrby(key, tokens)
if current > limit:
    await redis.decrby(key, tokens)  # rollback
```

期間若有別的 request increment → 看到的 current 會偏高。但**不會超賣**(atomic)。只是偶爾 rollback 後別人 increment 過了 → 自己被拒,但實際 quota 還沒滿。可接受的 race(over-rejection 而非 over-allow)。

### 踩雷 8:Migration 與 prod 部署

Alembic migration 在 deploy 時要先跑(`alembic upgrade head`)再啟 API。否則 schema 不一致 crash。docker-compose 加 init container:

```yaml
api:
  command: sh -c "alembic upgrade head && uvicorn ..."
```

## 9. 參考資料

### docs/01-11

- [docs/05](../05-settings-memory-context.md) — Settings 多層合併、managed settings 概念可借鑑
- [docs/09](../09-large-tool-results.md) — 大結果處理(從 fs 改 S3)

### TS 源檔(借鑑用)

- `src/services/policyLimits/` — yaml policy engine
- `src/services/remoteManagedSettings/` — 企業集中管理
- `src/services/api/ultrareviewQuota.ts` — quota 設計

### 外部資源

- [Docker SDK for Python](https://docker-py.readthedocs.io/)
- [E2B](https://e2b.dev/) — 託管 sandbox 替代方案
- [SQLAlchemy 2.0 async](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
- [Alembic migrations](https://alembic.sqlalchemy.org/)
- [aioboto3](https://aioboto3.readthedocs.io/)
- [redis-py async](https://redis-py.readthedocs.io/en/stable/examples/asyncio_examples.html)
- [Anthropic prompt caching cost analysis](https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching)

## 完成檢查表

- [ ] Docker sandbox per-session
- [ ] 容器池化 + idle cleanup
- [ ] Bash/FileWrite 在 sandbox 內跑
- [ ] Postgres 取代 JSONL transcript
- [ ] Redis cache for per-session state
- [ ] S3 取代 tool-results 本機 fs
- [ ] Quota manager(token / session 數)
- [ ] Yaml policy engine
- [ ] docker-compose.yml 完整 stack
- [ ] 端到端 stress test(50 並發 user)
- [ ] 寫 Phase 7 心得

完成後進入 [Phase 8:Hooks/Skills/Plugins](./08-hooks-skills-plugins.md)。
