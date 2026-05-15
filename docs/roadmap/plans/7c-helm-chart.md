# Phase 7c — Kubernetes 部署 + Helm Chart + Pod-per-session Sandbox

**狀態**:📋 Plan(等 K8s cluster 環境)
**前置**:Phase 7 完成(SandboxBackend Protocol、DbSessionManager、deploy/Dockerfile)
**估時**:1-2 週

> 本文件是 **完整 K8s 部署 spec**。原來拆成兩份(`07b-kubernetes.md` 講 why/architecture、`7c-helm-chart.md` 講 how/steps),已合併以避免漂移。

## 動機

Phase 7 範圍 B 完成了 Production Foundation,本機 dev 用 `docker-compose.yml` + Docker socket mount。**production K8s 走這個 phase**:
1. K8s 環境下 Docker socket mount **是反 pattern**(見下節)
2. 沒 cluster 可實測 K8s 設計,因此把 Helm chart / Pod-per-session sandbox 完整實作切到本 phase
3. 想把單機 SaaS 升級到 multi-instance K8s 部署時,直接接 phase 7c

### 為何不沿用 Phase 7 的 Docker socket mount?

| 問題 | 說明 |
|---|---|
| Pod 通常拿不到 docker daemon | K8s 用 containerd / CRI-O,不是 docker |
| 即使能 mount socket | 等於給 API Pod host 級 root,巨大攻擊面 |
| K8s 排程 / 資源管理失效 | 你 spawn 的 container 不在 K8s 視野內,監控 / 限額都 bypass |
| 跨 node 排程不可能 | docker socket 只看到本 node |

K8s 的解法:**用 K8s API 動態建 Pod**,讓 K8s 負責排程、隔離、監控、回收。

## K8s vs Docker 設計對比

```
┌─────────────────────────────────────────────────────────────────┐
│ Phase 7(Docker socket mount,本機 dev / 單機 SaaS)              │
├─────────────────────────────────────────────────────────────────┤
│  API container ─ socket mount ─▶ host docker daemon              │
│                                       ↓                         │
│                                  spawn container                │
│                                                                 │
│  ❌ 不適合 K8s                                                  │
│  ❌ Security 反 pattern                                          │
│  ✅ 簡單(本機 dev)                                              │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ Phase 7c(本文件,K8s 原生)                                      │
├─────────────────────────────────────────────────────────────────┤
│  API Pod ─ K8s API(via SA token)─▶ Pod-per-session             │
│                                          ↓                       │
│                                     sandbox 容器                 │
│                                                                 │
│  ✅ K8s 原生 lifecycle / scheduling                              │
│  ✅ ServiceAccount + RBAC 限縮權限                               │
│  ✅ gVisor / Kata 容器級 / VM 級隔離                              │
│  ✅ NetworkPolicy 切網                                           │
│  ✅ ResourceQuota 限資源                                          │
│  ⚠️ 冷啟動較慢(~5-10s),需預熱 pool 緩解                       │
└─────────────────────────────────────────────────────────────────┘
```

## 4 種 K8s 方案對比

| 方案 | 說明 | 適合 |
|---|---|---|
| **A. Pod-per-session(推薦)** | API 用 K8s API 動態建 Pod | 大多數情境 |
| **B. 預熱 Pod pool** | StatefulSet / ReplicaSet 維持 N 個 idle pod,session 來綁 label | 高 QPS / 冷啟動敏感 |
| **C. KubeVirt + Kata Containers** | 完整 VM 級隔離 | 高安全需求(金融 / 醫療) |
| **D. 外部託管(E2B / Modal)** | API 走 HTTPS 呼叫 E2B 啟 sandbox | 不想自管 / 快速 MVP |

**推薦組合**:**A + B 混合**(基本 pod-per-session,加預熱 pool 緩解冷啟動)+ **gVisor runtime**(不需自建 Kata / KubeVirt)。

## 推薦架構

