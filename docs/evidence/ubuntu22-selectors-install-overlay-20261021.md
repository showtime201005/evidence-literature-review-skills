# Ubuntu 22.04 whole-unit selector regression and installation

2026-10-21: **65/65 passed**, no failures/errors/skips. unittest 42.452 seconds; harness 43.173s. Actual Ubuntu 22.04.5 LTS / Python 3.12.13 checked immediately before freeze. Zero API calls and no key transferred; Python socket guard inherited by subprocesses. No source modifications made during validation.

## Selected scope

- test_paper_review_v2: 17
- test_section_review_v2: 4
- test_review_workflow_v2: 8
- test_native_review_inputs: 14
- test_native_review_v2_run: 3
- test_install_skills: 15
- test_review_observation_selectors: 4

The selector suite is explicitly loaded as `test_review_observation_selectors.SelectorTransportTests`: exactly four independent cases, no imported fixture TestCase counted. Paper/section/workflow suites include actual SDK scripted whole-unit selector execution. Fixture judgments remain scripted; passing does not establish real-model scientific quality.

## Frozen source and evidence

Host `.ubuntu22-vm/selectors-install-overlay-20261020T191327Z/`; guest `/home/reviewer/selectors-install-overlay-20261020T191327Z/`. Root final freeze capture: `2026-10-20T19:13:29.357871+00:00`. Complete manifest covers 480 canonical skill/script/test/doc source files including all five skill definitions/references. No API key or reports directories transferred. Existing approved test fixtures remain test data. Local guest tokenizer symlink uses immutable snapshot5 pinned tokenizer, avoiding CLI skips or network downloads.

Base `offline-snapshot-20261019T211747Z` remains untouched; all 564 source/input manifest files reverified. All 35 loaded runtime submodules point into this overlay, exact paths in `overlay-results.json`.

| Key runtime file | SHA256 |
|---|---|
| native_review.py | `f318500af5a1472e895f7c6c33cfc4fc36e7b91fedc554d7c644e1225c2c245c` |
| paper_review_v2.py | `a6fc154ecf17138eac7f36047f2fe0b8315912a5ebd7406822db6031938da107` |
| paper_review_worker_v2.py | `ad248a2a19e6c6dca21fb86ba71f53e29e61a602d925cf8926409376537e6bff` |
| review_observation_selectors.py | `87ef3d2d4032d07fca25bc1bfdd6f915dc2df581d402c12b7b5735b3674f9b56` |
| review_workflow_v2.py | `094508bed57f15f72310154bdbb61e26a9962cffa59e2b4bf5bd27606b1271c2` |
| section_review_v2.py | `dd7d0f9205a8e049d79403bb3fe15254238082bd29ac52f619442cdaa61c1519` |
| section_review_worker_v2.py | `3502392483339bb9f6f8e4a03e680a1b46f0700fbabb9eac657daa2d1993907e` |

Source manifest SHA256: `4cd12700d74b5dcec65cb35388feccb06772888d3325327150fa0c880ac5b664`.
Archive SHA256: `b2a0629c56a3375088ffda1948aadde2f43fff2e443df67f431e3bdf47fa7efa`.

## Fresh installation

Guest target `/home/reviewer/selectors-install-overlay-20261020T191327Z/fresh-installed-project/skills`. All five installation manifests verified file-by-file; each skill's 67 runtime Python files exactly match frozen canonical runtime. Every skill explicitly contains `review_observation_selectors.py`.

From `/tmp`, installed `native_review.py --help` succeeds and contains `--review-observations`; installed `native_doctor.py --skip-key-check` passes skill/reference, module, pinned dependency and tokenizer checks. No model call. Manifest file counts: literature-review 87; verify-citations 82; analyze-paper, compare-papers, write-review 81 each.

Evidence files: `overlay-manifest.json`, `overlay-results.json`, `overlay-tests.log`, `installed-verification.json`, `fresh-install.log`, `installed-native-review-help.log`, `installed-native-doctor.log`, `run-overlay.py`, `overlay.tar.gz`.

This is the seven requested suites plus fresh installation checks. It is not a full legacy regression run, live provider-quality validation, or 100-paper/90-minute acceptance result.
