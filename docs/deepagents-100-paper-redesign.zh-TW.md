# DeepAgents 百篇文獻回顧重設計與驗收規格

日期：2026-10-20。狀態：實作中；原生 task 入口、任務儲存、科學閱讀紀錄與分層 proof gate 已有程式及局部測試。完整綜整、修訂、交付與百篇雙平台驗收尚未完成，不能宣稱已達標。

### 目前實作證據

- `scripts/runtime/litreview_core/native_agent.py`（位於 literature-review skill）：真實 DeepAgents 0.7.15 task/CompiledSubAgent、隔離 skill、runtime 身分、callback ancestry、並行上限及失敗清理。沒有 host 預先呼叫研究 worker graph。
- 同一 runtime 的 `task_store.py`、`scientific_records.py`、`record_review.py`：不可變產物與租約、完整 UTF-8 來源覆蓋、九欄抽取／問題 dispositions／反證保留、獨立支持與遺漏查核；原文段落選取與 lossless quote projection 減少重複輸出／輸入。
- `hierarchical_proof.py`：新版本 proof DAG 的機械接受條件；尚待完整 pipeline 產生實際科學 proofs，不能以離線測試當作模型查核。
- `proof_planner.py` 已由實際來源、閱讀紀錄及 rendered sections 編譯 source／assembly 責任與依賴；26 項離線測試通過。`proof_worker.py` 以原生獨立 task 收集逐主張與保留義務判定，保存負面結果及真實 runtime identity。
- `review_artifacts.py` 與 `draft_worker.py`：證據卡、比較與分層綜整的 typed draft、來源／會員／premise 約束及實際呈現行清單；write-review／compare-papers 已新增對應 skill profile。接受 draft 不等於科學查核通過，完整流程尚待接線。
- 新增短篇 reasoning 品質控制工具，涵蓋六類已知錯誤及正例；預設僅準備資料，尚未執行真實模型的 thinking 對照測試。正式預設仍啟用 reasoning。
- `qwen_transport.py`、`request_governor.py`、`qwen_tokens.py`：套件內 Qwen transport、reasoning_details、共用 request admission、200K 上限及 90 分鐘 admission deadline；tokenizer 有固定 hash。
- 2026-10-20 本機離線套件測試：70 項通過，紀錄在工作區 `reports/native-runtime-offline-tests.txt`。此數字只代表該次測試，不是完整任務完成率。
- 後續離線套件測試執行 103 項，102 通過、1 略過；新增 draft worker 另測 4 項通過。這些結果不取代實際百篇冷啟動驗收。
- 再次整合測試執行 139 項，138 通過、1 略過。新增三篇小資料的完整 DAG 機械測試使用明確 mock 科學 verdict，不能當作模型的科學驗收。
- `native-pilot2-20261020-022026`：兩篇新冷啟動閱讀通過，60.704 秒，實際 Qwen parent task 及兩個獨立 readers；peak HTTP concurrency 2，RSS 約 204 MiB。這是閱讀階段，尚未驗證語意或完整回顧。
- `native-review2-20261020-022448`：兩篇閱讀通過；兩個全新 verifier 中一個通過、一個因供應商生成失敗／輸出耗盡未完成；整體階段明確未通過（85.891 秒）。沒有把 failed 改成 approved。
- Stage-only 執行入口：`skills/literature-review/scripts/native_reading.py --help`；可加 `--verify-records`。它不是完整百篇 review 的正式入口，輸出固定標示 `publication_verified=false`。

下一個整合重點：精簡且有界的 coordinator 延續上下文、比較／寫作 tickets、分層 proof plan 與真實 auditor、issue 驅動的定點修訂，以及正式可攜交付。既有舊版 harness 仍保留，尚未完成新的正式入口替換。

新整合入口 `skills/literature-review/scripts/native_review.py` 已有 CLI 與 reading → cards/comparison → hierarchical synthesis → proof DAG 接線，計時自輸入讀取前開始，共用原始 deadline，交付時間亦計入。`--help` 可執行；分批 native coordinator 與 delivery exporter 尚在整合測試，不宣稱已可完成正式百篇。語意修訂仍未實作，現況遇到獨立查核不通過便停止並保留失敗；下一步需先完成這項能力再做完整驗收。

後續整合進展：`coordinator_frontier.py` 已通過真 SDK、零 API 的分批 task 測試；`delivery_export.py` 已接入，交付時重新 gate，失敗可保存 unpublished attempt。`review_repair.py`／workflow 已實作最多兩輪 issue 驅動修訂，同層修改可並行、變更沿 premise 依賴傳遞，僅版本與所有依賴均未改變的 passed proof 可重用；原始負面 attestation 與舊票保留。離線完整 DAG 測試涵蓋首次通過、拒絕後修訂、重複拒絕耗盡上限，均通過；尚未證明真實 Qwen 修訂品質。

首次完整入口試跑 `native-full2-20261020-025004` 在 2.203 秒、送出 API 前因 Windows 深目錄複製範例檔案失敗。這是確定的整合缺陷，結果 passed=false/publication_verified=false；正調整 typed native skill snapshot，不能把此次當科學測試或忽略其失敗。

修正後的 `native-full2-20261020-025255` 已越過 Windows 路徑問題，兩篇閱讀 accepted；完整流程在 66.531 秒於 cards-and-comparison 階段失敗。一個 Cerebras 請求回 provider generation error；另一個 writer 提交空 claims 與 probe 佔位內容，完整 question／obligation gate 拒絕，不能作為證據卡。14 次 admission、13 次完成、1 次傳輸層標記失敗，實際 prompt 215,293／completion 61,744 tokens，peak concurrency 2；整體 publication_verified=false。新增可選 `--provider` 供相同 Qwen 模型的供應商對照，未改正式預設。

百篇容量審查另發現 P0：6,384 個 source parts 的逐項 metadata 序列化本身為 1,093,679 Qwen tokens，尚未包含義務或 premise。原本只去除原文仍不夠；必須對 inference source catalog 篩選實際引用且採共享版本字典與可逆表示，再重新測量完整 wire request。此阻塞尚未解除前不能啟動或宣稱百篇容量已達標。

後續已接入實際引用／義務來源聯集及 lossless draft wire；百篇 writer input 在兩種結構 fixture 從約 115／120 萬降為 11／16.4 萬 tokens。GroupedDraftSubmission 以短 obligation aliases 與相同決策分組，展開後仍走原始 validator。樂觀相同值分組輸出約 10,939／13,458 tokens；逐義務一組仍為 22,780／40,070，不能保證 16K 完成。Proof 輸入尚未解決，詳見 `reports/hierarchical100-sizing-review.zh-TW.md` 與 `reports/grouped-retention-sizing.json`。

`native-full2-modelrun-20261020-030036` 於 77.281 秒在寫作前遇 HTTP 521；兩篇已閱讀，沒有寫作品質比較證據。之後 transport 對已觀察的 521 增加原本一次上限內的 retry，仍共用總 deadline。

`native-grouped2-modelrun-20261020-030419` 於 85.766 秒停止：兩篇閱讀、其中一篇 writer accepted；另一篇連續提交 placeholder 與不完整 obligation aliases，未接受。已接受證據卡有 54 claims，尚未獨立查核且過長；已補強真實完整提交與 6–10 精簡段落的寫作指引（非刪除重要結果的硬上限）。完整回顧仍未通過，需以受控工具選擇測試釐清 placeholder 行為。

## 已確認的目標

