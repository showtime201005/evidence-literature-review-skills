"""Check installed skill entry points without network or model calls."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

NAMES=['analyze-paper','compare-papers','write-review','verify-citations','literature-review']
TARGETS={'codex':'.agents/skills','claude-code':'.claude/skills','opencode':'.opencode/skills','deepagents':'skills'}
p=argparse.ArgumentParser()
p.add_argument('--project',required=True)
p.add_argument('--skill',action='append',choices=NAMES)
p.add_argument('--harness',choices=TARGETS,default='opencode')
p.add_argument('--tokenizer',type=Path)
p.add_argument('--skip-key-check',action='store_true')
a=p.parse_args()
if sys.version_info<(3,11):
    raise SystemExit('Python 3.11+ required')
root=Path(a.project).resolve()/TARGETS[a.harness]
if a.harness=='deepagents':
    if not a.tokenizer:
        p.error('--tokenizer is required for the native diagnostic')
    selected=a.skill or NAMES
    anchor='literature-review' if 'literature-review' in selected else selected[0]
    doctor=root/anchor/'scripts/native_doctor.py'
    if not doctor.is_file():
        raise SystemExit('Missing native doctor: '+str(doctor))
    command=[sys.executable,'-X','utf8',str(doctor),'--skills-root',str(root),'--tokenizer',str(a.tokenizer.resolve())]
    if a.skip_key_check:
        command.append('--skip-key-check')
    for name in selected:
        command.extend(['--skill',name])
    raise SystemExit(subprocess.run(command).returncode)
results=[]
for name in a.skill or NAMES:
    folder=root/name
    if not (folder/'SKILL.md').is_file():
        raise SystemExit('Missing skill: '+name)
    for entry in ['litreview.py','harness_runner.py']:
        r=subprocess.run([sys.executable,'-X','utf8',str(folder/'scripts'/entry),'--help'],
                         cwd=a.project,capture_output=True,text=True,encoding='utf-8')
        if r.returncode:
            raise SystemExit(r.stderr or r.stdout)
    results.append({'skill':name,'cli_import':'passed'})
print(json.dumps({'skills':results,'model_inference':'not_tested','academic_quality':'not_tested'},indent=2))
