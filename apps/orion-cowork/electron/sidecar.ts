/**
 * Sidecar lifecycle:spawn / kill / 解析 stdout JSON frames。
 *
 * Wire format(newline-delimited JSON):每行一個 JSON object。
 * Sidecar 可能在一行寫多個 chunk 但 newline 一定是 frame boundary。
 *
 * RpcClient 提供:
 *   - call(method, params, onFrame):送 request,onFrame 為每筆 frame 觸發,
 *     resolve 時 final frame 已抵達。
 *   - dispose():SIGTERM sidecar,等 exit。
 */

import { ChildProcessWithoutNullStreams, spawn } from 'node:child_process'
import { resolve } from 'node:path'

type Frame = Record<string, unknown> & { id?: string; final?: boolean }
type FrameHandler = (frame: Frame) => void

let nextRequestId = 0

export class SidecarClient {
  private proc: ChildProcessWithoutNullStreams | null = null
  private buffer = ''
  private pending = new Map<string, FrameHandler>()
  private notifyListeners = new Set<FrameHandler>()
  private readyResolve: (() => void) | null = null
  private readyPromise: Promise<void>

  constructor() {
    this.readyPromise = new Promise((res) => {
      this.readyResolve = res
    })
  }

  /** Spawn `uv run --package orion-cowork-sidecar python -m orion_cowork_sidecar`。 */
  start(repoRoot: string): void {
    const proc = spawn('uv', ['run', '--package', 'orion-cowork-sidecar', 'python', '-m', 'orion_cowork_sidecar'], {
      cwd: repoRoot,
      env: { ...process.env, PYTHONUNBUFFERED: '1' },
      // stdin / stdout / stderr 都管
    })
    proc.stdout.setEncoding('utf8')
    proc.stderr.setEncoding('utf8')
    proc.stdout.on('data', (chunk: string) => this.onStdout(chunk))
    proc.stderr.on('data', (chunk: string) => {
      // Sidecar 的 stderr 給 main process 看 (debug);不送 renderer
      console.error('[sidecar]', chunk.trimEnd())
    })
    proc.on('exit', (code, signal) => {
      console.error(`[sidecar] exited code=${code} signal=${signal}`)
      // 通知所有 pending: error
      for (const [id, handler] of this.pending) {
        handler({ id, error: { code: 'SIDECAR_EXIT', message: `sidecar exited` }, final: true })
      }
      this.pending.clear()
      this.proc = null
    })
    this.proc = proc
  }

  /** 等到 sidecar 寫出 `{"event":"sidecar.ready"}`。 */
  waitReady(): Promise<void> {
    return this.readyPromise
  }

  /** 註冊 notification(無 id 的 sidecar→main 訊息)handler。 */
  onNotification(handler: FrameHandler): () => void {
    this.notifyListeners.add(handler)
    return () => this.notifyListeners.delete(handler)
  }

  /**
   * 呼叫 RPC method。onFrame 每個 streaming frame 觸發一次;
   * Promise resolve 在收到 final:true 時。
   */
  call(method: string, params: Record<string, unknown>, onFrame?: FrameHandler): Promise<void> {
    if (!this.proc) throw new Error('sidecar not started')
    const id = `req-${nextRequestId++}`
    return new Promise((resolveCall, rejectCall) => {
      this.pending.set(id, (frame) => {
        onFrame?.(frame)
        if (frame.final) {
          this.pending.delete(id)
          if (frame.error) rejectCall(new Error(JSON.stringify(frame.error)))
          else resolveCall()
        }
      })
      const line = JSON.stringify({ id, method, params }) + '\n'
      this.proc!.stdin.write(line)
    })
  }

  dispose(): Promise<void> {
    if (!this.proc) return Promise.resolve()
    return new Promise((res) => {
      const p = this.proc!
      p.once('exit', () => res())
      try {
        p.stdin.end()  // EOF → graceful shutdown
      } catch {
        // ignore
      }
      // 強制 fallback 3 秒
      setTimeout(() => p.kill('SIGTERM'), 3000).unref()
    })
  }

  private onStdout(chunk: string): void {
    this.buffer += chunk
    const lines = this.buffer.split('\n')
    this.buffer = lines.pop() ?? ''
    for (const line of lines) {
      if (!line.trim()) continue
      let frame: Frame
      try {
        frame = JSON.parse(line)
      } catch (err) {
        console.error('[sidecar] malformed frame:', line)
        continue
      }
      if (frame.event === 'sidecar.ready' && !frame.id) {
        this.readyResolve?.()
        this.readyResolve = null
        continue
      }
      if (frame.id === undefined) {
        for (const h of this.notifyListeners) h(frame)
        continue
      }
      const handler = this.pending.get(frame.id)
      if (handler) handler(frame)
    }
  }
}

export function findRepoRoot(): string {
  // Electron __dirname is dist/electron/ at runtime,or apps/orion-cowork/electron/ in dev
  return resolve(__dirname, '..', '..', '..', '..')
}
