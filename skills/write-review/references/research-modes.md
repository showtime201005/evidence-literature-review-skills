# v0.5：完整回顧與既有報告補證

## 導覽

1. 共同原則與資料契約
2. 全庫回顧
3. 報告補證
4. 交付與失敗處理

## 共同原則與資料契約

以下命令皆使用本 skill 的 scripts/litreview.py 絕對路徑，以 CLI --help 為準。模型由目前 harness 執行，腳本不私下呼叫模型。
只處理使用者提供的原文，最多 100 個 logical papers，全部讀取，不把關鍵字 top-k 當作閱讀篩選。普通使用者只需給問題、文獻與必要時的既有報告，由 skill 整理下列 JSON。

- ReviewRequest v2：mode=review/augment、source_policy=corpus_only、corpus_hash、paper_ids、questions。每題 question_id/text/terms；terms 是本機搜尋用同義詞，不是篩掉論文的條件。
- SearchLedger v2：每題 × 每篇一列；列出 document_ids、blocks_searched、全部 hits（term、document_id、版本 hash、UTF-8 offsets、exact excerpt）。零命中仍有列。
- QuestionEvidenceMap v2：每題 × 每篇一列，question_id/paper_id/status/support_refs/counter_refs/reason/checked_part_ids。status=supporting/opposing/mixed/not_addressed/uncertain/source_missing。refs 是 Evidence IDs，只能用該論文／同 logical paper 補充材料的原文。
- 每列 checked_part_ids 必須涵蓋該篇全部實際已讀 parts。not_addressed 需要讀者判斷與理由，不能由關鍵字未命中推導。
- Map 的判斷仍是模型聲明；全文覆蓋和逐句獨立驗證各有不同作用，不能承諾完美理解。
- 來源證據位置、區段與報告映射語意沿用 data-dictionary.md。新契約仍使用 schema 2.0.0，新型別不冒充舊型別。

## 全庫回顧

先 prepare corpus，再建立 request。SPEC 例如：

```json
{"mode":"review","questions":[{"question_id":"effect","text":"方法效果、適用條件與反例是什麼？","terms":["accuracy","effect","準確率","limitation","限制"]}]}
```

```bash
python /ABS/SKILL/scripts/litreview.py research-request --corpus CORPUS --spec SPEC --out REQUEST
python /ABS/SKILL/scripts/litreview.py corpus-search --corpus CORPUS --request REQUEST --out SEARCH
# job init / next / submit / assemble：仍依 analyze-paper 完整讀全部 parts。
python /ABS/SKILL/scripts/litreview.py question-map-template --job JOB --request REQUEST --out MAP_TEMPLATE
```

Map template 的 artifact 帶 template=true、reason=MODEL_REVIEW_REQUIRED；這不是完成結果。讀完後，模型根據全文與原始分析逐格填入實際理由、支持／反對 Evidence IDs，移除 template flag；保留真實 checked_part_ids，產生新 artifact_id，再 validate。
一個 paper 可同時提供支持與反例；維度不同、資料集不同及同文版本不要硬排成單一效能排名。

```bash
python /ABS/SKILL/scripts/litreview.py research-check --job JOB --request REQUEST --search SEARCH --question-map MAP --evidence EVIDENCE
```

--evidence 可重複。後續 compare-papers 建矩陣，write-review 建完整正文及每篇附錄。必須回答每題、保留矛盾／未知，不把本 corpus 的缺口宣稱為全領域缺口。
報告使用 verification-plan 自動分片，--context 傳 REQUEST、SEARCH、MAP；完成獨立來源查核及新的組裝審核後 verification-merge。詳見 verification-shards.md。

```bash
python /ABS/SKILL/scripts/litreview.py review-deliver --job JOB --request REQUEST --search SEARCH --question-map MAP \
  --draft DRAFT --verification MERGED_VERIFICATION --comparison COMPARISON \
  --comparison-verification COMPARISON_VERIFICATION --evidence EVIDENCE --out NEW_DELIVERY
```

舊 deliver 是相容低階 API，不能代替 v0.5 的 research coverage gate。比較可先獨立查核；caller 可另外提供額外 Evidence，不能省略驗證已引用的 Evidence 或更改其 hash。

## 報告補證

先讀完整使用者報告，辨認數據缺口、未支持敘述及使用者指定項目。不要擴寫無關章節。為每個缺口提供精確 anchor；重複文字要給 Unicode start_char。
GAPS 是陣列，每項 gap_id（英數/底線/連字號）、anchor、operation=replace/insert_after、question、terms、requirements、expects_numeric。
requirements 使用 dataset/population/metric/unit/baseline/timepoint/sample_size/version，無要求留空；明確要求不可用不同設定補足。未知來源條件仍保留，不當作相同。

