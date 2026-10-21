"""Typed native worker for cards, comparison batches and synthesis sections.

The caller creates dependency tickets and invokes this factory only from the
native task adapter. Acceptance here means structurally valid draft, never
scientific approval or publication permission.
"""
from __future__ import annotations

import json
from pydantic import Field, ValidationError
from .native_agent import WorkerTask
from .native_reading import SubmissionArguments
from .review_artifacts import DraftClaim, DraftSubmission, _draft_submission, validate_draft, CARD_MAX_CLAIMS
from .draft_wire import project_draft_packet
from .draft_submission_wire import GroupedDraftSubmission, alias_obligations, decode_grouped_submission


class DraftArguments(SubmissionArguments):
    data: DraftSubmission


class GroupedDraftArguments(SubmissionArguments):
    data: GroupedDraftSubmission


class CardGroupedDraftSubmission(GroupedDraftSubmission):
    claims: list[DraftClaim] = Field(min_length=1,max_length=CARD_MAX_CLAIMS)


class CardGroupedDraftArguments(SubmissionArguments):
    data: CardGroupedDraftSubmission


def draft_worker(store, identity, ticket, *, on_accepted=None, revision=None):
    lease = store.claim(ticket, identity.role, identity.context_id)
    packet = lease['payload']
    try:
        kind = packet['kind']
        expected = 'comparer' if kind == 'comparison' else 'writer'
        if packet.get('schema') != 'review-draft-packet/1' or kind not in (
                'paper_card', 'comparison', 'synthesis') or identity.role != expected:
            raise ValueError('Draft kind and native role do not match')
        aliased_packet,aliases = alias_obligations(packet)
        wire_packet = project_draft_packet(aliased_packet)
    except Exception as exc:
        store.fail(ticket, identity.context_id, lease['lease'], {'reason':str(exc)})
        raise

    ContextArgumentsBase=CardGroupedDraftArguments if kind=='paper_card' else GroupedDraftArguments
    schema=ContextArgumentsBase.model_json_schema()
    schema['additionalProperties']=False

    def accept(raw, actual_identity):
        if actual_identity.context_id != identity.context_id:
            raise ValueError('Draft submission belongs to a different runtime context')
        if not isinstance(raw,dict) or set(raw)!={'data'} or not isinstance(raw['data'],dict):
            raise ValueError('Submit exactly {data: object}; no extra keys, strings or coercion')
        value=raw['data']
        if not value.get('claims'):
            _draft_submission(packet,{'claims':[], 'retention':[], 'cells':value.get('cells',[])})
        try:
            typed=GroupedDraftSubmission.model_validate(value,strict=True)
        except ValidationError as exc:
            errors=[{'loc':list(e['loc']),'type':e['type']} for e in
                exc.errors(include_input=False,include_context=False,include_url=False)]
            raise ValueError('Draft schema errors: '+json.dumps(errors,separators=(',',':'))) from None
        data=decode_grouped_submission(typed.model_dump(),aliases)
        section = validate_draft(packet, data, execution_id=identity.context_id)
        receipt = store.accept(ticket, identity.context_id, lease['lease'], section,
                               validator=lambda source, value: None)
        if on_accepted is not None:
            on_accepted(ticket, section, receipt)
        return receipt

    def finish(actual_identity, receipt):
        if not receipt.get('accepted'):
            # A downstream scheduling callback may fail after accepting a draft.
            # Preserve that valid draft; the pipeline still records the error and
            # must require its missing proof tasks before allowing publication.
            state = next(r for r in store.status() if r['id'] == ticket)
            if state['status'] == 'running':
                store.fail(ticket, identity.context_id, lease['lease'],
                           {'reason':receipt.get('error',receipt.get('reason','incomplete'))})

    return WorkerTask(
        instruction='Use the review-draft-wire/1 lossless encoding of the review-draft-packet/1 mapped-drafts profile '
            'and typed GroupedDraftSubmission. Obligation IDs o1, o2, etc. are exact runtime aliases. '
            'Submit retention_groups: group obligation_ids only when status, claim_ids and reason all apply '
            'to every member. Cover every supplied obligation alias exactly once; grouping is not omission. '
            'submit_result is for the actual complete research draft, not for probing the schema. '
            'Do not submit placeholder, probe, sample or empty content. All required input and schema are supplied. '
            'The packet field retains all non-source values; source_encoding tables '
            'use named columns and paper_version_index into paper_versions. Interpret each row as the exact '
            'paper_id/part_id source locator, original offsets and source version; no values are summaries. '
            'Claim evidence_refs must use exact paper_id/part_id IDs from citation-index.json. '
            'reader_evidence_ids are extraction bookkeeping, never valid report citations. '
            'When reader_context_profile is reader-finding-context/1, reader_findings contains each complete '
            'original finding and its actual source_refs once. This is unverified extraction, not scientific truth; '
            'read the original sources and preserve governing qualifications. For EVERY retention obligation read its exact '
            'finding_id there before choosing destination claims; do not guess its content from a source-part topic. '
            'Retain the full material finding in the actual named claim texts, or justify its scientific exclusion. '
            'If revision.json is supplied, address each independent issue against the current sources or premises; '
            'preserve valid details and do not merely change labels to satisfy a checker. '
            'Complete only the assigned kind and membership. Read every assigned source or actual premise. '
              'For any derived comparison or synthesis, premise_retention obligations cover every actual direct premise claim. '
            'Included decisions must bind delivered claims that list that premise_claim_id; excluded decisions '
            'need a scientific reason. Preserve critical counterevidence and scope qualifications across levels. '
            'For a paper_card, aim for 6–10 compact substantive paragraphs: consolidate repeated facts '
            'and related qualifications instead of reproducing the entire extraction. The card contract is '
            'at most 12 claims and 3000 total Unicode characters of claim text; aim for 1200–2200 characters '
            'in Traditional Chinese. Raw extraction remains archived. Background exposition and repeated '
            'method descriptions need not be reproduced; explicitly justify excluded obligations when '
            'they do not materially qualify the research answers, or are redundant with retained qualifications. '
            'These bounds never permit dropping distinct important results or limitations; an independent '
            'reviewer checks important omissions and exclusions. Rewrite a concise complete card, never truncate. '
            'Retain qualifying adverse/null results, persistent failures and missing measurements. '
            'Use concise Traditional Chinese scientific prose. Submit an unverified draft; '
            'do not run a legacy CLI, independently approve it, or manufacture bibliography.',
        inputs={'draft-packet.json':wire_packet, 'citation-index.json':sorted(packet['sources']),
                **({'revision.json':revision} if revision else {})}, accept=accept,
        submission_schema=schema,raw_tool_arguments=True,max_model_calls=3,
        skill_documents=('SKILL.md','references/mapped-drafts.md'), on_finish=finish)
