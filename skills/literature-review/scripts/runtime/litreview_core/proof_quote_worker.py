"""Opt-in source witness experiment using the actual native proof worker.

Literal checks supplement the existing scientific attestation. The proof gate
does not yet require this experimental witness protocol across an entire DAG.
"""
from dataclasses import replace
from pydantic import ValidationError

from .proof_planner import node_payload
from .proof_quote_wire import (SourceWitnessWireSubmission, adapt_source_witness_wire,
    source_witness_tool_schema, unwrap_source_witness_tool_arguments)
from .proof_quote_witness import WitnessValidationError
from .proof_submission_wire import decode_proof_submission
from .proof_worker import proof_worker


def source_witness_worker(bundle, node_id, dependencies, identity, *, save, **kwargs):
    if bundle['node_specs'][node_id]['kind'] != 'source' or dependencies:
        raise ValueError('Experimental quote witnesses require a dependency-free source node')
    audit = {}

    def save_with_witness(node, execution, submission):
        return save(node, execution, {**submission, 'quote_witness': dict(audit)})

    base = proof_worker(bundle, node_id, dependencies, identity, save=save_with_witness, **kwargs)
    packet = node_payload(bundle, node_id, dependencies)
    wire_packet = base.inputs['proof-task.json']
    aliases = wire_packet['responsibility_aliases']

    def accept(arguments, actual_identity):
        value = unwrap_source_witness_tool_arguments(arguments)
        try:
            wire = SourceWitnessWireSubmission.model_validate(value).model_dump(exclude_none=True)
        except ValidationError as exc:
            raise WitnessValidationError('WITNESS_SCHEMA_INVALID', 'Malformed witness submission',
                value, exc.errors(include_input=False, include_url=False)) from exc
        decoded = decode_proof_submission(wire, aliases)
        adaptation = adapt_source_witness_wire(packet, decoded,
                                               expected_material_hashes=bundle['node_specs'][node_id]['inputs'])
        audit.clear()
        audit.update(adaptation)
        # Preserve the exact parsed, aliased tool arguments as well as the
        # canonical scientific responsibilities used by the literal validator.
        audit['original_tool_arguments'] = arguments
        return base.accept(adaptation['literal_validation']['proof_submission'], actual_identity)

    instruction = base.instruction + (
        '\nThis source task additionally requires ordered clause_checks for every assigned claim verdict. '
        'Each clause is an exact substring of the actual claim. Together clauses must cover every '
        'non-whitespace character, including punctuation, in textual order. For each clause classify '
        'explicit_support, topic_only, not_reported, contradicted, or unresolved. A passed clause needs '
        'one or more exact original quotes from that claim\'s own declared refs. Each quote must uniquely '
        'occur within its declared part; include enough surrounding words to make it unique. '
        'Do not calculate byte or character offsets; the runtime derives them. '
        'Quote presence proves literal location only. Independently assess whether the quote entails '
        'EVERY factual component, including ordering, frequency, populations, quantities and conditions. '
        'A quote containing the same topic or events does not establish a relation between them. '
        'Use topic_only or not_reported when a claimed relation lacks explicit support. '
        'Do not supply clause_checks for obligation verdicts; preserve their normal individual judgments. '
        'An honest negative is terminal for this verifier and must not be changed just to pass validation.'
    )
    return replace(base, instruction=instruction, accept=accept,
                   submission_schema=source_witness_tool_schema(), raw_tool_arguments=True)