```
                    K8s Cluster
   ┌────────────────────────────────────────────────────────────┐
   │                                                            │
   │  Namespace: orion-api(API 自己的)                          │
   │  ┌────────────────────────────────────────────┐           │
   │  │ Deployment: orion-api(N replicas)          │           │
   │  │   ServiceAccount: orion-api-sa              │           │
   │  │   Container: FastAPI app                    │           │
   │  └─────────────────┬──────────────────────────┘           │
   │                    │                                       │
   │           K8s API(create_pod / exec)                      │
   │                    │                                       │
   │  Namespace: orion-sandboxes(sandbox 專用)                  │
   │  ┌─────────────────────────────────────────────────────┐  │
   │  │ NetworkPolicy: deny-egress(預設切網)               │  │
   │  │ ResourceQuota: total CPU/memory limit               │  │
   │  │ LimitRange: per-pod 上限                            │  │
   │  │ RuntimeClass: gvisor                                │  │
   │  │ PSS label: pod-security/enforce: restricted        │  │
   │  │                                                     │  │
   │  │ ┌───────┐ ┌───────┐ ┌───────┐ ┌───────┐            │  │
   │  │ │warm-1 │ │warm-2 │ │warm-3 │ │ ...   │ ← 預熱 pool│  │
   │  │ └───────┘ └───────┘ └───────┘ └───────┘            │  │
   │  │                                                     │  │
   │  │ ┌──────────────┐ ┌──────────────┐                  │  │
   │  │ │sandbox-{s1}  │ │sandbox-{s2}  │ ← 已 assign     │  │
   │  │ │label: session│ │label: session│   給 session     │  │
   │  │ │  =<uuid>     │ │  =<uuid>     │                  │  │
   │  │ └──────────────┘ └──────────────┘                  │  │
   │  └─────────────────────────────────────────────────────┘  │
   │                                                            │
   │  Namespace: orion-data                                     │
   │  ├── Postgres(StatefulSet 或 cloud DB)                    │
   │  ├── Redis(Deployment 或 ElastiCache)                     │
   │  └── MinIO / S3 secret                                     │
   │                                                            │
   └────────────────────────────────────────────────────────────┘
```

## 模組映射(取代 Phase 7 部分檔案)

| Python 模組 | Phase 7(Docker)| Phase 7c(本文件,K8s) |
|---|---|---|
| `src/orion_agent/sandbox/docker_backend.py` | Docker SDK 包裝 | **改用** `src/orion_agent/sandbox/k8s_backend.py` |
| pool 邏輯 | Docker container pool | **改造**:用 label-based pod pool(`k8s_pool.py`) |
| proxy_tools | 透過 docker.exec_run | **改造**:透過 K8s exec API |
| `deploy/sandbox.Dockerfile` | sandbox image | 同(可重用) |
| `deploy/docker-compose.yml` | 完整 stack(本機 dev) | **新增** Helm chart `deploy/helm/orion-agent/` |
| 其他 storage / quota | 不變 | 不變 |

## 範圍

### 做

| 項目 | 說明 |
|---|---|
| **Helm chart** | `deploy/helm/orion-agent/` 含 values.yaml、Deployment、Service、Ingress、ConfigMap、Secret、ServiceAccount、HPA、PDB |
| **K8sBackend** | `src/orion_agent/sandbox/k8s_backend.py` — 每 conversation 一個 Pod;exec via K8s exec API;檔讀寫 via base64+exec 或 client subresource |
| **Pod template** | per-session sandbox Pod spec(image=orion-agent-sandbox:tag) |
| **NetworkPolicy** | sandbox Pod 預設 deny-all egress,只開 allowlist DNS / proxy |
| **gVisor RuntimeClass** | 額外 syscall 隔離(可選 — node 須裝 runsc) |
| **Pod Security Standards** | sandbox namespace `pod-security.kubernetes.io/enforce: restricted` |
| **RBAC** | API Pod 需 ServiceAccount 能 create/exec/delete sandbox Pods 在 `orion-sandboxes` namespace |
| **ResourceQuota + LimitRange** | sandbox namespace 限總 CPU / RAM / pod 數 |
| **預熱 pool** | warm Pod 池減少 cold start;ReplicaSet selector `state=warm`(label patch 後 RS 自動補) |
| **Migration job** | Helm hook 跑 `alembic upgrade head` 在 API rollout 前 |
| **Cross-instance session 復原** | 加 Redis 存 Conversation state snapshot,任何 worker 都能 resume |
| **Probes** | livenessProbe / readinessProbe / startupProbe |

### 不做(留更後)

- Multi-tenancy(per-tenant namespace)→ 後續 phase
- Service mesh(Istio / Linkerd)→ optional,operator 自選
- Vault / Secrets operator → optional,Helm 預設用 K8s Secret
- Custom Operator(取代 ReplicaSet 的精準 pool 控制)→ 後續

## 檔案結構

