# Ubuntu closed-schema and malformed-negative supplement

Final corrected run **23/23 passed**, zero failures/errors/skips: closed scientific checks 12 and workflow v2 11. Harness time 30.034s; exact unittest time in log. Zero API/key, inherited socket guard active. This explicitly requested short regression may overlap root's independent paid control; no runtime from that control was modified.

Four-file supplement `.ubuntu22-vm/closed-schema-overlay-20261020T194400Z/`, same guest directory under `/home/reviewer/`, based on immutable `closed-checks-install-overlay-20261020T193833Z`. All 482 base source file hashes and four supplement hashes reverified. Two runtime imports explicitly asserted to supplement. Final harness also loads both test modules from explicit supplement paths to prevent fixture imports from changing selection.

| Captured file | SHA256 |
|---|---|
| source/skills/literature-review/scripts/runtime/litreview_core/closed_scientific_checks.py | `8a436a1d409ac7e08747ef973d722f42932eacb9ebe696f46e1fc45497920df9` |
| source/skills/literature-review/scripts/runtime/litreview_core/paper_review_worker_v2.py | `b573a19790fe40f4917d975e2a8f815a7edb043671faf96661e3864318348ccd` |
| source/tests/test_closed_scientific_checks.py | `650f6a61d59b487a057f6c1159b7fd1a9788af74c727baceaf16d6e2a504f906` |
| source/tests/test_review_workflow_v2.py | `9172318f1bc298796c3829089d103f4ed5cac4ef7165921d78a11c56795434f6` |

Version difference: packet-specific closed-check schema enums and uniqueItems are now advertised in actual SDK; paper worker treats nonempty missing_components as a semantic negative even if malformed, enabling revision rather than operational retry. Workflow runtime itself is unchanged. The new malformed-missing workflow test ran in the final 11-case workflow suite.

Audit: first harness run loaded new closed12 but base workflow10 due to a fixture import changing sys.path (22 total). It is not counted as requested completion. First-attempt log/results preserved. Harness-only correction uses importlib explicit paths with assertions; rerun loaded closed12+new workflow11 and passed23. Frozen source hashes did not change. Archive contains original harness; `run-overlay-corrected.py` separately records exact final harness used.

Original 85-test overlay remains unchanged. This is not a full-suite rerun or a new five-skill installation; prior installed source remains its earlier version. Scripted tests do not establish real-model scientific accuracy.

Evidence: overlay-manifest.json, overlay-results.json, overlay-tests.log, first-attempt-overlay-results.json, first-attempt-overlay-tests.log, run-overlay-corrected.py, overlay.tar.gz.
