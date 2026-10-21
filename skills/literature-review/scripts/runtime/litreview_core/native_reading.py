"""Real-model native delegation acceptance for the full-reading stage.

This is a stage acceptance command, not yet a complete literature-review entry.
It deliberately reports publication_verified=false even when all readers pass.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import time

from langchain.tools import tool
from langchain_core.messages import HumanMessage, messages_to_dict
from pydantic import BaseModel, ValidationError, field_validator

from .native_agent import WorkerTask, create_review_agent
from .qwen_transport import create_model, aclose_http_clients, close_http_clients
from .qwen_tokens import QwenRequestCounter
from .request_governor import RequestGovernor, ThroughputConfig
from .resource_monitor import ResourceMonitor
from .scientific_records import ReaderSubmission, source_packet, validate_reader
from .record_review import RecordReviewSubmission, RecordReviewFailure, validate_record_review, record_projection
from .task_store import TaskStore


class SubmissionArguments(BaseModel):
    data: dict

    @field_validator('data', mode='before')
    @classmethod
    def decode_json_object(cls, value):
        # Some Qwen routes serialize the data argument as a JSON string.
        # Decode syntax only; never change scientific values or verdicts.
        if isinstance(value, str):
            return json.loads(value)
        return value


class ReaderArguments(SubmissionArguments):
    data: ReaderSubmission


def reader_tool_schema():
    """Advertise the typed reader contract without SDK payload-echo errors.

    Validation runs below after native_agent has durably saved the complete raw
    arguments. JSON Schema tools deliver raw dictionaries rather than allowing
    the SDK to reject an input before our bounded diagnostic can be produced.
    """
    schema = ReaderArguments.model_json_schema()
    schema['additionalProperties'] = False
    return schema


def validate_reader_arguments(packet, raw, *, execution_id):
    """Strict raw envelope, concise schema errors, then unchanged source gate."""
    if not isinstance(raw, dict):
        raise ValueError('Reader schema errors: [{"loc":[],"type":"dict_type"}]')
    errors = []
    if 'data' not in raw:
        errors.append({'loc':['data'], 'type':'missing'})
    for key in sorted(set(raw)-{'data'}):
        errors.append({'loc':[key], 'type':'extra_forbidden'})
    if 'data' in raw and not isinstance(raw['data'], dict):
        # Never decode strings or coerce scientific arguments on this path.
        errors.append({'loc':['data'], 'type':'dict_type'})
    if errors:
        raise ValueError('Reader schema errors: '+json.dumps(errors, ensure_ascii=False, separators=(',',':')))
    try:
        arguments = ReaderArguments.model_validate(raw, strict=True)
    except ValidationError as exc:
        errors = [{'loc':list(e['loc']), 'type':e['type']} for e in
                  exc.errors(include_url=False, include_context=False, include_input=False)]
        raise ValueError('Reader schema errors: '+json.dumps(errors, ensure_ascii=False, separators=(',',':'))) from None
    return validate_reader(packet, arguments.data.model_dump(), execution_id=execution_id)


class ReviewArguments(SubmissionArguments):
    data: RecordReviewSubmission


async def run(args):
    started = time.monotonic()
    output = args.out.resolve()
    if output.exists():
        raise ValueError('Cold-run output directory must not exist')
    source = args.sources.resolve()
    if output.is_relative_to(source):
        raise ValueError('Output must be outside input')
    paths = sorted(source.glob('*.md'))
    if not 1 <= len(paths) <= 100:
        raise ValueError('Provide 1..100 Markdown papers')
    questions = json.loads(args.questions.read_text(encoding='utf-8'))
    if isinstance(questions, dict):
        questions = questions['questions']
    counter = QwenRequestCounter(args.tokenizer)
    governor = RequestGovernor(ThroughputConfig(workers=args.workers, minimum_workers=1,
        deadline_seconds=args.deadline, token_counter=counter))
    store = TaskStore(output / 'artifacts')
    for path in paths:
        store.create('reader', source_packet(path.stem, path.read_bytes(), questions), max_attempts=1)

    @tool
    def ready_tasks() -> dict:
        """Get ready task tickets; delegate each through task with description JSON containing ticket."""
        rows = store.ready(args.workers)
        return {'ready':[{'subagent_type':r['role'], 'description':json.dumps({'ticket':r['id']})} for r in rows],
                'counts':{status:sum(r['status']==status for r in store.status())
                          for status in ('pending','running','accepted','failed')}}

    def factory(identity, description):
        request = json.loads(description)
        lease = store.claim(request['ticket'], identity.role, identity.context_id)
        failure_detail = {}
        def finish(identity, receipt):
            if not receipt.get('accepted'):
                store.fail(lease['ticket'], identity.context_id, lease['lease'],
                           {'reason':receipt.get('reason', receipt.get('error','incomplete')), **failure_detail})
        if identity.role == 'verifier':
            payload = lease['payload']
            def accept_review(data, identity):
                try:
                    review = validate_record_review(payload['source'], payload['record'], data,
                                                    execution_id=identity.context_id)
                except RecordReviewFailure as exc:
                    failure_detail['review_hash'] = store.put(exc.review)
                    raise
                return store.accept(lease['ticket'], identity.context_id, lease['lease'], review,
                                    validator=lambda a,b: None)
            return WorkerTask(instruction='Use the scientific-record-review/1 profile and typed tool. '
                'Independently read the complete original source, then verify every finding in the record. '
                'Also inspect important omissions: adverse/null results, persistent failures after mitigation, '
                'unmeasured quantities, study design and applicability. Individual true statements do not excuse '
                'a missing qualification. Return honest unsupported/needs_revision when appropriate; do not rewrite '
                'the record or treat structural validation as scientific approval.',
                inputs={'source.json':payload['source'], 'record.json':record_projection(payload['source'],payload['record'])},
                accept=accept_review, submission_schema=ReviewArguments,
                skill_documents=('SKILL.md','references/scientific-record-review.md'),on_finish=finish)
        def accept(data, identity):
            record = validate_reader_arguments(lease['payload'], data, execution_id=identity.context_id)
            receipt = store.accept(lease['ticket'], identity.context_id, lease['lease'], record,
                                   validator=lambda source, record: None)
            if args.verify_records:
                store.create('verifier', {'source':lease['payload'],'record':record},
                             dependencies=[lease['ticket']], max_attempts=1)
            return receipt
        return WorkerTask(
            instruction='Use the scientific-source/1 profile and typed ReaderSubmission. '
                'For evidence prefer only part_id with quote=null, so the runtime preserves the full exact original '
                'paragraph without retyping it. Select all necessary parts for compound assertions. '
                'Use one short content-specific sentence per observation and concise field-assessment reasons; '
                'put substantive research details in findings rather than repeating them in observations and reasons. '
                'Read the entire assigned paper. Combine repeated statements into source-linked findings; '
                'retain all distinct important results, adverse/null findings, missing measurements and '
                'persistent failures. Assess all nine fields and all research questions. '
                'Do not execute the legacy CLI or generate a whole review. Return Traditional Chinese research text.',
            inputs={'source.json':lease['payload']}, accept=accept,
            submission_schema=reader_tool_schema(), raw_tool_arguments=True, max_model_calls=3,
            skill_documents=('SKILL.md','references/scientific-records.md'), on_finish=finish)

    def worker_model(identity):
        return create_model(governor=governor, force_submit=True, max_tokens=16384,
                            reasoning_effort='low', temperature=0.1)
    coordinator = create_review_agent(
        create_model(governor=governor, max_tokens=4096, reasoning_effort='low'),
        output/'agents', args.skills_root, worker_factory=factory,
        worker_model_factory=worker_model, coordinator_tools=[ready_tasks], max_concurrency=args.workers,
        coordinator_prompt='This invocation is an explicit full-reading-stage acceptance test '
            'with independent record checking when verifier tickets are supplied. '
            'Use ready_tasks, delegate ALL ready tickets to their specified roles by task in parallel using the EXACT description JSON, '
            'then repeat ready_tasks until all are accepted or failed. Do not do comparison/writing/verification '
            'beyond the supplied tickets during this stage. Do not execute shell or legacy harness. Stop with a truthful stage summary; '
            'accepted reading does not mean a verified literature review.')
    error = None
    monitor = ResourceMonitor()
    try:
        result = await asyncio.wait_for(coordinator.ainvoke({'messages':[HumanMessage(content=
            'Use the literature-review skill to complete full reading of every supplied paper. '
            'Start with ready_tasks and delegate the returned tickets.')]},
            {'recursion_limit':max(40, len(paths)*8)}), timeout=max(0.01,args.deadline-(time.monotonic()-started)))
        (output/'coordinator-messages.json').write_text(
            json.dumps(messages_to_dict(result['messages']), ensure_ascii=False, indent=2),encoding='utf-8')
    except Exception as exc:
        error = {'type':type(exc).__name__, 'message':str(exc)}
    finally:
        governor.close()
        await aclose_http_clients()
        close_http_clients()
        resources = monitor.close()
    rows = store.status()
    expected_tasks = len(paths) * (2 if args.verify_records else 1)
    passed = len(rows)==expected_tasks and all(row['status']=='accepted' for row in rows) and error is None
    report = {'stage':'full_reading', 'passed':passed, 'publication_verified':False,
              'cold_run':True, 'papers':len(paths), 'elapsed_seconds':time.monotonic()-started,
              'independent_record_review':args.verify_records,
              'tasks':rows, 'error':error, 'resources':resources,
              'telemetry':governor.finish(completed=passed)}
    (output/'reading-result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('stage','passed','publication_verified','papers','elapsed_seconds','error')},ensure_ascii=False))
    return 0 if passed else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources',type=Path,required=True)
    parser.add_argument('--questions',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--skills-root',type=Path,required=True)
    parser.add_argument('--tokenizer',type=Path,required=True)
    parser.add_argument('--workers',type=int,default=4)
    parser.add_argument('--deadline',type=float,default=5400)
    parser.add_argument('--verify-records',action='store_true')
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args)))


if __name__ == '__main__':
    main()
