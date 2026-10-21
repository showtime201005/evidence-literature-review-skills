# 安裝與首次執行

> 2026-10-21 開發交接：請先讀 [目前交接狀態](docs/HANDOFF-2026-10-21.zh-TW.md) 與 [HTML 技術介紹](docs/implementation-guide.zh-TW.html)。百篇／90 分鐘尚未驗收，最新兩篇完整 v2 測試也未完成交付。下文同時保留 native v1 與 legacy 功能，不能將不同協定的旗標混用。最新候選 strict 工具功能僅為 Python API，尚無 native CLI 開關及供應商實測。

## DeepAgents 0.7.15 原生 Qwen 流程（整合測試中）

此入口使用真實 coordinator `task` 派工。完整百篇、90 分鐘與雙平台驗收尚未通過；目前不要把安裝診斷當成研究品質驗收。

先準備 Python 3.11 或更新版本的獨立虛擬環境。Ubuntu 22.04 的預設 Python 3.10 不符合此 runtime 要求；以下 `python` 必須指向已備妥的相容環境。Windows 與 Ubuntu 均使用同一組 Python 入口。

在 repo 根目錄執行（替換範例絕對路徑）：

```bash
python -m pip install -r skills/literature-review/scripts/requirements-native.txt
python scripts/install_skills.py --source skills --target /ABS/RESEARCH_PROJECT --harness deepagents
python /ABS/RESEARCH_PROJECT/skills/literature-review/scripts/runtime/litreview_core/qwen_tokens.py --download --path /ABS/RESEARCH_PROJECT/qwen-tokenizer.json
```

此完整流程需安裝五項 skills。獨立單技能入口為各技能的 `scripts/native_task.py`，支援 reader、writer、comparer、verifier；參數與輸入契約請以該入口 `--help` 及原生 profile 為準。獨立 verifier 控制實驗不等同整份報告驗收，不能以舊 `harness_runner.py` 代替原生入口。

在目前程序環境設定 `OPENROUTER_API_KEY`。此入口不會自動讀取 `.env`，不沿用舊 runner 的 `LITREVIEW_API_KEY`。模型固定為 `qwen/qwen3.8-27b`，正式預設啟用 reasoning；不要把金鑰放進命令列參數或版本庫。

以下診斷不發出網路或模型請求，檢查版本、檔案、tokenizer SHA 與金鑰是否存在，不驗證金鑰有效性：

```bash
python scripts/check_installation.py --project /ABS/RESEARCH_PROJECT --harness deepagents --tokenizer /ABS/RESEARCH_PROJECT/qwen-tokenizer.json
```

真正的冷啟動研究會呼叫模型並計費。`papers` 只放本批 1–100 篇 Markdown 論文，接受 `.md` 與 `.markdown`（副檔名不分大小寫），不同檔案的檔名主體不得僅大小寫不同或相同；問題 JSON 可為問題陣列或含 `questions` 欄位的物件；輸出目錄必須不存在：

```bash
python /ABS/RESEARCH_PROJECT/skills/literature-review/scripts/native_review.py --sources /ABS/RESEARCH_PROJECT/papers --questions /ABS/RESEARCH_PROJECT/questions.json --out /ABS/RESEARCH_PROJECT/run-new --skills-root /ABS/RESEARCH_PROJECT/skills --tokenizer /ABS/RESEARCH_PROJECT/qwen-tokenizer.json --review-protocol v2 --review-observations whole-unit --closed-checks --workers 8 --deadline 5400
```

上述為實驗 v2 範本；未指定 `--review-protocol` 時預設仍是 v1。v2 全程共用至多兩輪語意修訂，目前這項策略已使最新兩篇測試停止，尚待修正。CLI 的 deadline 從內部 run 計時；正式驗收應由外部 caller 包含 imports／啟動／交付全程計時並傳入剩餘時間。失敗產物標記未驗證；v2 即使 protocol 完成仍為 experimental，不代表科學品質通過。`--provider` 僅供指定 OpenRouter 供應商的對照測試，設定後停用供應商 fallback。

`--coordinator-provider` 可單獨指定主代理的 OpenRouter 路由；未指定時繼承 `--provider`。各子代理仍使用 `--provider`，所有角色維持 Qwen 模型與完整請求容量檢查。此選項可分別測量主代理委派與子代理科學工作的延遲，尚不代表任何混合路由已完成品質或百篇時限驗收。

預設交付包含主報告 `review.md`、精簡證據卡 `evidence-cards.md`、比較表 `comparison-table.md`、CSV、來源索引及原文；索引與 manifest 保留可追溯定位與內容雜湊。失敗輸出使用未發布狀態及草稿命名，不能當成通過驗收的報告。結構查核通過也不代表所有科學判斷必然正確；目前仍有引用支持範圍的模型誤判待改善。

效能實驗參數：`--proof-max-units` 接受 1–128，預設 16；`--reviewer-max-output-tokens` 接受 16384 或 32768，預設 16384。提高批次或輸出預算不會提高 200,000 完整請求 token 上限，實際並行仍受總負載 admission 控制。`--workers 8` 是並行上限，並非保證八個模型請求同時執行。較大批次與 32768 輸出尚未完成百篇品質及時限驗收。

