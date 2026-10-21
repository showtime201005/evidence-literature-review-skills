# 2026-10-21 開發交接封裝

這份封裝保留目前五個 skills、canonical runtime、測試程式、安裝器及技術文件。**這是開發交接快照，百篇／90 分鐘與報告品質驗收尚未通過。**

## 閱讀順序

1. [HTML 技術介紹](implementation-guide.zh-TW.html)：可下載後以瀏覽器離線開啟，供團隊簡報與實作說明。
2. [交接文件](HANDOFF-2026-10-21.zh-TW.md)：目前結果、已知缺點、接續任務與驗收條件。
3. [驗證證據摘要](evidence/current-status.json)：由既有實測紀錄擷取的機器可讀摘要及原檔 SHA256。
4. [安裝指南](../INSTALL.md)、[native requirements](../skills/literature-review/scripts/requirements-native.txt)。舊文件的版本與驗收敘述應以本次交接文件為準。

## 封裝範圍

- `skills/`：五個 skill 的指令、references、scripts 與 canonical runtime。
- `scripts/`、`tests/`、`examples/`：安裝／研究輔助程式、測試原始碼與合成示例。
- `docs/`：目前架構、交接、技術介紹及精選證據；保留的舊版文件有歷史用途。
- `PACKAGE-MANIFEST.json`：ZIP 內每個檔案的相對路徑、大小與 SHA256。

未包含 API key、`.env`、虛擬環境、tokenizer 下載快取、VM、完整外部原始執行目錄或所有歷史 sizing 報告。精選紀錄保留來源檔 hash；僅有 hash 不能取代完整原始執行證據。

## 重建 ZIP

在此儲存庫執行（Python 3.11+，僅標準函式庫，不呼叫模型）：

```text
python -X utf8 scripts/package_handoff.py
```

產物位於 `dist/`，包含 ZIP、SHA256 與外部 manifest。腳本會排除快取／環境檔，檢查已知憑證格式，並核對 ZIP CRC 與內部檔案 SHA256。這些封裝檢查不代表文獻回顧品質驗收。

儲存庫的 `.gitattributes` 保留原始換行 bytes，避免 Windows／Linux 的自動換行轉換使 manifest 雜湊失配。若自行編輯檔案，請重新產生封裝與清單。

## 使用注意

模型固定為 `qwen/qwen3.8-27b`；使用者應在執行環境自行設定 `OPENROUTER_API_KEY`。200K 是完整單次請求的上限，較小的 provider 限制仍須遵守。`--deadline 5400` 是時間限制設定，不是百篇能在該時間內完成的保證。

`strict-supported-subset/1` 仍是 Python API 候選功能，未接入 native CLI，也尚未完成真實 provider probe。不得將離線序列化測試當作供應商端已接受的證據。
