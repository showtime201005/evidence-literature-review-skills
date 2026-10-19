"""Install selected self-contained skills; never overwrite an existing skill."""
import argparse
import json
import re
from pathlib import Path
import shutil
import sys

NAMES=['analyze-paper','compare-papers','write-review','verify-citations','literature-review']
TARGETS={'codex':'.agents/skills','claude-code':'.claude/skills','opencode':'.opencode/skills','deepagents':'skills'}
parser=argparse.ArgumentParser();parser.add_argument('--source',required=True,help='Canonical skills root')
parser.add_argument('--target',required=True,help='Project root; Deep Agents must explicitly configure the resulting skills directory')
parser.add_argument('--harness',choices=TARGETS,required=True);parser.add_argument('--skill',action='append',choices=NAMES)
args=parser.parse_args();source=Path(args.source).resolve();project=Path(args.target).resolve();names=args.skill or NAMES
# Discover by frontmatter too: managed Skills workspaces may use stable-ID folders.
resolved={}
for skill_file in source.glob('*/SKILL.md'):
    match=re.search(r'^name:\s*[\"\']?([a-z0-9-]+)[\"\']?\s*$',skill_file.read_text(),re.M)
    if match and match[1] in names:
        if match[1] in resolved:raise SystemExit('Duplicate source skill: '+match[1])
        resolved[match[1]]=skill_file.parent
# Preflight all copies before creating any output.
for name in names:
    if name not in resolved:raise SystemExit('Missing source skill: '+name)
    for target in TARGETS.values():
        path=project/target/name
        if path.exists():raise SystemExit('Duplicate skill installation: '+str(path))
for name in names:
    shutil.copytree(resolved[name],project/TARGETS[args.harness]/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
print(json.dumps({'harness':args.harness,'installed':names,'skills_root':str(project/TARGETS[args.harness]),
    'native_runtime_verification':'not_performed','deepagents_sources_configuration_required':args.harness=='deepagents'},indent=2))
