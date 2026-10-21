"""Diagnose a complete native review installation without network or inference."""
import argparse
import ast
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
import sys


def diagnose(skills_root, tokenizer, *, require_key=True, skills=None):
    root=Path(skills_root).resolve()
    checks=[]
    def check(name,passed,detail):
        checks.append({'check':name,'passed':bool(passed),'detail':detail})
    check('python',sys.version_info>=(3,11),sys.version.split()[0])
    required={
        'literature-review':['SKILL.md','scripts/native_review.py','scripts/requirements-native.txt'],
        'analyze-paper':['SKILL.md','references/scientific-records.md'],
        'compare-papers':['SKILL.md','references/mapped-drafts.md'],
        'write-review':['SKILL.md','references/mapped-drafts.md'],
        'verify-citations':['SKILL.md','references/hierarchical-proof.md','references/scientific-record-review.md']}
    selected=list(dict.fromkeys(skills or required))
    unknown=set(selected)-set(required)
    if unknown:
        raise ValueError('Unknown skills: '+', '.join(sorted(unknown)))
    for skill in selected:
        files=required[skill]
        missing=[f for f in files if not (root/skill/f).is_file()]
        check('skill:'+skill,not missing,{'missing':missing})
    anchor='literature-review' if 'literature-review' in selected else selected[0]
    pins=root/anchor/'scripts/requirements-native.txt'
    check('requirements',pins.is_file(),str(pins))
    if pins.is_file():
        for line in pins.read_text(encoding='utf-8').splitlines():
            if not line.strip() or line.lstrip().startswith('#'):
                continue
            name,expected=line.strip().split('==',1)
            try:
                actual=version(name)
            except PackageNotFoundError:
                actual=None
            check('dependency:'+name,actual==expected,{'expected':expected,'installed':actual})
    runtime=root/anchor/'scripts/runtime'
    for module in ('native_agent','native_review','review_workflow','coordinator_frontier',
                   'proof_planner','proof_worker','review_repair','delivery_export','qwen_transport','qwen_tokens',
                   'review_minimum_units','paper_review_v2','paper_review_v2_wire','paper_review_worker_v2',
                   'section_review_v2','section_review_worker_v2','review_workflow_v2',
                   'review_release_v2','delivery_export_v2','review_observation_selectors','closed_scientific_checks'):
        check('module:'+module,(runtime/'litreview_core'/ (module+'.py')).is_file(),str(runtime/'litreview_core'/(module+'.py')))
    # Read the pinned literal without executing runtime code or requiring HOME.
    token_module=runtime/'litreview_core/qwen_tokens.py'
    if token_module.is_file():
        syntax=ast.parse(token_module.read_text(encoding='utf-8'))
        expected=next(ast.literal_eval(node.value) for node in syntax.body
            if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='EXPECTED_SHA256' for t in node.targets))
        path=Path(tokenizer)
        digest=sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        check('tokenizer',digest==expected,{'path':str(path.resolve()),'expected_sha256':expected,'actual_sha256':digest})
    if require_key:
        check('openrouter_key',bool(os.environ.get('OPENROUTER_API_KEY')),
              'Presence only; value is never displayed and authentication is not tested')
    return {'schema':'native-installation-diagnostic/1','passed':all(c['passed'] for c in checks),
            'checks':checks,'network_calls':0,'model_inference':'not_tested','academic_quality':'not_tested',
            'full_pipeline':'not_tested','selected_skills':selected,'runtime_skill':anchor}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skills-root',type=Path,required=True)
    parser.add_argument('--tokenizer',type=Path,required=True)
    parser.add_argument('--skip-key-check',action='store_true')
    parser.add_argument('--skill',action='append',choices=('literature-review','analyze-paper',
        'compare-papers','write-review','verify-citations'))
    args=parser.parse_args()
    result=diagnose(args.skills_root,args.tokenizer,require_key=not args.skip_key_check,skills=args.skill)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    raise SystemExit(0 if result['passed'] else 1)


if __name__=='__main__':
    main()
