# Phase 7c — Kubernetes 部署 + Helm Chart + Pod-per-session Sandbox

**狀態**:📋 Plan(等 K8s cluster 環境)
**前置**:Phase 7 完成(SandboxBackend Protocol、DbSessionManager、deploy/Dockerfile)
**估時**:1-2 天

## 動機

Phase 7 範圍 B 完成了 Production Foundation,但**沒有 cluster 可實測 K8s**,
因此把 Helm chart / Pod-per-session sandbox 完整實作切到本 phase。Phase 7
的 `deploy/docker-compose.yml` 是本機 dev 用,production 走這個。

## 範圍

### 做

| 項目 | 說明 |
|---|---|
| **Helm chart** | `deploy/helm/orion-agent/` 含 values.yaml、Deployment、Service、Ingress、ConfigMap、Secret、ServiceAccount、HPA |
| **K8sBackend** | `src/orion_agent/sandbox/k8s_backend.py` — 每 conversation 開一個 Pod,exec via `kubectl exec` API,讀寫檔 via `kubectl cp` 或 client-go subresource |
| **Pod template** | per-session sandbox Pod spec(image=orion-agent-sandbox:tag) |
| **NetworkPolicy** | sandbox Pod 預設 deny-all egress,只開 allowlist DNS / proxy |
| **gVisor RuntimeClass** | 額外 syscall 隔離(可選 — node 須裝) |
| **RBAC** | API Pod 需 ServiceAccount 能 create/exec/delete sandbox Pods 在 `orion-sandbox` namespace |
| **預熱 pool**(可選) | warm Pod 池減少 cold start;ReplicaSet 維持 N 個 idle Pods |
| **Migration job** | Helm hook 跑 `alembic upgrade head` 在 API rollout 前 |
| **Cross-instance session 復原** | 加 Redis 存 Conversation state snapshot,任何 worker 都能 resume |
| **Probes** | livenessProbe / readinessProbe / startupProbe |

### 不做(留更後)

- Multi-tenancy(per-tenant namespace) → Phase 11+
- Service mesh(Istio / Linkerd) → optional,operator 自選
- Vault / Secrets operator → optional,Helm 預設用 K8s Secret

## 檔案結構

```
deploy/helm/orion-agent/
├── Chart.yaml
├── values.yaml                         預設值
├── values.production.yaml              production override 範例
└── templates/
    ├── _helpers.tpl
    ├── deployment-api.yaml             API Deployment(replicas, env, probes)
    ├── service-api.yaml                ClusterIP
    ├── ingress.yaml                    可選
    ├── configmap.yaml                  ORION_LOG_FORMAT 等
    ├── secret.yaml                     placeholder(production 改用 ExternalSecret)
    ├── serviceaccount.yaml
    ├── rbac.yaml                       Role / RoleBinding(create pods 在 sandbox ns)
    ├── networkpolicy-api.yaml          API egress allow-list
    ├── networkpolicy-sandbox.yaml      sandbox egress deny-all + DNS allow
    ├── job-migrate.yaml                Helm hook pre-upgrade
    ├── hpa.yaml                        Horizontal Pod Autoscaler
    └── poddisruptionbudget.yaml

src/orion_agent/sandbox/
└── k8s_backend.py                      [新] K8sBackend 實作 SandboxBackend Protocol

src/orion_agent/api/
└── session_state_redis.py              [新] Redis-backed Conversation snapshot

deploy/
└── README.md                           [改] 加 Helm install / upgrade / rollback 段落
```

## 實作順序(11 步)

| Step | 工作 |
|---|---|
| 1 | `pyproject` 加 `kubernetes` Python client、`redis[hiredis]` |
| 2 | `sandbox/k8s_backend.py`(client.CoreV1Api、`stream` API exec、`get_log`)|
| 3 | unit test:K8sBackend with mock kubernetes client |
| 4 | `api/session_state_redis.py`:dump / load Conversation state(Pickle 或 JSON) |
| 5 | `api/session_manager_db.py` 整合 Redis fallback(DB cache miss → Redis 復原) |
| 6 | Helm chart skeleton + values.yaml |
| 7 | API Deployment + Service + ConfigMap + ServiceAccount + RBAC templates |
| 8 | NetworkPolicy + gVisor RuntimeClass(可選 annotation)|
| 9 | Migration Job(pre-install / pre-upgrade hook) |
| 10 | HPA + PodDisruptionBudget |
| 11 | `deploy/README.md` Helm install / upgrade 流程 + Phase 7c 完工 doc |

## Verification

```bash
# 1. Helm lint
helm lint deploy/helm/orion-agent

# 2. Render templates
helm template deploy/helm/orion-agent --values deploy/helm/orion-agent/values.production.yaml

# 3. 實際安裝(需 cluster)
kubectl create namespace orion
helm install orion-agent deploy/helm/orion-agent -n orion \
    --set image.tag=latest \
    --set env.ANTHROPIC_API_KEY=... \
    --set env.ORION_JWT_SECRET=... \
    --set postgres.url=postgresql+asyncpg://...

# 4. K8sBackend smoke
kubectl exec -n orion deploy/orion-agent-api -- \
    orion run --sandbox k8s "echo hi from k8s"
# → 開 sandbox Pod、exec、cleanup
```

## 風險

| 風險 | 緩解 |
|---|---|
| K8s API client 需 in-cluster credentials | ServiceAccount + RBAC 自動掛 |
| Pod cold start 慢 | 加 warm pool ReplicaSet(opt-in,values.warmPool.enabled) |
| sandbox Pod 出 control plane 流量 | NetworkPolicy egress deny-all,只開 DNS + proxy |
| RBAC 過大 | scope 到 namespace `orion-sandbox` 即可 |
| gVisor 需 node 裝 runsc | 標 RuntimeClass `gvisor`,沒有就 fallback runc(values flag) |
| state snapshot 體積大 | 只存 state_messages + replacement_state,壓縮 |

## 完成 Phase 7c 後

進 Phase 8(hooks / skills / plugins)或 Phase 9(advanced agents)。
