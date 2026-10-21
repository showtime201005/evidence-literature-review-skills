"""Full-source native reader shared by staged and complete reviews."""
from .native_agent import WorkerTask
from .native_reading import reader_tool_schema, validate_reader_arguments


def reader_worker(store, identity, ticket, *, on_accepted=None):
    if identity.role != 'reader':
        raise ValueError('Reading requires a native reader identity')
    lease = store.claim(ticket, identity.role, identity.context_id)

    def accept(data, actual_identity):
        if actual_identity.context_id != identity.context_id:
            raise ValueError('Foreign reader submission')
        record = validate_reader_arguments(lease['payload'],data,execution_id=identity.context_id)
        receipt = store.accept(ticket,identity.context_id,lease['lease'],record,
                               validator=lambda source, value: None)
        if on_accepted is not None:
            on_accepted(ticket,record,receipt)
        return receipt

    def finish(actual_identity, receipt):
        if not receipt.get('accepted'):
            state = next(r for r in store.status() if r['id']==ticket)
            if state['status']=='running':
                store.fail(ticket,identity.context_id,lease['lease'],
                           {'reason':receipt.get('error',receipt.get('reason','incomplete'))})

    return WorkerTask(instruction='Use scientific-source/1 and typed ReaderSubmission. '
        'Call submit_result with exactly one data object containing ONLY observations, findings, fields, questions. '
        'Use the existing note, text and reason properties for explanations; never add *_note or other undeclared keys. '
        'Read every source part and assess all nine fields and all research questions. '
        'For evidence prefer part_id with quote=null to bind the exact original paragraph. '
        'Give each observation a short content-specific sentence. Consolidate repetitions, '
        'but retain all distinct relevant findings, null/adverse results, missing measurements, '
        'persistent failures, design limits and applicability. Explicitly tag evidence obligations. '
        'Use Traditional Chinese scientific text. Do not generate a whole review or run the legacy CLI.',
        inputs={'source.json':lease['payload']},accept=accept,submission_schema=reader_tool_schema(),
        raw_tool_arguments=True,
        max_model_calls=3,skill_documents=('SKILL.md','references/scientific-records.md'),on_finish=finish)