```
deploy/helm/orion-agent/
├── Chart.yaml
├── values.yaml                         預設值
├── values.production.yaml              production override 範例
└── templates/
    ├── _helpers.tpl
    ├── api/
    │   ├── deployment.yaml             API Deployment(replicas, env, probes)
    │   ├── service.yaml                ClusterIP
    │   ├── ingress.yaml                可選
    │   ├── serviceaccount.yaml
    │   └── hpa.yaml                    Horizontal Pod Autoscaler
    ├── sandbox/
    │   ├── namespace.yaml              orion-sandboxes ns + PSS label
    │   ├── rbac.yaml                   Role / RoleBinding
    │   ├── networkpolicy.yaml          deny-egress + ingress-from-api
    │   ├── runtimeclass.yaml           gvisor(若集群沒先裝)
    │   ├── resourcequota.yaml
    │   ├── limitrange.yaml
    │   └── warm-pool-replicaset.yaml
    ├── data/
    │   ├── postgres-statefulset.yaml   或省略,用 cloud DB
    │   ├── redis-deployment.yaml
    │   └── minio-deployment.yaml       或用 S3
    ├── job-migrate.yaml                Helm hook pre-upgrade
    ├── configmap.yaml                  ORION_LOG_FORMAT 等
    ├── secret.yaml                     placeholder(production 改 ExternalSecret)
    └── poddisruptionbudget.yaml

src/orion_agent/sandbox/
├── k8s_backend.py                      [新] K8sBackend 實作 SandboxBackend Protocol
└── k8s_pool.py                         [新] 預熱 pool acquire / release

src/orion_agent/api/
└── session_state_redis.py              [新] Redis-backed Conversation snapshot

deploy/
└── README.md                           [改] 加 Helm install / upgrade / rollback 段落
```

## 實作順序(11 步)

| Step | 工作 |
|---|---|
| 1 | `pyproject` 加 `kubernetes_asyncio`、`redis[hiredis]` |
| 2 | `sandbox/k8s_backend.py`(`CoreV1Api` create / exec via WS / delete) |
| 3 | `sandbox/k8s_pool.py`(label-based warm pool acquire / release) |
| 4 | unit test:K8sBackend / K8sPool with mock kubernetes client |
| 5 | `api/session_state_redis.py`:dump / load Conversation state(JSON) |
| 6 | `api/session_manager_db.py` 整合 Redis fallback(DB cache miss → Redis 復原) |
| 7 | Helm chart skeleton + values.yaml |
| 8 | API templates(Deployment + Service + ConfigMap + ServiceAccount + RBAC) |
| 9 | sandbox templates(Namespace + NetworkPolicy + RuntimeClass + Quota) + warm-pool ReplicaSet |
| 10 | Migration Job(pre-install / pre-upgrade hook) + HPA + PDB |
| 11 | `deploy/README.md` Helm install / upgrade 流程 + 驗收 + 完工 doc |

## Python Skeleton

### `sandbox/k8s_backend.py`

