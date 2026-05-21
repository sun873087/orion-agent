# Enterprise scale — 公司內部 10K+ user / 跨國場景

此文件記錄「**未來若要把 orion-agent 推到企業內部 1 萬人、跨國使用**」的設計思考。
目前不在實作範圍 — 留作未來再拿出來討論的起點。

> 一句話定位:現在 orion 是「**對的方向但很多地基還缺**」。從 hobby / team SaaS
> 升到企業級,工程量大約等於「再做一輪 model-proxy 規模」的事。

---

## TL;DR 三條紅線(不商量)

從 hobby 到企業 10K + 跨國,三件事沒得妥協:

1. **不自建 identity** — 接公司 corporate SSO(Okta / Entra ID / Google Workspace),Orion 只是 IdP 的 consumer。Identity 工程是個黑洞,在企業環境已經有現成 IdP,自建就是白做。
2. **資料 region-pinned** — 歐洲 user 對話絕對不能流出歐洲(連 audit log 也是)。data plane 必須 per-region;control plane 可 global。
3. **DLP / PII redaction 必須在 proxy egress 層做** — 不在 client(可繞過),不在 LLM provider(資料已出去),只能在 proxy 攔。

---

## 整體架構:三層解耦

```
┌─────────────────────────────────────────────────────────────┐
│  Identity layer (consumer of corporate IdP)                 │
│  - OIDC / SAML federation (Okta / Entra ID / Google)        │
│  - SCIM provisioning + deprovisioning                       │
│  - Group / role sync from AD                                │
│  - Service account / API token for automation               │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│  Control plane (global, replicated)                         │
│  - User / org / cost-center tree                            │
│  - Configuration / policy / DLP rules                       │
│  - Audit log aggregation (read-only)                        │
│  - Billing rollup / chargeback                              │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│  Data plane (region-pinned: EU / US / APAC / CN)            │
│  - Per-region orion-model-proxy + chat-api + Cowork sidecar │
│  - Per-region Postgres (user history, usage_log, audit_log) │
│  - Per-region LLM endpoint routing                          │
│  - Per-region blob store                                    │
└─────────────────────────────────────────────────────────────┘
```

---

## 各層具體要做的事

### 🔐 1. Identity / Auth

**必須**:
- **OIDC / SAML** federation — 接 Okta / Entra ID / Google Workspace / Ping
- **SCIM 2.0 endpoint** — 自動 provision/deprovision,人離職馬上撤所有 access
- **Group / role 從 IdP 同步** — 「research-team」「engineering」「admin」直接 inherit
- **Service account** — 自動化任務(CI / batch)用 non-human credential,有獨立 budget
- **MFA / 2FA** — admin endpoint 強制(可委派給 IdP MFA)
- **Just-in-time provisioning** — user 第一次 SSO 登入就建 row,不需先匯入

**取代什麼**:
- SDK `users.username + password_hash` 完全廢棄
- `user.id` 改成 SSO subject(idempotent across re-provision)
- Cowork 桌機從「本機 1 user 寫死」改成「sign in to corporate account」

**為什麼**:10K user 沒人會接受 username + password;IT 不會核可;onboarding/offboarding 必須自動。

---

### 🌐 2. Multi-region / data sovereignty

**必須**:
- **資料 row 加 `region` tag** — 任何 user / session / message / usage_log 都標 region
- **Per-region data plane** — EU / US / APAC / CN 各自獨立 stack
- **Per-region LLM provider routing**:
  - EU → Anthropic EU + OpenAI EU(若有)+ Mistral
  - US → Anthropic / OpenAI / Azure OpenAI US
  - APAC → Azure OpenAI Japan / Anthropic
  - CN → Azure OpenAI 中國區 / 通義千問 / 智譜
- **Cross-region 不允 query**(GDPR/個保法 default deny,例外要 legal 審)
- **Disaster recovery 跨 region**(備份)但**讀取 region-pinned**

**為什麼**:
- GDPR / 中國個保法 / 韓國 PIPA / 日本 APPI 各家對「跨境傳輸」有不同限制
- 中國 user 直連 OpenAI/Anthropic 會被擋,需要落地 provider
- 延遲問題:user 在台北 → US-east proxy → US LLM,RTT 累積到體驗爛

---

### 💰 3. Cost governance at scale

10K user × $50/月中位 = **$500K/月 LLM spend**。這個級別需要:

