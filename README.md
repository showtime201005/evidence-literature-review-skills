# Evidence Literature Review Skills v0.6

可獨立使用的全文分析、比較、寫作、引用查核與完整回顧 skills。正式交付附來源快照、精確證據、逐主張驗證、閱讀覆蓋與可讀報告。

**範圍：提供的 Markdown 文獻，最多 100 篇邏輯論文。** 不自動搜尋外部資料庫或宣稱搜盡整個領域。缺少數據時保留缺口，不猜補。

## 交給另一台電腦的 OpenCode

複製本 repo 的 `release/v0.6` branch 後，將以下指令交給 OpenCode：

> 請讀取這個 repository 的 INSTALL.md，將五個 skills 安裝到我指定的研究專案，執行安裝檢查。保留既有檔案；先使用 examples/papers 的合成語料校準。完成後回報實際產物與驗證狀態。不要把診斷通過當成文獻研究品質通過。

需要 Python 3.11+（實測 3.12.14）、OpenCode。原生 runner 固定測試 OpenCode 1.19.3；其他版本須重新驗收。DeepAgents 原生入口固定 0.7.0。

## 能力

| Skill | 可直接提供的輸入 | 主要輸出 |
|---|---|---|
| analyze-paper | 單篇 Markdown 或來源封包 | 分析、主張、原文證據與限制 |
| compare-papers | 原文、分析或外部研究筆記 | 可比較條件、矩陣、分歧與缺口 |
| write-review | 可追溯證據或外部研究筆記 | 草稿、引用映射與證據交接包 |
| verify-citations | 人類報告與原文 | 支持／反駁／不足判定及修正需求 |
| literature-review | 完整語料、問題或待補數據報告 | 全文回顧／補證、獨立驗證與正式交付 |

四個子 skills 不需要彼此安裝或先跑協調器。完整協調模式才需要五個 skills。

## 已測與未測

- 207 項回歸全通過；五個 skills 的兩套框架入口診斷共 10 次成功。
- 原生 CLI／SDK 的載入、讀檔、Python 與子代理整合使用 scripted provider 測試。
- 當前模型對三篇合成文獻的回顧，27 個主張、23 份證據、9 個來源分片及獨立整份審核通過。
- 尚未驗收真實 provider 在兩套框架內的研究品質；未人工學術複核；100 篇只測機械負載。

詳見 [驗收紀錄](docs/validation-summary.md)、[原生入口](docs/native-harness-guide-v06.zh-TW.md)。`examples/papers/` 是合成資料，不能作為真實研究證據。
