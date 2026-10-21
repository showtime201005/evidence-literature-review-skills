"""Cross-field capability contracts. Schema validity is not scientific approval."""
import copy
from .artifacts import envelope,canonical,digest
from .errors import ReviewError

FIELDS=('research_question','contributions','method','evaluation','results','limitations','conditions','relevance','unexpected_findings')


def need(condition,message,details=None):
    if not condition:
        raise ReviewError('CAPABILITY_INVALID',message,details)


def unique(values,label):
    need(len(values)==len(set(values)),label+' contains duplicates')


def check_invariants(artifact):
    p=artifact['payload'];kind=artifact['artifact_type']
    if kind in ('ReviewRequest','QuestionEvidenceMap'):
        from .research import research_invariants
        research_invariants(artifact)
    if kind=='AugmentationPlan':
        from .augmentation import augmentation_invariants
        augmentation_invariants(artifact)
    if kind=='PaperAnalysis':
        unique(p['checked_part_ids'],'checked_part_ids')
        unique(p['claim_refs'],'claim_refs')
        need(set(p['fields'])==set(FIELDS),'All nine standard fields are required; extensions belong outside fields')
        refs=set()
        for name,field in p['fields'].items():
            unique(field['claim_refs'],name+'.claim_refs')
            need(set(field['checked_part_ids'])<=set(p['checked_part_ids']),'Field references unchecked source parts',name)
            if field['status']=='reported':
                need(field['text'].strip() and field['claim_refs'],'Reported field needs text and claim_refs',name)
            else:
                need(not field['claim_refs'],'Missing field cannot contain reported claims',name)
            if field['status'] in ('not_reported','not_applicable'):
                need(p['checked_part_ids'] and set(field['checked_part_ids'])==set(p['checked_part_ids']),
                     'Absence/applicability assessment must cover the complete delivered paper',name)
            refs.update(field['claim_refs'])
        need(refs==set(p['claim_refs']),'Paper claim_refs must equal the union of field claim_refs')
    elif kind=='FieldAssessmentSet':
        if not p['assessments']:
            need(p['paper_type']!='unknown' and isinstance(p.get('classification_reason'),str) and p['classification_reason'].strip(),
                 'A classification-only assessment needs a known paper_type and classification_reason')
        names=[a['field'] for a in p['assessments']];unique(names,'assessment fields')
        for a in p['assessments']:unique(a['checked_part_ids'],'assessment checked_part_ids')
        need(bool(artifact.get('producer',{}).get('context_id')),'Field assessments require an actual reader context')
    elif kind=='ComparisonSet':
        unique(p['paper_ids'],'paper_ids');unique(p['dimensions'],'dimensions')
        ids=[c['claim_id'] for c in p['claims']];unique(ids,'comparison claim IDs')
        need(set(p['material_refs'])==set(ids),'material_refs must identify all comparison-owned claims')
        cells=p['cells'];unique([c['cell_id'] for c in cells],'cell_ids')
        pairs=[(c['paper_id'],c['dimension']) for c in cells];unique(pairs,'paper/dimension cells')
        need(set(pairs)=={(pid,dim) for pid in p['paper_ids'] for dim in p['dimensions']},'One cell per declared paper and dimension is required')
        evidence={e for c in p['claims'] for e in c['evidence_refs']}
        for claim in p['claims']:
            need(claim['claim_type']!='scope_statement','Comparison claims must be substantive, not procedural scope statements')
            need(claim['evidence_refs'],'Comparison claims need source evidence; for unavailable sources return TaskResult needs_input')
        for c in cells:
            need(set(c['material_refs'])<=set(ids),'Cell has unknown claim refs',c['cell_id'])
            need(set(c['counterevidence_refs'])<=evidence,'Counterevidence must be in the comparison claim evidence set',c['cell_id'])
            if c['status']=='mixed':need(c['counterevidence_refs'],'Mixed cell needs explicit counterevidence',c['cell_id'])
        for c in p['contradiction_candidates']:
            unique(c['claim_refs'],'contradiction claim refs')
            need(set(c['claim_refs'])<=set(ids),'Contradiction refers to unknown claims')
    elif kind=='TaskResult':
        if p['status']=='succeeded':need(p['artifact_refs'],'Succeeded task needs an output artifact')
        if p['status'] in ('partial','needs_input','failed'):need(p['issues'],'Incomplete/failed task must explain the actionable problem')
        if p['status']=='needs_input':need(any(i['required_input'] for i in p['issues']),'needs_input must specify the missing input')
        if p['quality']=='passed':need(p.get('verification_refs'),'Passed quality needs verifier references; declarations alone do not establish trust')
    elif kind=='ComparisonVerification':
        from .contracts import validate
        validate(p['review_verification'])
        need(p['review_verification']['artifact_type']=='VerificationSet','Comparison verification must contain a VerificationSet')


