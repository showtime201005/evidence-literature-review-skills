# Ubuntu reader prompt supplemental regression

**6/6 reader raw submission tests passed**, zero failures/errors/skips, unittest 2.360 seconds. Zero API, no key transfer, Python socket guard active. This short regression was explicitly requested during an independently running frozen live control; it did not change that control's installed source.

Overlay `.ubuntu22-vm/reader-prompt-overlay-20261020T191934Z/`, same guest basename under `/home/reviewer/`; base `selectors-install-overlay-20261020T191327Z` remains unchanged. Only two source files captured at `2026-10-20T19:19:34.126296+00:00`:

| File | SHA256 |
|---|---|
| source/skills/literature-review/scripts/runtime/litreview_core/reader_worker.py | `0e8d19e0900fc616bb3db3320c26b6073d5fe0a7b6c50b9031ad3c28929fc145` |
| source/skills/analyze-paper/references/scientific-records.md | `936bdd3fbb599d7fbf5d988b5f6f5bcec50b9a2925c79f35c94eca081a035b79` |

This is a **prompt supplement** stating the exact four data keys and existing explanation fields. No accept/schema change is claimed. All 480 base-overlay source manifest files and both supplemental files were reverified. Runtime import of reader_worker is asserted to the supplement. Tests and original reader fixtures come unchanged from the 65-test base; the pinned local tokenizer link allows direct native_reading replay without skips.

The reference Markdown is captured and hash-verified; this Python suite does not independently validate its prose or claim model compliance. No full-suite rerun or fresh five-skill install was performed. The original 65-test result refers to its original frozen prompt, not this later supplement. These scripted replays establish preservation/strict-validation mechanics, not reduction of real Qwen retries.

Evidence: `overlay-manifest.json`, `overlay-results.json`, `overlay-tests.log`, `run-overlay.py`, `overlay.tar.gz`.
