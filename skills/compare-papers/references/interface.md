# compare-papers 介面（v0.4）

## 用途與邊界

單獨比較指定研究材料，不要求 analyze-paper 已跑過，不先寫綜述、不外網補查。

## 輸入

必須：比較問題、比較維度及帶來源身分的材料。可接受 PaperAnalysis、原文證據、外部 notes/CSV。若使用者未指定維度，先提出與問題相符的維度，記錄在輸出。
可用既有 notes 做降級探索；缺原文／證據不能產生假裝可驗證的 v2 比較。回 needs_input 或 partial，附未驗證探索材料與所需來源。
完整 v2 比較需要比較主張及 program-checked Evidence；沒有 run_id／私有資料庫前提。

## 輸出

ComparisonSet v2 + evidence 材料；handoff 生成矩陣與詳細條件。範例見 ../assets/examples/comparison.json 及 data-dictionary.md。
每格明確命題、觀察值、條件、可比性、理由與反證；所有科學主張在 claims 中有原文 evidence_refs。
不要使用最終報告 claim ID 作為比較的必需上游。

## 獨立查核

```bash
python /ABS/SKILL/scripts/litreview.py capability-check COMPARISON
python /ABS/SKILL/scripts/litreview.py comparison-packet COMPARISON --corpus CORPUS --evidence EVIDENCE --out PACKET
# 新的 verifier 任務只接收 PACKET，產生 VerificationSet；由 caller 綁定：
python /ABS/SKILL/scripts/litreview.py comparison-accept COMPARISON --corpus CORPUS --evidence EVIDENCE --verification VERDICTS --out COMPARISON_VERIFICATION
python /ABS/SKILL/scripts/litreview.py comparison-check COMPARISON --corpus CORPUS --evidence EVIDENCE --verification COMPARISON_VERIFICATION
```

--evidence 可重複。comparability、反證或任何 metadata 改動均使舊驗證失效。cell verification_status 保持 unverified，信任由外部匹配的 ComparisonVerification 給予。
若只做探索，可交付清楚標示未驗證的材料，不必為此執行 write-review。

## 人可讀交接

```bash
python /ABS/SKILL/scripts/litreview.py handoff COMPARISON --material EVIDENCE --corpus CORPUS --out NEW_HANDOFF
```

檢查 manifest.unresolved_refs。條件不相容時不排名，保留 mixed／unresolved，缺資料不是零。
