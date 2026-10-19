# v0.5：可續跑的獨立分片驗證

## 建立、來源查核、組裝審核、合併

```bash
python /ABS/SKILL/scripts/litreview.py verification-plan DRAFT --corpus CORPUS --evidence EVIDENCE \
  --context REQUEST --context SEARCH --context QUESTION_MAP --max-chars 90000 --out VERIFY_DIR
python /ABS/SKILL/scripts/litreview.py verification-status --plan VERIFY_DIR
```

--context 可重複：完整回顧需 request/search/map；補證需 augmentation plan/resolutions/request/search/map。--max-chars 是封包字元限制，不是 token 上限；實際 harness 仍須對模型 messages/tools/output 計算預算。
輸出 plan.json、target.json、corpus、evidence、packets、context 及可逐項保存的 records。每個 packet 完整包含自己的草稿、主張、原文上下文、局部 lines_to_scan；同一主張與跨行映射不會被切斷。
packet.corpus_location='../corpus' 以 packet JSON 所在資料夾為基準解析；可以移動整個 VERIFY_DIR 續跑，不可只搬單一 packet。

將每個 pending packet 交給與 writer 不同的實際 verifier 任務；使用 verify-citations。只給 packet 和 skill，不給 writer 自辯。當 context 不夠時使用新的 verifier 任務，不讓對話累積超限。
回傳 VerificationSet 的 target/hash/evidence_hashes 取自該 packet；scan offsets 使用 packet 的 LOCAL start_char/end_char，不是 global_range。

```bash
python /ABS/SKILL/scripts/litreview.py verification-submit VERIFICATION_JSON --plan VERIFY_DIR --shard SHARD_ID
```

程式逐項重查原文定位、hash、writer/verifier 不同上下文、完整主張與非空行、所有 verdict supported，才保存 record。失敗不計完成；accepted record 不同內容不得覆寫。status 會只列 pending；不要重做已驗收片段。

```bash
python /ABS/SKILL/scripts/litreview.py verification-assembly-packet --plan VERIFY_DIR --out ASSEMBLY_PACKET
```

必須全部片段通過後，交給新的 assembly auditor 任務。它必須與 writer 及來源 verifiers 皆為不同實際上下文。依封包的 target_path/context_paths 讀必要內容（可分段），檢查整份組裝的引用、來源範圍、問題回答、反證及跨章節一致性。
這個組裝檢查不是再把整個 corpus 塞入單一 prompt；逐句原文支持已有完整片段紀錄，auditor 審查最終組裝及全部研究 context。讀不下必要內容就回 unresolved，不能只看 accepted 數量就批准。

AssemblyAudit v2：target_artifact_id/target_hash/plan_hash、checks、issues、producer.context_id。
checks 必須含 coverage/citation_consistency/scope/counterevidence/question_coverage，每項 status=passed/needs_revision/unresolved 和具體 reason。issues 用共用 Issue 格式，不可漏填。

```bash
python /ABS/SKILL/scripts/litreview.py verification-merge --plan VERIFY_DIR --audit ASSEMBLY_AUDIT --out MERGED_VERIFICATION
```

合併不是把幾個 passed 串在一起。程式重驗每片、恢復 global offsets、核對每個主張恰好一次與每個非空行完整覆蓋，保留 sharded_proof（plan、各 verifier record、assembly audit）；最終 gate 可在沒有原佇列 DB 時重驗。
修改目標文字、主張、證據、研究 context，必須新建 plan；舊驗證不可挪用。發現原文上下文不足／大型原子表格，明確要求調整來源封包或提高預算，不截斷。不可分割的單一單位過大會 OVERSIZED_VERIFICATION_UNIT，而不是假稱已分片完成。

## 比較的分片

小型比較仍可 comparison-packet → verifier → comparison-accept。大型比較先執行 `comparison-draft COMPARISON --out DRAFT`，再用該投影建 verification-plan；合併 VerificationSet 再 comparison-accept。這一步不先組裝超出預算的單一封包。比較本身的完整內容／metadata 仍綁定同一投影與來源，不需要先寫綜述。
