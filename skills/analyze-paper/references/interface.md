# analyze-paper 介面（v0.4）

## 用途與邊界

只分析指定論文或閱讀封包；不自動啟動比較、寫綜述或外網補查。人可用一般語言指定檔案及問題，不必先產生 JSON。

## 輸入

必須：一篇本機 Markdown（可含明確指定補充）、或 CorpusIndex + 文件範圍、或自足 TaskSpec。選填：研究問題、quick/standard/deep、語言、輸出目錄；未指定使用一般研究問題、standard、使用者語言及新目錄。論文類型不明先 unknown。
TaskSpec 模式須完整讀 parts 並產生 ChunkAnalysis；不可用單篇摘要取代逐 part 回應。

## 輸出

- 封包模式：ChunkAnalysis + submit receipt；succeeded 不等於完成整篇。
- 單篇／全部封包完成：PaperAnalysis v2、claims.jsonl、evidence.jsonl、coverage.json；組裝器自動生成 paper_readings/ 中文報告。
- 要做完整交接：用 handoff 附 claims / evidence / corpus，產生 paired JSON/Markdown/manifest。
- 明確缺失判定：FieldAssessmentSet + assess-fields，新版本保留舊版。

## 最小操作

原文與 schema 形狀見 [assets/examples](../assets/examples/)，檔名見該資料夾 example-index.json。
以下為實際 CLI，將大寫路徑換成絕對路徑，命令預設不覆寫：

```bash
python /ABS/SKILL/scripts/litreview.py prepare ONE_PAPER_INPUT --out CORPUS
python /ABS/SKILL/scripts/litreview.py job init --corpus CORPUS --out JOB --config CONFIG
python /ABS/SKILL/scripts/litreview.py job next --job JOB --worker ACTUAL_READER_CONTEXT
# 讀 task_path，寫 ChunkAnalysis，再逐封包提交：
python /ABS/SKILL/scripts/litreview.py job submit RESPONSE --job JOB --worker ACTUAL_READER_CONTEXT
python /ABS/SKILL/scripts/litreview.py job assemble --job JOB --out ANALYSIS
```

獨立使用不需 coordinator；job 僅為分段／覆蓋工具。收集完可將 JSONL 的特定 PaperAnalysis 存為單一 JSON 再 handoff。

## 缺資料與完成條件

無檔案、表格 context 不足、輸出不足以回傳完整封包：回 TaskResult v2 needs_input，具體指出 required_input，不提交 partial ChunkAnalysis。
全文覆蓋完成仍是 unverified。not_reported 需全篇檢查理由；沒有 findings 一律 not_extracted。