- 由使用者向一個 DeepAgent 下達任務；它載入 literature-review skill，實際委派框架 subagents 完成工作。不能以外部 Python 寫死所有研究階段後呼叫獨立模型冒充此驗收。
- 使用 OpenRouter `qwen/qwen3.8-27b`，每次完整請求含系統訊息、歷史、工具 schema、預留輸出與安全餘額不得超過 200,000 tokens。200K 是硬上限，不是每次填滿的目標。
- 最多 100 篇、每篇約 10 頁等量文字的 Markdown 論文。正式以實際 tokens／表格大小界定容量，頁數只是描述。所有指定來源完整閱讀，輸入不含 PDF。
- 使用者已選定：主報告＋百篇精簡證據卡＋比較表＋可追溯引用；保留完整抽取資料與原文。
- 使用者已選定：環境與輸入備妥後，首次處理整批論文，從下達任務至驗證後交付的 elapsed wall time ≤ 5,400 秒。包含排程、所有重試、修訂、查核與輸出；不得扣除人工介入或重跑時間。
- Windows 與 Ubuntu 22.04 均須實機驗收。原生 Windows 不以 WSL 成功替代。

## 現況證據與缺陷清單

基準為 synthetic10-20261020-013803-3e4cf7a4 與 reports/synthetic10-benchmark.json。十篇最終通過，但含歷次修訂的總 elapsed 為 84.6 分鐘、累計執行含修訂約 39.9 分鐘，不能當作冷啟動耗時。

獨立程式與事件檢查：最終接受的 36 個 context、45 次 AI 回覆只有 45 次 submit_result，task 為 0；現有模型 wrapper 強制 submit_result。原 bundled coordinator 雖宣告部分 subagents，未宣告文件所稱的 assembly-auditor。新的 coordinator 必須允許工具選擇；只有有界提交葉節點可以強制 submit_result。

| 缺陷 | 修正方向 | 關閉缺陷的證據 |
|---|---|---|
| 外部 runner 排程葉節點，非主代理委派驗收 | 正式入口建立 coordinator 與明確角色 subagents；允許模型呼叫 task | 真實 Qwen trace 含父 task tool call、子 graph、對應產物與回傳 |
| bundled adapter 鎖 0.7.0，已裝版本 0.7.15；Windows 入口拒絕 | 升級並固定實測版本，平台無關 Python 工具，套件內自足 | 乾淨目錄僅安裝 skills 與依賴即可執行，兩平台 smoke 與整體測試 |
| 全域綜整／assembly audit 百篇估計 128–164 萬 tokens | 分層主張與分層證據／查核協定，依實際 tokenizer 分包 | 百篇全部 wire request ≤200K；沒有隱性截斷 |
| 全域 scope claim 綁全部證據，單一原子單位也爆量 | scope 分成逐篇葉節點與明確集合聚合；新版本 proof 支援集合完整性 | 少一篇、重複篇、過時子節點均拒絕；超大原子表格明確阻擋 |
| 重複載入原文、證據、全部規則與大型 schema | 不可變 artifact store；按任務載入；短 ID 映射、必要上下文每包去重 | 比較 wire tokens、工具讀取、完整來源送達紀錄 |
| 大訊息被 middleware 轉為預覽 | 子代理獨立套用受測 middleware 與 context guard | 來源尾端標記、超大訊息與工具截斷回歸 |
| 推理耗盡輸出／JSON 不完整 | 小任務、角色輸出預算、完整輸出預留、可分割時分割；記錄 provider 實際行為 | finish_reason、reasoning/output tokens、工具提交成功率 |
| 有效最後一次工具回覆被預算檢查丟棄 | 接受有效提交後才終止；區分傳輸與內容失敗 | 第三次有效提交成功，失敗不得第四六次無限重試 |
| CI、缺失測量、觀察研究、條件重疊、普遍敘述出錯 | 型別化事實與語意查核；普遍敘述聲明完整會員集；保留原文 | 對抗資料含錯誤版本，獨立查核能拒絕且真實版本通過 |
| 摘要遺漏 adverse subgroup／修正後仍存在的失敗 | mandatory evidence obligations，從抽取追蹤至證據卡／綜整 | 每個重要反證有最終位置或受審核的排除理由 |
| 科學性標題未登記，複合句只部分有證據 | 中性標題或登記 claim；句子分解後逐項支持 | 全部非空行與全部 factual components 覆蓋 |
| 人工找問題、外部手動修復、整輪重跑 | 模型 writer 依 issue 修訂；依賴圖只使受影響 proof 失效 | 無人工編輯科學結論的冷啟動完成；重用 proof 均重新驗證依賴 |
| writer/verifier ID 由模型自行宣稱 | runtime 注入真實子圖身分與父子 lineage，工具綁定身分 | 冒名、共享 writer 上下文、重播與 stale lease 被拒絕 |
| 長路徑、shell quoting、重複 runtime 副本漂移 | 短任務路徑、相對引用、參數陣列 subprocess、發布複本 hash 一致 | Windows 長路徑及 Ubuntu 路徑／搬移測試 |
| 先前時間與 cache 混合 | 單次 cold run ID、單調時鐘與完整事件串 | elapsed≤5400、無 accepted 分析 cache、重試全計入 |

## 目標架構

```text
使用者 → DeepAgents coordinator（literature-review skill）
               │ task：模型選擇角色與有界任務
               ├─ reader × N（analyze-paper）
               │     → evidence cards / question dispositions / evidence obligations
               ├─ comparer × N（compare-papers）
               │     → 可比較研究群組、矩陣、差異與反證
               ├─ writer × N（write-review）
               │     → 證據卡、主題段落、主報告
               ├─ source verifier × N（verify-citations；全新上下文）
               └─ assembly auditor × N（verify-citations；獨立分層任務）
                         ↓
              程式驗證完整 proof graph → 可搬移交付
```

保留五項公開 skills；reader/comparer/writer/verifier/auditor 是角色，不必增加大量對使用者可見的 skills。每個自訂 subagent 明確載入所需 skill、工具、Qwen model、token governor 與 middleware；不假設繼承父代理設定。查核一律 isolated，不能 fork writer 的推理。

coordinator 保存計畫、任務狀態、問題與產物索引，不讀入百篇全文。以一輪多個 task calls 或經實測的本機 compiled subagent 排程讓獨立工作重疊；實際同時 HTTP 數受全域 governor 約束。不要求遠端 LangSmith AsyncSubAgent。

每項委派證據須包含真正 Qwen response 的 tool_call_id、task role、ticket/input hashes、子圖 callback ancestry、子圖 model response IDs、skill hashes、runtime context、native acceptance receipt，以及回到原 tool call 的 ToolMessage。禁止 host 合成 AI task events。等待子代理的 coordinator 不占 HTTP request slot，避免巢狀排程死鎖。

Python 工具負責讀檔、token packing、lease、hash、結構驗證、依賴排程資訊與合併。研究問題、分群、科學主張、反證處理和修訂由讀取 skill 的模型作決定。工具不得偷偷完成整份研究流程後只回傳 completed。驗收檢查模型確實調用多種角色，而非只檢查角色設定存在。

## 證據及 context 分層