單技能 `native_task.py --role verifier --quote-witness` 可選用實驗性逐句原文見證，搭配該入口的 `--max-output-tokens 32768` 量測輸出負載。模型提供逐句判斷及精確引文，程式僅在該句已宣告的來源段落中唯一匹配時補上定位。原文匹配不等同邏輯支持；仍由獨立模型判斷引用是否支持整句。此選項目前只適用無前置依賴的 source 查核節點，未在完整報告流程預設啟用，也不構成百篇研究品質驗收。

完整流程可加 `--source-quote-witness` 對所有 source 節點啟用同樣的實驗查核。啟用時，流程完成及匯出都會重驗每個來源節點的完整引文紀錄；缺漏或變更的紀錄不得交付為已驗證報告。交付的 `proof/submissions.json` 保留逐項判斷與原始引文回覆。這是附加的文字查核，仍須通過原有獨立科學證明鏈；預設未啟用。

`--merge-full-source` 為另一個預設關閉的容量實驗：只有來源查核及其配對的組裝查核同時符合原有規劃限制時才合併，否則拆分。它不刪除全文遺漏檢查或逐項責任；通常需搭配較大的 `--proof-max-units` 才有減少任務數的效果。

`--early-card-verification` 可在比較與整合寫作之前，先完成每張卡片的來源及獨立組裝查核。未通過的卡片先修訂；全程共用原本至多兩輪修訂與同一總時限。後續只重用本次執行中內容、責任、依賴與身份仍一致的原始 proof，不載入過往分析快取。失敗版本及小型查核計畫保存在 TaskStore，`review-result.json` 的 `early_card_history` 提供對應 hash。此選項預設關閉，完整 SDK 離線流程已驗證；尚未完成新版 Qwen 冷啟動品質與時限測試。

完整流程另提供 `--active-token-limit` 控制同時執行請求的總預留量，預設 1,000,000，實驗範圍 200,000–6,400,000。此值包含各請求的輸入、輸出預算與安全餘裕；每次請求仍不得超過 200,000。增加 `--workers` 時，可在壓測中搭配調整此總量，觀察記憶體、延遲與限流；較大設定尚未完成負載驗收，預設值維持不變。

`--reviewer-reasoning low|off`、`--reader-reasoning low|off`、`--writer-reasoning low|off` 供品質／延遲對照，預設 `low`；coordinator 保持 low。舊的無逐句見證 off 測試曾漏檢重要缺陷，因此不可只因 off 回覆較快就宣稱品質合格。正式設定仍待完整實跑決定。`--proof-max-units`、`--early-card-verification`、`--source-quote-witness` 等 v1 proof 選項不可直接混入 v2；請以當前入口的驗證規則與交接文件為準。

## 既有 OpenCode 與 legacy runner

在 repo 根目錄執行；`/ABS/RESEARCH_PROJECT` 換成使用者指定的研究專案絕對路徑。

```bash
python scripts/install_skills.py --source skills --target /ABS/RESEARCH_PROJECT --harness opencode
python scripts/check_installation.py --project /ABS/RESEARCH_PROJECT
```

安裝器建立 `.opencode/skills/<skill-name>/`，不覆蓋既有同名 skill。已有安裝時先比較版本、備份，再由使用者決定替換，不可自行刪除。只裝一項可加 `--skill analyze-paper`（檢查時也加同樣參數）。

在研究專案開啟 OpenCode，請它讀取 `.opencode/skills/literature-review/SKILL.md`，用絕對路徑提供來源及輸出目錄。每個 skill 內的 Python CLI 不需額外 runtime dependencies。

例如：

> 使用 literature-review，完整閱讀 /ABS/THIS_REPO/examples/papers 三篇合成文獻，分析檢索品質、索引新鮮度、部署限制及缺失成本。只使用提供文本。先建立閱讀與逐問題覆蓋紀錄，再由獨立子代理查核，正式結果輸出到 /ABS/RESEARCH_PROJECT/work。

原生可重現 runner 需要另外安裝固定框架：

```bash
npm install --prefix /ABS/RESEARCH_PROJECT/runtime/opencode opencode-ai@1.19.3
```

使用安裝產生的 opencode 可執行檔（一般為 `runtime/opencode/node_modules/.bin/opencode`；Windows 使用對應 `.cmd` 啟動器），先執行：

```bash
python /ABS/RESEARCH_PROJECT/.opencode/skills/literature-review/scripts/harness_runner.py --harness opencode --skill literature-review --workspace /ABS/RESEARCH_PROJECT --skills-root /ABS/RESEARCH_PROJECT/.opencode/skills --opencode-bin /ABS/OPENCODE_EXECUTABLE --diagnose --result-file /ABS/RESEARCH_PROJECT/diagnose.json
```

Linux 為本輪實測環境；其他 OS 的 npm 啟動器需當地診斷。診斷不呼叫模型。真正研究需設定 `LITREVIEW_BASE_URL`、`LITREVIEW_MODEL_ID`，必要時設定 `LITREVIEW_API_KEY`，再將 `--diagnose` 改為 `--request-file /ABS/request.txt`。不要將金鑰提交到 repo。

如使用 OpenCode 已有模型設定直接開啟對話，可直接載入 skills；自帶 runner 使用明確 endpoint，不自動沿用未指定的雲端服務。無法取得獨立驗證上下文時，只能輸出未驗證草稿。

舊 DeepAgents 0.7.0 runner 使用 `skills/literature-review/scripts/deepagents070/requirements-tested.lock` 與 `docs/native-harness-guide-v06.zh-TW.md`。這是 legacy 路線，與上述 0.7.15 原生流程分開安裝；不能在同一環境用舊版本鎖覆蓋新依賴。