```bash
python /ABS/SKILL/scripts/litreview.py augmentation-plan --report ORIGINAL_MD --gaps GAPS --context-id ACTUAL_PLANNER --out AUG_PLAN
python /ABS/SKILL/scripts/litreview.py augment-request --corpus CORPUS --augmentation-plan AUG_PLAN --out REQUEST
python /ABS/SKILL/scripts/litreview.py corpus-search --corpus CORPUS --request REQUEST --out SEARCH
# 全文閱讀所有原文，再完成每個 gap × paper 的 QuestionEvidenceMap。
```

AugmentationPlan 固定 report_text、report_hash、每個 gap 的字元位置；原始 bytes 包含 CRLF 必須保留。不要直接手改報告再沿用舊 plan。
GapResolutionSet v2：plan_id/plan_hash/corpus_hash/claims/resolutions，producer.context_id 是實際補證 writer。每 gap 一筆 gap_id/status/reason/claim_refs/data_points。

- status：filled、partially_filled、not_found、conflicting、incomparable、needs_source。
- claim_refs 指向本 resolution set 的 claims，不是未附的原報告引用；claims 必須有原文 Evidence。
- data_points：value_text（原文數字字串）、conditions（完整 StudyConditions）、evidence_refs。每個數字必須確實出現在所綁定原文中；不支援從外部常識或未審查公式推算。
- filled 的數據條件必須與 gap requirements 相符；要同義詞正規化時明示在理由，不做暗中單位／指標替換。
- not_found 不等於該領域不存在；not_found/uncertain 的來源與閱讀理由必須可稽核。
- 只有 filled 會修改對應 anchor；其他狀態保留原始缺口，另在補證說明呈現可用的局部證據與未解理由。

```bash
python /ABS/SKILL/scripts/litreview.py augmentation-draft --augmentation-plan AUG_PLAN --resolutions RESOLUTIONS \
  --corpus CORPUS --evidence EVIDENCE --out SUPPLEMENT_DRAFT
```

投影草稿把要求、原報告的未驗證上下文、數據條件、擬修改文字與未解理由一起交給 verifier。不要只檢查「數字有沒有出現在原文」，也要確認數字屬於正確方法／族群／指標。
對 SUPPLEMENT_DRAFT 用 verification-plan，--context 必須附 AUG_PLAN、RESOLUTIONS、REQUEST、SEARCH、MAP。來源 verifier 不修改 writer 內容；新的 assembly auditor 檢查所有 context artifacts 後才能 merge。

```bash
python /ABS/SKILL/scripts/litreview.py augment-deliver --report ORIGINAL_MD --augmentation-plan AUG_PLAN --resolutions RESOLUTIONS \
  --job JOB --request REQUEST --search SEARCH --question-map MAP --verification MERGED_VERIFICATION \
  --evidence EVIDENCE --out NEW_DELIVERY
```

## 交付與失敗處理

所有 `--evidence` 接受單一 Evidence JSON 或逐行 Evidence 的 `.jsonl`，可重複混用；assemble 的 evidence.jsonl 可直接接入，不需手動拆檔。JSONL 每一行仍須是完整合法的 Evidence envelope，重複 ID 的內容必須一致。

兩種正式交付均保留 reading_checkpoint/：原文、凍結任務、逐區段閱讀回應、接受紀錄與擷取證據。可對該路徑執行 status 和 assemble 重檢全文覆蓋；不需要原本的 SQLite 佇列或私人對話。閱讀 observation 是模型的執行聲明，不能當成人工閱讀保證。

回顧增加 research_request.json、search_ledger.json、question_evidence_map.json、research_coverage.md。
補證提供 original_report.md（原文不覆寫）、augmented_report.md、supplement.md、patch_manifest.json、原始來源／分析／搜尋／查核。使用獨立的 [補1] 等來源標記，不覆蓋原報告原有編號。
supplement_quality=passed 不代表原報告全文已正確；original_report_quality=not_audited 必須出現在摘要和產物。想查原報告全部內容需另外執行 verify-citations。
來源不足仍可交付「有查核、未能補足」的補證報告，不能為了填滿欄位編造數值。模型／程式 gate 失敗則回傳明示未通過的草稿、問題和 checkpoint；不能當成正式成功。