```python
"""K8s-based sandbox。每 session 一個 Pod。

取代 Phase 7 的 sandbox/docker_backend.py。
依賴:kubernetes_asyncio(async 版 K8s client)。
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from uuid import UUID

from kubernetes_asyncio import client, config
from kubernetes_asyncio.client.rest import ApiException
from kubernetes_asyncio.stream import WsApiClient
from kubernetes_asyncio.stream.ws_client import ERROR_CHANNEL


@dataclass
class K8sSandboxConfig:
    namespace: str = "orion-sandboxes"
    image: str = "your-registry/orion-agent-sandbox:latest"
    runtime_class: str = "gvisor"        # gvisor / kata-qemu(看集群)
    cpu_request: str = "200m"
    cpu_limit: str = "1000m"
    memory_request: str = "256Mi"
    memory_limit: str = "2Gi"
    workspace_size: str = "1Gi"
    pod_startup_timeout: int = 60
    image_pull_secret: str | None = None


# 在 cluster 內(API Pod)用 in-cluster config;本機 dev 用 kubeconfig
async def _load_k8s_config() -> None:
    if os.environ.get("KUBERNETES_SERVICE_HOST"):
        await config.load_incluster_config()
    else:
        await config.load_kube_config()


class K8sSandbox:
    """單一 sandbox Pod 的 wrapper。"""

    def __init__(self, pod_name: str, namespace: str) -> None:
        self.pod_name = pod_name
        self.namespace = namespace

    async def exec(
        self,
        command: list[str],
        *,
        timeout: float = 60.0,
        cwd: str = "/workspace",
        stdin_input: str | None = None,
    ) -> tuple[int, str, str]:
        """在 Pod 內執行命令,返回 (returncode, stdout, stderr)。"""
        await _load_k8s_config()
        wrapped = ["sh", "-c", f"cd {cwd} && " + " ".join(
            f"'{c}'" for c in command
        )]

        async with WsApiClient() as ws_client:
            api = client.CoreV1Api(ws_client)
            ws = await api.connect_get_namespaced_pod_exec(
                self.pod_name,
                self.namespace,
                command=wrapped,
                container="sandbox",
                stderr=True, stdin=bool(stdin_input), stdout=True, tty=False,
                _preload_content=False,
            )
            try:
                await asyncio.wait_for(
                    self._stream_loop(ws, stdin_input),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                await ws.close()
                return -1, "", "timeout"

            stdout = ws.read_stdout() or ""
            stderr = ws.read_stderr() or ""
            err_chan = ws.read_channel(ERROR_CHANNEL) or "{}"
            return self._parse_exit_code(err_chan), stdout, stderr

    async def _stream_loop(self, ws, stdin_input: str | None) -> None:
        if stdin_input:
            await ws.write_stdin(stdin_input)
            await ws.write_stdin_eof()
        while ws.is_open():
            await asyncio.sleep(0.05)

    @staticmethod
    def _parse_exit_code(err_chan: str) -> int:
        import json
        try:
            data = json.loads(err_chan)
            if data.get("status") == "Success":
                return 0
            for cause in data.get("details", {}).get("causes", []):
                if cause.get("reason") == "ExitCode":
                    return int(cause.get("message", "1"))
        except Exception:
            pass
        return 1

    async def write_file(self, path: str, content: str) -> None:
        """寫檔到 Pod 內(base64 + sh -c,簡化版)。"""
        import base64
        encoded = base64.b64encode(content.encode()).decode()
        await self.exec(
            ["sh", "-c", f"echo '{encoded}' | base64 -d > {path}"],
        )

    async def read_file(self, path: str) -> str:
        rc, stdout, _ = await self.exec(["cat", path])
        if rc != 0:
            raise FileNotFoundError(path)
        return stdout

    async def stop(self) -> None:
        """刪 Pod。"""
        await _load_k8s_config()
        async with client.ApiClient() as api_client:
            api = client.CoreV1Api(api_client)
            try:
                await api.delete_namespaced_pod(
                    name=self.pod_name,
                    namespace=self.namespace,
                    grace_period_seconds=5,
                )
            except ApiException as e:
                if e.status != 404:
                    raise


async def create_sandbox(
    cfg: K8sSandboxConfig,
    session_id: UUID,
) -> K8sSandbox:
    """建立新 sandbox Pod。"""
    await _load_k8s_config()
    pod_name = f"sandbox-{session_id}"
    pod_spec = client.V1Pod(
        metadata=client.V1ObjectMeta(
            name=pod_name,
            namespace=cfg.namespace,
            labels={
                "app": "orion-agent-sandbox",
                "session-id": str(session_id),
                "managed-by": "orion-agent",
            },
        ),
        spec=client.V1PodSpec(
            runtime_class_name=cfg.runtime_class,
            restart_policy="Never",
            automount_service_account_token=False,  # sandbox 不該拿 K8s SA token
            enable_service_links=False,             # 不要把 cluster 服務注入 env
            security_context=client.V1PodSecurityContext(
                run_as_non_root=True,
                run_as_user=1000,
                run_as_group=1000,
                fs_group=1000,
                seccomp_profile=client.V1SeccompProfile(type="RuntimeDefault"),
            ),
            containers=[client.V1Container(
                name="sandbox",
                image=cfg.image,
                image_pull_policy="IfNotPresent",
                command=["sleep", "infinity"],
                resources=client.V1ResourceRequirements(
                    requests={
                        "cpu": cfg.cpu_request,
                        "memory": cfg.memory_request,
                        "ephemeral-storage": "500Mi",
                    },
                    limits={
                        "cpu": cfg.cpu_limit,
                        "memory": cfg.memory_limit,
                        "ephemeral-storage": "2Gi",
                    },
                ),
                security_context=client.V1SecurityContext(
                    allow_privilege_escalation=False,
                    capabilities=client.V1Capabilities(drop=["ALL"]),
                    read_only_root_filesystem=False,  # workspace 要寫
                    run_as_non_root=True,
                ),
                volume_mounts=[client.V1VolumeMount(
                    name="workspace", mount_path="/workspace",
                )],
            )],
            volumes=[client.V1Volume(
                name="workspace",
                empty_dir=client.V1EmptyDirVolumeSource(
                    size_limit=cfg.workspace_size,
                ),
            )],
            image_pull_secrets=(
                [client.V1LocalObjectReference(name=cfg.image_pull_secret)]
                if cfg.image_pull_secret else None
            ),
        ),
    )

    async with client.ApiClient() as api_client:
        api = client.CoreV1Api(api_client)
        await api.create_namespaced_pod(namespace=cfg.namespace, body=pod_spec)
        await _wait_for_pod_ready(api, cfg.namespace, pod_name, cfg.pod_startup_timeout)

    return K8sSandbox(pod_name=pod_name, namespace=cfg.namespace)


async def _wait_for_pod_ready(api, namespace, pod_name, timeout) -> None:
    """polling Pod 進到 Running 狀態。"""
    start = asyncio.get_event_loop().time()
    while asyncio.get_event_loop().time() - start < timeout:
        pod = await api.read_namespaced_pod(pod_name, namespace)
        if pod.status.phase == "Running":
            if pod.status.container_statuses and all(
                s.ready for s in pod.status.container_statuses
            ):
                return
        elif pod.status.phase in ("Failed", "Unknown"):
            raise RuntimeError(f"Pod {pod_name} entered {pod.status.phase}")
        await asyncio.sleep(0.5)
    raise TimeoutError(f"Pod {pod_name} not ready within {timeout}s")
```

