"""Install skills without overwriting existing installations.

DeepAgents installs exact selected SKILL/references and the canonical native
entry points/pins/runtime, excluding legacy example assets. Other harnesses
retain their complete-skill copy behavior. No dependencies or models are run.
This shared implementation uses only the Python standard library and travels
with each native skill; entrypoint wrappers must import their own runtime.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from uuid import uuid4

NAMES=['analyze-paper','compare-papers','write-review','verify-citations','literature-review']
TARGETS={'codex':'.agents/skills','claude-code':'.claude/skills','opencode':'.opencode/skills','deepagents':'skills'}
NATIVE_PROFILE='deepagents-native-typed/1'
COMMON_ENTRIES=('native_doctor.py','native_task.py','install_skills.py','requirements-native.txt')
REVIEW_ENTRIES=('native_review.py','native_reading.py')
REQUIRED_MODULES=('__init__.py','native_agent.py','native_task.py','native_review.py','native_reading.py',
    'coordinator_frontier.py','task_store.py','qwen_transport.py','qwen_tokens.py','request_governor.py','provider_routes.py',
    'scientific_records.py','record_review.py','reader_worker.py','draft_worker.py','draft_wire.py','draft_submission_wire.py',
    'review_artifacts.py','review_workflow.py','review_repair.py','proof_planner.py','proof_worker.py','proof_submission_wire.py','proof_citation_view.py',
    'proof_quote_witness.py','proof_quote_wire.py','proof_quote_worker.py','source_witness_audit.py',
    'hierarchical_proof.py','delivery_export.py','resource_monitor.py',
    'review_minimum_units.py','paper_review_v2.py','paper_review_v2_wire.py','paper_review_worker_v2.py',
    'section_review_v2.py','section_review_worker_v2.py',
    'review_workflow_v2.py','review_release_v2.py','delivery_export_v2.py',
    'review_observation_selectors.py','closed_scientific_checks.py','skill_installation.py')
_IGNORED={'__pycache__','.git','.venv','node_modules'}


def _discover(source,names):
    resolved={}
    for skill_file in source.glob('*/SKILL.md'):
        match=re.search(r'^name:\s*[\"\']?([a-z0-9-]+)[\"\']?\s*$',
                        skill_file.read_text(encoding='utf-8'),re.M)
        if match and match[1] in names:
            if match[1] in resolved:
                raise ValueError('Duplicate source skill: '+match[1])
            resolved[match[1]]=skill_file.parent
    return resolved


def _files(folder):
    if folder.is_symlink():
        raise ValueError('Native source directories must not be symlinks: '+str(folder))
    for path in sorted(folder.rglob('*')):
        relative=path.relative_to(folder)
        if any(part in _IGNORED for part in relative.parts) or path.suffix=='.pyc':
            continue
        if path.is_symlink():
            raise ValueError('Native source files must not be symlinks: '+str(path))
        if path.is_file():
            yield relative,path


def _native_plans(resolved,names):
    canonical=resolved.get('literature-review')
    if canonical is None:
        raise ValueError('Native installation requires canonical literature-review scripts in --source')
    scripts=canonical/'scripts'
    for entry in (*COMMON_ENTRIES,*REVIEW_ENTRIES):
        if not (scripts/entry).is_file():
            raise ValueError('Missing canonical native entry: '+str(scripts/entry))
    core=scripts/'runtime/litreview_core'
    for module in REQUIRED_MODULES:
        if not (core/module).is_file():
            raise ValueError('Missing canonical native runtime module: '+str(core/module))
    if not (core/'contracts/__init__.py').is_file() or not list((core/'contracts').glob('*.schema.json')):
        raise ValueError('Missing canonical contracts runtime or schemas')
    runtime={Path('scripts/runtime')/relative:path.read_bytes() for relative,path in _files(scripts/'runtime')}
    entries={Path('scripts')/entry:(scripts/entry).read_bytes() for entry in (*COMMON_ENTRIES,*REVIEW_ENTRIES)}
    plans={}
    for name in names:
        folder=resolved[name]
        files={Path('SKILL.md'):(folder/'SKILL.md').read_bytes()}
        references=folder/'references'
        if not references.is_dir():
            raise ValueError('Missing selected skill references: '+str(references))
        files.update({Path('references')/relative:path.read_bytes() for relative,path in _files(references)})
        files.update(runtime)
        files.update({path:data for path,data in entries.items()
                      if name=='literature-review' or path.name not in REVIEW_ENTRIES})
        plans[name]=files
    return plans


def _exclusive_copy(source,destination):
    """Commit only into this transaction's exclusively reserved directories."""
    with source.open('rb') as reader,destination.open('xb') as writer:
        shutil.copyfileobj(reader,writer)
        writer.flush()
        os.fsync(writer.fileno())


