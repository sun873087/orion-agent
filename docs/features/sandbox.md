# Sandbox

把 `Bash` / `Read` / `Write` / `Edit` 等會碰 host 的工具關到隔離環境(Docker container 或
受限 local subprocess),保護 host 不被 LLM 誤觸發。

**實作位置**:`packages/orion-sdk/src/orion_sdk/sandbox/`

## 3 種 mode

| Mode | 行為 |
|---|---|
| **`none`**(預設) | 直接在 host 跑(快、無隔離)— dev / 信任場景 |
| **`local`** | subprocess + chroot-like jail + ulimit(CPU / memory cap)— Linux/macOS 輕量 |
| **`docker`** | 跑指定 image 內,workdir mount RW,網路 off / on toggle — production |

## 設定

```bash
ORION_SANDBOX=docker
# or local / none

# Docker mode 進一步:
ORION_SANDBOX_IMAGE=python:3.12-slim
ORION_SANDBOX_NETWORK=off      # off / bridge
ORION_SANDBOX_CPU_LIMIT=2
ORION_SANDBOX_MEMORY_LIMIT=2g
ORION_SANDBOX_TIMEOUT=300
```

## 介入

Sandbox-aware tools(Bash / Read / Write / Edit)在 SDK 內查 ctx.sandbox_config,根據 mode
切實際執行 backend:

```
Bash("ls -la /")
  ├─ ORION_SANDBOX=none  → asyncio.subprocess
  ├─ ORION_SANDBOX=local → subprocess in jail dir + ulimit
  └─ ORION_SANDBOX=docker → docker run --rm -v workspace:/work:rw --network off image bash -c "ls -la /"
```

## 設計取捨

- **None 預設**:dev 自家機器跑 agent 沒必要 sandbox。Production / shared 環境才開
- **Docker 透過 docker-py**:不寫 shell call,API control 更精準
- **Workspace 永遠 RW mount**:LLM 要編輯 code,要能寫進去。但 host /etc 之類不 mount

## 限制 / 已知問題

- **Docker mode 起 container 慢**:cold start ~1s,每個 Bash 都 spawn 一次 → 反覆 call 累積。要 long-lived container + exec 模式(尚未做)
- **Local jail 不 secure**:LLM 可以走 absolute path / symlink 逃逸。真要 secure 用 docker
- **Network off 阻擋 pip install / npm install**:LLM 想裝套件就失敗 — workaround:base image 預裝 / on-demand toggle

## 未來方向

- **Long-lived sandbox**:同 session 共用一個 container,exec 進去跑 command,不每次 spawn
- **gVisor / Firecracker**:更輕量的 sandbox runtime(比 docker 啟動快 10×)
- **Per-tool sandbox**:`Bash` 在 docker,`Read` 在 local(read-only 不必這麼重)

## 看完繼續

- [tools.md](./tools.md) — Tool 怎麼宣告自己要 sandbox
- [permissions.md](./permissions.md) — 跟 permission policy 互補
