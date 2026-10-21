"""Prepare or explicitly run paired Qwen verifier reasoning quality controls.

Preparation is local and is the default. --execute opts into remote model calls.
Original synthetic10 Markdown is required; gold.json is never read. The assigned
sources are complete, short synthetic micro-papers made from exact source
sentences, not representations of full reading of the original ten-page papers.
Expected labels stay outside every model's assigned input and filesystem root.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import random
import re
import statistics
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/literature-review/scripts/runtime"))

from litreview_core.scientific_records import FIELDS, source_packet, validate_reader
from litreview_core.record_review import record_projection
from litreview_core.task_store import canonical


QUESTIONS = [
    {"id": "q1", "text": "What tested contrast and findings are stated in the supplied synthetic micro-paper?"},
    {"id": "q2", "text": "Which uncertainty, missing measurements, adverse results or persistent failures qualify its findings?"},
]
# Match native_reading's verifier instruction; source scope is explicitly supplied
# by the micro-paper itself, rather than adding expected-case hints to this task.
VERIFIER_INSTRUCTION = (
    "Use the scientific-record-review/1 profile and typed tool. "
    "Independently read the complete original source, then verify every finding in the record. "
    "Also inspect important omissions: adverse/null results, persistent failures after mitigation, "
    "unmeasured quantities, study design and applicability. Individual true statements do not excuse "
    "a missing qualification. Return honest unsupported/needs_revision when appropriate; do not rewrite "
    "the record or treat structural validation as scientific approval.")
VERIFIER_PARAMETERS = {"max_tokens": 16384, "reasoning_max_tokens": 2048,
                       "temperature": .1, "force_submit": True, "profile": "verifier"}


def _fact(local_id, field, anchors, topic, obligations=()):
    return {"local_id": local_id, "field": field, "anchors": anchors,
            "topic": topic, "obligations": list(obligations)}


SOURCE_FACTS = {
    "s04": [
        _fact("f_design", "method", ["The study uses a randomized crossover experiment with balanced query order."], "Describes assignment and query-order design."),
        _fact("f_effect", "results", ["The aggregate comparison estimates an intervention-minus-baseline difference of +0.019 in answer F1, with a ninety-five percent confidence interval from -0.006 to +0.044."], "Reports the aggregate F1 contrast and its interval.", ["null_result"]),
        _fact("f_boundary", "limitations", ["The interval includes zero, so this analysis does not establish a clear aggregate improvement."], "Qualifies the aggregate improvement interpretation.", ["null_result", "critical_limitation"]),
    ],
    "s03": [
        _fact("f_design", "method", ["The study uses a cluster-randomized controlled experiment."], "Describes cluster assignment."),
        _fact("f_cost", "limitations", ["Monetary cost was not measured in either condition."], "States the monetary accounting boundary.", ["missing_measurement"]),
        _fact("f_energy", "limitations", ["The study did not measure energy consumption."], "States the energy-measurement boundary.", ["missing_measurement"]),
    ],
    "s02": [
        _fact("f_design", "method", ["The study uses a observational before-and-after comparison."], "Describes observational comparison design."),
        _fact("f_effect", "results", ["The aggregate comparison estimates an intervention-minus-baseline difference of +0.048 in nDCG@10, with a ninety-five percent confidence interval from +0.012 to +0.084."], "Reports the observed nDCG contrast and its interval."),
        _fact("f_boundary", "limitations", ["The nonrandom design permits residual confounding, so the observed association does not establish that the intervention caused the difference."], "Explains the causal interpretation boundary.", ["critical_limitation"]),
    ],
    "s07": [
        _fact("f_design", "method", ["The study uses a observational interrupted time-series study."], "Describes interrupted time-series design."),
        _fact("f_effect", "results", ["The aggregate comparison estimates an intervention-minus-baseline difference of -0.062 in stale-answer rate, with a ninety-five percent confidence interval from -0.089 to -0.035."], "Reports aggregate stale-answer contrast and interval."),
        _fact("f_failure", "unexpected_findings", ["The unexpected finding was the persistence of a burst of uncached requests immediately after invalidation despite the addition of dependency-specific warm-up queues."],
              "Describes uncached-request behavior after invalidation and warm-up queues.", ["persistent_failure"]),
        _fact("f_cost", "limitations", ["Monetary cost was not measured in either condition."], "States the accounting boundary.", ["missing_measurement"]),
    ],
    "s08": [
        _fact("f_design", "method", ["The study uses a randomized query-pair controlled experiment."], "Describes query-pair assignment."),
        _fact("f_effect", "results", ["The aggregate comparison estimates an intervention-minus-baseline difference of +0.047 in Recall@5, with a ninety-five percent confidence interval from +0.018 to +0.076."], "Reports the aggregate Recall@5 contrast and interval."),
        _fact("f_subgroup", "results", ["The prespecified subgroup consists of adversarial near-synonym queries.",
                "The subgroup contrast was -0.039, with a ninety-five percent confidence interval from -0.074 to -0.004.", "The subgroup interval excludes zero in the adverse direction, providing explicit evidence of worse subgroup performance."],
              "Reports the specified near-synonym subgroup and uncertainty.", ["adverse_result"]),
        _fact("f_failure", "unexpected_findings", ["The unexpected finding was the persistence of mapping a near-synonym to a semantically adjacent but wrong concept despite the addition of explicit negative concept constraints."],
              "Describes concept mapping under explicit negative concept constraints.", ["persistent_failure"]),
        _fact("f_missing", "limitations", ["The study did not measure downstream clinical utility."],
              "States the clinical-utility measurement boundary.", ["missing_measurement"]),
    ],
}
NEGATIVES = (
    ("ci_significance", "s04", "f_effect", "The intervention produced a statistically significant improvement in answer F1; the 95% confidence interval excludes zero."),
    ("unmeasured_zero", "s03", "f_cost", "Monetary cost was measured as USD 0 per query in both conditions."),
    ("observational_causality", "s02", "f_effect", "The intervention caused the +0.048 improvement in nDCG@10, establishing a causal effect."),
    ("universal_subgroups", "s08", "f_effect", "Controlled-vocabulary bridging improved Recall@5 in every evaluated query subgroup, without adverse subgroup effects."),
    ("persistent_failure_s07", "s07", "f_failure", None),
    ("persistent_failure_s08", "s08", "f_failure", None),
)


@dataclass(frozen=True)
class ControlCase:
    case_id: str
    source: dict
    record: dict
    expected: dict
    provenance: dict

    def assigned_inputs(self):
        # Deliberate whitelist: expected/provenance never enter an agent input.
        return {"source.json": self.source, "record.json": record_projection(self.source, self.record)}

    @property
    def workload_hash(self):
        return sha256(canonical({"inputs": self.assigned_inputs(), "instruction": VERIFIER_INSTRUCTION})).hexdigest()


def extract_sentence(raw, anchor):
    text = raw.decode("utf-8")
    sentences = [sentence for paragraph in re.split(r"\r?\n\s*\r?\n", text)
                 if not paragraph.startswith(("#", "|"))
                 for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z])", paragraph.strip())]
    matches = sorted({sentence for sentence in sentences if anchor in sentence}, key=lambda value: (len(value), value))
    if not matches:
        raise ValueError("Required original synthetic source statement unavailable: " + anchor)
    value = matches[0]
    begin = len(text[:text.index(value)].encode("utf-8"))
    return value, {"start_byte": begin, "end_byte": begin + len(value.encode("utf-8")),
                   "quote_sha256": sha256(value.encode("utf-8")).hexdigest()}


def build_cases(sources, *, paired_positives=False):
    """Create valid unverified records and separate host-only expected labels."""
    sources = Path(sources).resolve()
    prepared = {}
    for study, definitions in SOURCE_FACTS.items():
        original = sources / (study + ".md")
        raw = original.read_bytes()
        facts, fragments = [], []
        for definition in definitions:
            statements = [extract_sentence(raw, anchor) for anchor in definition["anchors"]]
            facts.append({**definition, "text": " ".join(value for value, _ in statements)})
            fragments.extend({"local_id": definition["local_id"], **span} for _, span in statements)
        intro = ("SYNTHETIC MICRO-PAPER. This is the complete supplied miniature source, with no real publication claim. "
                 "Its substantive statements are selected unchanged sentences from an authored synthetic benchmark. "
                 "The original full paper is not supplied here and is not represented as fully read.")
        content = intro + "\n\n" + "\n\n".join(fact["text"] for fact in facts) + "\n"
        paper_id = "micro-" + sha256(content.encode()).hexdigest()[:16]
        packet = source_packet(paper_id, content.encode("utf-8"), QUESTIONS)
        for fact in facts:
            fact["part_id"] = next(part["part_id"] for part in packet["parts"] if part["text"].strip() == fact["text"])
        prepared[study] = (packet, facts, {"source_path": str(original), "source_sha256": sha256(raw).hexdigest(),
                                          "original_fragments": fragments,
                                          "scope": "Complete short synthetic source; not original ten-page full-paper verification"})

    def make_case(kind, study, target, changed_text, positive=False):
        packet, definitions, provenance = prepared[study]
        case_id = "case_" + sha256(canonical([kind, study, positive])).hexdigest()[:16]
        findings = []
        for fact in definitions:
            if not positive and fact["local_id"] == target and changed_text is None:
                continue
            findings.append({"local_id": fact["local_id"], "field": fact["field"],
                "text": changed_text if not positive and fact["local_id"] == target else fact["text"],
                "attribution": "author_limitation" if fact["field"] == "limitations" else "author_result",
                "evidence": [{"part_id": fact["part_id"], "quote": None}],
                "obligations": [] if not positive and fact["local_id"] == target else list(fact["obligations"])})
        assessed_fields = {fact["field"] for fact in findings}
        caveats = [fact["local_id"] for fact in findings if fact["obligations"] or fact["field"] in {"limitations", "unexpected_findings"}]
        principal = [fact["local_id"] for fact in findings if fact["field"] in {"method", "results"}]
        topics = {fact["part_id"]: fact["topic"] for fact in definitions}
        submission = {"observations": [{"part_id": part["part_id"], "note": topics.get(part["part_id"],
            "Defines the miniature synthetic source and its limited publication scope.")} for part in packet["parts"]],
            "findings": findings,
            "fields": [{"field": field, "status": "extracted" if field in assessed_fields else "not_reported",
                        "reason": "Source-linked findings retained." if field in assessed_fields else
                                  "Not stated in this complete, limited-scope miniature source."} for field in FIELDS],
            "questions": [{"question_id": "q1", "status": "addressed" if principal else "not_addressed",
                           "reason": "The supplied source states the listed design/findings.", "support": principal, "counterevidence": caveats},
                          {"question_id": "q2", "status": "addressed" if caveats else "not_addressed",
                           "reason": "The listed qualifications are stated in the supplied source.", "support": caveats, "counterevidence": []}]}
        record = validate_reader(packet, submission, execution_id="host-control-fixture-author-" + case_id)
        target_part = next(fact["part_id"] for fact in definitions if fact["local_id"] == target)
        expected = {"kind": "positive" if positive else kind,
                    "expected_status": "passed" if positive else "needs_revision",
                    "target_finding_id": None if positive or changed_text is None else target,
                    "omitted_part_id": target_part if not positive and changed_text is None else None,
                    "paired_negative_kind": kind if positive else None}
        return ControlCase(case_id, packet, record, expected, provenance)

    result = [make_case(*spec) for spec in NEGATIVES]
    positives = list(NEGATIVES) if paired_positives else [NEGATIVES[-1]]
    result.extend(make_case(*spec, positive=True) for spec in positives)
    return result


def grade_review(case, review):
    """Grade target localization as well as overall status, without model hints."""
    if not review:
        return {"completed_judgment": False, "correct": False, "reason": "No complete independently validated judgment"}
    expected = case.expected
    verdicts = {item["finding_id"]: item["status"] for item in review["verdicts"]}
    if expected["expected_status"] == "passed":
        correct = review["status"] == "passed"
    elif expected["target_finding_id"]:
        correct = review["status"] == "needs_revision" and verdicts.get(expected["target_finding_id"]) in {
            "partially_supported", "unsupported", "contradicted", "uncertain"}
    else:
        correct = (review["status"] == "needs_revision" and review["omission_check"] == "needs_revision"
            and any(issue["kind"] in {"important_omission", "missing_obligation", "incorrect_condition"}
                and expected["omitted_part_id"] in issue["part_ids"] for issue in review["issues"]))
    return {"completed_judgment": True, "correct": bool(correct), "expected_status": expected["expected_status"],
            "observed_status": review["status"], "target_finding_status": verdicts.get(expected["target_finding_id"]),
            "explanation_semantically_audited": False,
            "grading_scope": "Structured verdict/omission localization; explanations remain available for manual source review"}


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def transport_metrics(telemetry, events):
    """Keep actual reported reasoning/cost/provider behavior separate from intent."""
    roles = {event["response_id"]: event["role"] for event in events
             if event["event"] == "model_response" and event.get("response_id")}
    requests = telemetry.get("events", [])
    verifier = [row for row in requests if roles.get(row.get("response_id")) == "verifier"]

    def summarize(rows):
        cost, missing_cost, reasoning = 0.0, 0, 0
        for row in rows:
            usage = row.get("usage") or {}
            amount = usage.get("cost")
            if isinstance(amount, (int, float)):
                cost += amount
            else:
                missing_cost += 1
            reasoning += (usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0) or 0
        return {"responses_with_transport_events": len(rows), "recorded_cost_usd": round(cost, 8),
                "responses_missing_cost": missing_cost, "reported_reasoning_tokens": reasoning,
                "providers": dict(Counter(row.get("provider") or "unknown" for row in rows))}
    return {"all_roles": summarize(requests), "verifier": summarize(verifier),
            "transport_events_without_role_match": sum(row.get("response_id") not in roles for row in requests),
            "cost_scope": "Recorded usage.cost only; missing or ambiguous charges are not assumed zero",
            "verifier_finish_reasons": dict(Counter(event.get("metadata", {}).get("finish_reason", "unknown")
                for event in events if event["event"] == "model_response" and event["role"] == "verifier"))}


def prepare_artifacts(cases, output):
    output = Path(output)
    for case in cases:
        _write(output / "public-fixtures" / case.case_id / "source.json", case.source)
        _write(output / "public-fixtures" / case.case_id / "record.json", case.record)
    _write(output / "expected.host-only.json", {case.case_id: case.expected for case in cases})
    manifest = {"scope": "Short complete synthetic-source controls, not full ten-page paper verification",
                "gold_json_read": False, "expected_labels_delivered_to_models": False,
                "fixture_writer": "deterministic host author; no fabricated model writer identity",
                "cases": [{"case_id": case.case_id, "workload_hash": case.workload_hash,
                           "source_bytes": sum(len(part["text"].encode()) for part in case.source["parts"]),
                           "findings": len(case.record["findings"]), "provenance": case.provenance} for case in cases]}
    _write(output / "controls-manifest.json", manifest)
    return manifest


async def run_arm(args, cases, output, *, reasoning_enabled, repetition, model_factory=None, counter=None):
    """Execute actual native coordinator/task/verifier graphs; injectable offline."""
    from langchain.tools import tool
    from langchain_core.messages import HumanMessage, messages_to_dict
    from pydantic import BaseModel, field_validator
    from litreview_core.native_agent import WorkerTask, create_review_agent
    from litreview_core.record_review import RecordReviewSubmission, RecordReviewFailure, validate_record_review
    from litreview_core.task_store import TaskStore
    from litreview_core.request_governor import RequestGovernor, ThroughputConfig
    from litreview_core.resource_monitor import ResourceMonitor
    from litreview_core.qwen_tokens import QwenRequestCounter
    from litreview_core.qwen_transport import create_model, aclose_http_clients, close_http_clients

    class ReviewArguments(BaseModel):
        data: RecordReviewSubmission

        @field_validator("data", mode="before")
        @classmethod
        def decode_data(cls, value):
            return json.loads(value) if isinstance(value, str) else value

    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    counter = counter or QwenRequestCounter(args.tokenizer)
    governor = RequestGovernor(ThroughputConfig(workers=args.workers, minimum_workers=1,
        deadline_seconds=args.deadline, token_counter=counter))
    store = TaskStore(output / "artifacts")
    ordered = list(cases)
    random.Random(args.seed + repetition).shuffle(ordered)
    ticket_cases, reviews, lock = {}, {}, threading.RLock()
    for case in ordered:
        ticket = store.create("verifier", {"source": case.source, "record": case.record}, max_attempts=1)
        ticket_cases[ticket] = case

    @tool
    def ready_tasks() -> dict:
        """Get opaque ready tickets and counts; scientific verdicts must remain independent."""
        ready = store.ready(args.workers)
        statuses = store.status()
        return {"ready": [{"subagent_type": row["role"], "description": json.dumps({"ticket": row["id"]})} for row in ready],
                "counts": {state: sum(row["status"] == state for row in statuses)
                           for state in ("pending", "running", "accepted", "failed")}}

    def worker_factory(identity, description):
        ticket = json.loads(description)["ticket"]
        lease = store.claim(ticket, identity.role, identity.context_id)
        case, detail = ticket_cases[ticket], {}

        def accept(data, supplied_identity):
            try:
                review = validate_record_review(case.source, case.record, data, execution_id=supplied_identity.context_id)
            except RecordReviewFailure as error:
                with lock:
                    reviews[case.case_id] = error.review
                detail["review_hash"] = store.put(error.review)
                raise
            with lock:
                reviews[case.case_id] = review
            return store.accept(ticket, supplied_identity.context_id, lease["lease"], review, validator=lambda a, b: None)

        def finish(supplied_identity, receipt):
            if not receipt.get("accepted"):
                store.fail(ticket, supplied_identity.context_id, lease["lease"],
                           {"reason": receipt.get("error", receipt.get("reason", "incomplete")), **detail})
        return WorkerTask(VERIFIER_INSTRUCTION, case.assigned_inputs(), accept,
                          submission_schema=ReviewArguments, max_model_calls=3,
                          skill_documents=("SKILL.md", "references/scientific-record-review.md"), on_finish=finish)

    provider = {"order": [args.provider], "allow_fallbacks": False} if args.provider else None
    factory = model_factory or create_model
    verifier_parameters = {**VERIFIER_PARAMETERS, "reasoning_enabled": reasoning_enabled}
    if not reasoning_enabled:
        verifier_parameters.pop("reasoning_max_tokens")

    def worker_model(identity):
        return factory(governor=governor, provider_preferences=provider, **verifier_parameters)

    agent = create_review_agent(factory(governor=governor, reasoning_enabled=True, max_tokens=4096,
                    reasoning_max_tokens=1024, provider_preferences=provider), output / "agents", args.skills_root,
                    worker_factory=worker_factory, worker_model_factory=worker_model,
                    coordinator_tools=[ready_tasks], max_concurrency=args.workers,
                    coordinator_prompt="This invocation is a bounded independent-record-review benchmark. "
                        "Call ready_tasks and delegate every returned ticket to its specified verifier role. "
                        "Continue until no pending/running tickets remain. Each task may honestly accept or require revision; "
                        "do not ask a verifier to change its verdict or commission writer repairs. "
                        "Do not perform other literature-review stages or claim publication verification.")
    monitor, error = ResourceMonitor(), None
    try:
        result = await asyncio.wait_for(agent.ainvoke({"messages": [HumanMessage(content=
            "Use ready_tasks and delegate the independent verification tickets. Preserve all honest judgments.")]},
            {"recursion_limit": max(60, len(cases) * 8)}), timeout=args.deadline)
        _write(output / "coordinator-messages.json", messages_to_dict(result["messages"]))
    except Exception as exc:
        error = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        governor.close()
        await aclose_http_clients()
        close_http_clients()
        resources = monitor.close()
    outcomes = [{"case_id": case.case_id, "expected_host_only": case.expected,
                 "workload_hash": case.workload_hash, "review": reviews.get(case.case_id),
                 "grade": grade_review(case, reviews.get(case.case_id))} for case in cases]
    complete = all(row["grade"]["completed_judgment"] for row in outcomes) and error is None
    passed = complete and all(row["grade"]["correct"] for row in outcomes)
    telemetry = governor.finish(completed=passed)
    actual_metrics = transport_metrics(telemetry, agent.events)
    response_roles = {event["response_id"]: event["role"] for event in agent.events
                      if event["event"] == "model_response" and event.get("response_id")}
    verifier_events = [event for event in telemetry.get("events", []) if response_roles.get(event.get("response_id")) == "verifier"]
    positives = [row for row in outcomes if row["expected_host_only"]["expected_status"] == "passed"]
    negatives = [row for row in outcomes if row["expected_host_only"]["expected_status"] != "passed"]
    record = {"scope": "Reasoning quality tradeoff on complete short synthetic micro-papers; not a full literature review",
        "publication_verified": False, "repetition": repetition, "reasoning_enabled_requested": reasoning_enabled,
        "coordinator_reasoning_enabled_requested": True, "verifier_parameters": verifier_parameters,
        "submission_schema_sha256": sha256(canonical(ReviewArguments.model_json_schema())).hexdigest(),
        "requested_provider": args.provider, "passed": passed, "all_judgments_completed": complete,
        "elapsed_seconds": time.monotonic() - started, "error": error,
        "negative_detection": {"correct": sum(row["grade"]["correct"] for row in negatives), "total": len(negatives)},
        "positive_acceptance": {"correct": sum(row["grade"]["correct"] for row in positives), "total": len(positives)},
        "verifier_request_seconds": [event.get("request_seconds") for event in verifier_events],
        "verifier_request_mean_seconds": statistics.mean(event["request_seconds"] for event in verifier_events) if verifier_events else None,
        "worker_limits": agent.worker_limits, "cases": outcomes, "tasks": store.status(),
        "actual_transport_metrics": actual_metrics,
        "reasoning_disabled_but_verifier_reported_reasoning": not reasoning_enabled
            and actual_metrics["verifier"]["reported_reasoning_tokens"] > 0,
        "reasoning_compliance_incomplete_due_to_unmatched_events": actual_metrics["transport_events_without_role_match"] > 0,
        "telemetry": telemetry, "resources": resources,
        "comparison_caveats": ["Requested reasoning may not match provider behavior; inspect actual usage and finish reasons.",
            "Transport/schema/output-limit failures remain incomplete, never successful scientific controls.",
            "Fresh isolated agent contexts do not imply cold provider prompt caches.",
            "A small deterministic control set cannot establish equivalence or full-paper omission accuracy.",
            "Changed providers or quota conditions confound latency differences; preserve actual response metadata."],
        "expected_labels_delivered_to_models": False}
    _write(output / "arm-result.json", record)
    return record


async def execute(args, cases):
    modes = [True, False] if args.reasoning == "both" else [args.reasoning == "enabled"]
    arms = []
    for repetition in range(args.repetitions):
        order = modes if repetition % 2 == 0 else list(reversed(modes))
        for enabled in order:
            name = f"rep-{repetition+1:02}-reasoning-{'enabled' if enabled else 'disabled'}"
            arms.append(await run_arm(args, cases, args.out / name, reasoning_enabled=enabled, repetition=repetition))
    report = {"scope": "Verifier-only reasoning comparison; coordinator reasoning remains enabled",
        "production_defaults_changed": False, "publication_verified": False,
        "arms": [{key: arm[key] for key in ("repetition", "reasoning_enabled_requested", "passed", "all_judgments_completed",
                   "elapsed_seconds", "negative_detection", "positive_acceptance", "verifier_request_mean_seconds",
                   "actual_transport_metrics", "error")} for arm in arms],
        "all_controls_correct_in_every_arm": all(arm["passed"] for arm in arms),
        "interpretation": "Inspect quality and completion before comparing speed/cost. No automatic production setting change or equivalence claim."}
    _write(args.out / "reasoning-controls-summary.json", report)
    return report


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--sources", type=Path, required=True, help="Original synthetic10 papers directory; only .md files are read")
    result.add_argument("--out", type=Path, required=True, help="New output directory outside the source directory")
    result.add_argument("--skills-root", type=Path, default=ROOT / "skills")
    result.add_argument("--tokenizer", type=Path, help="Required for --execute; existing pinned Qwen tokenizer.json, never downloaded here")
    result.add_argument("--reasoning", choices=("enabled", "disabled", "both"), default="enabled")
    result.add_argument("--repetitions", type=int, default=1)
    result.add_argument("--paired-positives", action="store_true", help="Add one matched positive for every negative (12 total instead of 7)")
    result.add_argument("--workers", type=int, default=4)
    result.add_argument("--deadline", type=float, default=900, help="Per-arm elapsed-time limit in seconds")
    result.add_argument("--provider", help="Optional identical provider route in both arms, with fallback disabled")
    result.add_argument("--seed", type=int, default=20261020)
    result.add_argument("--execute", action="store_true", help="Explicitly run remote Qwen calls; omitted means local fixture preparation only")
    return result


def main():
    cli = parser()
    args = cli.parse_args()
    args.sources, args.out, args.skills_root = args.sources.resolve(), args.out.resolve(), args.skills_root.resolve()
    if args.out.exists() or args.out.is_relative_to(args.sources):
        cli.error("--out must be a new directory outside --sources")
    if not 1 <= args.repetitions <= 10 or not 1 <= args.workers <= 16 or args.deadline <= 0:
        cli.error("repetitions=1..10, workers=1..16, and positive deadline are required")
    if args.execute and (args.tokenizer is None or not args.tokenizer.is_file()):
        cli.error("--execute requires a pre-existing --tokenizer file")
    cases = build_cases(args.sources, paired_positives=args.paired_positives)
    args.out.mkdir(parents=True)
    prepare_artifacts(cases, args.out)
    if args.execute:
        report = asyncio.run(execute(args, cases))
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["all_controls_correct_in_every_arm"] else 1
    print(json.dumps({"prepared_cases": len(cases), "output": str(args.out), "paid_api_calls": 0,
                      "execute_requested": False, "production_defaults_changed": False}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