**必須**:
- **Cost-center tree**:現在 `organizations` 是 flat,要改成 `company → department → team → user`,費用沿樹 aggregate
- **預算審批 workflow**:user 申請加額度 → manager 批 → IT 啟用,接 Slack / Teams approve button
- **月度 chargeback report 匯出**:finance system(SAP / Oracle / Workday)能讀的格式
- **異常偵測**:5 min 內燒 $500 → 自動 pause + page admin
- **Forecast**:看本月 burn rate + 預測月底會超
- **Per-model / per-task / per-cost-center 報表**:哪個部門用哪個 model 最多

**現在缺**:
- `organizations` 表只有 1 層(flat),沒樹狀
- 沒 approval workflow
- 沒 finance system 整合
- 沒 forecast / anomaly detection(只有 hard cap)

---

### 📋 4. Compliance

**必須**:
- **Audit log 不可竄改**:append-only + signed + cross-region 備份 + 7 年保存(財務 / 法務要求)
  - SQLite WAL 完全不夠
  - Postgres + cryptographic chain(hash 每筆鏈進下一筆)
  - 或外送 immutable storage(S3 object lock / BigQuery)
- **DLP / PII redaction**:prompt 進外部 LLM **前**掃,目前 0 防護
  - 偵測 SSN / 信用卡 / 電話 / 客戶資料 / source code commit
  - 接 Microsoft Purview / Google DLP API / Presidio
  - **必須在 proxy 那層做**,不在 client 做
- **資料分級**:
  - `internal` — 一般工作對話,可送外部 LLM
  - `confidential` — 限私有 LLM(self-hosted Llama / 公司 vLLM)
  - `restricted` — 不允 LLM 任何處理,只能本機 chunk 拆解
  - user 自己標 + DLP 自動分類
- **內部知識整合 + ACL**:
  - 整合 Confluence / SharePoint / Notion / Google Drive
  - retrieval 時必須 enforce 「user 可看的才回」,不能跨 user leak
- **Right to be forgotten**:user 離職 → 一鍵刪所有 history + audit 紀錄(留 metadata-only 計費歷史)

---

### 🛡 5. Security

**必須**:
- **VPN-only / zero-trust gateway**:Tailscale / Cloudflare Zero Trust / Zscaler,不開公網
- **mTLS** 服務間
- **KMS / secrets management**:Vault / AWS Secrets Manager / Azure Key Vault
  - `.env` 文件 enterprise 完全不行
  - Secret rotation 自動化
- **DB 加密**(at rest)
- **Blob store 加密**(`~/.orion/blobs/` 在 fleet 規模要 encrypted-at-rest)
- **Network egress 白名單**:只允去 specific LLM endpoints + 必要服務
- **API key 短期效期**:Service account token 自動旋轉(預設 90 天)
- **Admin SSO + MFA mandatory**

---

### 🔧 6. Reliability / SRE

**必須**:
- **Postgres production-ready**:現在 Postgres 支援但沒打磨。connection pool / index / query plan 都要校。
- **HA setup**:per-region primary + read replica + automated failover
- **LLM provider failover wire**:`failover.py` 骨架已有,要實作
  - Anthropic down → 自動切 Azure OpenAI(同 model 家族 mapping)
  - Cross-provider model alias(`reasoning-default` → 各 provider 對應 model)
- **SLO 定義**:
  - p99 first-token latency < 3s
  - Availability 99.9% 月度
  - Error rate < 0.5%
- **Incident runbook**:LLM provider outage / DB primary fail / region partition / 預算超
- **Connection pooling / circuit breaker** 完整

---

### 📊 7. Observability

**必須**:
- **OTel 全打開**:metrics / traces / logs 都送 Datadog / Splunk / Grafana Cloud
  - 現在 OTel skeleton 只 emit `_track_usage` 一個 span
- **Per-region dashboard**:每 region 一份 Grafana / Datadog dashboard
- **Alerting** 從 PagerDuty / Opsgenie 觸發:budget threshold / error rate / latency p99 / SLO burn rate
- **APM trace correlation**:`X-Orion-Request-Id` 串 client → proxy → upstream → log
- **Centralized structured logging**:JSON logs 統一格式,ELK / Splunk ingest

---

### 💻 8. Cowork 桌機 fleet management

10K endpoint 不可能各自下載安裝。

**必須**:
- **MDM 部署**(Jamf for Mac / Intune for Win / SCCM)+ pre-configured profile
  - 預設 proxy URL / model / SSO endpoint / cert pinning 都在 profile 內
- **Code signing + notarization** mandatory(Mac + Windows;Win 要 EV cert)
- **Staged rollout**:先 1% canary → 10% → 50% → 100%,error spike 自動 rollback
- **Group policy**:預設 model / DLP 等級 / 公司禁用設定 IT 強制
- **Crash reporting**:Sentry / Crashlytics
- **Auto-update opt-out for compliance**:有些部門必須鎖版本

