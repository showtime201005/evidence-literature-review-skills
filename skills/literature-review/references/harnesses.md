# Harness adapters

Use the same capability rules and public artifacts in all environments. Bundled core files execute from each skill's scripts/runtime; do not require files from another installed skill. No adapter calls an undocumented vendor API.

The portable adapter is a file-mailbox transport exposing capabilities(), dispatch(TaskSpec), collect(task_id), and optional cancel(task_id), through litreview_core.harness.MailboxAdapter. Native OpenCode 1.19.3 and DeepAgents 0.7.0 entry points are bundled as scripts/harness_runner.py in every skill. See native-harnesses.md for setup, standalone selection and endpoint configuration. Native integration tests use scripted providers; real provider research quality requires a separate evaluation. Verify actual paths/version/capabilities before a real run.

| Harness | Installation target | Execution guidance | Validation state |
| --- | --- | --- | --- |
| Codex | .agents/skills/NAME | Use actual available file/Python tools and isolated model tasks. Bound concurrency by harness limits. | Current environment forward test only; no separate Codex CLI certification |
| Claude Code | .claude/skills/NAME | Load reader/verifier skill in explicit separate contexts. Coordinator retains queue ownership. | File transport contract tested; native executable unavailable here |
| OpenCode | .opencode/skills/NAME or staged canonical copies | Load source packets in bounded tasks. Set the workspace explicitly with --dir. | Native CLI 1.19.3 skill loading, shell execution and reader delegation tested with a scripted provider; company model inference pending |
| Deep Agents | explicit configured skill sources | Supply a real filesystem/execution backend, skills visibility to each subagent, and identical source/runtime versions. | SDK 0.7.0 graph, isolated subagent, skill loading and local execute tested with a scripted model; company Qwen inference pending |

Capabilities probe JSON: `{ "version":"actual-or-unknown", "read_files":true, "write_files":true, "python":true, "model_analysis":true, "independent_contexts":true, "max_workers":4, "cancel":false, "usage":false, "path_mapping":{} }`. Never claim a capability from this example alone; observe it in the actual harness. `adapter HARNESS --probe probe.json` checks declarations, not live vendor integration. Missing mandatory read/write/Python/model capability returns blocked. Missing independent contexts permits draft analysis, but blocks independent publication.

Avoid duplicate same-name skill installations. A source package may install selected skills only; each is self-contained. Deep Agents paths must map to the actual backend that also executes Python, not just a virtual skill store. A virtual backend without program execution cannot satisfy exact locator validation. Preserve file manifests for cross-harness transfers and rebuild the lease database from public receipts after transfer. Never equate mailbox contract tests with four-harness end-to-end acceptance.
