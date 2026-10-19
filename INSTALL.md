# 安裝與首次執行

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

DeepAgents：安裝 `skills/literature-review/scripts/deepagents070/requirements-tested.lock`，安裝器改 `--harness deepagents`，依 `docs/native-harness-guide-v06.zh-TW.md` 指定 skill sources 及 endpoint。
