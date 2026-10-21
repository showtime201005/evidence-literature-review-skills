# Evidence Literature Review Skills — 開發交接快照

**2026-10-21：百篇／90 分鐘驗收尚未通過。這份版本供接續開發與技術交接。**

以 DeepAgents 真實 SDK `task` subagents，配合 OpenRouter `qwen/qwen3.8-27b`，處理 Markdown 論文的抽取、證據卡、比較、綜合與可追溯查核。目標環境為 Windows 與 Ubuntu 22.04；完整單次 LLM request 上限為 200K，較低 provider 上限仍生效。

## 文件與下載

- [完整繁體中文 HTML 技術介紹](docs/implementation-guide.zh-TW.html)：下載後可離線開啟，包含架構圖、五個 skills、協定、input/output、獨立執行及特殊設計。
- [目前進度與開發交接](docs/HANDOFF-2026-10-21.zh-TW.md)：限制、測試證據與接手工作。
- [ZIP 交接包](dist/evidence-literature-review-handoff-2026-10-21.zip)、[SHA256](dist/evidence-literature-review-handoff-2026-10-21.zip.sha256)、[封裝說明](docs/PACKAGE-README.zh-TW.md)。
- [最新實測摘要](docs/evidence/current-status.json)、[安裝指南](INSTALL.md)。

## 五個 skills

| Skill | 用途 | Typed native 入口 |
|---|---|---|
| `analyze-paper` | 原文抽取、條件／限制／反例與 finding obligations | `native_task.py --role reader` |
| `compare-papers` | 維度比較、差異與不相容條件 | `native_task.py --role comparer` |
| `write-review` | 證據卡與分層綜合，保留 claim／來源／保留義務對應 | `native_task.py --role writer` |
| `verify-citations` | 引用與科學主張查核 | 單任務 CLI 是 v1 source-proof 子集；v2 完整 reviewer 由 workflow 或 Python API 驅動 |
| `literature-review` | 協調完整 DAG、修訂、release gate 與匯出 | `native_review.py` |

## 本次狀態

- 最新兩篇冷啟動 v2 實測約 **412.922 秒**後失敗：全流程共用兩輪語義修訂額度耗盡，尚未完成比較、綜合與報告交付。
- 六個定向 closed-check controls 約 **17.984 秒，6/6 符合預期**；不是完整冷啟動 review，也不能代表百篇品質或時間。
- 可攜安裝器已統一。Windows／Ubuntu 歷史測試的版本範圍詳見交接文件，尚未涵蓋所有最新修改。
- 新 `strict-supported-subset/1` 是 Python API 候選，只有離線測試；尚無 provider live probe、尚無 native CLI flag。
- `protocol_completed_experimental`、`publication_verified` 與 `quality_validated` 意義不同；不能以結構驗證或程序完成宣稱科學品質已驗收。

## 開始使用

Python 3.11+。先閱讀交接文件與 HTML 介紹，安裝 [固定依賴](skills/literature-review/scripts/requirements-native.txt)，在環境中設定 `OPENROUTER_API_KEY`，再依文件建立全新執行目錄。模型呼叫可能收費。

`native_review.py` 預設協定仍為 **v1**；本次實驗 v2 必須明確指定 `--review-protocol v2`。`--deadline 5400` 只是時間限制，不代表百篇可在 90 分鐘內完成。範例與 benchmark 均為合成資料，不是可引用的真實研究證據。

原 v0.6 README 保留為 [歷史文件](docs/README-v06.zh-TW.md)；其中測試數量與 SDK 敘述不應視為本次最新版本的驗收結果。