1. **原文層**：凍結 Markdown 和 source version hash。逐 part 全文閱讀，超長普通文字依精確位移分割；表格連同必要 caption／notes。完整讀取與理解分開記錄。
2. **論文層**：一次閱讀盡量共同產出九類抽取、研究問題 dispositions、精簡證據卡候選與 mandatory evidence obligations，減少重新讀一輪做 question map。需要新版本 schema；輸出放不下時繼續有界 extraction 任務，不能剪掉反證。
3. **群組層**：依問題、方法、族群、metric／unit 等可比較性形成群組，token 大小決定每包篇數。每組產出主張、支持、反證、條件、未解問題與子節點來源。複數群組可以引用同一研究，但分母必須去重。
4. **全域層**：主報告根據有來源 lineage 的群組成果回答問題，不按任意檔案批次直接宣稱共識。跨組矛盾需專門 comparison 任務，必要時再讀原文。全域節點保留反證索引；重要資訊過多就增加層次或分開章節，不能截掉後半段。

每個 artifact 用不可變 ID＋content hash＋schema/version。任務只回傳路徑、hash、狀態及少量問題；長資料不回灌主對話。模型可讀指定原文，但工具須回傳明確 truncated/remaining 狀態。

現有十篇實際 packing 是每批兩篇；在新版資料結構實測之前，容量規劃保留百篇約 50 批，不能直接假設每批五篇。反證 obligations 必須同時檢查 QMap、unexpected_findings、limitations 及原文失敗段落；只保留 QMap.counter_refs 會重現已知漏項。

建議起始工作區間（不是已實測最適值）：coordinator 10–30K、reader 15–45K、comparer/writer 30–80K、source verifier 30–90K、assembly 30–80K。所有角色均以完整 wire token 預算檢查為準。目標大部分請求低於 100K，為推理／輸出／工具回合留下餘裕；任何必要原子單位超限均回傳明確 needs_split/oversized。

## 新分層查核協定：不得假裝舊 gate 已支援

舊 AssemblyAudit v2 要求一次查核完整 target/context，不能把它改成摘要仍宣稱相同保證。新增顯式版本的 HierarchicalReviewProof（暫名），保留舊模式相容；目前既有 gate 尚不接受此協定。

- **葉節點 source proof**：完整核對每個交付主張的所有成分與原文，涵蓋每張證據卡、每個矩陣項、每段主報告及 factual headings。local offsets/hash/來源集合完整。
- **局部 assembly proof**：獨立 auditor 檢查一個章節／群組與其所有必要問題 dispositions、反證 obligations、來源界線；不是只數 passed。
- **跨組 proof**：獨立查核全域結論與群組差異；新科學推論須回溯完整原文支持及反證，不能以「摘要被批准」代替原文證據。
- **根 proof**：程式驗證整個 DAG、交付全文非空行 exact coverage、研究與版本去重、全部問題與論文 membership、引用解析、完整 obligation dispositions；模型審核主報告、跨組結論與尚存問題。過大則進一步分層。
- 普遍／否定敘述需聲明 population IDs 與逐成員 proof coverage。抽樣不構成全體查核；雜湊只證明綁定，不能證明語意。
- 所有必要節點通過且沒有阻擋問題才交付 verified。覆蓋率與語意品質分開報告。自動模型查核仍不是人工學術審查。

## 品質與修訂流程

初次閱讀就保存未測量、CI 含虛無值、觀察性限制、負向 subgroup、失敗在改善後仍存在、適用條件與重複研究等資料。證據卡必須呈現與問題有關的重大限制。並非要求每個細節進主報告，而是每個影響結論的 obligation 有可查核去向。

來源查核與局部 assembly 在內容完成後立即開始，不等百篇所有階段完成。失敗 issue 綁定 claim／section／source version，writer 在新修訂任務修改，原 verifier 不兼任 writer。預設每個受影響節點最多兩輪科學修訂；超過則留下 needs_revision 與未完成狀態，不重抽 verifier 直到通過。內容問題與格式／暫時傳輸錯誤分開計數。

改動依賴精確失效：local claim proof 只綁本地主張、必要來源與版本；assembly proof 同時綁子 proof 和上下文。父章節改變不應無故迫使不變葉節點重新付費，但任何相關來源／語意／會員集改變均需重驗。保留完整失敗歷史。

## 90 分鐘工作預算與資源治理

以下為工程預算，尚非實測預測；階段可交疊，不把預算當成完成承諾。

| elapsed 時點 | 工作目標 |
|---|---|
| 0–5 分 | 前置容量檢查、問題與計畫、3–5 篇代表性校準（成果計入正式工作） |
| 5–35 分 | 全文閱讀、抽取、卡片與逐篇／逐問題 dispositions；已完成批次開始比較與查核 |
| 20–50 分 | 群組比較、主題撰寫、局部來源與 assembly 查核 |
| 45–65 分 | 主報告與跨組衝突處理、全域與分層 assembly |
| 65–80 分 | 定點修訂及受影響依賴重驗 |
| 80–90 分 | 最終 gate、搬移可用的交付與效能紀錄；保留尾延遲餘裕 |

以 4 個同時請求開始短校準，按實際吞吐上升到 8／12／16；受供應商 RPM/TPM、在途 token、記憶體及尾延遲限制，不用單純增大 workers 保證速度。沿用 token reservation 與 429/5xx 降載，重試設 deadline 和 jitter。正常模型 timeout 不盲目重複付費。

記錄角色 p50/p95、等待時間、模型服務時間、tool latency、input/output/reasoning tokens、provider、finish reason、重試率、成本、RSS、CPU、active tokens 與峰值 HTTP concurrency。若 provider 不遵守 reasoning budget，以實際數據認定；不得宣稱硬限制生效。比較較小任務與 provider 路由的效果，所有模型仍是指定 Qwen。

單次根任務採硬 90 分鐘驗收；timeout 產出部分資料與 checkpoint，狀態為未通過。續跑成功可有價值，但不是 cold-run SLA 成功。

## 打包與移植

把已實測的 Qwen transport、reasoning_details 保留、tokenizer、governor、telemetry、Windows 路徑處理移入 skill 隨附 runtime。不得依賴 Desktop 上的私人 runner。固定 DeepAgents 與相依 lock；官方最新 docs 只作參考，實際 API 以固定安裝版本驗證。

使用 Python pathlib 與 subprocess argument arrays；避免模型拼 shell 命令、POSIX quoting 搬到 Windows。每個 task 有獨立短工作目錄及受限制產物寫入工具；共用原文 read-only，runtime 管理身分。獨立 skill 可安裝其所需 runtime；發布時自動產生／檢查共用副本，避免手動維護五份不一致程式。

## 實作次序與驗收

1. **原生入口**：先讓真實 Qwen coordinator 載入 skill，呼叫 reader/writer/verifier 等 task，產出有 runtime lineage 的小型有效成果。保留工具選擇能力，不能全域 force_submit。測並行有實際 HTTP 重疊。
2. **新資料與 proof 協定**：實作論文證據卡／問題 dispositions／obligations、分層比較／綜整、分層 source＋assembly gates、依賴局部失效與拒絕測試。
3. **自動修訂與打包**：writer 接收 issue 的有限修訂循環；任何 known blocker 必須解決或明確未完成。把 runtime 整合回五項 skills；無外部人工 repair 腳本。
4. **10 篇冷啟動回歸**：五項 skill 單獨入口及完整委派，驗證舊錯誤的回歸；不得使用先前分析／修訂快取。gold 不提供給執行代理。
5. **30 篇壓測**：測 context 峰值、尾延遲、限流、loading 與實際費用，據此調整 task 大小及 concurrency。此測試不能代替百篇驗收。
6. **100 篇正式 cold run**：具差異的 Markdown papers，不以十篇複製十次充數；長度分布接近正式使用、含跨群組衝突、重複版本、多語重疊、缺失測量與晚出現的反證。需完整獨立模型查核，host-only gold 評分與來源抽查分開報告。
7. **跨平台驗收**：Windows 與 Ubuntu 22.04 各自從乾淨輸出目錄完成完整百篇，紀錄硬體、供應商與時間。平台通過不只靠 import 或 mock。90 分鐘結果屬該硬體與 endpoint 條件，不宣稱任意負載下保證。