def _install_native(plans,project,destination):
    # Freeze all source bytes before destination mutation, then stage all skills
    # before reserving any final directory. Keep ownership receipts for rollback.
    transaction=uuid4().hex
    project.mkdir(parents=True,exist_ok=True)
    created=[]
    with tempfile.TemporaryDirectory(prefix='.lr-stage-',dir=project.parent) as temporary:
        staging=Path(temporary).resolve()
        if staging.parent!=project.parent.resolve():
            raise ValueError('Staging escaped the intended project parent')
        for index,(name,files) in enumerate(plans.items()):
            stage=staging/str(index)
            stage.mkdir()
            for relative,data in files.items():
                path=stage/relative
                path.parent.mkdir(parents=True,exist_ok=True)
                path.write_bytes(data)
            manifest={'schema':'native-skill-installation/1','profile':NATIVE_PROFILE,
                'skill':name,'transaction_id':transaction,'status':'installed',
                'runtime_source_skill':'literature-review',
                'files':{p.as_posix():sha256(data).hexdigest() for p,data in sorted(files.items())},
                'excluded':['legacy assets','legacy harness scripts','legacy 0.7.0 requirements'],
                'model_inference':'not_tested','academic_quality':'not_tested','publication_verified':False}
            (stage/'native-installation.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
        try:
            for name in plans:
                target=destination/name
                target.mkdir(parents=True,exist_ok=False)
                try:
                    (target/'.native-install-owner').write_text(transaction,encoding='ascii')
                except BaseException:
                    target.rmdir()
                    raise
                created.append(target)
            for index,name in enumerate(plans):
                target=destination/name
                for relative,path in _files(staging/str(index)):
                    final=target/relative
                    final.parent.mkdir(parents=True,exist_ok=True)
                    _exclusive_copy(path,final)
        except BaseException as original:
            for target in reversed(created):
                try:
                    # Validate resolved absolute targets before recursive cleanup.
                    if (target.is_symlink() or target.resolve().parent!=destination.resolve()
                            or target.name not in plans
                            or (target/'.native-install-owner').read_text(encoding='ascii')!=transaction):
                        raise ValueError('Refusing rollback of an unowned path: '+str(target))
                    shutil.rmtree(target)
                except BaseException as cleanup:
                    original.add_note('Installation rollback: '+type(cleanup).__name__+': '+str(cleanup))
            raise


def install(source,project,harness,names=None):
    source,project=Path(source).resolve(),Path(project).resolve()
    names=list(names or NAMES)
    if harness not in TARGETS or any(name not in NAMES for name in names):
        raise ValueError('Unknown harness or skill')
    if harness=='deepagents' and len(set(names))!=len(names):
        raise ValueError('Duplicate selected skill')
    required=set(names)|({'literature-review'} if harness=='deepagents' else set())
    resolved=_discover(source,required)
    for name in required:
        if name not in resolved:
            raise ValueError('Missing source skill: '+name)
    for name in names:
        for location in TARGETS.values():
            target=project/location/name
            if target.exists() or target.is_symlink():
                raise ValueError('Duplicate skill installation: '+str(target))
    destination=project/TARGETS[harness]
    if harness=='deepagents':
        _install_native(_native_plans(resolved,names),project,destination)
    else:
        for name in names:
            shutil.copytree(resolved[name],destination/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    result={'harness':harness,'installed':names,'skills_root':str(destination),
        'native_runtime_verification':'not_performed','deepagents_sources_configuration_required':harness=='deepagents'}
    if harness=='deepagents':
        result.update(profile=NATIVE_PROFILE,model_inference='not_tested',academic_quality='not_tested',
                      publication_verified=False,canonical_runtime_source='literature-review')
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',required=True,help='Canonical skills root')
    parser.add_argument('--target',required=True,help='Project root; DeepAgents uses the resulting skills directory')
    parser.add_argument('--harness',choices=TARGETS,required=True)
    parser.add_argument('--skill',action='append',choices=NAMES)
    args=parser.parse_args(argv)
    try:
        result=install(args.source,args.target,args.harness,args.skill)
    except (ValueError,OSError) as exc:
        parser.exit(2,'Installation failed: '+str(exc)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
