# DeepAgents 文獻回顧核心 skills

此資料夾只包含五個 skills 的 DeepAgents 原生指令、所需 references、執行入口與相依 runtime；沒有交接 HTML、歷史報告、測試、示例語料、API key 或虛擬環境。

`skills/` 含 analyze-paper、compare-papers、write-review、verify-citations、literature-review。各 skill 帶獨立 runtime，是為了可單獨搬移使用；共用的內部程式模組保留原版本，沒有為縮小體積刪除相依。

## 準備

Windows／Ubuntu 22.04 均需 Python 3.11+（Ubuntu 22.04 預設 3.10 不符合）。在此資料夾執行：

```text
python -m pip install -r skills/literature-review/scripts/requirements-native.txt
python -X utf8 skills/literature-review/scripts/runtime/litreview_core/qwen_tokens.py --download --path qwen-tokenizer.json
```

自行在目前程序的環境設定 `OPENROUTER_API_KEY`；程式不自動讀 `.env`。模型固定為 `qwen/qwen3.8-27b`，完整請求最多 200K，較低 provider 限制仍生效。

## 完整執行

替換所有 `/ABS/` 路徑（Windows 可用 `C:/...`）。來源只接受資料夾第一層的 1–100 篇 UTF-8 Markdown；questions 是問題陣列或含 questions 欄位的 JSON；輸出目錄需全新。

```text
python -X utf8 skills/literature-review/scripts/native_review.py --sources /ABS/papers --questions /ABS/questions.json --out /ABS/new-run --skills-root /ABS/deepagents-literature-review-core/skills --tokenizer /ABS/deepagents-literature-review-core/qwen-tokenizer.json --review-protocol v2 --review-observations whole-unit --closed-checks --workers 8 --deadline 5400
```

此入口會建立真正 DeepAgents coordinator，透過 SDK task 呼叫 subagents。單項任務使用該 skill 的 `scripts/native_task.py`，reader/writer/comparer/verifier 需要各自合法 JSON packet，不能直接傳 Markdown。v2 reviewers 由完整 workflow 或 Python API 驅動。

## 狀態

這是從交接版抽出的 DeepAgents 核心包，另將 SKILL.md 整理為 native-only 說明。底層程式未改，未重跑模型驗收；百篇／90 分鐘及最新兩篇完整交付仍未通過。`--deadline 5400` 不是完成時間保證。strict 工具候選仍只有 Python API，沒有 native CLI 開關或供應商實測。

每個 skill 的 native-installation.json 與根目錄 CORE-MANIFEST.json 記錄抽取後檔案雜湊。