關鍵回歸：長訊息完整送達、不可分表格超限、缺一論文／一問題／一行／一反證拒絕、stale source/proof拒絕、冒用 verifier身份拒絕、未知ID與複合句部分支持拒絕、工具最後一次有效提交、reasoning_details往返、原始輸入不變、Windows長路徑、搬移後proof可驗、重試含在elapsed。

完成條件是上述真實端到端證據，並非 SKILL.md 寫完、mock 通過、十篇時間乘十或模型回覆 completed。

## 尚待實測決定

### 已確認的驗收口徑與目前證據（2026-10-20）

使用者已確認預設交付為「主報告＋百篇精簡證據卡＋比較表與可追溯引用」。90 分鐘從資料與環境準備完成後的首次任務下達開始，包含模型重試、科學修訂、查核與交付；重用先前 reader／writer 結果的受控測試不能算冷啟動驗收。

目前尚未通過百篇驗收。最近兩篇冷啟動 `native-bounded2-20261020-033924` 在約 351.406 秒查核階段失敗，保留的兩張證據卡各 12 個 claims。另有離線人工式來源核對發現局部引用與時序支持等缺點；格式被接受不等於科學品質通過。

已修正查核回覆的兩項工程阻塞：允許附帶本節點責任範圍內的額外 verdict，但必要 claims／obligations 仍須逐項且唯一，任何負面 verdict 均不得以 passed 提交；成功 proof 必須把真正 TaskStore 收據交回原生委派追蹤，不能只回 proof hash。保留獨立的 `proof_status` 與任務 `status`，避免混淆科學判斷與任務完成。

容量量測與實際完整請求驗證分開報告。僅有 planned JSON token 數低於門檻不構成 200K 完整請求合格；必須包含實際 SDK 訊息、技能、工具 schema、預留輸出及安全餘裕。僅有吞吐推算亦不構成 90 分鐘完成證據。

新增控制結果：同一 S01 查核輸入（12 claims＋4 obligations），low reasoning 約 166.531 秒產生有效 needs_revision，抓到局部引用及保留映射問題，但仍有兩處已知漏檢；off reasoning 約 33.078 秒全判 passed，卻漏掉前述問題。因此 verifier 不因速度較快就預設關閉 reasoning。這是重用既有分析的工程控制，不是冷啟動通過。

百篇結構容量測試使用每卡 12 claims／每篇 68 原始義務：8-unit／120K 規劃可形成完整 DAG，但需至少 5,558 個科學任務；16-unit／160K 仍至少 3,134 個任務，且最大完整 wire 加未來 child 資料保留量超過 200K。前者過度分片、後者容量不安全，均不能宣稱達成 90 分鐘。Production 120K 規劃門檻與 200K 完整請求上限不因此放寬。

正在實作的修正分開驗證：以可還原短碼傳送查核責任 IDs（逐項理由、負面 verdict 與 canonical proof 均保留）；比較階段使用實際證據卡 claims 與逐項 premise_retention，不再重新分派同批原始 reader 義務。原始義務的完整科學查核仍由證據卡來源層負責，交付必須通過其傳遞的原文 proof closure。草稿結構通過不等於該來源層已獲科學認可。

### 分層證據義務與容量修正（2026-10-20）

實際兩篇 reader 產生每篇 51–68 項原始義務。若百篇的所有義務反覆傳到每層綜合，僅靠壓縮 ID 無法可靠控制輸入與輸出大小。因此原始義務完整保留於來源證據卡的獨立來源／組裝查核；由證據卡衍生的 comparison 與後續 synthesis，則由 runtime 從直接前提的實際 claim 重新產生 `premise_retention` 義務。舊版直接讀原文的比較任務仍保留完整原始義務查核，供既有獨立輸入重建。

原生完整 runner 與單節點 verifier 可用 `--proof-max-units` 做 1–128 項責任的容量實驗，預設 16。此值只控制分片，不改 120K 規劃門檻或 200K 完整請求限制；任務輸出品質與延遲仍須實測。

每筆義務帶完整前提文字、來源定位、問題與論文範圍。納入時必須連到確實引用該前提的上層 claim；排除時必須提出科學理由並經獨立查核。此設計不能跳過下層完整查核，也不能將 metadata 或 passed 標記當作實際科學前提。主報告的重大反證與限制仍須保留。

查核分片正在整合：責任範圍必須涵蓋全部 claims、lines、papers、questions、cells、obligations，各階段精確覆蓋；單一不可分主張超出安全請求容量時必須要求拆寫，不能截斷來源。此修改與離線測試均不代表百篇已通過 90 分鐘驗收。

- 最佳 worker 數、每包 token／篇數、各角色輸出與 reasoning 設定：用冷啟動實測決定。
- 正式研究問題數與論文種類可能增加輸出量；runtime 須先報容量與範圍，不能默默只做部分問題。
- 90 分鐘內仍有科學性阻擋時回傳未完成，不犧牲引用查核來達標。

