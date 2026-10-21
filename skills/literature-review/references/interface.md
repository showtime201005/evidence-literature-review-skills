# literature-review 介面（v0.5）

## v0.5 正式入口

完整回顧依 [研究模式](research-modes.md) 執行 research-request → 全文閱讀與 corpus-search → QuestionEvidenceMap → 比較／寫作 → [分片來源查核與組裝審核](verification-shards.md) → review-deliver。缺口補證先輸入原報告及精確 anchors，建立 augmentation-plan 與 augment-request，執行同樣的全集閱讀／搜尋，再用 augmentation-draft → 獨立查核 → augment-deliver。

兩種交付均強制逐問題×逐論文覆蓋、凍結查核 context，並保存可重播的 reading_checkpoint/。補證另含原報告、修改後報告、補證說明及精確修改清單；原報告品質仍為 not_audited。以下 deliver 是舊資料相容入口，新完整回顧必須改用 review-deliver 並傳 request/search/question-map。

## 用途與邊界

協調完整 corpus-only 回顧或續跑；四個能力各自可獨立呼叫，不強制所有任務都經此入口。

## 輸入

新任務：Markdown 集合或 manifest、研究問題；選填深度、時間／worker 預算、語言、輸出位置。沿用既有確認事項；未指定用 standard / 全文優先 / soft deadline。
續跑：既有 job 路徑及目標，先 status / next，不覆寫 accepted responses。
已存在合格外部材料可跳過相應能力；沒有可對照的原文覆蓋時，不能稱為新完成的全文回顧。

## 輸出

完整交付有 review.md、paper_reviews/（查核過的逐篇附錄）、paper_analyses.jsonl（完整原始擷取＋報告選入資訊）、analysis/paper_readings/（原始可讀分析）、evidence_matrix.csv、comparison.json、verification.json、coverage.json、issues.jsonl、run_manifest.json、references.json、原文與證據。
新增 delivery-summary.md、comparison-summary.md、verification-summary.md。報告通過不表示所有原始擷取都已獨立驗證；publication_selection 記錄範圍。

paper_analysis_readings/ 與最終 paper_analyses.jsonl 由同一份資料產生；若另有明確缺失判定，deliver 用 --field-assessment ASSESSMENT（可重複，依修訂次序）套用，否則保留 not_extracted/unknown。不能只交已評估的 JSON 卻不傳 assessment，然後假設交付器會自行找到它。

## 新比較的交付

```bash
python /ABS/SKILL/scripts/litreview.py deliver --job JOB --draft DRAFT --verification REPORT_VERIFICATION \
  --comparison COMPARISON_V2 --comparison-verification COMPARISON_VERIFICATION \
  --evidence EVIDENCE --out NEW_DELIVERY
```

--evidence 重複提供完整集合（JSON 或 JSONL）；各 verifier 宣告的證據須是其實際使用且 hash 相符的集合。可額外攜帶未被該目標引用的材料，不能把未查核材料宣稱已查核。報告與比較皆須經獨立查核。可以先比較查核，再寫報告。
舊 v1 比較仍保留原有報告 claim 綁定規則，不能冒充新版獨立比較。

## 品質與問題交接

TaskResult v2 表達 complete/partial 的實際任務結果與所需輸入；succeeded 不等於 quality passed。
研究內容缺口、漏擷取、來源缺漏和未知欄位必須顯示，不能用「100% 區段都有 observation」抵銷。
嚴格期限內做不完，保留 job/checkpoint 與 issues；提供人類可讀摘要及下次操作，不宣稱正式交付成功。
自動驗證大型分片、人工學術基準、100 篇真實模型與公司推論仍需後續驗收。