### `sandbox/k8s_pool.py`(預熱 pool)

```python
"""K8s sandbox pool。

策略:
  - ReplicaSet 維持 N 個 "warm" pod(label: state=warm)
  - 新 session 來 → patch label state=warm → state=in-use, session-id=<uuid>
  - 用完 → **不重用**,刪掉(安全大於性能);ReplicaSet 自動補一個新的

不重用的理由:即使 reset workspace 也可能有殘留(env / mount cache)。
session-per-pod 安全保證強。
"""
from __future__ import annotations

from uuid import UUID

from kubernetes_asyncio import client

from orion_agent.sandbox.k8s_backend import (
    K8sSandbox,
    K8sSandboxConfig,
    _load_k8s_config,
    create_sandbox,
)


class K8sSandboxPool:
    def __init__(self, namespace: str, warm_size: int = 5) -> None:
        self.namespace = namespace
        self.warm_size = warm_size

    async def acquire(self, session_id: UUID) -> K8sSandbox:
        """從 warm pool 取一個,patch label。池空了直接 create。"""
        await _load_k8s_config()
        async with client.ApiClient() as api_client:
            api = client.CoreV1Api(api_client)
            pods = await api.list_namespaced_pod(
                namespace=self.namespace,
                label_selector="app=orion-agent-sandbox,state=warm",
            )
            if not pods.items:
                return await create_sandbox(
                    K8sSandboxConfig(namespace=self.namespace), session_id,
                )

            warm_pod = pods.items[0]
            pod_name = warm_pod.metadata.name
            patch = {
                "metadata": {
                    "labels": {
                        "state": "in-use",
                        "session-id": str(session_id),
                    }
                }
            }
            await api.patch_namespaced_pod(
                name=pod_name, namespace=self.namespace, body=patch,
            )
            return K8sSandbox(pod_name=pod_name, namespace=self.namespace)

    async def release(self, session_id: UUID) -> None:
        """釋放(直接刪 Pod,ReplicaSet 補新的)。"""
        await _load_k8s_config()
        async with client.ApiClient() as api_client:
            api = client.CoreV1Api(api_client)
            pods = await api.list_namespaced_pod(
                namespace=self.namespace,
                label_selector=f"session-id={session_id}",
            )
            for pod in pods.items:
                await api.delete_namespaced_pod(
                    name=pod.metadata.name,
                    namespace=self.namespace,
                    grace_period_seconds=5,
                )
```

> **注意**:StatefulSet 不適合(Stateful 是有序、固定身份)。實務上用 **ReplicaSet + label patch** 或自寫 Operator 更彈性。

## K8s Manifests

### Namespace + PSS

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: orion-sandboxes
  labels:
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/warn: restricted
---
apiVersion: v1
kind: Namespace
metadata:
  name: orion-api
```

### ServiceAccount + RBAC

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: orion-api-sa
  namespace: orion-api
---
# 授權 API SA 在 sandbox namespace 管 pods
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: sandbox-manager
  namespace: orion-sandboxes
rules:
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["create", "get", "list", "watch", "delete", "patch"]
  - apiGroups: [""]
    resources: ["pods/exec"]
    verbs: ["create", "get"]
  - apiGroups: [""]
    resources: ["pods/log"]
    verbs: ["get"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: api-can-manage-sandboxes
  namespace: orion-sandboxes
subjects:
  - kind: ServiceAccount
    name: orion-api-sa
    namespace: orion-api
roleRef:
  kind: Role
  name: sandbox-manager
  apiGroup: rbac.authorization.k8s.io
```

### NetworkPolicy(預設 deny egress)

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: sandbox-deny-egress
  namespace: orion-sandboxes
spec:
  podSelector:
    matchLabels:
      app: orion-agent-sandbox
  policyTypes:
    - Egress
  egress:
    # 只允許 DNS(若需要)
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: kube-system
      ports:
        - protocol: UDP
          port: 53
    # 不允許其他 egress(包括 internet 與 cluster 內服務)
    # 若 sandbox 工具需要連外(WebFetch),走 API Pod 代理
---
# 同 namespace 內 ingress 只允許 API Pod
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: sandbox-ingress-from-api
  namespace: orion-sandboxes
spec:
  podSelector:
    matchLabels:
      app: orion-agent-sandbox
  policyTypes:
    - Ingress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: orion-api
          podSelector:
            matchLabels:
              app: orion-agent-api
```

### RuntimeClass(gVisor)

```yaml
apiVersion: node.k8s.io/v1
kind: RuntimeClass
metadata:
  name: gvisor
