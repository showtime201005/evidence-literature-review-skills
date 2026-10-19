"""Mechanical checks only. A valid locator does not imply semantic support."""
import re
from ..artifacts import digest
from ..contracts import validate
from ..errors import ReviewError
from ..sources.evidence import check_evidence
from ..artifacts.importer import citation_tokens


def issue(code,message,details=None,severity='blocker'):
    return dict(code=code,message=message,details=details,severity=severity)


def inspect_draft(artifact,evidence_ids=None):
    """Conservative triage for undeclared text; not the M2 semantic sentence scan.

    Every nonempty prose line not entirely covered by a claim mapping is returned
    for review. This intentionally over-flags opinions and headings in imports.
    """
    validate(artifact)
    if artifact['artifact_type']!='ReviewDraft':
        raise ReviewError('WRONG_ARTIFACT_TYPE','Expected ReviewDraft')
    draft=artifact['payload']
    text=draft['text']
    findings=[]
    claims={c['claim_id']:c for c in draft['claims']}
    if len(claims)!=len(draft['claims']):
        findings.append(issue('DUPLICATE_ID','Duplicate claim ID'))
    mapped=set()
    valid_intervals=[]
    for item in draft['claim_mappings']:
        cid=item['claim_id']
        left,right=item['start_char'],item['end_char']
        if cid not in claims or not 0<=left<right<=len(text):
            findings.append(issue('INVALID_CLAIM_MAPPING','Invalid claim mapping',item))
            continue
        if text[left:right]!=claims[cid]['text']:
            findings.append(issue('CLAIM_TEXT_MISMATCH','Claim text is different from the mapped draft',cid))
            continue
        mapped.add(cid)
        valid_intervals.append((left,right))
    for cid,claim in claims.items():
        if cid not in mapped:
            findings.append(issue('UNMAPPED_CLAIM','Claim does not appear in the draft mapping',cid))
        if not claim['evidence_refs'] and claim['claim_type']!='scope_statement':
            findings.append(issue('MISSING_CITATION','Claim needs evidence',cid))
        if evidence_ids is not None:
            for eid in claim['evidence_refs']:
                if eid not in evidence_ids:
                    findings.append(issue('UNKNOWN_EVIDENCE','Claim references unknown evidence',eid))
    offset=0
    for line in text.splitlines(keepends=True):
        stripped=line.strip()
        if stripped and not stripped.startswith(('#','<!--','-->')):
            # Subtract registered intervals and citation tokens, then flag leftover prose.
            chars=list(line)
            for start,end in valid_intervals:
                for n in range(max(offset,start),min(offset+len(line),end)):
                    chars[n-offset]=' '
            for token in citation_tokens(line):
                for n in range(token['start_char'],token['end_char']):
                    chars[n]=' '
            leftover=''.join(chars).strip(' \t\r\n.,;:!?。，；：！？-*|')
            if leftover:
                findings.append(issue('UNMAPPED_TEXT_REQUIRES_REVIEW','Unmapped report text must be scanned by an independent verifier',
                    {'start_char':offset,'end_char':offset+len(line),'text':line.rstrip()},severity='needs_review'))
        offset+=len(line)
    for token in citation_tokens(text):
        literal=token['token']
        if literal.startswith('{{evidence:'):
            eid=literal[len('{{evidence:'):-2]
            if evidence_ids is not None and eid not in evidence_ids:
                findings.append(issue('UNKNOWN_EVIDENCE','Unknown citation placeholder',eid))
        elif literal not in draft['citation_map']:
            findings.append(issue('UNRESOLVED_REFERENCE','Unmapped external citation',literal))
    for candidate in draft.get('reference_candidates',[]):
        if candidate['status']!='mapped_unverified':
            findings.append(issue(candidate['status'].upper(),'External reference is not uniquely mapped',candidate))
    findings.append(issue('SEMANTIC_VERIFICATION_REQUIRED','Mechanical validation does not establish semantic support; use an independent verifier and publication gate',severity='needs_review'))
    return findings


def inspect_artifact(artifact,corpus_dir=None,index=None,evidence=None):
    validate(artifact)
    issues=[]
    kind=artifact['artifact_type']
    if kind=='Evidence':
        if index is None:
            issues.append(issue('SOURCE_REQUIRED','Evidence location check requires --corpus'))
        else:
            check_evidence(corpus_dir,index,artifact)
    elif kind=='ReviewDraft':
        issues.extend(inspect_draft(artifact,None if evidence is None else set(evidence)))
        if index is not None:
            for value in (evidence or {}).values():
                check_evidence(corpus_dir,index,value)
    elif kind=='VerificationSet':
        issues.append(issue('SEMANTIC_ATTESTATION_UNVERIFIED','Imported verification is schema-valid but not independently authenticated',severity='needs_review'))
    return {'schema_valid':True,'locator_valid':kind=='Evidence' and not issues,
            'mechanical_status':'failed' if any(i['severity']=='blocker' for i in issues) else 'passed',
            'quality':'unverified','issues':issues}
