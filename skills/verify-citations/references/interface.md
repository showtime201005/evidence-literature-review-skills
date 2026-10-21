# verify-citations 介面（v0.4）

## 用途與邊界

獨立查核提供報告或比較的每個主張、非空行及原文支持；不負責替作者修文、補外部來源或確認外部撤稿資訊。

## 輸入

可接受任意人寫報告 + 來源 + 明確書目 aliases、ReviewDraft + Evidence + corpus，或 verification packet。比較使用 comparison-packet 產生的投影封包，不要求先寫 review。
必須與 writer/comparer 有不同的實際任務上下文；不可只改 ID 假裝獨立。來源與被查核目標版本必須完整；不足則 needs_input。

## 輸出

VerificationSet（原有 1.x 契約仍適用）：target ID/hash、evidence hashes、每 claim 判定與理由、每非空行分類、issues、實際 producer context。handoff 產生逐句查核報告，必要時附原草稿與來源。
比較 caller 使用 comparison-accept 綁定成 ComparisonVerification v2；verifier 自己不改比較 JSON 的信任欄位。
判定 partially_supported、unsupported、contradicted、uncertain 都不能當作 publication passed。

## 最小操作

```bash
python /ABS/SKILL/scripts/litreview.py verification-packet DRAFT --corpus CORPUS --evidence EVIDENCE --out PACKET
# 在另一實際任務上下文完整閱讀 PACKET；寫出 VERIFICATION_JSON。
python /ABS/SKILL/scripts/litreview.py validate VERIFICATION_JSON
python /ABS/SKILL/scripts/litreview.py handoff VERIFICATION_JSON --material DRAFT --material EVIDENCE --corpus CORPUS --out NEW_HANDOFF
```

每個 reason 說明原文支持到哪裡；不要只回 supported。每個修正問題指出 claim ID、所需修正、required_input、owner、retryable。
大型封包不能截斷；目前要求 caller 分節並最終掃描整份組裝報告，自動分片合併器仍未完成。
範例中的 fixture 驗證不是模型真實審查答案；不能複製 verdict 當作本次結論。
