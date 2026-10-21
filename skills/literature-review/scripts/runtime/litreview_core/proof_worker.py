"""Native independent semantic attestations for a compiled review proof DAG."""
from __future__ import annotations

from typing import Literal
import json
from collections import Counter
from pydantic import Field

from .scientific_records import StrictModel
from .native_reading import SubmissionArguments
from .native_agent import WorkerTask
from .hierarchical_proof import (DIMENSIONS, RuntimeIdentity, payload_hash, seal_node,
                                prepare_dependency_receipts)
from .proof_planner import node_payload
from .proof_submission_wire import alias_proof_packet, decode_proof_submission
from .proof_citation_view import attach_citation_view


class UnitVerdict(StrictModel):
    unit_id: str
    verdict: Literal['passed','needs_revision','unresolved']
    reason: str = Field(min_length=1)


class ProofIssue(StrictModel):
    unit_ids: list[str] = Field(min_length=1)
    description: str = Field(min_length=1)
    correction: str = Field(min_length=1)


class ProofSubmission(StrictModel):
    checked: dict[str,list[str]]
    verdicts: list[UnitVerdict] = Field(description='One verdict for each assigned claim and obligation. Other checked dimensions need no separate verdict. Empty for integration/root tasks with no assigned claims or obligations.')
    status: Literal['passed','needs_revision','unresolved']
    reason: str = Field(min_length=1)
    issues: list[ProofIssue]


class ProofArguments(SubmissionArguments):
    data: ProofSubmission


class SemanticProofFailure(ValueError):
    code = 'VERIFICATION_ISSUES'

    def __init__(self, node):
        super().__init__('Independent proof requires revision or remains unresolved')
        self.node = node


