"""Provider-independent mailbox transport. No undocumented vendor API calls."""
from pathlib import Path
from .artifacts import read_json,write_json,safe_path
from .contracts import validate
from .errors import ReviewError

HARNESSES=('codex','claude-code','opencode','deepagents')


def check_capabilities(harness,probe):
    if harness not in HARNESSES:
        raise ReviewError('UNKNOWN_HARNESS','Unsupported harness',harness)
    required=('read_files','write_files','python','model_analysis')
    missing=[name for name in required if probe.get(name) is not True]
    return {'harness':harness,'version':probe.get('version','unknown'),
        'status':'blocked' if missing else 'ready','missing':missing,
        'transport':'file_mailbox','parallelism':max(1,int(probe.get('max_workers',1))) if probe.get('independent_contexts') else 1,
        'verification_context_policy':'Require a separate task context for writer and verifier; if unavailable, publication is blocked',
        'native_vendor_api_validation':'not_performed','path_mapping':probe.get('path_mapping',{}),
        'cancel':bool(probe.get('cancel',False)),'usage_reporting':bool(probe.get('usage',False))}


class MailboxAdapter:
    """dispatch/collect/capabilities/cancel with the same contract on all harnesses.

    The running harness consumes requests and runs model skills. dispatch does
    not secretly invoke a shell command, provider SDK or model endpoint.
    """
    def __init__(self,root,harness,probe):
        self.root=Path(root);self._capabilities=check_capabilities(harness,probe)

    def capabilities(self):return self._capabilities

    def dispatch(self,task):
        validate(task)
        if self._capabilities['status']!='ready':
            raise ReviewError('HARNESS_BLOCKED','Required execution capabilities missing',self._capabilities)
        if task['artifact_type']!='TaskSpec':
            raise ReviewError('WRONG_ARTIFACT_TYPE','dispatch expects TaskSpec')
        tid=task['payload']['task_id']
        path=safe_path(self.root/'requests',tid+'.json');write_json(path,task)
        return {'task_id':tid,'status':'pending','request_path':str(path)}

    def collect(self,task_id):
        path=safe_path(self.root/'results',task_id+'.json')
        if not path.exists():return {'task_id':task_id,'status':'pending'}
        result=validate(read_json(path))
        if result['artifact_type']!='TaskResult' or result['payload']['task_id']!=task_id:
            raise ReviewError('TASK_MISMATCH','Mailbox result belongs to another task')
        return result

    def cancel(self,task_id):
        if not self._capabilities['cancel']:
            raise ReviewError('CANCEL_UNSUPPORTED','Harness did not advertise cancellation')
        write_json(safe_path(self.root/'cancellations',task_id+'.json'),{'task_id':task_id,'status':'cancel_requested'})
        return {'task_id':task_id,'status':'cancel_requested'}
