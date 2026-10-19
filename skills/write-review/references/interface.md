# write-review 介面（v0.4）

## 用途與邊界

由提供的可追溯材料寫整篇或指定一節；不要求固定上游，不自動執行新文獻閱讀或外網補查。

## 輸入

必須：寫作問題／範圍及研究材料。選填：讀者、語言、篇幅、章節、比較結果、既有草稿。預設使用者語言、一般研究讀者、依材料內容選擇適當篇幅；明示這些選擇，不重新詢問已確認事項。
原文證據不足可產生明示未驗證的草稿，同時 TaskResult partial/needs_input 列出所需證據。來源缺漏不可用模型常識補齊。

## 輸出

sections.json → ReviewDraft（原有 1.x 契約仍適用）、原文 Evidence、精確 claim_mappings 與 citation placeholders；handoff 另生可讀 summary.md。
保留 source_fact / synthesis / analyst_inference / scope_statement 差異。寫作不改變原始 PaperAnalysis.fields；未選入的結果記為 selection，不是 not_reported。
ComparisonSet v2 可以作材料，但報告自己的 Claim 仍需原文證據；不能把比較通過當作所有新改寫句子已查核。

## 最小操作

```bash
python /ABS/SKILL/scripts/litreview.py draft SECTIONS_JSON --context-id ACTUAL_WRITER --out DRAFT_JSON
python /ABS/SKILL/scripts/litreview.py handoff DRAFT_JSON --material EVIDENCE --corpus CORPUS --out NEW_HANDOFF
```

sections 的完整可用範例見 ../assets/examples/sections.json。輸出 JSON 與人讀 Markdown 必須來自同一版內容。

## 完成與交接

寫作完成預設 unverified；由不同任務上下文查核。只寫一節不必提供全 corpus appendices。
完整 literature-review 交付另外要求全部逐篇附錄與來源覆蓋；不要為了讓一節通過而偽造全篇覆蓋。
若人改過輸出 Markdown，當成新輸入 report 重建映射及驗證，不沿用舊 hash。