def proof_worker(bundle, node_id, dependencies, identity, *, save, on_finish=None,
                 proof_nodes=None, proof_identities=None):
    """Save receives (sealed_node, RuntimeIdentity, full_submission) for all verdicts.

    The caller persists failed attestations as well as successful ones. Only
    successful nodes may unblock dependency tickets. All hashes and identities
    are derived here from the actual delivered input, never from model arguments.
    If save returns a TaskStore receipt, return its actual ticket, context,
    input/output hashes and accepted status to the native delegation verifier.
    Scientific proof_status remains distinct from task lifecycle status.
    """
    spec = bundle['node_specs'][node_id]
    if identity.role != spec['role']:
        raise ValueError('Proof role does not match runtime task')
    if set(dependencies) != set(spec['dependencies']):
        raise ValueError('Every planned dependency proof must be delivered')
    actual_hashes = {mid:payload_hash(bundle['materials'][mid]) for mid in spec['input_ids']}
    if actual_hashes != spec['inputs']:
        raise ValueError('Planned proof inputs changed before delivery')
    for dep, node in dependencies.items():
        p = node['payload']
        if (node['payload_hash'] != payload_hash(p) or p['node_id'] != dep
                or p['status'] != 'passed' or p['issues']):
            raise ValueError('Dependency proof is stale, failed, or unresolved')
    dependency_hashes = {nid:node['payload_hash'] for nid,node in dependencies.items()}
    compact = node_id in bundle.get('plan', {}).get('payload', {}).get('dependency_delivery', {}).get('node_ids', [])
    receipts, receipt_hashes = None, {}
    if compact and dependencies:
        if proof_nodes is None or proof_identities is None:
            raise ValueError('Compact dependency delivery requires the complete trusted node/identity registry')
        registry, identities = dict(proof_nodes), dict(proof_identities)
        if any(dep not in registry or registry[dep] != node for dep, node in dependencies.items()):
            raise ValueError('Actual child proof differs from the trusted completed-node registry')
        receipts = prepare_dependency_receipts(bundle['plan'], registry, bundle['materials'], identities,
                                               list(dependencies))
        receipt_hashes = {dep: payload_hash(receipt) for dep, receipt in receipts.items()}
    packet, aliases = alias_proof_packet(attach_citation_view(node_payload(bundle,node_id,dependencies,
                                                        dependency_receipts=receipts)))

    def accept(data, actual_identity):
        if actual_identity.context_id != identity.context_id:
            raise ValueError('Foreign proof submission context')
        wire_submission = ProofSubmission.model_validate(data)
        submission = ProofSubmission.model_validate(
            decode_proof_submission(wire_submission.model_dump(), aliases))
        coverage = spec['coverage']
        if set(submission.checked) != set(DIMENSIONS):
            raise ValueError('Declare all six checked dimensions')
        coverage_errors={}
        for dim in DIMENSIONS:
            ids = submission.checked[dim]
            if len(ids) != len(set(ids)) or set(ids) != set(coverage[dim]):
                counts=Counter(ids)
                coverage_errors[dim]={'missing':sorted(set(coverage[dim])-set(ids)),
                    'unknown':sorted(set(ids)-set(coverage[dim])),
                    'duplicates':sorted(uid for uid,count in counts.items() if count>1)}
        if coverage_errors:
            raise ValueError('Checked coverage mismatch: '+json.dumps(coverage_errors,ensure_ascii=False))
        required = set(coverage['claims']) | set(coverage['obligations'])
        verdict_ids = [v.unit_id for v in submission.verdicts]
        allowed = {unit for dim in DIMENSIONS for unit in coverage[dim]}
        counts=Counter(verdict_ids)
        problems={'missing':sorted(required-set(verdict_ids)),
                  'unknown':sorted(set(verdict_ids)-allowed),
                  'duplicates':sorted(uid for uid,count in counts.items() if count>1)}
        if any(problems.values()):
            raise ValueError('Verdict inventory mismatch; each assigned claim and obligation requires one verdict; '
                'optional verdicts may only name other assigned coverage units. '+
                json.dumps({**problems,'required_verdict_ids':sorted(required)},ensure_ascii=False))
        # Root nodes roll up child coverage without claiming it twice. They
        # still need to report scope/integration defects against actual inputs.
        all_units = {u for dim in DIMENSIONS for u in coverage[dim]} | set(actual_hashes)
        if any(not set(issue.unit_ids) <= all_units for issue in submission.issues):
            raise ValueError('Issue references unknown responsibility units')
        if submission.status == 'passed' and (submission.issues or
                any(v.verdict != 'passed' for v in submission.verdicts)):
            raise ValueError('Passed status contradicts the supplied findings')
        node = seal_node(node_id,spec['kind'],identity.context_id,actual_hashes,
                         dependency_hashes,coverage,submission.status,submission.reason,
                         [i.model_dump() for i in submission.issues])
        execution = RuntimeIdentity(execution_id=identity.context_id,context_id=identity.context_id,
            role=identity.role,input_hashes=actual_hashes,dependency_hashes=dependency_hashes,
            output_hashes={node_id:node['payload_hash']},task_call_id=identity.task_tool_call_id,
            parent_context_id=identity.coordinator_context_id,
            delivered_dependency_receipt_hashes=receipt_hashes)
        saved_receipt = save(node,execution,submission.model_dump())
        if submission.status != 'passed':
            raise SemanticProofFailure(node)
        result = {'node_id':node_id,'status':'passed','proof_status':'passed',
                  'proof_hash':node['payload_hash']}
        if saved_receipt is not None:
            result.update(saved_receipt)
        return result

    return WorkerTask(instruction='Use hierarchical-proof-task/1 and its typed ProofSubmission profile. '
        'When dependency_delivery is dependency-proof-receipt/1, the host has preflighted complete child '
        'proofs and identities; you receive their exact compact receipts, not their full input/dependency '
        'hash manifests. Review every supplied actual scientific premise and context. A receipt/hash '
        'does not replace those materials or independently prove the new conclusion. '
        'coverage uses runtime short IDs from responsibility_aliases; resolve each to its exact canonical '
        'unit in the unchanged materials. Use short IDs in checked, verdict unit_id and issue unit_ids. '
        'Each unit still needs its own scientific judgment and reason; aliases do not group or omit work. '
        'Use citation_view claim_rows to compare each exact claim with only its declared complete source parts. '
        'Other original context can reveal contradictions or omissions but cannot supply missing local support. '
        'For obligation_rows check preservation only in that disposition\'s named_claims, not elsewhere in the card. '
        'Original_not_delivered is not a quoted source: cross-group and assembly tasks must follow their '
        'actual premise/dependency responsibilities without pretending to have original text. '
        'When materials include dependency-scientific-view/1, claims_by_dependency identifies this '
        'node\'s selected independently checked child premises. Read every complete selected claim '
        'and its supplied section/context to assess the new inference and all assigned local retention, '
        'including excluded dispositions. Preserve child full-source lineage while leaving unselected '
        'raw child obligations with their assigned child reviewers. Missing selected claims or necessary '
        'context requires unresolved; never claim to reread an original absent from this task. '
        'Independently inspect all assigned materials and every declared responsibility. '
        'checked must match all six assigned coverage lists. verdicts needs only the assigned claims and '
        'obligations, exactly once each; do not waste output repeating line/paper/question/cell verdicts. '
        'For empty-coverage integration/root tasks use verdicts=[] and report defects in issues. '
        'Check every factual clause against its declared citation locators: support elsewhere in a paper '
        'does not repair an incorrect local citation. Do not infer unreported temporal order. '
        'Return honest scientific verdicts, including omissions and unsupported inference. '
        'Do not rewrite the target or call the legacy CLI. A dependency approval is not proof of a new inference.',
        inputs={'proof-task.json':packet},accept=accept,submission_schema=ProofArguments,
        max_model_calls=3,skill_documents=('SKILL.md','references/hierarchical-proof.md'),on_finish=on_finish)
