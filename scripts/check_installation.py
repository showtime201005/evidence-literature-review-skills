"""Check selected installed skill entry points without model calls."""
import argparse,json,subprocess,sys
from pathlib import Path
NAMES=['analyze-paper','compare-papers','write-review','verify-citations','literature-review']
p=argparse.ArgumentParser();p.add_argument('--project',required=True);p.add_argument('--skill',action='append',choices=NAMES);a=p.parse_args()
if sys.version_info<(3,11):raise SystemExit('Python 3.11+ required')
root=Path(a.project).resolve()/'.opencode/skills';results=[]
for name in a.skill or NAMES:
    folder=root/name
    if not (folder/'SKILL.md').is_file():raise SystemExit('Missing skill: '+name)
    for entry in ['litreview.py','harness_runner.py']:
        r=subprocess.run([sys.executable,str(folder/'scripts'/entry),'--help'],cwd=a.project,capture_output=True,text=True)
        if r.returncode:raise SystemExit(r.stderr or r.stdout)
    results.append({'skill':name,'cli_import':'passed'})
print(json.dumps({'skills':results,'model_inference':'not_tested','academic_quality':'not_tested'},indent=2))
