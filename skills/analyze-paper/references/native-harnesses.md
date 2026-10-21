# DeepAgents 0.7.15 typed task profile

When the runtime supplies a typed source, draft, or hierarchical proof task,
follow its assigned profile and submit through the supplied typed tool. This is
the current native review path. Do not execute the legacy harness commands or
install the 0.7.0 dependencies described below for a typed task.

Use `scripts/requirements-native.txt` from the native installation for its
pinned environment. `native_doctor.py` checks installation only; its successful
result does not establish model inference, scientific quality, or publication.
The full `native_review.py` path requires all five skills. Selected reading,
comparison, and writing tasks use `native_task.py` with a canonical task packet
and actual coordinator-to-subagent delegation. These drafts are unverified.
Independent proof tasks in the full workflow use fresh verifier/auditor contexts.

## Legacy harness reference

# OpenCode 與 DeepAgents 原生入口（v0.6）

每個 skill 都包含自己的 scripts/harness_runner.py 及完整 runtime。單獨分析、比較、寫作或查核只需安裝該 skill；literature-review 的完整協調模式才需要五個 skills。來源可來自人類或其他系統的公開檔案，不需上游私有狀態。

## 安裝與載入

已固定驗收版本：OpenCode 1.19.3（npm 套件 opencode-ai）、Python DeepAgents 0.7.0、langchain-openai 1.7.2。OpenCode 2 的設定格式不同，此入口會拒絕未驗收版本，避免靜默套錯設定。

```bash
npm install --prefix ./runtime/opencode opencode-ai@1.19.3
python -m pip install deepagents==0.7.0 langchain-openai==1.7.2
```

正式研究執行不安裝套件。先在準備階段安裝依賴並保留環境 lock；DeepAgents 可沿用 coordinator 的 requirements-tested.lock。來源 skills 目錄可用標準名稱或管理系統 ID；入口會建立內容指紋綁定、資料夾名稱正確的副本供原生框架載入，不修改原 skills。

```bash
python /ABS/SELECTED_SKILL/scripts/harness_runner.py --harness deepagents --skill analyze-paper \
  --workspace /ABS/WORK --skills-root /ABS/SKILLS --diagnose --result-file /ABS/WORK/diagnose.json
python /ABS/SELECTED_SKILL/scripts/harness_runner.py --harness opencode --skill analyze-paper \
  --workspace /ABS/WORK --skills-root /ABS/SKILLS --opencode-bin /ABS/opencode \
  --diagnose --result-file /ABS/WORK/diagnose-opencode.json
```

diagnose 不呼叫模型，不能代表論文理解或報告品質通過。真正研究需要設定 LITREVIEW_BASE_URL、LITREVIEW_MODEL_ID 與服務需要時的 LITREVIEW_API_KEY；金鑰僅放環境變數，不寫進報告或設定檔。不指定 endpoint 時明確 blocked，不自動選雲端服務。

## 執行與獨立性

```bash
python /ABS/SELECTED_SKILL/scripts/harness_runner.py --harness deepagents --skill analyze-paper \
  --workspace /ABS/WORK --skills-root /ABS/SKILLS --request-file /ABS/WORK/request.txt \
  --result-file /ABS/WORK/result.json
# OpenCode：改 --harness opencode 並加 --opencode-bin /ABS/opencode。
# 完整協調：改 --skill literature-review 並提供五個 skills。
```

把輸入放在 workspace 內；request.txt 用絕對路徑指定來源、研究問題、深度與產出位置。每次入口執行建立新對話；續跑需明確提供 job/checkpoint 路徑，從公開紀錄恢復。不可把 writer 的同一對話改名後當作獨立 verifier。

OpenCode 協調模式宣告 reader/comparer/writer/verifier/assembly-auditor 子代理。DeepAgents 明確傳入每個子代理的 skills 與受預算保護的模型。新來源 verifier 和整份 assembly auditor 必須使用不同實際任務上下文。無獨立上下文時可交草稿及問題，正式查核會阻擋。

執行使用本機 shell，有與執行程序相同的 OS 權限；不是隔離沙箱。OpenCode 會寫入每次任務專屬設定與事件紀錄，保留使用者正常設定；不使用 --auto 放寬既有拒絕規則。這份設定的本機檔案與 Python 工具權限用於使用者已授權的研究工作，外部搜尋預設拒絕。

## 效率與驗收

先用 3–5 篇代表性資料校準封包大小，已接受結果可直接計入正式工作。各深度仍讀全篇；減少選用深化，保留反證與關鍵限制。依實際模型輸出與硬體吞吐調整 workers，勿從 200K context 推定一次可輸出完整報告。字元限制不是 token 限制；DeepAgents 的保守 byte estimate 也不是真實 tokenizer。

復原時先 status；不重做 accepted reading 或 accepted verifier records。新文本／新證據版本需重驗相關主張。大型比較先 comparison-draft 再分片，正式交付另產出 evidence_catalog.md，逐張列出主張、原文摘錄、來源章節／行號／連結／hash。

verification plan 的 max-chars 包含實際儲存 JSON 的縮排、換行與結尾換行，採 Unicode 字元數，並非 UTF-8 bytes 或 tokens。若單一主張及必要上下文超過預算，保留明確失敗，拆分主張或記錄理由提高預算；不可刪除必要證據來湊大小。更新計畫格式時建立新目錄，保留舊查核紀錄。

驗收應分開記錄：①版本安裝；②原生技能載入與工具呼叫；③真實模型研究；④獨立引用查核；⑤人工學術評估。測試用腳本 provider 只能證明②，不得宣稱③。模型或程序回傳 completed 仍須通過正式 artifact gates 才能稱報告通過。

官方對照：<https://opencode.ai/docs/skills/>、<https://opencode.ai/docs/cli/>、<https://opencode.ai/docs/providers/>、<https://docs.langchain.com/oss/python/deepagents/skills>、<https://docs.langchain.com/oss/python/deepagents/subagents>。實際驗收以固定安裝版本為準。
