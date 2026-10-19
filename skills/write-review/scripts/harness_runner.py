#!/usr/bin/env python3
"""Run this skill independently, or the full suite, in a pinned native harness."""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent/'runtime'))


def main():
    from litreview_core.deepagents070 import NAMES
    from litreview_core.errors import ReviewError
    from litreview_core.artifacts import write_json
    p=argparse.ArgumentParser()
    p.add_argument('--harness',choices=['deepagents','opencode'],required=True)
    p.add_argument('--skill',choices=NAMES,required=True)
    p.add_argument('--workspace',required=True);p.add_argument('--skills-root',required=True)
    p.add_argument('--request-file');p.add_argument('--diagnose',action='store_true')
    p.add_argument('--result-file',required=True);p.add_argument('--opencode-bin',default='opencode')
    p.add_argument('--timeout',type=int,default=1800,help='OpenCode process deadline in seconds; DeepAgents uses its per-tool timeout and recursion limit')
    a=p.parse_args()
    if not a.diagnose and not a.request_file:p.error('Supply --request-file or --diagnose')
    try:
        if a.harness=='deepagents':
            from litreview_core.deepagents070 import native_diagnostics,create_skill_agent,model_from_environment
            if a.diagnose:result=native_diagnostics(a.workspace,a.skills_root,a.skill)
            else:
                agent=create_skill_agent(a.skill,model_from_environment(),a.workspace,a.skills_root)
                value=agent.invoke({'messages':[{'role':'user','content':Path(a.request_file).read_text(encoding='utf-8')}]},config={'recursion_limit':300,'max_concurrency':1})
                result={'status':'completed','final_response':value['messages'][-1].content,'academic_quality':'check_artifact_gates'}
        else:
            from litreview_core.opencode import version,run
            if a.diagnose:
                result={'opencode_version':version(a.opencode_bin),'model_call_performed':False,'academic_quality':'not_tested'}
            else:result=run(Path(a.request_file).read_text(encoding='utf-8'),a.workspace,a.skills_root,a.skill,a.opencode_bin,a.timeout)
    except ReviewError as exc:result={'status':'blocked','error':exc.as_dict(),'resume':'Source artifacts and reading checkpoints remain on disk.'}
    write_json(a.result_file,result);print(json.dumps(result,ensure_ascii=False,indent=2))
    return 2 if result.get('status') in ('blocked','failed','timeout') else 0


if __name__=='__main__':raise SystemExit(main())