handler: runsc
# 假設集群已安裝 gVisor:
# https://gvisor.dev/docs/user_guide/quick_start/kubernetes/
```

### ResourceQuota + LimitRange

```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: sandbox-total-quota
  namespace: orion-sandboxes
spec:
  hard:
    pods: "100"               # 全 namespace 最多 100 個 sandbox
    requests.cpu: "20"
    requests.memory: "40Gi"
    limits.cpu: "100"
    limits.memory: "200Gi"
---
apiVersion: v1
kind: LimitRange
metadata:
  name: sandbox-pod-limits
  namespace: orion-sandboxes
spec:
  limits:
    - type: Container
      max:
        cpu: "2"
        memory: "4Gi"
      min:
        cpu: "100m"
        memory: "128Mi"
      default:
        cpu: "1"
        memory: "2Gi"
      defaultRequest:
        cpu: "200m"
        memory: "256Mi"
```

### 預熱 pool(用 ReplicaSet)

```yaml
apiVersion: apps/v1
kind: ReplicaSet
metadata:
  name: sandbox-warm-pool
  namespace: orion-sandboxes
spec:
  replicas: 5  # 預熱 5 個
  selector:
    matchLabels:
      app: orion-agent-sandbox
      state: warm
  template:
    metadata:
      labels:
        app: orion-agent-sandbox
        state: warm
    spec:
      runtimeClassName: gvisor
      automountServiceAccountToken: false
      enableServiceLinks: false
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: sandbox
          image: your-registry/orion-agent-sandbox:latest
          command: ["sleep", "infinity"]
          resources:
            requests:
              cpu: "200m"
              memory: "256Mi"
            limits:
              cpu: "1"
              memory: "2Gi"
          securityContext:
            allowPrivilegeEscalation: false
            capabilities:
              drop: ["ALL"]
            runAsNonRoot: true
          volumeMounts:
            - name: workspace
              mountPath: /workspace
      volumes:
        - name: workspace
          emptyDir:
            sizeLimit: "1Gi"
```

> **重要**:當 ReplicaSet 偵測到 `state=warm` 的 Pod 數量低於 `replicas`(因為被 patch 成 `state=in-use` 後不再 match selector),會自動補新的。**ReplicaSet 的 selector 改用 `state=warm`**,不是只看 `app`。這樣 patch label 後該 Pod 就「離開 ReplicaSet」,不會被 ReplicaSet 控制。

### API Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: orion-api
  namespace: orion-api
spec:
  replicas: 3
  selector:
    matchLabels:
      app: orion-agent-api
  template:
    metadata:
      labels:
        app: orion-agent-api
    spec:
      serviceAccountName: orion-api-sa
      containers:
        - name: api
          image: your-registry/orion-agent:latest
          ports:
            - containerPort: 8000
          env:
            - name: ORION_DB_URL
              valueFrom:
                secretKeyRef:
                  name: db-credentials
                  key: url
            - name: REDIS_URL
              value: "redis://redis.orion-data:6379/0"
            - name: ORION_SANDBOX_NAMESPACE
              value: orion-sandboxes
            - name: ORION_SANDBOX_RUNTIME_CLASS
              value: gvisor
          resources:
            requests:
              cpu: "500m"
              memory: "512Mi"
            limits:
              cpu: "2"
              memory: "2Gi"
          livenessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 30
            periodSeconds: 10
          readinessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 5
            periodSeconds: 5
```

## Helm Chart values.yaml 範例

```yaml
api:
  image: your-registry/orion-agent
  tag: "0.1.0"
  replicas: 3
  resources:
    requests: {cpu: 500m, memory: 512Mi}
    limits: {cpu: 2, memory: 2Gi}

sandbox:
  image: your-registry/orion-agent-sandbox
  tag: "0.1.0"
  runtimeClass: gvisor   # gvisor / kata-qemu / runc
  warmPoolSize: 5
  resources:
    requests: {cpu: 200m, memory: 256Mi}
    limits: {cpu: 1, memory: 2Gi}
  networkEgress: deny    # deny / allow-internet / proxy-via-api

postgres:
  enabled: true   # 設 false 用 cloud DB,從 secret 讀 url
  storageClass: standard
  storageSize: 20Gi

redis:
  enabled: true

monitoring:
  enabled: true
  otelEndpoint: "tempo.monitoring:4317"
```

## 設計決策與取捨

### 為何 sandbox 不重用?

對應 Phase 9 的 sub-agent 隔離設計。**安全 > 性能**:
- 重用容器有殘留風險(env、cache、tmpfs)
- gVisor / Kata 啟動已不慢(2-5s with warm image)
- 預熱 pool 已緩解 cold start

