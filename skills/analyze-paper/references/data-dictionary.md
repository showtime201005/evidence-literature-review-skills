# 資料字典與信任邊界（v0.6）

## 版本與獨立性

核心程式版本 0.6.0；舊資料 schema 1.x 可讀，新能力契約使用 2.0.0。不要把更改版本字串當作升級。`migrate` 只有同版本 identity，沒有猜測式跨版轉換。
每個產物自帶 schema_version、artifact_type、artifact_id、payload，可附 producer；不要求 run_id、資料庫或指定上游 skill。
用 `capability-check ARTIFACT` 檢查能力介面。v1 回覆 legacy_requires_explicit_normalization，不升級信任；v2 的 ready 只代表結構可接手。

## 身分與引用

v0.5 的 ReviewRequest、SearchLedger、QuestionEvidenceMap、AugmentationPlan、GapResolutionSet、VerificationPlan、AssemblyAudit 欄位與完整操作見 [研究模式](research-modes.md) 及 [分片查核](verification-shards.md)。搜尋零命中不代表未讀；not_found 是針對已凍結的提供文本範圍。filled 才能改寫指定缺口；其餘狀態保留原文。

| 欄位 | 含義 | 不可誤解為 |
| --- | --- | --- |
| paper_id | 邏輯論文，可含主文、補充與版本 | 檔案路徑 |
| document_id / content_hash | 一份原文快照及其 UTF-8 bytes 版本 | 論文學術品質 |
| artifact_id | 一份具版本的資料產物 | 認證簽章 |
| claim_id / claim_refs | 可逐項判斷的主張及引用 | 書目編號 |
| evidence_id / evidence_refs | 精確原文 span；必須附原文版本 | 該句已被語意支持 |
| producer.context_id | 實際 reader/writer/verifier 任務上下文 | 任意改名即可製造獨立性 |
| target_hash | 目標 payload 指紋 | 另一版文字的驗證通行證 |
| material_refs | 在 v2 ComparisonSet 中指向該比較自己的 claims | 任意外部 notes ID 或最終報告 claim |

原文 span 使用 UTF-8 byte `[start_byte,end_byte)`；報告映射使用 Unicode code point `[start_char,end_char)`，不是 JS UTF-16 索引。章節／論文名稱供人閱讀；offset/hash 供機械稽核。

## 缺失不是一種狀態

| 狀態 | 意義／條件 |
| --- | --- |
| reported | 已擷取文字與 claim_refs，尚不代表獨立語意通過 |
| not_extracted | 這個欄位尚無擷取主張，不能推導原文沒提 |
| not_reported | 閱讀者明確判定原文未報告；須理由及全篇 checked_part_ids |
| not_applicable | 論文類型不適用；須理由及全篇檢查範圍 |
| source_missing | 必要原文／補充資料缺漏，須明確說明 |
| not_checked | 尚未檢查，不可稱為 absence |
| parse_error | 原文存在但無法可靠解析，保留原因 |
| raw_claim_dispositions | selected_exact / derived_in_report / not_mapped_to_report；沒有主張 lineage 不代表研究內容確定沒被使用，更不是原文缺失 |

PaperAnalysis v2 必須包含九欄：research_question、contributions、method、evaluation、results、limitations、conditions、relevance、unexpected_findings。每欄有 status / text / claim_refs / reason / checked_part_ids。未知論文類型標 unknown，不假造實驗。
組裝器不猜 not_reported。要明確判定，產生 FieldAssessmentSet（目標 ID/hash、paper_type、assessments、實際 reader context），再用 `assess-fields` 產生新版本；不能覆蓋已有的 reported 證據。這仍是閱讀者聲明，非獨立語意保證。
若只需分類論文類型，可 assessments=[]，但須明確 paper_type 及 classification_reason，無須編造缺失判定。完整 handoff 應附 assessment 及其目標分析版本；manifest 會列出未附的引用。
capability-check 另依 empirical / theoretical / survey / other 檢查研究內容缺口；缺口不以讀取覆蓋率抵銷。

## 比較語意

ComparisonSet v2 有 question / paper_ids / dimensions / claims / material_refs / cells / unknowns / contradiction_candidates。
每個 paper × dimension 恰好一格。cell 包含 cell_id、paper_id、dimension、proposition、value、status、material_refs、conditions、study_conditions、comparability、counterevidence_refs、reason、verification_status=unverified。

- proposition 是要判斷的具體命題；value 是觀察結果，不是全域排名。
- supported / contradicted / mixed 指該研究與命題的關係；不是 verifier 給的支持判定。
- not_addressed 是檢查後未涉及；unresolved 是證據不足。
- study_conditions 必須明列 dataset / population / metric / unit / baseline / timepoint / sample_size / version。未知用空字串並在 reason/unknowns 解釋，不填 0。
- comparability 有 status（comparable / conditional / not_comparable / unknown）及 reason。不能跨不相容指標直接比大小。
- counterevidence_refs 是 Evidence IDs，必須包含在比較 claims 的 evidence_refs 中；mixed 不可省略反證。
- contradiction_candidates 每筆含 contradiction_id / claim_refs（至少兩個不同主張）/ status / reason。條件差異不直接稱為學術矛盾。

比較自己的主張與所有 cell metadata 會投影成 ReviewDraft 供獨立 verifier 檢查。比較的 immutable JSON 不把 cell 改成 verified；匹配的 ComparisonVerification 才是判定紀錄。

## 執行狀態、品質與問題

TaskResult v2 必須有 task_id / status / quality / artifact_refs / source_hashes / issues。
status 是 succeeded / partial / needs_input / failed / cancelled；quality 是 unverified / needs_revision / passed，兩者獨立。
succeeded 要有 artifact_refs；partial / needs_input / failed 要有問題；needs_input 要明列所需資料。passed 要 verifier refs，仍需 caller 對照實際 gate，不能相信外部標籤。

Issue 必填 code / severity（blocker、warning、info）/ message / required_input（字串陣列）/ owner / retryable / affected_refs。
建議 code：NEEDS_SOURCE、NEEDS_EXTRACTION、AMBIGUOUS_REFERENCE、CONTEXT_BUDGET_EXCEEDED、OUTPUT_TRUNCATED、UNSUPPORTED_CLAIM。不要把這些問題代碼當成 status。
只回報問題，不自行外網補查；預算不足時保留 checkpoint，不偷偷省掉反例。

## 人類閱讀與可攜交接

`handoff ARTIFACT --material MATERIAL [--material ...] [--corpus CORPUS] --out NEW_DIR` 產生 artifact.json / summary.md / materials/ / manifest.json；加 corpus 時包含原文快照並檢查 Evidence locator。
--material 接受 envelope JSON 或 JSONL，也接受組裝器 claims.jsonl 的裸 Claim records（會驗證並封裝）。檔案參照只在 manifest 使用相對路徑。
manifest 列出缺失引用 unresolved_refs；needs_materials 不得當作完整自足交接。無 corpus 只能檢查包裝，不能聲稱原文已附或定位已檢查。
`handoff-check DIRECTORY` 檢查生成後的 bytes 是否改變。這是完整性檢查，不是防惡意竄改的簽章認證。
summary.md 顯示中文欄位、研究條件、原文摘錄；提供 corpus 才能顯示來源檔名／章節。
人若改 Markdown：保留舊版，以 import-artifact --kind report 匯入新檔、建立新 claims/mappings 並重新驗證。不要改 manifest checksum 掩蓋修訂。