---

## 跨國的「不對稱複雜度」

公司在多國通常意味:

| 領域 | 複雜度 |
|---|---|
| **法務** | GDPR / CCPA / 個資法 / 中國個保法 / 日本 APPI / 韓國 PIPA / 巴西 LGPD,每個都不同玩法 |
| **LLM 可用性** | 中國要 Azure OpenAI 中國區 / 通義;歐洲偏好 Mistral;CN/RU 用戶完全不能去 OpenAI |
| **時區 + on-call** | 24/7 oncall = follow-the-sun,跨 3 個 office |
| **Localization** | UI / docs / support 至少 EN + 主要市場語言;UI date/number 格式 |
| **採購 / 合約** | 各國子公司可能各自跟 LLM 廠商簽約,計費要對應到各國 entity |
| **支付 / 計費幣別** | 各 region 用自己幣別,需要 FX 換算與 audit |
| **稅務** | LLM 廠商發票稅務不同,需要 per-region 抓 |

---

## 切片順序(future critical path)

要做就要按這個順序,跳順序會卡:

### 階段 A:地基(blocking everything else)

1. **接 corporate SSO**(OIDC + SCIM)
2. **重畫 user / org / cost-center schema**(user → team → cost-center 樹),user_id = SSO subject
3. **Postgres production-ready**(alembic / pool / index / migration)
4. **KMS / Vault 接入**,secret 從 env 移走
5. **資料 row 加 `region` tag**(連 schema 都先加,讓 migration 不痛)

### 階段 B:治理

6. **DLP / PII redaction layer**(proxy 加一層,prompt egress 前掃)
7. **Audit log 升級**(append-only + signed + 跨 region 備份)
8. **Cost-center 層級計費** + chargeback report export
9. **預算審批 workflow**(Slack / Teams approve button)
10. **Anomaly detection**(burn rate spike 自動 pause)

### 階段 C:規模

11. **Multi-region 拆**:per-region data plane(EU / US / APAC / CN),global control plane
12. **LLM provider failover wire**(跨 provider 切換 + model alias)
13. **HA setup**(read replica / automated failover / circuit breaker)
14. **Cowork MDM 包裝**(Jamf / Intune profile)
15. **SLO 定義 + 告警 + runbook**

### 階段 D:可選 / 進階

16. **私有 LLM 部署選項**(self-hosted Llama / vLLM)給 confidential data
17. **內部知識 ACL-aware retrieval**(Confluence / SharePoint 整合)
18. **Custom fine-tune pipeline**(公司專屬語料)
19. **Internal LLM marketplace**(部門自選 model + 自管 prompt template)

---

## 不會走的路(明確 out-of-scope,即使企業也不該做)

- **完全自建 IdP** — 沒 ROI,接 Okta/Entra ID 就好
- **完全自建 LLM training pipeline** — 用商業 fine-tune API(OpenAI / Anthropic 提供)就足夠 99% 場景
- **多 cloud 全自管**(AWS + Azure + GCP 同時跑)— pick one,multi-cloud 是工程黑洞
- **自家 vector DB infra** — 用 pgvector / Pinecone / Weaviate cloud
- **獨立的 audit log database 系統** — append-only to Postgres + S3 object lock 就夠

---

## 為什麼現在不做

- **10K user 規模需要團隊**(SRE / security / compliance 各 1-2 人),hobby project 階段做不到
- **法務合規工作 > 技術工作** — 沒法務 review 寫出來的 GDPR 控制不會有人簽
- **工程量大致是「再做一輪 model-proxy」**:proxy 寫了大概兩個 phase,企業化大概要 4-6 個 phase
- **過早 build 會 over-engineer** — hobby 階段需要的是 iteration 速度,enterprise control plane 會拖後腿

---

## 何時觸發這個討論

當下面 3 個之中任一發生:

1. 公司 / 客戶說「我們要正式採用,給我 SSO + audit log」
2. 月度 LLM cost 累積到「需要 cost-center 拆分管理」(估計 $50K/月起)
3. 多 region 需求出現(歐洲 / 中國同事說「資料能不能不要出國」)

否則:**這份文件靜靜放在 roadmap/ 就好**。

---

## 看完繼續

- [`README.md`](./README.md) — 主要 roadmap(現有規模的方向)
- [`../architecture/design-decisions.md`](../architecture/design-decisions.md) — 已凍的設計決策
- [`../features/model-proxy.md`](../features/model-proxy.md) — proxy 的現況(企業化的起點)
