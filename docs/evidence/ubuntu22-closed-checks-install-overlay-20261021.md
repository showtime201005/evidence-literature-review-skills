# Ubuntu 22.04 closed-checks regression and fresh installation

**85/85 passed**, zero failures/errors/skips. unittest 51.317 seconds; harness 51.947s. Actual existing Ubuntu 22.04.5 / Python 3.12.13 VM, zero API and no key transferred. Socket guard inherited by Python subprocesses. No source modifications made during validation.

## Exact suites

- test_review_observation_selectors: 4
- test_native_review_inputs: 15
- test_paper_review_v2: 17
- test_section_review_v2: 4
- test_review_workflow_v2: 10
- test_native_review_v2_run: 3
- test_install_skills: 15
- test_closed_scientific_checks: 11
- test_reader_raw_submission: 6

Selector suite explicitly loads `SelectorTransportTests` only, avoiding imported fixture TestCase duplication. Actual SDK scripted tests exercise closed checks through v2 workflow and CLI, including negative revision blocking. These are mechanical/scripted regressions, not real-model scientific-quality measurements.

## Frozen overlay

Host `.ubuntu22-vm/closed-checks-install-overlay-20261020T193833Z/`; guest `/home/reviewer/closed-checks-install-overlay-20261020T193833Z/`. Root-authorized freeze captured `2026-10-20T19:38:34.407182+00:00`. Manifest covers 482 canonical source files across skills/scripts/tests/docs, including complete five skills and references, and existing regression fixtures. No API key or reports transferred. Pinned tokenizer reused through local guest link, so no tests skipped for tokenizer absence.

Base snapshot5 `offline-snapshot-20261019T211747Z` untouched; all 564 baseline manifest files reverified. Previous overlays untouched. All 36 loaded runtime submodules resolved into this new overlay. Manifest and archive hashes:

- overlay-manifest.json: `2da6aa5de1bf386c122959f187f745a62a69862bff55ad261f7c8d8ba312d415`
- overlay.tar.gz: `99671f72d7d21c52b3efe768a2a4a5f401e367b8edf4c1934b0649804d573561`

| Runtime | SHA256 |
|---|---|
| closed_scientific_checks.py | `d72a861c21f03aab876aeda12a0d1bcc4ec16fe5c3b38a90772354d2678386f6` |
| delivery_export_v2.py | `8c44dad63cb1794c63a614303613841ee457d715eb0e937764f7532424aeea15` |
| native_review.py | `8579f25899f552277ab7a8ad882fd814457d10d1db366fcad25b2df2ccc3b271` |
| reader_worker.py | `0e8d19e0900fc616bb3db3320c26b6073d5fe0a7b6c50b9031ad3c28929fc145` |
| review_release_v2.py | `27ff065668925d9d0307b1c8486a07dce6a8bea2e4ddb185b34860730d4754ed` |
| review_workflow_v2.py | `cde72d0527e2d0ea21f8a71d57ad2509dfb74e02508cd9f34a2680593263837a` |

## Five-skill fresh install

Target `/home/reviewer/closed-checks-install-overlay-20261020T193833Z/fresh-installed-project/skills`. All installed manifest hashes verified. Every skill has exactly 68 runtime Python files identical to captured canonical source, including `closed_scientific_checks.py` and `review_observation_selectors.py`. Manifest totals: literature-review 88; verify-citations 83; other three skills 82 each.

Installed CLI run from `/tmp`: `native_review.py --help` succeeds and includes `--closed-checks`; `native_doctor.py --skip-key-check` passes all diagnostics using pinned tokenizer. No model call. The doctor/installer and current skill references are those captured in this overlay.

Evidence: `overlay-manifest.json`, `overlay-results.json`, `overlay-tests.log`, `installed-verification.json`, `fresh-install.log`, `installed-native-review-help.log`, `installed-native-doctor.log`, `run-overlay.py`, `overlay.tar.gz`.

Scope is these nine requested suites plus installation checks, not the full legacy suite, live provider behavior, report quality or 100-paper/90-minute acceptance.