API 參考：[DeepAgents subagents](https://docs.langchain.com/oss/python/deepagents/subagents)、[DeepAgents skills](https://docs.langchain.com/oss/python/deepagents/skills)。本機已確認安裝 DeepAgents 0.7.15；最新文件中的功能不自動視為本機可用。

### 本輪已整合與尚未驗收的界線（2026-10-20）

- 已整合 dependency scientific views 與精簡 child proof receipts：模型收到完整選定科學前提、完整責任覆蓋及判斷；host 留存完整證明、身份與依賴鏈並在傳送前重驗。實際交付的收據 hash 綁在 RuntimeIdentity，最終 gate 重建核對，不能把精簡收據描述為模型看過完整 proof JSON。
- 已新增完整 `ReviewWorkflow → run_frontiers → DeepAgents task → submit_result → proof gate → export` 離線整合測試；腳本模型從實際 HumanMessage 讀取輸入，並核對交付內容。Windows 與 Ubuntu 22.04 均有通過紀錄；它證明工具與資料流程，不證明 Qwen 的科學判斷。
- Windows 本輪完整回歸 381 項、無失敗，tokenizer 環境未設定的一項跳過已透過實際 Qwen tokenizer 的 23 項 benchmark suite 補跑通過。新版 receipt／witness 的獨立 snapshot `offline-snapshot-20261019T203336Z` 在真正 Ubuntu 22.04 完成 381／381 項、無跳過，耗時 43.092 秒；逐檔 manifest 與舊 snapshot 各自保留。這是離線功能驗證，不含 Qwen 科學品質或百篇時限。
- 已提供單技能 `--quote-witness` 實驗入口：每個來源 claim 回傳逐句判斷與精確引文，由程式唯一匹配補上 Unicode／UTF-8 定位。完整原回覆及負面判斷保存；格式錯誤帶負面內容時終止該 verifier，不以格式重試洗掉判斷。原文匹配只證明文字位置，不證明邏輯支持。
- 完整流程已提供預設關閉的 `--source-quote-witness`；啟用後流程與匯出均重新核對所有 source 節點的引文紀錄，並保留 `proof/submissions.json`。完整原生 SDK 的預設、合併、witness、合併加 witness 四種組合離線測試通過，包含遺漏紀錄不能交付。這是附加查核，原本的完整科學 proof gate 仍必須通過。
- 固定 S01 的 ModelRun witness 實跑在 117.047 秒後因兩次供應商 502 連線錯誤終止，沒有有效回覆或科學判斷；不能評分已知缺陷是否改善。DeepInfra 的相同 low-reasoning witness 控制在原定 300 秒到期，worker 未回傳用量或判斷；未知費用不得當作零。所有單節點對照均不算百篇冷啟動驗收。
- DeepInfra 關閉 worker reasoning 的同資料對照於 285.813 秒完成：13 個 clause、41 個引文均通過字面定位，但四個已知引用／條件問題全部漏判。這證明精確引文紀錄不足以證明主張被支持；不能以結構通過宣稱科學品質合格，也不把 off 設為 reviewer 預設。完整紀錄保存在本機專案父目錄：[控制總結](../../reports/source-witness-controls-20261020.md)、[個別語意檢視](../../reports/witness-deepinfra-off-s01-20261020-044558-0e58/host-semantic-review.md)。此為已知工程樣本，不能估計泛化準確率。
- 下一個隔離實驗以實際 12 條主張各自建立 DeepAgents 子代理，每個只收到該主張及其宣告引用的完整段落，要求逐事實組件核對。範圍明確標示為局部引用支持檢查，不授予全文遺漏／反證檢查或最終交付通過資格。輸入由既有材料機械產生，模型不得收到 host 缺陷答案。先驗證完整請求容量、真實 task 身份、並行交付與負面紀錄，再進行付費對照。
- 真正 Ubuntu 22.04 最新離線 snapshot `offline-snapshot-20261019T204708Z` 通過 396／396 項、無跳過，耗時 47.932 秒；五個技能均實際安裝並核對 runtime 檔案。這份 snapshot 早於新增供應商 registry，不代表後續變更已完成 Linux 回歸，更不代表百篇模型實測通過。
- 百篇結構 fixture 的 `--proof-max-units 96 --merge-full-source`：100 張證據卡均通過來源及配對 assembly 規劃預算，形成 404 個 proof 節點，加 260 個 reader／draft 共 664 個科學任務。合併使上層收據較寬，故不能用簡單減法宣稱只有 329 proof 節點。完整來源查核責任仍逐項保留。
- 最大合併 source 使用真正 witness 工具 schema、實際 SDK 請求封包及 32768 輸出預算的離線測量為 183306／200000 tokens；這只證明初始請求可容納，不保證第二次帶歷史的請求、模型輸出品質或 90 分鐘完成。81 項判斷加逐句見證的輸出情境可超過 16K，reasoning 未有可靠硬上限。
- 閱讀 profile 新增同欄位重複資訊合併指引，保留必要來源、不同族群／時間／條件、反證及每段觀察；無 finding 數量上限。這是待模型實測的提示改善，不能預先宣稱 token 或耗時下降。原生 runner 新增單調時鐘的階段計時，成功、失敗、外層取消都保留時間與結果；`test_native_review_inputs.py` 共八項離線測試通過，其中三項涵蓋計時與例外傳遞。總時限仍由原始全程時鐘控制。
- Ubuntu 第四個獨立 snapshot `offline-snapshot-20261019T205802Z` 通過 405／405 項（47.763 秒，無跳過），包含 provider registry、包裝缺檔拒絕測試及閱讀整併指引；五個技能均重新安裝核對。之後的計時變更透過獨立兩檔 overlay 在同一 Ubuntu 環境補驗八項全部通過，原 snapshot 的 562 檔保持不變。[完整回歸](../../reports/ubuntu22-offline-tests-snapshot4-20261020.md)、[計時補驗](../../reports/ubuntu22-timing-overlay-20261020.md)。八項包含既有五項，不能把兩次測試數直接相加作為獨立案例數；這些仍是離線工程驗證。
- 已找到早期 proof 重用的排序缺陷：sealed coverage 會排序，planner 的相同責任集合可能未排序，舊程式因列表不等而保守拒絕重用。現在以同一嚴格 coverage 正規化比較，仍拒絕重複、未知或缺失維度，保留原 node／身份／hash，不重新簽封。四項 repair 回歸通過；三項真 SDK 離線整合中，merged 提前四個節點全部重用，global 九節點只新執行五個；split 提前十個節點全部重用，global 十五節點亦只新執行五個。來源／卡片改版仍失效，偽造 JSON 身份仍被拒絕。這證明重用機制可行，早期卡片排程與修訂關卡尚在實作，不能算模型品質或百篇速度已驗收。證據：`reports/early-card-proof-reuse-before-fix.json`、`reports/early-card-proof-reuse-offline.json`。

### 早期查核整合與局部 Qwen 對照（後續進展）

- `--early-card-verification` 已接入正式 runner／workflow，預設關閉。每張卡先通過真 source／assembly，再允許比較；失敗先保留紀錄並修卡。早期與後期共用原始 deadline 及最多兩輪修訂，後期重用原 sealed proof。歷史失敗 ticket 不會被當作新的待執行任務，也不被改成成功。188 項相關離線回歸通過，包含完整 SDK 的負面修訂、耗盡前不建立比較、來源改版、witness 與最終匯出；尚未跑新版模型冷啟動。
- 新增選用的 `--coordinator-provider`，允許主代理與科學子代理分別指定路由；未設定時維持原行為，模型仍為同一 Qwen。這是供後續延遲量測使用，未宣稱混合路由速度或品質已驗收。
- 12 個單主張查核的離線完整請求最大 32,707 tokens，合計 385,327；1M 並行預算能容納 12 個。但真正 Qwen 對照首次因 parent 任務描述格式錯誤停於委派階段，修正精確 description 契約後才建立 12 個實際 workers。
- 修正後 Chutes／low 對照在 300.110 秒逾時：11／12 條主張有原始回覆，共 18 份；四條正式接收，14 份因片段間文字覆蓋而拒收。H03 的缺失引用被指出且負面紀錄保留；H01 的未支持時序仍被判成支持；H02 無回覆而未評估。另發現 c11 將推測語氣加強的漏檢。不得將原始判斷、格式接收與科學正確性混為一談。此控制沒有通過品質或完整交付，更不是百篇時限驗收。
- 本輪暫不追加同條件模型重跑。先診斷標點與真正漏字，並研究原文關係抽取與主張關係比對。全文漏項 F10 不在局部主張任務的責任內，仍須由完整來源層處理。[實測與逐項檢視](../../reports/local-claim-s01-chutes-low-20261020-050958-e454/host-local-review.md)。
- 最新正式 runtime 的 Ubuntu 第五 snapshot 完成 425／425 項、無失敗或跳過，五技能安裝與新 flags 通過；明確排除仍在修改、依賴 reports 原型的單一實驗測試。此 snapshot 早於後續四個技能 reference 的語氣／關係指引更新。[報告](../../reports/ubuntu22-offline-tests-snapshot5-20261020.md)。
- 局部原型標點 adapter 的 13 項離線測試通過；原 18 回覆獨立重播的 literal valid 從 4 增至 9，只消除五份純標點失敗。原 trial 的逾時、未完成及科學漏檢維持不變。數字、單位、否定、關係詞、非白名單標點仍不可被吞掉。
- 新增來源證據語氣與關係指引到 analyze／write／compare／verify 四個 native profiles；它是尚待新模型驗證的提示修改，不能據此宣稱修復 H01 或 c11。
- 重新查詢官方模型 metadata：Qwen3.8-27B 宣告 effort 選項，但未宣告 `supports_max_tokens`；不能把 low 或歷史 `reasoning.max_tokens` 設定當成已證實的 thinking 硬上限。本次有 `reasoning_details` 但 provider reported reasoning tokens 為零，也不能解釋成無 thinking。完整每請求上限仍維持 200K，未改模型。[官方推理設定說明](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens)，查詢快照 `docs/provider-metadata/qwen3.8-reasoning-20261019.json`。

### V2 審查分工與下一輪品質控制

- 新架構採獨立 opt-in 契約候選：每個 section 的 reviewer 同時負責來源／新推論與完整實際呈現，獨立性仍要求 writer 與 reviewer 分離；host 負責可重播的完整性與依賴閉包。不能刪除舊 assembly 後冒稱通過 v1。首個 paper-review 垂直切片尚在實作，不具正式發布資格。詳見 `reports/review-v2-responsibility-graph-proposal.md`。
- 依現有百篇結構 fixture，未分片的 v2 目標為 420 個科學 tasks，相較 v1 的 664 減少 36.7%；尚未證明全部新 payload 能容納、模型品質或 90 分鐘完成。task 數也不等於 HTTP calls，修訂、主代理與重試另計。
- 正在建立來源先讀、再驗主張的獨立局部原型：來源 reader 不接收待判主張，產出可追溯關係索引；verifier 仍須讀自身完整宣告來源，索引不構成科學認證。此原型只檢驗局部引用支持，不能取代全文漏項審查。
- Transport／governor 新增 reasoning 欄位存在性與供應商報告 token 數的觀測；缺少用量維持 null，零用量卻有 details 時明示矛盾，不記錄推理內容、不推算虛構 token 數。Windows 與真正 Ubuntu 22.04 的 transport 10 項及 provider 8 項離線測試均通過；Ubuntu 以獨立四檔 overlay 補驗，原 snapshot5 的 564 檔未變。這不是新版全套回歸或模型品質證據。[補驗報告](../../reports/ubuntu22-telemetry-overlay-20261020.md)。
- 新增 20 個獨立合成品質控制案例，涵蓋時序、共同前後事件、敘述順序、推測語氣、相關與因果、條件、頻率、缺失測量及族群範圍，每類都有支持與不支持的對照。worker inputs 與 host-only key 分檔，未執行模型、未取得準確率；不得將手寫預期答案當作模型通過。資料位於專案父目錄 `reports/relation-validation-set-20261020`。

### Source-first 首次模型控制（2026-10-20 05:35）

- 離線真 SDK 預檢已完成 1 reader → 12 dependent verifiers；reader 完成以前不建立 verifier tickets。Reader 不接收待查主張，verifier 只接收 own refs 的完整來源與派生索引。11 項實驗測試通過，不構成科學品質證據。
- Reader 16K output、verifier 8K、parent 4K、low effort、Chutes/fp8、1M active tokens、38 admissions 上限、每 worker 最多兩次；完整 reader wire 預留 38,196 tokens，初始 verifier 最大 25,554。實際 ledger 可能更大，後續請求仍須由 governor 重算，不能把 fixture 容量當作所有歷史請求保證。
- 唯一付費控制 `source-first-s01-chutes-low-20261020-053530-8bc5` 在 **300.062 秒逾時**，三次 HTTP admission（兩次 parent 回應、一次 reader 無回應），尚無 ledger、沒有釋出 verifier。H01/H02/H03/c11 全部未評估，不能推斷新方法改善或惡化準確率。
- 已知回報費用 subtotal $0.00050661，reader request 3 的用量缺失，不能當作免費。峰值程序 RSS 202,244,096 bytes、host CPU 24.7%、程序 CPU 8.9%（占全機）、可用記憶體最低約 13.27 GB；此資料沒有顯示本機記憶體不足。
- Launcher 已修正重複 timeout 競爭，原始全程期限含 setup／cleanup；不論主報告是否回傳均封存 governor final telemetry。helper exit 0 只表示封存完成，控制本身未通過。
- 下一步先檢查同一模型其他路由的完整容量與費用；不再直接重跑相同 Chutes 條件。此控制重用了既有論文／草稿，始終不是百篇冷啟動驗收。

### Cerebras 對照與實際歷史膨脹修正（05:43–05:49）

- 同一 Qwen 模型的 Cerebras/fp16 路由上限為 65,536，本次 governor 使用此較小上限。16K reader 對照在 24.625 秒失敗：兩次 parent 工具呼叫成功，reader 兩次供應商 error，沒有 ledger。兩次 reader 都用滿 16,384 completion tokens，reported reasoning 卻為 18,349／19,164；不能據此斷定強制工具不相容，也不能把 low effort 當硬推理上限。
- 單因素提高 reader output 至 32,768 後，控制在 25.047 秒停於下一請求的容量檢查。Reader 首次返回工具參數，但 data 為截斷的 JSON 字串，第五個 fact 尚未完整；completion 32,768 中 reported reasoning 32,012，沒有可接受完整 ledger。第二請求預留 125,146 > 65,536，被拒絕且沒有截斷來源。各項科學品質仍未評估，四個可讀 fact 片段不能代替完整抽取。
- SDK 會把相同推理同時序列化為 reasoning 與 reasoning_details；這次兩份各 140,010 字元且逐字相同。正式 transport 現只移除完全相同的 plaintext 副本，保留 reasoning_details 原樣、不同推理內容及全部科學資料。12 項 transport 離線測試通過。
- 離線歷史歸因顯示短格式錯誤回饋約 40 tokens，並非回饋重複整份資料。精確去重可減約 34,670 input-estimate tokens，但完整第二請求仍約需 90,474 tokens（含原32K output及8K margin），仍不適用此路由；不能宣稱去重已使這次控制可完成。
- 審查 v2 已改 host minimum-unit IDs，免模型重抄整句與標點。原文字仍完整交付，每個 unit 恰好一次必查；單位覆蓋不等於語義原子完整證明。新版完整 inverse＋column rows 的密集單卡初始請求含16K output與8K margin約64,534，Cerebras餘裕僅1,002；8K／14K格式錯誤歷史的次請求仍超限。完整200K路由或更小任務仍是必要備案，不能宣稱所有修復都可在65K完成。
- 目前上層 v2 inference-review 已有獨立五階段真SDK垂直切片（reader、card writer、paper reviewer、section writer、section reviewer），包含保留及排除的直接前提、完整render及負面終止。尚未接正式workflow、尚未通過模型品質或百篇驗收。

### 429 診斷與修復（05:51 後）

- 只關閉來源 reader 隱藏推理、保留 parent／verifier low 的單因素控制於26.438秒因HTTP429停止。request1是parent首attempt，retry後成功；request4／5是reader，均被拒，沒有來源回覆或verifier。原凍結版沒有保存error body／Retry-After，無法判斷帳戶、provider、RPM、TPM或容量限制，不能推論reader-off品質。
- 四次source-first控制合計376.172秒，已知usage.cost subtotal $0.08351201，五筆usage未知；失敗請求upstream cost_details $0.06984796另列，不能當成使用者確定被收費額直接相加。各項科學結果全部unassessed。[控制總表](../../reports/source-first-controls-20261020.md)。
- 正式transport新增HTTP status、Retry-After、去除金鑰後的有限provider／upstream訊息。先前retry delay把伺服器等待時間截為最多10秒；現改成遵守完整Retry-After，並由governor在其超過原始剩餘期限時拒絕重試，不延長任務期限。14項transport離線測試通過；這項修改尚未經新模型／限流實跑，Ubuntu補驗另記。
- V2 paper切片已有15項離線回歸，上層section切片有3項／4條真SDK流程。正式完整workflow、最終v2交付、100篇模型品質與90分鐘驗收仍未完成；正在規劃opt-in接線，v1預設保持原協定。


### V2 安裝與語意診斷（2026-10-20）

- 已確認首次處理全程 90 分鐘，包含重試、修訂、查核及交付，禁止帶入校準分析快取。交付主報告、百篇精簡證據卡、比較表與可追溯引用。
- CLI 新增 `--review-protocol v2`，預設仍為 v1。安裝器與 doctor 要求九個 v2 模組。封裝測試 15/15，包括新目錄安裝、異目錄 CLI help、安裝副本匯入與 bytes 檢查；CLI 輸入 12/12。尚非 Qwen 端到端驗收。
- 最新 source-first 控制耗時 19.875 秒，來源回應 3.625 秒。52 facts 中 14 facts／16 欄違反逐字端點要求，兩筆遺漏否定作用域。修訂請求遭 Cerebras upstream 429，verifier 未執行；不能據此推估百篇速度或宣稱品質改善。
- 嚴格端點檢查保持不變，錯誤回饋新增 fact ID 與欄位。讀取及查核指引和 v2 paper reviewer 實際指令加入否定作用域規則。Source-first 12/12、paper v2 15/15 離線測試通過；提示修正的模型效果待測。
- 真 Ubuntu 22.04 先前 overlay 40/40 通過，涵蓋 transport/provider/paper/section v2，未涵蓋本輪完整 workflow、CLI 與安裝接線。百篇首次處理 90 分鐘與報告品質尚未驗收。

### 完整 V2 流程與跨平台安裝驗證

- 完整真 SDK 流程新增 7 項離線測試：四類交付與原文、逐層負面修訂、共用修訂額度、來源變動、零變更重抽拒絕、原始 deadline。Windows 再跑 7/7 通過（23.417 秒）。模型回應為 scripted fixture，不能代表 Qwen 品質。
- 真 Ubuntu 22.04 凍結 overlay `v2-workflow-install-overlay-20261019T220725Z` 共 52/52 通過；完整五 skills 新安裝、每份 66 個 runtime Python 檔逐位元組核對、安裝 manifest、異目錄 CLI help 與 doctor 均通過。原 snapshot5 的 564 檔不變。報告位於專案 `reports/ubuntu22-v2-workflow-install-overlay-20261020.md`。
- 凍結後增加獨立 `--reader-reasoning low/off` 實驗選項，預設 low 不變。Windows 輸入測試 13/13；Ubuntu 另做補充驗證，不能把先前 52 項算成涵蓋這個修改。
- 下一個品質實測以完整兩篇 Qwen cold review 為範圍，覆蓋全部五 skills 及交付。外部程序計時須包含 Python imports 至 exit；內部 run timing 另列。仍未完成百篇 90 分鐘驗收。

### 完整兩篇 Qwen cold2 首輪實測

- 新目錄 `reports/native-v2-cold2-20261019T221026Z-88d3`，完整 Qwen 27B／真 SDK，reader off、writer/reviewer low、reviewer 32K、auto 路由，無分析快取。外部 600 秒上限；實際 375.047 秒結束，未交付。
- 讀取 65.813 秒、卡片寫作 89.891 秒均完成；兩篇卡片查核耗時 216.375 秒，一篇通過，另一篇三次模型回合後未被接受。24 HTTP 全部完成，無傳輸失敗，已回報費用合計 US$0.61926567，無缺漏 usage。不能把未完成的兩篇時間外推百篇。
- 失敗 reviewer 首回合沒有有效 data object，後兩回合均有原文引句不匹配；這是 operational failure，尚未進入科學負面修訂或比較。兩個 reviewer 首回合各用滿 32,768 completion tokens，其中 reported reasoning 為 29,916／30,727；推理耗用仍是效率風險。
- 主機曾有約 5 秒背景 tokenizer 工作重疊（06:10:54–06:10:59），未扣除時間，非獨占機器基準。原稿、失敗結果、partial export 與外部計時均保留。
- 已將 paper reviewer 的引句錯誤回饋細化為 unit／minimum-unit／observation 位置及 source_ref，未放寬逐字檢查。15 項 paper 回歸通過；下一輪模型效果未測。完整 native_review.run 真 SDK 離線整合另有 3/3 通過，但不代表科學品質。

### Worker reasoning off 完整流程控制

- 新凍結五 skills 加入連續逐字引句及 named-retention 範圍要求；新執行 `reports/native-v2-cold2-alloff-20261019T222003Z-21e0` 使用 reader/writer/reviewer off、parent low，其餘維持 600 秒與 200K 上限。這是新配置控制，非純單變因對照。
- 外部 107.531 秒終止，費用 US$0.19992295；一篇 reader accepted，另一篇三回合未接受，未執行 writer/reviewer，不能據此判斷其 off 速度或品質。
- 兩篇 reader 首次均多提交未定義 `questions_note` 欄位，SDK 驗證錯誤將約 24K–25K 字的原始 kwargs 回餵模型；後續 S01 又出現欄位狀態與 finding 數量不一致。下一修正為嚴格 raw schema 邊界及精確短錯誤回饋，保留原稿、不忽略 extras、不增加回合數。
- 上一輪 cold2 人工核對 21 條卡片主張，主要數值與反證未見明顯新增矛盾，但 S08 有一處過度宣稱完整保留、S01 rare-case named-retention 仍有範圍缺口。完整科學品質未通過；詳見 repo `reports/native-v2-cold2-host-audit-20261020-01/host-semantic-review.zh-TW.md`。

### Reader 嚴格 raw 提交修正

- reader worker 與直接 native_reading 入口共用 `validate_reader_arguments`；先保存原始參數，再嚴格要求 `{data: object}` 並執行 ReaderArguments 與原科學驗證。額外欄位、字串 data、數字型別轉換均拒絕，模型回合上限仍為三次。
- 真失敗原稿重播：`questions_note` 錯誤現只回傳 loc/type，不再回餵 24K–25K 字原稿；欄位狀態矛盾一次列出所有 field/status/finding_count/finding_ids。原始提交的檔案 hash 維持不變。
- Windows reader 6、scientific 4、CLI 3 共 13 項通過；paper 精確引句錯誤回饋測試增至 16 項。Ubuntu 獨立 overlay `reader-raw-cli-overlay-20261019T222535Z` 共 29/29，零跳過、零 API；含原始測試資料及 pinned tokenizer。
- 已準備全新 `native-v2-cold2-readerfix-plan-20261020-03`，沿用 worker off、parent low、600 秒、200K、auto 路由配置。上述測試尚不能代替實際模型完成與科學品質驗收。

### Reader 修正後完整模型重測

- 執行 `reports/native-v2-cold2-readerfix-20261019T222627Z-c029`，外部 509.046 秒，43 次請求、已回報費用 US$0.88001003、無缺漏 usage；未完成交付。
- reading 34.156 秒、cards draft 11.594 秒完成；第一次卡片查核出現真負面，保留原稿後實際 revision 32.828 秒、重新查核 33.781 秒通過，共用修訂額度使用 1 輪。沒有將負面結果重抽為通過。
- comparison draft 13.438 秒完成，comparison reviewer 耗時 257.813 秒後因 `Premise quote does not match actual declared premise text` 耗盡回合，綜合報告尚未建立。該階段長回應約 28K completion tokens，不能將短 reader 時間當作整體提速達標。
- 下一步評估共同 source/premise 片段選擇介面：模型選明確連續原文片段 ID，host 僅還原逐字原文，不代替任何科學判斷。必須保留選擇 raw、來源版本、還原結果與原負面歷史；不得模糊比對或修補舊失敗引文。尚未實作或驗收此模式。

### 精確引用選擇模式的實作決定

- 實際 comparison 有 69 段引句，只有一段將分號改逗號。三次提交內容 SHA 相同，各回應 28,228 tokens；後兩次重送耗時 162.015 秒、US$0.16331508。這是格式失敗，不能藉此宣稱比較稿科學通過。
- 最小模式採完整 source part／完整 premise claim selector，原文仍完整提供；避免增加重複句子 catalog。模型仍逐 minimum unit 判斷科學關係、限制與反證，host 只還原模型所選原文。定位粒度較粗，不能宣稱 entailment 更強。
- 比較 reviewer 的 canonical output 若改 ref-only，約省 9.49%；主要預期效益是避免抄寫錯誤重送，非單次輸出縮小數倍。是否可一次完成待模型實測。
- CLI 新增明確 `--review-observations quotes|whole-unit`，預設 quotes。V1 拒絕 whole-unit；內部模式為 `quotes|whole-unit-selectors/1`。CLI 14 項輸入測試通過。Adapter、實際身份與 fresh release 重播整合正在實作，尚未完成全流程驗證，暫不啟動新付費測試。

### Selector 整合與新模型實測（2026-10-21）

- 已完成 paper／section worker、raw selector 保存、完整原文還原與 fresh release 重播。補上真正 DeepAgents SDK 的 selector 論文、章節及完整 workflow 測試，涵蓋負面、修訂、巢狀依賴與匯出。獨立程式審查未發現可重現的 selector 特有繞過；這不是語義品質證明。
- Windows 與真 Ubuntu 22.04 的相關七組 65 個獨立案例均通過：selector 4、CLI inputs 14、paper v2 17、section v2 4、workflow v2 8、native run v2 3、installer 15。五 skills 全新安裝，每份 67 個 runtime Python 檔逐 byte 一致；manifest、異目錄 help 與 doctor 通過。Ubuntu 耗時 42.452 秒、零跳過／API；原 snapshot 未改。[Ubuntu 紀錄](../../reports/ubuntu22-selectors-install-overlay-20261021.md)。
- 兩篇首次處理實測 `reports/native-v2-selectors-20261020T191516Z-335a` 全程 598.531 秒，在 600 秒限制內停止；未完成交付。reading 105.266 秒、cards draft 20.812 秒、cards review 153.812 秒、comparison draft 28.984 秒，comparison review 284.641 秒後遭 deadline 取消。30 筆請求、29 筆有完成回報，已知費用 US$0.51819175；第 30 筆中止請求用量未知，不能當零。
- 記憶體峰值約 232.4 MiB，無低記憶體樣本；兩篇最多同時 2 個請求，不能據此宣稱百篇的吞吐。主機同時有已記錄的離線審查測試等背景工作，CPU 樣本不作獨占環境效能聲明。
- 新稿獨立原文對照確認 6 組漏檢：1 組 S08 c7 的 own-ref 月頻率引用缺口，5 組具名保留錯配，涉及 13 個義務列；accepted reviewer 全判 supported。主要數值、CI、負面子群、持續失敗與未測量資訊仍有保留。另 3 項語氣／精度疑慮未灌入確定錯誤數。[獨立對照](../reports/native-v2-selectors-host-audit-20261021-01/reviewer-comparison.zh-TW.md)。
- 同 finding 多標籤使 s01 產生 60 個 retention 義務（29 個 finding），s08 產生 106 個（49 個 finding）。writer 已分組傳輸；reviewer 理由全部不同，不能由 host 無損刪除。保留理由占輸出 bytes 約 58%／55%。下一版理由將引用 ID 並說明關鍵支持／缺口，避免重抄完整 finding、claim 與 writer reason；不設會截斷科學內容的硬字數上限。
- 下一步是額外的閉合上下文查核：每個 claim 僅提供 own declared 原文／premise；每個 finding 僅提供它的原文與實際 named destinations。原全文 reviewer 仍保留所有查核義務。相同 finding／相同 disposition 可共用一次任務輸入，但每個原 obligation 必須各有獨立 status，任何負面都不能被同組 pass 掩蓋。這個模式尚在實作，不宣稱模型測試或百篇驗收通過。
- 實測另出現未定義的 `fields_note`／`questions_note` 重試。reader 提示已列出唯一四個 data keys；schema／接受邏輯不變。Windows 與 Ubuntu 的 reader raw 六項補驗均通過，提示對模型是否有效仍待新實測。[Ubuntu 提示補驗](../../reports/ubuntu22-reader-prompt-overlay-20261021.md)。

### 閉合查核與 writer handoff 修正

- 新 `closed_scientific_checks.py` 已接入真正 SDK task、同一輪修訂、parent 依賴與 fresh release／export；原全文 reviewer 全部義務保留。Ubuntu 新模式 85/85 通過；後續 schema 與 malformed-negative 補驗 closed 12＋workflow 11 共 23/23，不能把重疊案例相加宣稱獨立總數。[主補驗](../../reports/ubuntu22-closed-checks-install-overlay-20261021.md)、[schema 補驗](../../reports/ubuntu22-closed-schema-supplement-20261021.md)。
- 第一輪六個指定案例 20.797 秒、已知 US$0.07973791，因模型將 observations 寫成解釋字串而非 material ID，全部被拒；負面 raw 保存，沒有視為語義通過。其後工具 schema 加入每包精確 unit／minimum／material ID enums，明確限定 observations 只填 ID。
- 第二輪 `reports/closed-controls-off-20261020T194348Z-2963`：六個案例全部匹配，包含兩正例、一個 own-ref 具體性缺口與三個具名保留錯配；八個原保留義務各自判負面，沒有由同組平均遮蔽。17.984 秒、已知 US$0.06438726；一個正例有一次重複 unit 列的格式重試，已再把 schema 列數綁到 required inventory。這是選定既有案例的目標實驗，非無偏誤差率、完整 cold review 或百篇時間證據。上游科學文字以 scripted 真 SDK producer 重播，verifier 與 coordinator 使用真 Qwen，未匯入 JSON 當可信身份；host expected／理由未交付模型。
- 確認 writer 的 `draft_packet` 原本只交保留義務 finding ID、類別與原文位置，沒有 finding.text。同段原文可對應多個不同 finding，初稿容易猜錯具名保留內容。V2 現以明確 `reader-finding-context/1` 交付所有完整 finding 一次及實際來源綁定、reader／record hash；不重送全份 observations 與引用原文。該 profile 寫入 card，paper plan／fresh release 從實際 reader 重建，舊 profile 保留。
- 新 context 仍是未驗證 extraction，writer 必須讀全篇原文；來源、科學判斷與反證義務不變。Windows context 三項、既有 artifacts 十項、完整 workflow 十一項通過；新版本 Qwen 完整流程與 Ubuntu 補驗待續。

### 最終交付補充需求

- 使用者要求持續修正至 skill 可交付，交付後提供獨立繁體中文 HTML 技術介紹：每個 skill 的用途、協定、輸入／輸出、獨立執行、實作架構、特殊設計及驗收／限制，供同事技術報告使用。內容須依最終凍結版本，區分 legacy、current native 與實驗功能。
- 百篇目標仍為 90 分鐘。若實測不能達標，先優化可消除等待、重複資料及重試；只有具體量測支持時才判斷技術限制。最終另提供不同篇數的實測／推估時間、並行與資源條件、模型／修訂設定及不確定範圍；不以失敗的小樣本直接線性承諾百篇耗時。