若你的場景對冷啟動極敏感(< 1s),才考慮重用 + 嚴格 reset。

### 為何 sandbox SA token automount = false?

sandbox Pod 不該拿 K8s API token 對 cluster 操作。設 `automountServiceAccountToken: false` 確保。

### 為何用 ReplicaSet 而非 StatefulSet?

- StatefulSet 給有序、固定身份(`pod-0`、`pod-1`),適合 DB
- Sandbox 是無狀態 worker,**ReplicaSet 更貼合**
- 進階方案:寫 Operator(custom controller)更精準控制 pool

### 為何預熱 ReplicaSet 的 selector 用 `state=warm`?

當 Pod 被 patch 成 `state=in-use`,ReplicaSet 的 selector 不再 match → ReplicaSet 視為「少了一個」→ 自動補新的。比寫 controller 簡單,且 K8s 原生機制保證一致。

### 為何 NetworkPolicy 預設 deny egress?

最大攻擊面是 sandbox 連外:
- 攻擊者 prompt 注入 → Bash 連外網挖礦 / 滲透
- WebFetch tool 被誤用打內網

預設切網,要連外的工具(WebFetch)走 API Pod 代理。代價:WebFetch 慢一點(多一跳),但 cluster 安全大幅提升。

### 為何用 gVisor 而非 Kata?

| | gVisor(runsc)| Kata Containers |
|---|---|---|
| 隔離強度 | user-space kernel(中) | full VM(強) |
| 啟動時間 | 1-2s | 3-5s |
| 性能損失 | 5-15% | 10-25% |
| 相容性 | 大多數 syscall | ~100%(VM) |
| 集群安裝 | 簡單(DaemonSet) | 需 KVM 支援 |

**MVP 建議 gVisor**(夠安全 + 啟動快)。安全要求極高才升 Kata。

### 為何 sandbox 走 K8s exec API 而非 SSH / agent?

- K8s exec 已內建,不用維運第二層服務
- 透過 SA token 認證,不用管 SSH key
- 串流支援好

代價:exec 延遲略高(~100-200ms vs Docker 50ms)。

## 性能與規模

| Metric | 預期值 |
|---|---|
| Pod 冷啟動(無 warm pool)| 5-10 秒 |
| Pod 啟動(從 warm pool)| ~50ms(label patch) |
| Exec 命令延遲 | 100-200ms / call |
| Pod 密度 | 100-500 per node(看 node 規格) |
| 預熱 pool 維持成本 | 5 × (200m CPU + 256Mi RAM) = 1 vCPU + 1.3 GiB / 集群 |

## Verification

```bash
# 1. Helm lint
helm lint deploy/helm/orion-agent

# 2. Render templates
helm template deploy/helm/orion-agent \
    --values deploy/helm/orion-agent/values.production.yaml

# 3. 啟 kind cluster(local K8s)
kind create cluster --config kind-config.yaml

# 4. 安裝 gVisor RuntimeClass(若 kind 沒 runsc node 可改 runc 跑通流程)
kubectl apply -f deploy/helm/orion-agent/templates/sandbox/runtimeclass.yaml

# 5. helm install
kubectl create namespace orion-api
kubectl create namespace orion-sandboxes
helm install orion-agent deploy/helm/orion-agent \
    -n orion-api \
    --set image.tag=latest \
    --set env.ANTHROPIC_API_KEY=... \
    --set env.ORION_JWT_SECRET=... \
    --set postgres.url=postgresql+asyncpg://...

# 6. K8sBackend smoke
kubectl exec -n orion-api deploy/orion-api -- \
    orion run --sandbox k8s "echo hi from k8s"
# → 開 sandbox Pod、exec、cleanup

# 7. 跑單元測試
pytest tests/sandbox/k8s/ -v
```

關鍵測試:

- `test_create_pod.py`:create + ready + exec + delete 端到端
- `test_pod_isolation.py`:在 Pod 內 `rm -rf /workspace` 不影響其他 Pod
- `test_network_policy.py`:Pod 內 `curl https://google.com` 失敗(deny egress 生效)
- `test_warm_pool_replenish.py`:patch state=in-use 後 ReplicaSet 自動補
- `test_resource_limit.py`:Pod 內 fork bomb 觸發 OOM kill

手動驗證:

```bash
# 看 sandbox namespace
kubectl get pods -n orion-sandboxes
# 應該看到 5 個 state=warm 的 Pod + 0~N 個 state=in-use

# 模擬 user 跑對話 → 看新 Pod
kubectl get pods -n orion-sandboxes -w

# 對話結束 → 看 Pod 被刪 + 新 warm 補上
```

## 風險與踩雷

