"""Offline rotation tests using actual DeepAgents task graphs, never a provider."""
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
sys.path.insert(0, str(ROOT / "tests"))

from langchain_core.messages import AIMessage, ToolMessage
from test_native_agent import ScriptedModel
from litreview_core.coordinator_frontier import run_frontiers
from litreview_core.native_agent import ROLE_SKILLS, WorkerTask, create_review_agent
from litreview_core.task_store import TaskStore, ScopedTaskStore


class FrontierTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="native-frontier-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.skills = self.root / "skills"
        for name in set(ROLE_SKILLS.values()) | {"literature-review"}:
            folder = self.skills / name
            folder.mkdir(parents=True)
            (folder / "SKILL.md").write_text(
                f"---\nname: {name}\ndescription: Offline fixture.\n---\n# {name}\nFollow the assigned ticket.\n",
                encoding="utf-8")
        self.store = TaskStore(self.root / "store")
        self.network_attempts = []

        def blocked(*args, **kwargs):
            self.network_attempts.append(True)
            raise AssertionError("Network forbidden in offline frontier tests")
        self.addCleanup(patch.stopall)
        patch.object(socket, "create_connection", blocked).start()
        import httpx
        patch.object(httpx.Client, "send", blocked).start()
        patch.object(httpx.AsyncClient, "send", blocked).start()

    def model(self, role, script):
        return ScriptedModel(role=role, script=script,
            profile={"tool_calling": True, "max_input_tokens": 200000, "max_output_tokens": 16384})

    def tickets(self, count, role="reader"):
        return [self.store.create(role, {"fixture": index}, max_attempts=1) for index in range(count)]

    def factory(self, *, mode="normal", dynamic=False, delay=0.01, entered=None, foreign=None, bad_receipt=False):
        graphs, visible, identities, model_histories = [], [], [], []
        leases = {}
        lock = threading.Lock()

        def build(ready_tasks, workspace):
            number = len(graphs)+1
            calls = [0]

            def parent(messages, role):
                calls[0] += 1
                model_histories.append((number, list(messages)))
                call_id = f"r{number}-call{calls[0]}"
                tools = [message for message in messages if isinstance(message, ToolMessage)]
                if not tools or tools[-1].name == "task":
                    return AIMessage(content="", id=call_id, tool_calls=[{
                        "name": "ready_tasks", "args": {}, "id": call_id+"-ready"}])
                result = json.loads(tools[-1].content)
                if result["frontier_complete"]:
                    return AIMessage(content="Fixed frontier finished; publication proof belongs to the application.")
                visible.append((number, result["ready"]))
                if mode == "no_progress":
                    return AIMessage(content="I did not execute the assigned task.")
                if mode == "repeat_ready":
                    return AIMessage(content="", id=call_id, tool_calls=[{
                        "name": "ready_tasks", "args": {}, "id": call_id+"-ready"}])
                ready = result["ready"]
                if mode == "foreign":
                    ready = [{"subagent_type": "reader", "description": json.dumps({"ticket": foreign})}]
                return AIMessage(content="", id=call_id,
                    response_metadata={"id": call_id+"-actual-response"},
                    tool_calls=[{"name": "task", "args": item, "id": call_id+f"-task{index}"}
                                for index, item in enumerate(ready)])

            def worker_factory(identity, description):
                ticket = json.loads(description)["ticket"]
                lease = self.store.claim(ticket, identity.role, identity.context_id)
                with lock:
                    identities.append(identity)
                    leases[identity.context_id] = lease

                def accept(data, supplied_identity):
                    self.assertIs(identity, supplied_identity)
                    if mode == "scientific_failure":
                        class RequiresRevision(Exception):
                            code = "VERIFICATION_ISSUES"
                        raise RequiresRevision("Independent fixture found unsupported evidence")
                    receipt = self.store.accept(ticket, identity.context_id, lease["lease"], data,
                                                validator=lambda source, result: None)
                    if dynamic and identity.role == "reader":
                        self.store.create("verifier", {"record_hash": receipt["output_hash"]},
                                          dependencies=[ticket], max_attempts=1)
                    if bad_receipt:
                        receipt["output_hash"] = "0"*64
                    return receipt

                def finish(identity, receipt):
                    if not receipt.get("accepted"):
                        self.store.fail(ticket, identity.context_id, lease["lease"],
                                        {"reason": receipt.get("error", receipt.get("reason", "incomplete"))})
                return WorkerTask("Complete only this local fixture.", {"input.json": lease["payload"]},
                                  accept, on_finish=finish)

            def worker_model(identity):
                def script(messages, role):
                    if entered:
                        entered.set()
                    if mode == "provider_failure":
                        raise RuntimeError("ORIGINAL_PROVIDER_FAILURE")
                    time.sleep(delay)
                    return AIMessage(content="", tool_calls=[{"name": "submit_result",
                        "args": {"data": {"fixture_output": leases[identity.context_id]["payload"]}},
                        "id": identity.context_id+"-submit"}])
                return self.model(identity.role, script)

            agent = create_review_agent(self.model("coordinator", parent), workspace, self.skills,
                worker_factory=worker_factory, worker_model_factory=worker_model,
                coordinator_tools=[ready_tasks], max_concurrency=4)
            graphs.append(agent)
            return agent
        build.graphs, build.visible, build.identities, build.histories = graphs, visible, identities, model_histories
        return build

    def run_frontier(self, factory, *, size=2, deadline=None, name="rotation"):
        return asyncio.run(run_frontiers(self.store, factory, self.root/name,
            time.monotonic()+20 if deadline is None else deadline, frontier_size=size))

    def test_bounded_real_task_rotation_persists_fresh_parents_and_artifact_identity(self):
        self.tickets(5)
        factory = self.factory()
        report = self.run_frontier(factory)
        self.assertTrue(report["passed"], report)
        self.assertFalse(report["publication_verified"])
        self.assertEqual([len(row["frontier"]) for row in report["rounds"]], [2, 2, 1])
        self.assertEqual(len({agent.coordinator_context_id for agent in factory.graphs}), 3)
        self.assertEqual(len(factory.identities), 5)
        self.assertEqual(sum(event["event"] == "task_delegated" for graph in factory.graphs for event in graph.events), 5)
        self.assertTrue(all(len(rows) <= 2 for _, rows in factory.visible))
        for summary in report["rounds"]:
            workspace = Path(summary["workspace"])
            messages = json.loads((workspace/"coordinator-messages.json").read_text(encoding="utf-8"))
            self.assertEqual(sum(message["type"] == "human" for message in messages), 1)
            for message in messages:
                if message["type"] == "ai":
                    for call in message["data"].get("tool_calls", []):
                        if call["name"] == "task":
                            self.assertIn(json.loads(call["args"]["description"])["ticket"],
                                          {row["id"] for row in summary["frontier"]})
            self.assertTrue((workspace/"coordinator-lineage.jsonl").is_file())
            self.assertEqual(len(summary["delegation_proofs"]), len(summary["frontier"]))
            self.assertTrue(summary["passed"])
        self.assertEqual(self.network_attempts, [])

    def test_downstream_dag_ticket_waits_for_new_parent_and_old_accepted_needs_no_new_trace(self):
        old = self.tickets(1)[0]
        lease = self.store.claim(old, "reader", "prior-authentic-context")
        self.store.accept(old, lease["context"], lease["lease"], {"prior": True}, validator=lambda a,b: None)
        self.tickets(1)
        factory = self.factory(dynamic=True)
        report = self.run_frontier(factory)
        self.assertTrue(report["passed"], report)
        self.assertEqual(report["initial_accepted"], 1)
        self.assertEqual([r["frontier"][0]["role"] for r in report["rounds"]], ["reader", "verifier"])
        self.assertEqual(len(factory.identities), 2)
        self.assertNotIn(old, {p["ticket"] for r in report["rounds"] for p in r["delegation_proofs"]})

    def test_return_without_task_is_no_progress_and_cannot_claim_complete(self):
        self.tickets(2)
        factory = self.factory(mode="no_progress")
        report = self.run_frontier(factory)
        self.assertFalse(report["passed"])
        self.assertEqual(report["stop_reason"], "no_progress")
        self.assertEqual(len(report["rounds"]), 1)
        self.assertEqual(factory.identities, [])

    def test_repeated_ready_without_task_stops_instead_of_spinning(self):
        self.tickets(1)
        report = self.run_frontier(self.factory(mode="repeat_ready"))
        self.assertFalse(report["passed"])
        self.assertEqual(report["stop_reason"], "round_error")
        self.assertIn("no progress", report["error"]["message"])
        self.assertEqual(len(report["rounds"]), 1)

    def test_independent_failure_is_preserved_and_next_frontier_not_started(self):
        self.tickets(2, role="verifier")
        factory = self.factory(mode="scientific_failure")
        report = self.run_frontier(factory, size=1)
        self.assertFalse(report["passed"])
        self.assertEqual(len(report["rounds"]), 1)
        self.assertEqual([r["status"] for r in self.store.status()], ["failed", "pending"])
        self.assertEqual(len(factory.identities), 1)

    def test_provider_failure_saves_real_partial_messages_and_lineage(self):
        self.tickets(1)
        report = self.run_frontier(self.factory(mode="provider_failure"))
        self.assertFalse(report["passed"])
        self.assertEqual(report["error"]["message"], "ORIGINAL_PROVIDER_FAILURE")
        workspace = Path(report["rounds"][0]["workspace"])
        self.assertIn("task", (workspace/"coordinator-messages.json").read_text(encoding="utf-8"))
        self.assertIn("worker_failed", (workspace/"coordinator-lineage.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(self.store.status()[0]["status"], "failed")

    def test_forged_receipt_does_not_prove_accepted_store_output(self):
        self.tickets(1)
        report = self.run_frontier(self.factory(bad_receipt=True))
        self.assertFalse(report["passed"])
        self.assertEqual(report["stop_reason"], "missing_native_delegation_proof")
        self.assertEqual(self.store.status()[0]["status"], "accepted", "Preserve real acceptance; report mismatch separately")

    def test_outside_frontier_model_call_is_rejected_before_worker_claim(self):
        tickets = self.tickets(2)
        factory = self.factory(mode="foreign", foreign=tickets[1])
        report = self.run_frontier(factory, size=1)
        self.assertFalse(report["passed"])
        self.assertIn("out-of-frontier", report["error"]["message"])
        self.assertEqual(factory.identities, [])
        self.assertTrue(all(row["status"] == "pending" for row in self.store.status()))

    def test_expired_original_deadline_does_not_build_agent_or_call_model(self):
        self.tickets(1)
        factory = self.factory()
        report = self.run_frontier(factory, deadline=time.monotonic()-1)
        self.assertFalse(report["passed"])
        self.assertEqual(report["stop_reason"], "deadline_exceeded")
        self.assertEqual(factory.graphs, [])

    def test_factory_time_and_all_rounds_share_original_deadline(self):
        self.tickets(6)
        factory = self.factory()
        async def slow_factory(ready, workspace):
            await asyncio.sleep(.35)
            return factory(ready, workspace)
        started = time.monotonic()
        deadline = started+1.3
        report = self.run_frontier(slow_factory, size=1, deadline=deadline)
        self.assertFalse(report["passed"])
        self.assertEqual(report["stop_reason"], "deadline_exceeded")
        self.assertGreaterEqual(sum(r["passed"] for r in report["rounds"]), 1)
        self.assertLess(len(factory.identities), 6)
        self.assertTrue(all(r["deadline_at_monotonic"] == deadline for r in report["rounds"]))
        self.assertLess(time.monotonic()-started, 2.0)

    def test_factory_cannot_predispatch_host_worker(self):
        ticket = self.tickets(1)[0]
        factory = self.factory()
        def bad_factory(ready, workspace):
            self.store.claim(ticket, "reader", "host-predispatch")
            return factory(ready, workspace)
        report = self.run_frontier(bad_factory)
        self.assertFalse(report["passed"])
        self.assertIn("before coordinator inference", report["error"]["message"])
        self.assertEqual(factory.identities, [])

    def test_cancellation_is_recorded_propagated_and_releases_native_worker(self):
        self.tickets(1)
        entered = threading.Event()
        factory = self.factory(delay=.25, entered=entered)
        output = self.root/"cancelled"
        async def cancel():
            running = asyncio.create_task(run_frontiers(self.store, factory, output, time.monotonic()+10))
            self.assertTrue(await asyncio.to_thread(entered.wait, 5))
            running.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await running
        asyncio.run(cancel())
        report = json.loads((output/"frontier-result.json").read_text(encoding="utf-8"))
        self.assertFalse(report["passed"])
        self.assertEqual(report["stop_reason"], "cancelled")
        self.assertEqual(factory.graphs[0].worker_limits["active"], 0)
        self.assertEqual(self.store.status()[0]["status"], "failed")

    def test_scoped_repair_runs_native_tasks_without_hiding_or_changing_old_negative(self):
        failed = self.tickets(1, role="verifier")[0]
        lease = self.store.claim(failed, "verifier", "historical-independent-reviewer")
        self.store.fail(failed, lease["context"], lease["lease"], {"unsupported": True})
        self.tickets(1)  # obsolete pending task must not block this exact revision stage
        historical = self.store.status()
        selected = self.tickets(2, role="writer")
        view = ScopedTaskStore(self.store, selected)
        factory = self.factory()
        report = asyncio.run(run_frontiers(view, factory, self.root/"scoped-repair", time.monotonic()+20, frontier_size=1))
        self.assertTrue(report["passed"], report)
        self.assertEqual(len(factory.identities), 2)
        self.assertEqual({row["id"] for row in report["tasks"]}, set(selected))
        self.assertEqual(self.store.status()[:2], historical)


if __name__ == "__main__":
    unittest.main()
