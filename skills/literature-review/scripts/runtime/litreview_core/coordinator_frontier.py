"""Rotate real native coordinators at durable, bounded DAG frontiers.

The host selects tickets and creates fresh parents; it never invokes a worker,
claims a lease, or accepts research output. ``agent_factory(ready_tasks, path)``
must return ``create_review_agent(...)`` with the supplied tool installed. Share
the caller's governor/model configuration across factories. This module neither
creates nor closes the caller's transport, governor, or store.

An accepted frontier proves execution of existing tickets, not publication
quality or the existence of every intended downstream stage. The application
must predeclare its DAG or create downstream tickets in native acceptance and
must separately check its complete scientific/publication proof contract.
"""
from __future__ import annotations

import asyncio
from collections import Counter
import inspect
import json
import math
import os
from pathlib import Path
import threading
import time
from uuid import uuid4

from langchain.tools import tool
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import HumanMessage, messages_to_dict

from .native_agent import NativeReviewAgent


class FrontierError(RuntimeError):
    """A frontier cannot safely continue."""


def _write(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _public_rows(rows):
    # Lease nonces are unnecessary in reports; retain immutable identities.
    fields = ("id", "role", "input_hash", "status", "context", "output_hash", "attempt", "error")
    return [{key: row.get(key) for key in fields} for row in rows]


def _ticket(description):
    request = json.loads(description)
    if not isinstance(request, dict) or set(request) != {"ticket"} or not isinstance(request["ticket"], str):
        raise FrontierError("Task description must contain exactly one ticket string")
    return request["ticket"]


class _FrontierGuard(BaseCallbackHandler):
    """Reject out-of-frontier model task calls before native tool execution."""
    run_inline = True
    raise_error = True

    def __init__(self, allowed, context_id, deadline_at):
        self.allowed, self.context_id, self.deadline_at = allowed, context_id, deadline_at
        self.parent_runs, self.delegated = set(), set()
        self.lock = threading.Lock()

    def on_chat_model_start(self, serialized, messages, *, run_id, metadata=None, **kwargs):
        if time.monotonic() >= self.deadline_at:
            raise TimeoutError("Original workflow deadline expired")
        metadata = metadata or {}
        if metadata.get("coordinator_context_id") == self.context_id and not metadata.get("worker_context_id"):
            with self.lock:
                self.parent_runs.add(str(run_id))

    def on_llm_end(self, response, *, run_id, **kwargs):
        with self.lock:
            if str(run_id) not in self.parent_runs:
                return
            for generations in response.generations:
                for generation in generations:
                    for call in getattr(getattr(generation, "message", None), "tool_calls", ()):
                        if call.get("name") != "task":
                            continue
                        args = call.get("args", {})
                        ticket = _ticket(args.get("description", ""))
                        if ticket not in self.allowed or args.get("subagent_type") != self.allowed[ticket]:
                            raise FrontierError("Coordinator attempted an out-of-frontier ticket or role")
                        if ticket in self.delegated:
                            raise FrontierError("Coordinator attempted to delegate a frontier ticket twice")
                        self.delegated.add(ticket)


def _proof(agent, rows, allowed):
    """Bind accepted store artifacts to actual parent AI task calls and children."""
    events = agent.events
    calls, delegated, accepted, finished, returned = {}, {}, {}, set(), set()
    for event in events:
        kind = event.get("event")
        if kind == "model_response" and event.get("role") == "coordinator":
            for call in event.get("tool_calls") or ():
                if call.get("name") == "task":
                    calls[call["id"]] = (event, call)
        elif kind == "task_delegated":
            delegated[event["task_tool_call_id"]] = event
        elif kind == "worker_accepted":
            accepted[event["identity"]["context_id"]] = event
        elif kind == "worker_finished" and event.get("status") == "accepted":
            finished.add(event["identity"]["context_id"])
        elif kind == "task_returned":
            returned.add(event["task_tool_call_id"])
    result, errors = [], []
    for row in rows:
        if row["id"] not in allowed or row["status"] != "accepted":
            continue
        event = accepted.get(row["context"])
        try:
            if event is None:
                raise FrontierError("Missing native worker_accepted event")
            identity, receipt = event["identity"], event["receipt"]
            call_id = identity["task_tool_call_id"]
            parent, call = calls[call_id]
            delegation = delegated[call_id]
            native = receipt["result"]
            if not (identity["context_id"] in finished and call_id in returned
                    and receipt.get("accepted") is True and receipt.get("status") == "accepted"
                    and identity["coordinator_context_id"] == agent.coordinator_context_id
                    and parent["context_id"] == agent.coordinator_context_id
                    and identity["parent_model_message_id"] == parent["message_id"]
                    and delegation["parent_model_message_id"] == parent["message_id"]
                    and delegation["coordinator_context_id"] == agent.coordinator_context_id
                    and _ticket(call["args"]["description"]) == row["id"]
                    and _ticket(delegation["description"]) == row["id"]
                    and call["args"]["subagent_type"] == row["role"] == identity["role"]
                    and all(native.get(key) == row[field] for key, field in (
                        ("ticket", "id"), ("context", "context"), ("input_hash", "input_hash"),
                        ("output_hash", "output_hash"), ("status", "status")))):
                raise FrontierError("Native task/child/artifact receipt mismatch")
            result.append({"ticket": row["id"], "role": row["role"], "context_id": row["context"],
                           "coordinator_context_id": agent.coordinator_context_id,
                           "task_tool_call_id": call_id, "parent_model_message_id": parent["message_id"],
                           "parent_response_id": parent.get("response_id"), "input_hash": row["input_hash"],
                           "output_hash": row["output_hash"]})
        except (KeyError, TypeError, ValueError, FrontierError) as exc:
            errors.append({"ticket": row["id"], "type": type(exc).__name__, "message": str(exc)})
    return result, errors


async def run_frontiers(store, agent_factory, output, deadline_at, frontier_size=16, *, config=None):
    """Run fixed ready snapshots through fresh actual DeepAgents coordinators.

    ``deadline_at`` is the caller's ORIGINAL absolute ``time.monotonic()``
    deadline. It is never reset. ``output`` must be a new directory. The factory
    may be synchronous or async, must only construct the native agent, and must
    install the supplied ``ready_tasks`` tool. It must not dispatch/claim work.
    Every round gets a fresh input message and fresh thread/context identity;
    previous messages, worker sources and scientific prose are never copied.

    Returns a JSON-compatible report; any operational/no-progress/failed-task
    outcome has ``passed=False``. External cancellation is recorded then raised.
    This module deliberately does not retry scientific failures or reset leases.
    """
    if type(frontier_size) is not int or not 1 <= frontier_size <= 100:
        raise ValueError("frontier_size must be an integer in 1..100")
    if isinstance(deadline_at, bool) or not isinstance(deadline_at, (int, float)) or not math.isfinite(deadline_at):
        raise ValueError("deadline_at must be a finite absolute monotonic time")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    (output / "rounds").mkdir()
    started, initial = time.monotonic(), store.status()
    report = {"schema": "native-coordinator-frontiers/1", "passed": False,
              "completed_all_existing_tasks": False, "publication_verified": False,
              "completion_scope": "Existing durable tickets only; caller must check its full scientific DAG/proof contract.",
              "deadline_at_monotonic": deadline_at, "frontier_size": frontier_size,
              "initial_tasks": len(initial), "initial_accepted": sum(row["status"] == "accepted" for row in initial),
              "rounds": [], "stop_reason": None, "error": None}
    context_ids = set()

    def save():
        rows = store.status()
        report.update(tasks=_public_rows(rows), counts=dict(Counter(row["status"] for row in rows)),
                      elapsed_seconds=time.monotonic() - started,
                      remaining_seconds=max(0.0, deadline_at - time.monotonic()))
        _write(output / "frontier-result.json", report)

    try:
        while True:
            if time.monotonic() >= deadline_at:
                report["stop_reason"] = "deadline_exceeded"
                break
            before = store.status()
            if not before:
                report["stop_reason"] = "empty_store"
                break
            if any(row["status"] == "failed" for row in before):
                report["stop_reason"] = "failed_task"
                break
            if all(row["status"] == "accepted" for row in before):
                report.update(passed=True, completed_all_existing_tasks=True, stop_reason="all_existing_tasks_accepted")
                break
            frontier = store.ready(frontier_size)
            if not frontier:
                report["stop_reason"] = "no_ready_tasks"
                break
            allowed = {row["id"]: row["role"] for row in frontier}
            before = store.status()  # includes any lease expiry performed by ready()
            number = len(report["rounds"]) + 1
            workspace = output / "rounds" / f"round-{number:04d}"
            workspace.mkdir()
            round_started, agent, latest = time.monotonic(), None, {"messages": []}
            summary = {"round": number, "workspace": str(workspace), "frontier": frontier,
                       "deadline_at_monotonic": deadline_at, "remaining_seconds_at_start": deadline_at-round_started,
                       "passed": False, "error": None, "delegation_proofs": [], "proof_errors": []}
            report["rounds"].append(summary)
            last_ready_snapshot = [None]
            ready_lock = threading.Lock()

            @tool
            def ready_tasks() -> dict:
                """Return ONLY this parent's fixed frontier. Delegate the exact JSON tickets with task, then stop when frontier_complete is true."""
                rows = [row for row in store.status() if row["id"] in allowed]
                snapshot = [(row["id"], row["status"], row["attempt"], row["output_hash"]) for row in rows]
                complete = all(row["status"] == "accepted" for row in rows)
                if any(row["status"] == "failed" for row in rows):
                    raise FrontierError("A frontier task failed; stop without retrying its scientific verdict")
                with ready_lock:
                    if not complete and snapshot == last_ready_snapshot[0]:
                        raise FrontierError("Coordinator made no progress between ready_tasks calls")
                    last_ready_snapshot[0] = snapshot
                return {"ready": [{"subagent_type": row["role"], "description": json.dumps({"ticket": row["id"]})}
                                  for row in rows if row["status"] == "pending"],
                        "counts": dict(Counter(row["status"] for row in rows)),
                        "frontier_size": len(allowed), "frontier_complete": complete, "stop_after_frontier": True}

            try:
                agent = agent_factory(ready_tasks, workspace)
                if inspect.isawaitable(agent):
                    agent = await asyncio.wait_for(agent, timeout=max(0.0, deadline_at-time.monotonic()))
                if not isinstance(agent, NativeReviewAgent):
                    raise FrontierError("Factory must return create_review_agent's NativeReviewAgent")
                if store.status() != before or any(event.get("event") in {"model_response", "task_delegated", "worker_started"}
                                                  for event in agent.events):
                    raise FrontierError("Agent factory dispatched or mutated tasks before coordinator inference")
                if agent.coordinator_context_id in context_ids:
                    raise FrontierError("Each frontier requires a fresh coordinator context identity")
                context_ids.add(agent.coordinator_context_id)
                if not agent.log.path.resolve().is_relative_to(workspace):
                    raise FrontierError("Native lineage must be saved inside this round workspace")
                summary["coordinator_context_id"] = agent.coordinator_context_id
                summary["native_lineage_path"] = str(agent.log.path)
                remaining = deadline_at-time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Original workflow deadline expired during coordinator construction")
                run_config = dict(config or {})
                guard = _FrontierGuard(allowed, agent.coordinator_context_id, deadline_at)
                callbacks = run_config.get("callbacks")
                if callbacks is None or isinstance(callbacks, list):
                    run_config["callbacks"] = [*(callbacks or []), guard]
                elif hasattr(callbacks, "copy") and hasattr(callbacks, "add_handler"):
                    callbacks = callbacks.copy()
                    callbacks.add_handler(guard, inherit=True)
                    run_config["callbacks"] = callbacks
                else:
                    raise FrontierError("Unsupported callback configuration")
                run_config["configurable"] = {**run_config.get("configurable", {}), "thread_id": agent.coordinator_context_id}
                run_config.setdefault("recursion_limit", max(40, frontier_size*8))

                async def drive():
                    nonlocal latest
                    async for state in agent.astream({"messages": [HumanMessage(content=
                        "Use ready_tasks, then delegate every returned ticket through the native task tool to its specified role. "
                        "Use the exact description JSON, issue independent task calls in parallel, and never perform a worker's research yourself. "
                        "This parent owns only the fixed frontier. Call ready_tasks after task receipts and stop when frontier_complete is true. "
                        "Do not request later tickets or claim that ticket acceptance proves a completed literature review.")]},
                        run_config, stream_mode="values"):
                        latest = state
                        _write(workspace / "coordinator-messages.json", messages_to_dict(state.get("messages", [])))

                await asyncio.wait_for(drive(), timeout=remaining)
                after = store.status()
                proofs, errors = _proof(agent, after, allowed)
                summary.update(delegation_proofs=proofs, proof_errors=errors)
                accepted_before = {row["id"] for row in before if row["status"] == "accepted"}
                new_accepted = {row["id"] for row in after if row["status"] == "accepted"} - accepted_before
                if new_accepted - allowed.keys():
                    report["stop_reason"] = "out_of_frontier_progress"
                elif any(row["status"] == "failed" for row in after):
                    report["stop_reason"] = "failed_task"
                elif errors or len(proofs) != len(allowed):
                    report["stop_reason"] = "missing_native_delegation_proof" if errors else (
                        "no_progress" if not new_accepted else "frontier_incomplete")
                elif time.monotonic() >= deadline_at:
                    report["stop_reason"] = "deadline_exceeded"
                else:
                    summary["passed"] = True
            except asyncio.CancelledError:
                report["stop_reason"] = "cancelled"
                summary["error"] = {"type": "CancelledError", "message": "Caller cancelled the workflow"}
                raise
            except Exception as exc:
                summary["error"] = {"type": type(exc).__name__, "message": str(exc)}
                report["error"] = summary["error"]
                report["stop_reason"] = "deadline_exceeded" if isinstance(exc, TimeoutError) else "round_error"
            finally:
                summary["elapsed_seconds"] = time.monotonic()-round_started
                summary["tasks_after"] = _public_rows(store.status())
                _write(workspace / "coordinator-messages.json", messages_to_dict(latest.get("messages", [])))
                if isinstance(agent, NativeReviewAgent):
                    # Raw native-lineage.jsonl is also retained incrementally.
                    lineage = "".join(json.dumps(event, ensure_ascii=False, allow_nan=False)+"\n" for event in agent.events)
                    (workspace / "coordinator-lineage.jsonl").write_text(lineage, encoding="utf-8")
                    summary["worker_limits"] = agent.worker_limits
                _write(workspace / "round-result.json", summary)
                save()
            if not summary["passed"]:
                break
    finally:
        save()
    return report
