# Phase 20:Transcript JSONL 壓縮

## 速覽

- **預計時程**:半天
- **前置 Phase**:Phase 2(JSONL transcript 已實作)
- **觸發來源**:Phase 2 完工後觀察:大 conversation transcript 不壓縮會肥到幾十 MB
- **主要交付物**:
  - 寫時可選 gzip(JSON line → gzip-compressed line)或整檔 rotate-and-gzip
  - 讀時 transparent 解壓
  - 環境變數 `ORION_TRANSCRIPT_COMPRESSION`(none / gzip,預設 none)

## 1. 為何要做

JSONL 文字壓縮率高(JSON 重複 key、空白多)。實測一個 50 turn 的 conversation 可從 5MB → 500KB。

但壓縮複雜度:
- 不能 line-by-line gzip(每行包 gzip header 浪費)
- 整檔 stream gzip 跟 anyio.Lock 衝突(append mode + gzip header reset 困難)

## 2. 任務拆解

選一個策略:

### 策略 A:每筆 record 個別 gzip + base64

- record 寫入時 `gzip.compress(json.dumps(rec).encode())` 再 base64 → 一行
- 讀時 base64 decode → gzip.decompress → json.loads
- 簡單但壓縮率較差(~50%)

### 策略 B:整檔 rotate-and-gzip

- transcript.jsonl 寫到 N MB 後 rename → transcript.jsonl.1.gz,gzip 壓
- 新 transcript.jsonl 開新檔
- 讀時掃所有 .jsonl + .jsonl.*.gz 串起
- 壓縮率好(~10%)但 rotation 邏輯複雜

**選 A**(簡單可控)。

- [ ] `storage/session.py:_serialize_record` 在 compression=gzip 時走 gzip+base64 路徑
- [ ] `iter_records_sync` 自動偵測(看是否 base64 + gzip header)
- [ ] 環境變數 `ORION_TRANSCRIPT_COMPRESSION` 控制
- [ ] 寫 unit test 驗 round-trip

## 3. 驗收標準

```python
async def test_gzip_transcript_roundtrip(monkeypatch):
    monkeypatch.setenv("ORION_TRANSCRIPT_COMPRESSION", "gzip")
    store = SessionStorage.open(sid)
    big_msg = NormalizedMessage(role="user", content="x" * 10000)
    await store.record_message(big_msg)
    # 檔案應比 raw JSON 小很多
    raw_size = len(json.dumps({"role": "user", "content": "x" * 10000}))
    file_size = sp.transcript.stat().st_size
    assert file_size < raw_size * 0.3
    # 讀回應一致
    records = iter_records_sync(sp.transcript)
    assert records[0]["message"]["content"] == "x" * 10000
```

## 4. 相關 code

- `orion_agent/storage/session.py:_serialize_record` / `iter_records_sync`
