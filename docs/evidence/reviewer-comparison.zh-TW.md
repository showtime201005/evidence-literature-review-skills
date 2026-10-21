# 本次 selector cold2：獨立卡片審查與 reviewer 對照

獨立結論先於 reviewer 對照封存：`2026-10-20T19:21:55.214951+00:00`。只讀本次原文、卡片、查核材料；未讀歷史 host audit/gold，未呼叫模型、tokenizer 或測試，未改執行中資料。

## 結果

- 已獨立檢查 S01 的 9 條、S08 的 12 條主張。主要效應、CI、null/adverse 子群、persistent failure、未測量成本或效用、研究設計與族群限制都有保留；未發現主要數值反轉。
- 原生 accepted reviewers：S01 71/71、S08 120/120 判 supported，兩者 issues/new_omissions 均空。
- 仍確認 6 組 reviewer false-pass：1 組指定引用缺口、5 組 named-retention 錯配（涉及 13 個義務列，不是 13 個獨立科學事實錯誤）。
- 另 3 項語氣/會計邊界/子群名稱精度疑慮保持不確定，不計入 confirmed false-pass。
- S08 的一次 selector 越 own refs 被機械拒絕後改正，不算以上科學問題的檢出。

## 確認漏檢

|獨立編號|指定責任|reviewer 實際判定與問題|
|---|---|---|
|I01|S08 c7 / u7 / m17|唯一引用 p0053 只有 update schedule，沒有 monthly；reviewer 重述 monthly，仍說四條條件「All match」。monthly 在原文其他 part，可補引用，不能借全文代替 own ref。|
|I02|S08 f38 → c4 / u89–91|c4 沒有標註品質檢查、未測 clinical utility。reviewer 對 u90 明說 utility 在 c6，仍判指定 c4 保留成功。|
|I03|S08 f29 → c6 / u65–66|c6 沒有 1880/14200。reviewer 明說這兩數在 c1，仍以 distributed across c1 and c6 判 supported。|
|I04|S08 f33 → c11 / u74–77|c11 是標註與共識標籤程序，沒有未測 clinical utility / Recall@5 邊界；reviewer 以 c2/c4/c6 他處資訊救援指定 c11。|
|I05|S08 f35 → c5 / u83–84|c5 的同凍結版本/受控設計不等於相同輸出政策、支持答案定義、衝突時來源權威；reviewer 把 partially in c5 當 included 成功。|
|I06|S08 f36 → c4 / u85–86|c4 的 qualification loss 不等於最小完整證據上下文、value/unit/population 綁定與表格 caption/notes 規則；reviewer 以同主題與部分條款取代整個義務。|

這些記錄直接顯示 named-claim 指派被放寬成「卡片任一處／同主題部分內容存在」。現行 worker 指令要求核對 exact named claims，並明確說 shared topic 或 one preserved clause 不足。這不是 selector 還原原文或版本綁定失效；是模型查核判斷未遵守責任。

## 保持不確定

- I07 S01 c5：原文 qualitative traces suggest，中文用「顯示／改變了」。reviewer 接受 direct，可能有語氣增強，但仍保留設計及外推限制；不列確定錯誤。
- I08 S08 c6：原文 unlogged maintenance work，中文略掉 unlogged。reviewer 接受；會計精度較粗，不列確定數值錯誤。
- I09 S01 c3：原文 subgroup curator-name，中文寫姓氏。reviewer 英文 paraphrase 回 name，沒有處理該差異；族群翻譯精度疑慮，不列確定數值錯誤。

## 追溯與範圍

- `independent-source-card-audit.json` 保留 reviewer 前的原始結論、完整當次卡片與 source packets。
- `reviewer-comparison.json` 保存實際 attestation 路徑/hash、required units、原始 verdict/reasons、指定 claims、retention rows、reader findings、相關完整原文 parts。
- 本報告不審 comparison/global/root，也不把 accepted 當 publication quality。仍需修正實質查核問題，不能因格式可運行就宣稱科學品質改善。
