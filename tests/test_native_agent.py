"""Offline real-SDK graph tests. Scripted models never call a provider.

Run with Python containing deepagents==0.7.15:
  python -m unittest discover -s tests -p test_native_agent.py -v
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/literature-review/scripts/runtime"))

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import BaseModel, Field

from litreview_core.native_agent import (NativeAgentError, ROLE_SKILLS, SKILL_SNAPSHOT_PROFILE,
                                        WorkerTask, create_review_agent, _snapshot_skill, _skill_hash)


class ScriptedModel(BaseChatModel):
    """Actual LangChain model API, deterministic local responses, no HTTP."""
    role: str
    script: object = Field(exclude=True)
    model_name: str = "offline-scripted-not-Qwen-inference"

    @property
    def _llm_type(self):
        return "offline-native-delegation-fixture"

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        return self.bind(tools=[convert_to_openai_tool(value) for value in tools], **kwargs)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=self.script(messages, self.role))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return await asyncio.to_thread(self._generate, messages, stop, run_manager, **kwargs)


class ToolRecordingModel(ScriptedModel):
    bound_tools: object = Field(exclude=True)

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        self.bound_tools.append((self.role, [convert_to_openai_tool(value) for value in tools]))
        return super().bind_tools(tools, tool_choice=tool_choice, **kwargs)


class Ancestry(BaseCallbackHandler):
    def __init__(self):
        self.parents, self.task_runs, self.model_runs = {}, set(), []
        self.lock = threading.Lock()

    def _add(self, run_id, parent_run_id):
        self.parents[str(run_id)] = str(parent_run_id) if parent_run_id else None

    def on_chain_start(self, serialized, inputs, *, run_id, parent_run_id=None, **kwargs):
        with self.lock:
            self._add(run_id, parent_run_id)

    def on_tool_start(self, serialized, input_str, *, run_id, parent_run_id=None, **kwargs):
        with self.lock:
            self._add(run_id, parent_run_id)
            if serialized.get("name") == "task":
                self.task_runs.add(str(run_id))

    def on_chat_model_start(self, serialized, messages, *, run_id, parent_run_id=None, **kwargs):
        with self.lock:
            self._add(run_id, parent_run_id)
            self.model_runs.append(str(run_id))

    def below_task(self, run_id):
        seen = set()
        while run_id and run_id not in seen:
            if run_id in self.task_runs:
                return True
            seen.add(run_id)
            run_id = self.parents.get(run_id)
        return False


class NativeDelegationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="native-agent-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.skills = self.root / "skills"
        for name in set(ROLE_SKILLS.values()) | {"literature-review"}:
            folder = self.skills / name
            folder.mkdir(parents=True)
            (folder / "SKILL.md").write_text(
                f"---\nname: {name}\ndescription: Offline fixture for {name}.\n---\n# {name}\nRead the assigned source and preserve honest failures.\n",
                encoding="utf-8")
        self.network_attempts = []

        def blocked(*args, **kwargs):
            self.network_attempts.append(True)
            raise AssertionError("Network forbidden in offline native delegation test")

        self.addCleanup(patch.stopall)
        patch.object(socket, "create_connection", blocked).start()
        import httpx
        patch.object(httpx.Client, "send", blocked).start()
        patch.object(httpx.AsyncClient, "send", blocked).start()

    def model(self, role, script):
        return ScriptedModel(role=role, script=script,
                             profile={"tool_calling": True, "max_input_tokens": 200000, "max_output_tokens": 16384})

    def build(self, roles=("reader", "reader"), *, scientific_failure=False, long_input=False, barrier=True,
              nested_task=False, worker_exception=None, finish_exception=None, bad_input=False,
              entered=None, release=None, worker_sleep=.025, max_concurrency=4,
              workspace=None, read_reference=False, max_model_calls=4, malformed_negative=False):
        actual, starts, ends, guard_roles, accepts = [], {}, {}, [], []
        lock = threading.Lock()
        rendezvous = threading.Barrier(len(roles)) if barrier and len(roles) > 1 else None
        parent_calls = [0]
        worker_calls = {}
        finished = []
        source = ("FULL_SOURCE_START\n" + "source body with conditions and null results. " * 6500 + "\nFULL_SOURCE_END") if long_input else "Actual assigned public source."

        def parent_script(messages, role):
            parent_calls[0] += 1
            if parent_calls[0] == 1:
                return AIMessage(content="", id="actual-parent-message",
                    response_metadata={"id": "offline-parent-response"},
                    tool_calls=[{"name": "task", "args": {"subagent_type": value, "description": json.dumps({"ticket": str(index)})},
                                 "id": "actual-task-" + str(index)} for index, value in enumerate(roles)])
            self.assertTrue(any(isinstance(message, ToolMessage) and message.name == "task" for message in messages))
            return AIMessage(content="Actual coordinator received task receipts.", id="actual-parent-final")

        def worker_script(identity):
            def respond(messages, role):
                text = "\n".join(str(message.content) for message in messages)
                self.assertNotIn("WRITER_PRIVATE_SHOULD_NOT_LEAK", text)
                self.assertIn(source, text)
                ticket = identity.task_tool_call_id.removeprefix("actual-task-")
                with lock:
                    worker_calls[ticket] = worker_calls.get(ticket, 0) + 1
                    starts[ticket] = time.monotonic()
                if entered:
                    entered.set()
                if release:
                    release.wait(timeout=10)
                if worker_exception:
                    raise worker_exception
                if read_reference and worker_calls[ticket] <= int(read_reference):
                    return AIMessage(content="", id="read-exact-reference-" + ticket,
                        tool_calls=[{"name": "read_file", "args": {
                            "file_path": f"/skills/{identity.skill}/references/portable.md"},
                            "id": "reference-read-" + ticket}])
                if read_reference:
                    self.assertTrue(any(isinstance(value, ToolMessage) and value.name == "read_file"
                                        and "EXACT_REFERENCE_BYTES_中文" in str(value.content) for value in messages))
                if nested_task and worker_calls[ticket] == 1:
                    return AIMessage(content="", id="nested-task-attempt",
                        tool_calls=[{"name": "task", "args": {"subagent_type": "general-purpose", "description": "untracked nested work"},
                                     "id": "nested-task-" + ticket}])
                if nested_task:
                    self.assertTrue(any(isinstance(value, ToolMessage) and value.status == "error"
                                        and "Only the coordinator" in value.content for value in messages))
                if rendezvous:
                    rendezvous.wait(timeout=10)
                time.sleep(worker_sleep)
                with lock:
                    ends[ticket] = time.monotonic()
                return AIMessage(content="", id="worker-model-" + ticket,
                    response_metadata={"id": "offline-worker-response-" + ticket},
                    tool_calls=[{"name": "submit_result", "args": {"data": {"ticket": ticket, "producer": {"context_id": "model-spoof"}}},
                                 "id": "actual-submit-" + ticket}])
            return respond

        def factory(identity, description):
            ticket = json.loads(description)["ticket"]
            with lock:
                actual.append(identity)
            self.assertEqual(identity.role, roles[int(ticket)])
            self.assertEqual(identity.parent_model_message_id, "actual-parent-message")
            self.assertEqual(identity.parent_response_id, "offline-parent-response")
            self.assertFalse((identity.workspace / "skills").exists(), "Factory receives a fresh workspace")

            def accept(data, supplied_identity):
                self.assertIs(supplied_identity, identity)
                self.assertEqual(data["ticket"], ticket)
                with lock:
                    accepts.append(identity.context_id)
                if malformed_negative:
                    class MalformedNegative(ValueError):
                        code = 'WITNESS_SCHEMA_INVALID'
                        semantic_negative_detected = True
                    raise MalformedNegative('Negative finding retained despite malformed coordinates')
                if scientific_failure:
                    class FindingRequiresRevision(Exception):
                        code = "VERIFICATION_ISSUES"
                    raise FindingRequiresRevision("Independent source verdict is unsupported")
                return {"ticket": ticket, "native_status": "validated_by_offline_fixture"}
            def on_finish(supplied_identity, receipt):
                with lock:
                    finished.append((supplied_identity.context_id, dict(receipt)))
                if finish_exception:
                    raise finish_exception
            return WorkerTask("Complete only the assigned local fixture.",
                              {"../escape.txt" if bad_input else "source.txt": source}, accept, on_finish=on_finish,
                              max_model_calls=max_model_calls)

        def worker_model_factory(identity):
            return self.model(identity.role, worker_script(identity))

        def guard(model, role):
            with lock:
                guard_roles.append(role)
            return model

        graph = create_review_agent(self.model("coordinator", parent_script), workspace or self.root / "run", self.skills,
                    worker_factory=factory, worker_model_factory=worker_model_factory,
                    guard_model=guard, max_concurrency=max_concurrency)
        graph.fixture_finished = finished
        self.assertEqual(actual, [], "Creating a coordinator must not pre-dispatch workers")
        return graph, actual, starts, ends, guard_roles, accepts

    def test_sync_real_task_parallelism_identity_and_callback_ancestry(self):
        graph, actual, starts, ends, guards, accepts = self.build()
        ancestry = Ancestry()
        graph.invoke({"messages": [{"role": "user", "content": "WRITER_PRIVATE_SHOULD_NOT_LEAK"}]},
                     config={"callbacks": [ancestry], "recursion_limit": 30})
        self.assertEqual(len(actual), 2)
        self.assertEqual(len(set(identity.context_id for identity in actual)), 2)
        self.assertLess(max(starts.values()), min(ends.values()), "Both real task subgraphs must overlap")
        self.assertCountEqual(guards, ["coordinator", "reader", "reader"])
        self.assertEqual(len(accepts), 2)
        self.assertEqual(len(graph.fixture_finished), 2)
        self.assertEqual(sum(event["event"] == "task_delegated" for event in graph.events), 2)
        self.assertEqual(sum(event["event"] == "task_returned" for event in graph.events), 2)
        self.assertEqual(sum(ancestry.below_task(value) for value in ancestry.model_runs), 2)
        self.assertEqual(len(ancestry.task_runs), 2)
        for identity in actual:
            self.assertEqual({p.name for p in (identity.workspace / "skills").iterdir()}, {identity.skill})
            receipt = json.loads((identity.workspace / "accepted.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["producer"]["context_id"], identity.context_id)
            self.assertNotEqual(receipt["producer"]["context_id"], "model-spoof")
        self.assertEqual(self.network_attempts, [])

    def test_persisted_callback_ancestry_contains_no_prompts_or_secrets(self):
        graph, actual, *_ = self.build()
        graph.invoke({"messages": [{"role": "user", "content": "WRITER_PRIVATE_SHOULD_NOT_LEAK"}]},
                     {"metadata": {"api_key": "SECRET_METADATA_MUST_NOT_LOG", "prompt": "SECRET_PROMPT_MUST_NOT_LOG"}})
        records = [json.loads(line) for line in graph.log.path.read_text(encoding="utf-8").splitlines()]
        callbacks = [row for row in records if row["event"].startswith("callback_")]
        self.assertNotIn("SECRET_METADATA_MUST_NOT_LOG", json.dumps(callbacks))
        self.assertNotIn("SECRET_PROMPT_MUST_NOT_LOG", json.dumps(callbacks))
        self.assertNotIn("WRITER_PRIVATE_SHOULD_NOT_LEAK", json.dumps(callbacks))
        parents = {row["run_id"]: row["parent_run_id"] for row in callbacks if row["event"].endswith("_start")}
        tasks = {row["run_id"]: row for row in callbacks if row["event"] == "callback_tool_start" and row["name"] == "task"}
        children = [row for row in callbacks if row["event"] == "callback_model_start" and row["metadata"].get("worker_context_id")]
        self.assertEqual(len(children), 2)
        for child in children:
            node = child["run_id"]
            seen = set()
            while node not in tasks:
                self.assertNotIn(node, seen)
                seen.add(node)
                node = parents[node]
                self.assertIsNotNone(node)
            self.assertEqual(tasks[node]["native_task_tool_call_id"], child["metadata"]["task_tool_call_id"])
        self.assertEqual({row["metadata"]["worker_context_id"] for row in children}, {identity.context_id for identity in actual})

    def test_async_worker_limit_applies_before_claim_factory(self):
        graph, actual, *_ = self.build(("reader",) * 6, barrier=False, worker_sleep=.08, max_concurrency=4)
        asyncio.run(graph.ainvoke({"messages": [{"role": "user", "content": "Six independent tickets."}]},
                                 {"max_concurrency": 2}))
        self.assertEqual(len(actual), 6)
        self.assertEqual(graph.worker_limits, {"maximum": 4, "active": 0, "peak": 2})
        self.assertEqual(len(graph.fixture_finished), 6)

    def test_provider_exception_cleanup_once_preserves_original_error(self):
        original = RuntimeError("ORIGINAL_PROVIDER_FAILURE")
        cleanup = ValueError("SECONDARY_LEASE_CLEANUP_FAILURE")
        graph, actual, *_ = self.build(("reader",), worker_exception=original, finish_exception=cleanup)
        with self.assertRaisesRegex(RuntimeError, "ORIGINAL_PROVIDER_FAILURE") as caught:
            graph.invoke({"messages": [{"role": "user", "content": "One failing provider ticket."}]})
        self.assertIs(caught.exception, original)
        self.assertTrue(any("SECONDARY_LEASE_CLEANUP_FAILURE" in note for note in caught.exception.__notes__))
        self.assertEqual(len(graph.fixture_finished), 1)
        receipt = graph.fixture_finished[0][1]
        self.assertEqual(receipt["status"], "failed")
        self.assertFalse(receipt["accepted"])
        final = json.loads((actual[0].workspace / "result.json").read_text(encoding="utf-8"))
        self.assertFalse(final["accepted"])
        self.assertEqual(graph.worker_limits["active"], 0)

    def test_finish_hook_exception_is_not_called_twice_or_marked_accepted(self):
        original = RuntimeError("FINISH_HOOK_FAILED")
        graph, actual, *_ = self.build(("reader",), finish_exception=original)
        with self.assertRaisesRegex(RuntimeError, "FINISH_HOOK_FAILED") as caught:
            graph.invoke({"messages": [{"role": "user", "content": "One finishing ticket."}]})
        self.assertIs(caught.exception, original)
        self.assertEqual(len(graph.fixture_finished), 1)
        receipt = json.loads((actual[0].workspace / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["status"], "failed")
        self.assertFalse(receipt["accepted"])
        self.assertTrue(receipt["native_submission_accepted_before_failure"])
        self.assertTrue((actual[0].workspace / "accepted.json").exists(), "Keep genuine pre-failure native receipt")

    def test_receipt_io_exception_propagates_without_model_retry(self):
        import litreview_core.native_agent as native
        original_write = native._atomic_json
        original = OSError("ACCEPTED_RECEIPT_IO_FAILED")

        def write(path, value):
            if Path(path).name == "accepted.json":
                raise original
            return original_write(path, value)
        graph, actual, *_ = self.build(("reader",))
        with patch.object(native, "_atomic_json", write), self.assertRaisesRegex(OSError, "ACCEPTED_RECEIPT_IO_FAILED") as caught:
            graph.invoke({"messages": [{"role": "user", "content": "Reject incomplete receipt persistence."}]})
        self.assertIs(caught.exception, original)
        self.assertEqual(len(graph.fixture_finished), 1)
        receipt = json.loads((actual[0].workspace / "result.json").read_text(encoding="utf-8"))
        self.assertFalse(receipt["accepted"])
        self.assertEqual(receipt["model_calls"], 1)
        self.assertEqual(graph.worker_limits["active"], 0)

    def test_preparation_exception_calls_finish_once(self):
        graph, actual, *_ = self.build(("reader",), bad_input=True)
        with self.assertRaisesRegex(NativeAgentError, "cannot traverse"):
            graph.invoke({"messages": [{"role": "user", "content": "Reject unsafe assigned path."}]})
        self.assertEqual(len(graph.fixture_finished), 1)
        self.assertFalse(graph.fixture_finished[0][1]["accepted"])
        self.assertFalse((actual[0].workspace.parent / "escape.txt").exists())
        self.assertEqual(graph.worker_limits["active"], 0)

    def test_cancellation_cleanup_once_queued_tasks_do_not_claim(self):
        entered, release = threading.Event(), threading.Event()
        graph, actual, *_ = self.build(("reader",) * 3, barrier=False, entered=entered, release=release,
                                      max_concurrency=1)

        async def cancel_run():
            running = asyncio.create_task(graph.ainvoke({"messages": [{"role": "user", "content": "Cancellation fixture."}]}))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 5))
                self.assertEqual(len(actual), 1, "Queued delegates must not claim leases")
                running.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await running
                self.assertEqual(len(graph.fixture_finished), 1)
                self.assertEqual(graph.fixture_finished[0][1]["status"], "cancelled")
                self.assertFalse(graph.fixture_finished[0][1]["accepted"])
                self.assertEqual(graph.worker_limits["active"], 0)
            finally:
                release.set()
        asyncio.run(cancel_run())

    def test_async_real_task_parallelism(self):
        graph, actual, starts, ends, guards, accepts = self.build(("reader", "comparer"))
        asyncio.run(graph.ainvoke({"messages": [{"role": "user", "content": "Delegate these two tickets."}]}))
        self.assertEqual(len(actual), 2)
        self.assertLess(max(starts.values()), min(ends.values()))
        self.assertCountEqual(guards, ["coordinator", "reader", "comparer"])
        self.assertEqual(self.network_attempts, [])

    def test_scientific_failure_is_preserved_without_verdict_retry(self):
        graph, actual, *_ = self.build(("verifier",), scientific_failure=True)
        result = graph.invoke({"messages": [{"role": "user", "content": "Verify this ticket."}]})
        receipt = json.loads(next(message.content for message in result["messages"] if isinstance(message, ToolMessage) and message.name == "task"))
        self.assertEqual(receipt["status"], "needs_revision")
        self.assertFalse(receipt["accepted"])
        self.assertEqual(receipt["model_calls"], 1)
        self.assertEqual(len(actual), 1)
        self.assertFalse((actual[0].workspace / "accepted.json").exists())

    def test_malformed_negative_is_terminal_and_raw_submission_is_retained(self):
        graph, actual, *_ = self.build(('verifier',), malformed_negative=True)
        result = graph.invoke({'messages': [{'role': 'user', 'content': 'Verify this ticket.'}]})
        receipt = json.loads(next(m.content for m in result['messages']
                                 if isinstance(m, ToolMessage) and m.name == 'task'))
        self.assertEqual(receipt['status'], 'needs_revision')
        self.assertFalse(receipt['accepted'])
        self.assertEqual(receipt['model_calls'], 1)
        self.assertEqual(len(list(actual[0].workspace.glob('submission-*.json'))), 1)
        self.assertFalse((actual[0].workspace/'accepted.json').exists())

    def test_long_human_input_is_delivered_without_default_eviction(self):
        graph, actual, *_ = self.build(("reader",), long_input=True)
        result = graph.invoke({"messages": [{"role": "user", "content": "Read complete long input."}]})
        self.assertTrue((actual[0].workspace / "accepted.json").exists())
        receipt_message = next(message for message in result["messages"] if isinstance(message, ToolMessage) and message.name == "task")
        self.assertLess(len(receipt_message.content), 4000, "Native task must return structured receipt, not full child messages")
        self.assertNotIn("FULL_SOURCE_START", receipt_message.content)
        self.assertNotIn("FULL_SOURCE_END", receipt_message.content)
        self.assertEqual(json.loads(receipt_message.content)["result"]["native_status"], "validated_by_offline_fixture")
        self.assertEqual(self.network_attempts, [])

    def test_leaf_nested_task_is_rejected_without_another_worker(self):
        graph, actual, *_ = self.build(("reader",), nested_task=True)
        result = graph.invoke({"messages": [{"role": "user", "content": "Run one real delegated reader."}]})
        receipt = json.loads(next(message.content for message in result["messages"] if isinstance(message, ToolMessage) and message.name == "task"))
        self.assertEqual(receipt["status"], "accepted")
        self.assertEqual(receipt["model_calls"], 2)
        self.assertEqual(len(actual), 1)
        self.assertEqual(sum(event["event"] == "worker_started" for event in graph.events), 1)
        self.assertEqual(sum(event["event"] == "task_delegated" for event in graph.events), 1)

    def test_generic_worker_is_rejected_before_factory(self):
        calls = [0]

        def script(messages, role):
            calls[0] += 1
            return (AIMessage(content="", tool_calls=[{"name": "task", "args": {"subagent_type": "general-purpose", "description": "bypass"}, "id": "bad-task"}])
                    if calls[0] == 1 else AIMessage(content="Generic role was rejected."))

        def forbidden(*args):
            self.fail("Generic task must not invoke worker_factory")

        graph = create_review_agent(self.model("coordinator", script), self.root / "generic-run", self.skills, worker_factory=forbidden)
        result = graph.invoke({"messages": [{"role": "user", "content": "Try a disallowed role."}]})
        self.assertTrue(any(isinstance(value, ToolMessage) and value.status == "error" for value in result["messages"]))
        self.assertTrue(any(value["event"] == "delegation_rejected" for value in graph.events))
        self.assertEqual(self.network_attempts, [])

    def test_typed_skill_snapshot_exact_references_hash_profile_and_no_legacy_trees(self):
        source = self.skills / "analyze-paper"
        references = source / "references" / "nested"
        references.mkdir(parents=True)
        (references/"retained.md").write_bytes(b"EXACT_REFERENCE\r\noriginal bytes\n")
        scripts, assets = source/"scripts", source/"assets/examples/corpus"
        scripts.mkdir()
        assets.mkdir(parents=True)
        (scripts/"legacy.py").write_text("NEVER_EXECUTE", encoding="utf-8")
        (assets/("a"*64+".json")).write_text("EXAMPLE_NOT_ASSIGNED_SOURCE", encoding="utf-8")
        before = _skill_hash(source)
        target = self.root/"snapshot"
        manifest = _snapshot_skill(source, target)
        self.assertEqual(manifest["profile"], SKILL_SNAPSHOT_PROFILE)
        self.assertEqual(manifest["skill_sha256"], before)
        self.assertEqual((target/"SKILL.md").read_bytes(), (source/"SKILL.md").read_bytes())
        self.assertEqual((target/"references/nested/retained.md").read_bytes(), (references/"retained.md").read_bytes())
        self.assertFalse((target/"assets").exists())
        self.assertFalse((target/"scripts").exists())
        self.assertEqual({row["path"] for row in manifest["files"]}, {"SKILL.md", "references/nested/retained.md"})
        (assets/("a"*64+".json")).write_text("CHANGED_EXCLUDED_EXAMPLE", encoding="utf-8")
        self.assertEqual(_skill_hash(source), before)
        (references/"retained.md").write_text("CHANGED_VISIBLE_REFERENCE", encoding="utf-8")
        self.assertNotEqual(_skill_hash(source), before)
        with self.assertRaisesRegex(NativeAgentError, "new or empty"):
            _snapshot_skill(source, target)

    def test_deep_windows_round_path_omits_long_example_and_readtool_reads_reference(self):
        for name in {"literature-review", "analyze-paper"}:
            folder = self.skills/name
            references = folder/"references"
            references.mkdir()
            (references/"portable.md").write_text("EXACT_REFERENCE_BYTES_中文\n", encoding="utf-8")
            example = folder/"assets/examples/comparison-handoff/corpus/sources"
            example.mkdir(parents=True)
            (example/("f"*64+".md")).write_text("EXCLUDED_EXAMPLE_PAPER", encoding="utf-8")
        padding = "deep-" + "x"*max(1, 140-len(str(self.root)))
        workspace = self.root/padding/"stages/reading/rounds/round-0001"
        legacy_path = workspace/"coordinator/skills/literature-review/assets/examples/comparison-handoff/corpus/sources"/("f"*64+".md")
        self.assertGreater(len(str(legacy_path)), 260, "Reproduce the legacy Win32-copytree failure shape")
        graph, identities, *_ = self.build(("reader",), workspace=workspace, read_reference=True)
        result = asyncio.run(graph.ainvoke({"messages": [{"role": "user", "content": "Read the assigned fixture and reference."}]}))
        self.assertEqual(len(identities), 1)
        identity = identities[0]
        self.assertEqual(identity.skill_snapshot_profile, SKILL_SNAPSHOT_PROFILE)
        self.assertTrue((identity.workspace/"accepted.json").exists())
        self.assertFalse((identity.workspace/"skills/analyze-paper/assets").exists())
        self.assertFalse((workspace/"coordinator/skills/literature-review/assets").exists())
        self.assertEqual(graph.events[0]["skill_snapshot_profile"], SKILL_SNAPSHOT_PROFILE)
        self.assertTrue(any(isinstance(message, ToolMessage) and message.name == "task" for message in result["messages"]))
        self.assertEqual(self.network_attempts, [])

    def test_six_model_calls_have_sufficient_framework_steps(self):
        reference=self.skills/'analyze-paper/references'
        reference.mkdir()
        (reference/'portable.md').write_text('EXACT_REFERENCE_BYTES_中文',encoding='utf-8')
        graph,identities,*_=self.build(('reader',),read_reference=5,max_model_calls=6)
        asyncio.run(graph.ainvoke({'messages':[{'role':'user','content':'Read then submit.'}]}))
        result=json.loads((identities[0].workspace/'result.json').read_text(encoding='utf-8'))
        self.assertTrue(result['accepted'])
        self.assertEqual(result['model_calls'],6)

    def test_more_graph_steps_do_not_increase_model_call_budget(self):
        reference=self.skills/'analyze-paper/references'
        reference.mkdir()
        (reference/'portable.md').write_text('EXACT_REFERENCE_BYTES_中文',encoding='utf-8')
        graph,identities,*_=self.build(('reader',),read_reference=6,max_model_calls=6)
        asyncio.run(graph.ainvoke({'messages':[{'role':'user','content':'Read then submit.'}]}))
        result=json.loads((identities[0].workspace/'result.json').read_text(encoding='utf-8'))
        self.assertFalse(result['accepted'])
        self.assertEqual(result['model_calls'],6)

    def test_each_selected_role_runs_real_task_with_only_its_single_skill_installed(self):
        class FixtureArguments(BaseModel):
            data: dict

        for role, skill in ROLE_SKILLS.items():
            with self.subTest(role=role, skill=skill):
                single = self.root/("single-"+role)
                source = single/"installed-skills"/skill
                source.mkdir(parents=True)
                (source/"SKILL.md").write_bytes((self.skills/skill/"SKILL.md").read_bytes())
                (source/"references").mkdir()
                (source/"references/single.md").write_text("SELECTED_ROLE_REFERENCE_ONLY", encoding="utf-8")
                contexts, bound, guarded, calls = [], [], [], [0]
                parent_calls, worker_calls = [0], [0]

                def model(which, script):
                    return ToolRecordingModel(role=which, script=script, bound_tools=bound,
                        profile={"tool_calling": True, "max_input_tokens": 200000, "max_output_tokens": 16384})

                def parent(messages, which):
                    parent_calls[0] += 1
                    if parent_calls[0] == 1:
                        return AIMessage(content="", id="single-parent-"+role,
                            response_metadata={"id": "single-response-"+role},
                            tool_calls=[{"name": "task", "args": {"subagent_type": role,
                                "description": json.dumps({"ticket": "selected-"+role})}, "id": "single-task-"+role}])
                    return AIMessage(content="Actual selected worker receipt received.")

                def worker(messages, which):
                    worker_calls[0] += 1
                    text = "\n".join(str(message.content) for message in messages)
                    self.assertIn("SELECTED_ROLE_REFERENCE_ONLY", text)
                    self.assertNotIn("PRIVATE_COORDINATOR_TRACE", text)
                    if role == "reader" and worker_calls[0] == 1:
                        # Even a model that emits a hidden nested task cannot
                        # bypass the leaf guard or create another worker.
                        return AIMessage(content="", tool_calls=[{"name": "task", "args": {
                            "subagent_type": "reader", "description": "forbidden nested work"}, "id": "hidden-nested-task"}])
                    if role == "reader":
                        self.assertTrue(any(isinstance(message, ToolMessage) and message.status == "error"
                                            and "Only the coordinator" in str(message.content) for message in messages))
                    return AIMessage(content="", tool_calls=[{"name": "submit_result", "args": {
                        "data": {"result": "actual-selected-output", "producer": "MODEL_IDENTITY_IS_UNTRUSTED"}},
                        "id": "single-submit-"+role}])

                def factory(identity, description):
                    calls[0] += 1
                    contexts.append(identity)
                    self.assertEqual(identity.role, role)
                    self.assertEqual(identity.skill, skill)
                    self.assertEqual(json.loads(description), {"ticket": "selected-"+role})
                    self.assertEqual(identity.parent_model_message_id, "single-parent-"+role)
                    self.assertEqual(identity.parent_response_id, "single-response-"+role)
                    def accept(data, actual_identity):
                        self.assertIs(actual_identity, identity)
                        self.assertEqual(data["result"], "actual-selected-output")
                        return {"fixture_validated": True, "ticket": "selected-"+role}
                    return WorkerTask("Complete only the selected role's fixture.", {"source.txt": "PUBLIC_ASSIGNED_INPUT"},
                        accept, submission_schema=FixtureArguments,
                        skill_documents=("SKILL.md", "references/single.md"))

                def guard(value, which):
                    guarded.append(which)
                    return value

                graph = create_review_agent(model("coordinator", parent), single/"run", source.parent,
                    worker_factory=factory, worker_model_factory=lambda identity:model(identity.role, worker),
                    guard_model=guard, roles={role}, coordinator_skill=skill)
                self.assertEqual(calls[0], 0, "No host pre-dispatch")
                ancestry = Ancestry()
                value = {"messages": [{"role": "user", "content": "PRIVATE_COORDINATOR_TRACE"}]}
                if role in {"verifier", "assembly-auditor"}:
                    result = asyncio.run(graph.ainvoke(value, {"callbacks": [ancestry]}))
                else:
                    result = graph.invoke(value, {"callbacks": [ancestry]})
                self.assertEqual(calls[0], 1)
                self.assertEqual(graph.roles, (role,))
                self.assertEqual(graph.coordinator_skill, skill)
                self.assertEqual(guarded, ["coordinator", role])
                self.assertEqual(len(ancestry.task_runs), 1, "Only the actual parent task may enter SDK dispatch")
                self.assertEqual(sum(event["event"] == "task_delegated" for event in graph.events), 1)
                self.assertEqual({folder.name for folder in (single/"run/coordinator/skills").iterdir()}, {skill})
                self.assertEqual({folder.name for folder in (contexts[0].workspace/"skills").iterdir()}, {skill})
                self.assertEqual(graph.events[0]["role_skills"], {role: skill})
                self.assertEqual(graph.events[0]["coordinator_skill"], skill)
                worker_model_runs = [run for run in ancestry.model_runs if ancestry.below_task(run)]
                self.assertEqual(len(worker_model_runs), worker_calls[0])
                parent_tools = [tool["function"] for which, tools in bound if which == "coordinator"
                                for tool in tools if tool["function"]["name"] == "task"]
                self.assertTrue(parent_tools)
                for task in parent_tools:
                    self.assertIn(role, task["description"])
                    self.assertNotIn("general-purpose", task["description"])
                    for other in ROLE_SKILLS:
                        if other != role:
                            # 'verifier' occurs inside assembly-auditor's own
                            # description, so inspect declared worker headings.
                            self.assertNotIn(f"- {other}:", task["description"])
                self.assertTrue(any(which == role for which, tools in bound))
                self.assertTrue(all(tool["function"]["name"] != "task" for which, tools in bound
                                    if which == role for tool in tools))
                receipt = json.loads(next(message.content for message in result["messages"]
                    if isinstance(message, ToolMessage) and message.name == "task"))
                self.assertTrue(receipt["accepted"])
                self.assertEqual(receipt["producer"]["context_id"], contexts[0].context_id)
                self.assertNotEqual(receipt["producer"]["context_id"], "MODEL_IDENTITY_IS_UNTRUSTED")
                self.assertNotEqual(contexts[0].context_id, graph.coordinator_context_id)
        self.assertEqual(self.network_attempts, [])

    def test_selected_role_rejects_other_supported_role_before_factory(self):
        source = self.root/"only-reader/analyze-paper"
        source.mkdir(parents=True)
        (source/"SKILL.md").write_bytes((self.skills/"analyze-paper/SKILL.md").read_bytes())
        calls = [0]
        def parent(messages, role):
            calls[0] += 1
            if calls[0] == 1:
                return AIMessage(content="", tool_calls=[{"name": "task", "args": {
                    "subagent_type": "writer", "description": "not selected"}, "id": "wrong-selected-role"}])
            return AIMessage(content="Unselected role was rejected.")
        def forbidden(*args):
            self.fail("Unselected role must not enter a factory")
        graph = create_review_agent(self.model("coordinator", parent), self.root/"selected-rejection", source.parent,
            worker_factory=forbidden, roles=("reader",), coordinator_skill="analyze-paper")
        result = asyncio.run(graph.ainvoke({"messages": [{"role": "user", "content": "Reject unselected role."}]}))
        self.assertTrue(any(isinstance(message, ToolMessage) and message.status == "error"
                            and "use one of reader" in message.content for message in result["messages"]))
        self.assertTrue(any(event["event"] == "delegation_rejected" for event in graph.events))
        self.assertEqual(sum(event["event"] == "worker_started" for event in graph.events), 0)

    def test_invalid_role_collections_and_coordinator_skill_fail_before_workspace_creation(self):
        for index, roles in enumerate(([], (), set(), "reader", b"reader", {}, 1, [None], ["unknown"], ["reader", "reader"])):
            with self.subTest(roles=roles):
                workspace = self.root/("invalid-role-"+str(index))
                with self.assertRaises(NativeAgentError):
                    create_review_agent(self.model("coordinator", lambda a,b: AIMessage(content="not called")),
                        workspace, self.skills, worker_factory=lambda a,b: None, roles=roles)
                self.assertFalse(workspace.exists())
        for coordinator_skill in ("../analyze-paper", "unknown", None):
            with self.subTest(coordinator_skill=coordinator_skill), self.assertRaises(NativeAgentError):
                create_review_agent(self.model("coordinator", lambda a,b: AIMessage(content="not called")),
                    self.root/"invalid-coordinator", self.skills, worker_factory=lambda a,b: None,
                    roles=("reader",), coordinator_skill=coordinator_skill)


if __name__ == "__main__":
    unittest.main()