| 風險 / 踩雷 | 緩解 |
|---|---|
| K8s API client 需 in-cluster credentials | ServiceAccount + RBAC 自動掛 |
| Pod cold start 慢 | 加 warm pool ReplicaSet(opt-in,values.warmPool.enabled) |
| sandbox Pod 出 control plane 流量 | NetworkPolicy egress deny-all,只開 DNS + proxy |
| RBAC 過大 | scope 到 namespace `orion-sandboxes` 即可 |
| gVisor 需 node 裝 runsc | 標 RuntimeClass `gvisor`,沒有就 fallback runc(values flag) |
| state snapshot 體積大 | 只存 state_messages + replacement_state,壓縮 |
| **gVisor 不支援某些 syscall**(strace、bpf 相關) | 事前確認 sandbox image 內所有預期工具都能跑;`gvisor-compat-test` 掃 syscall |
| **K8s exec stream 取消不乾淨**(`asyncio.wait_for` timeout 後 ws leak) | 明確 `await ws.close()`;sandbox 內加 timeout 機制(雙保險) |
| **image pull 慢(冷啟動主因)** | DaemonSet pre-pull;imagePullPolicy: IfNotPresent;本地 registry 加速 |
| **NetworkPolicy 沒生效**(CNI 不支援) | 確認集群 CNI(Calico / Cilium 支援,Flannel 預設不支援) |
| **OOMKill 沒監控** | 從 Pod events / metrics 抓(`reason=OOMKilling`),回給模型有意義錯誤訊息 |
| **ResourceQuota 觸發** | graceful 處理 + 回 429 給 user(等 quota 釋放) |
| **warm pool 消耗預算** | off-hour CronJob 縮 pool size,或用 KEDA 按 queue depth 調 pool |
| **Pod 殭屍**(process crash 但 Pod 還在) | 設 cron job 清:`state=in-use AND age > N hours` |
| **K8s API rate limit** | API Pod 加 client-side rate limiting(`max-qps` flag in kubernetes client) |
| **本機 dev 沒 K8s** | kind / minikube / k3d;`docker-compose.yml` 保留為「無 K8s」dev 模式,production 才走 K8s |

## 參考資料

- [kubernetes_asyncio](https://github.com/tomplus/kubernetes_asyncio) — async K8s Python client
- [gVisor docs](https://gvisor.dev/) — user-space kernel
- [Kata Containers](https://katacontainers.io/) — VM-level isolation
- [Pod Security Standards](https://kubernetes.io/docs/concepts/security/pod-security-standards/) — restricted profile
- [NetworkPolicy](https://kubernetes.io/docs/concepts/services-networking/network-policies/)
- [E2B](https://e2b.dev/) — managed sandbox 替代方案
- [Modal](https://modal.com/) — 同上
- [KubeVirt](https://kubevirt.io/) — VM-in-K8s(進階方案)
- [Phase 7](../07-sandbox-production.md) — Docker socket mount 版本(本文件取代其 sandbox 部分)
- [Phase 9](../09-worktree-telemetry.md) — sub-agent 隔離(同樣用 sandbox)

## 完成檢查表

- [ ] `sandbox/k8s_backend.py` 取代 / 並列 `sandbox/docker_backend.py`
- [ ] `sandbox/k8s_pool.py` warm pool acquire / release
- [ ] `api/session_state_redis.py` cross-instance state snapshot
- [ ] K8s manifests:Namespace / SA / RBAC / NetworkPolicy / RuntimeClass / ResourceQuota / LimitRange
- [ ] gVisor RuntimeClass 集群安裝(或對應 Kata)
- [ ] 預熱 ReplicaSet pool 邏輯
- [ ] Helm chart 骨架 + values.yaml + values.production.yaml
- [ ] Migration Job(pre-install / pre-upgrade hook)
- [ ] HPA + PodDisruptionBudget
- [ ] 在 kind / minikube 上跑通端到端
- [ ] NetworkPolicy 驗證(Pod 內 curl 外網失敗)
- [ ] `deploy/README.md` Helm install / upgrade 流程
- [ ] phase-7c 完工 doc:K8s 與 Docker 設計取捨對比

## 完成 Phase 7c 後

進 Phase 8(hooks / skills / plugins)的 Phase 8c(plugin marketplace),或回頭做其他 follow-on phases。

## 一句話總結

**API 部署在 K8s 時,**不要** mount docker socket — 改用 K8s API 動態建 Pod-per-session,搭配 gVisor RuntimeClass + Pod Security Standards restricted + NetworkPolicy deny egress + 預熱 ReplicaSet pool;sandbox SA token automount = false 防 token leak;exec 走 K8s exec API 不需 SSH;ReplicaSet selector 用 `state=warm` label 自動補位用掉的 Pod;production 化用 Helm chart 包整套(API + sandbox + Postgres + Redis + monitoring)— 安全大於性能,sandbox 用完就刪不重用。**