def capability_check(artifact):
    from .contracts import validate
    validate(artifact)
    current=artifact['schema_version']=='2.0.0'
    gaps=[]
    if current and artifact['artifact_type']=='PaperAnalysis':
        expected={'empirical':['research_question','method','evaluation','results','limitations'],
            'theoretical':['research_question','contributions','method','conditions','limitations'],
            'survey':['research_question','method','contributions','limitations'],
            'other':['research_question','contributions','limitations'],'unknown':[]}
        p=artifact['payload']
        for field in expected[p['paper_type']]:
            if p['fields'][field]['status'] in ('not_extracted','not_checked','parse_error','source_missing'):
                gaps.append({'code':'NEEDS_EXTRACTION','field':field,'message':'Required analysis dimension is unresolved; complete reading is not sufficient.'})
        if p['paper_type']=='unknown':gaps.append({'code':'PAPER_TYPE_UNKNOWN','message':'Classify the paper before assessing research-content adequacy.'})
    return {'schema_valid':True,'capability_status':('ready_with_gaps' if gaps else 'ready') if current else 'legacy_requires_explicit_normalization',
            'research_content_gaps':gaps,
            'quality':'unverified','note':'Readiness is structural, not semantic support or independent verification.'}


def apply_assessments(analysis,assessment):
    from .contracts import validate
    validate(analysis);validate(assessment)
    need(analysis['artifact_type']=='PaperAnalysis' and analysis['schema_version']=='2.0.0','Use a v2 PaperAnalysis as assessment target')
    need(assessment['artifact_type']=='FieldAssessmentSet','Expected FieldAssessmentSet')
    p=assessment['payload'];target=analysis['payload']
    need(p['target_artifact_id']==analysis['artifact_id'] and p['target_hash']==digest(canonical(target).encode()),'Assessment targets an obsolete analysis')
    revised=copy.deepcopy(target);revised['paper_type']=p['paper_type']
    if p.get('classification_reason'):revised['classification_reason']=p['classification_reason']
    for a in p['assessments']:
        field=revised['fields'][a['field']]
        need(field['status']!='reported','Cannot erase reported evidence with an absence assessment',a['field'])
        need(set(a['checked_part_ids'])<=set(target['checked_part_ids']),'Assessment references unseen parts')
        field.update(status=a['status'],reason=a['reason'],checked_part_ids=a['checked_part_ids'])
    revised['assessment_ref']=assessment['artifact_id']
    revised['assessment_provenance']=assessment.get('producer',{})
    revised['derived_from']={'artifact_id':analysis['artifact_id'],'payload_hash':digest(canonical(target).encode())}
    out=envelope('PaperAnalysis',revised,analysis.get('producer'),schema_version='2.0.0')
    validate(out)
    return out


def task_result(task_id,status,issues=None,artifact_refs=None,source_hashes=None,context_id='unknown'):
    from .contracts import validate
    result=envelope('TaskResult',dict(task_id=task_id,status=status,quality='unverified',
        artifact_refs=artifact_refs or [],source_hashes=source_hashes or [],issues=issues or []),
        producer={'context_id':context_id},schema_version='2.0.0')
    validate(result)
    return result
