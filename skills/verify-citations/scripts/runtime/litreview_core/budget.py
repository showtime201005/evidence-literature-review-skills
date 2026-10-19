"""Model-independent budget checks; no tokenizer download or provider calls."""
from dataclasses import dataclass
import json
from .errors import ReviewError


@dataclass(frozen=True)
class ContextBudget:
    context_tokens: int = 200000
    input_tokens: int = 120000
    output_tokens: int = 8192
    safety_tokens: int = 24000

    def __post_init__(self):
        for name in ('context_tokens','input_tokens','output_tokens','safety_tokens'):
            value=getattr(self,name)
            if type(value) is not int or value<=0:
                raise ReviewError('BUDGET_INVALID',name+' must be a positive integer')
        if self.input_tokens+self.output_tokens+self.safety_tokens>self.context_tokens:
            raise ReviewError('BUDGET_INVALID','Input, output and safety budgets exceed the context window')

    def check(self,messages,tools=None,counter=None,output_tokens=None,extras=None):
        output=self.output_tokens if output_tokens is None else output_tokens
        if type(output) is not int or output<=0 or output>self.output_tokens:
            raise ReviewError('OUTPUT_BUDGET_EXCEEDED','Requested output exceeds configured maximum')
        if counter is not None:
            count=counter(messages,tools or [])
            if type(count) is not int or count<0:
                raise ReviewError('TOKEN_COUNTER_INVALID','Counter must return a nonnegative integer')
            kind='supplied_chat_template_counter'
            # Request-level structured-output schemas may not be in tools.
            if extras:
                count+=len(json.dumps(extras,ensure_ascii=False,default=str).encode('utf-8'))
        else:
            # UTF-8-byte estimate avoids the misleading chars/4 approximation
            # for Chinese and code. This is NOT certified Qwen tokenization.
            text=json.dumps({'messages':messages,'tools':tools or [],'extras':extras or {}},ensure_ascii=False,default=str)
            count=len(text.encode('utf-8'))+32*len(messages)+256
            kind='utf8_byte_estimate_not_exact_tokens'
        result={'input_count':count,'counting_method':kind,'input_limit':self.input_tokens,
                'output_limit':output,'safety_tokens':self.safety_tokens,'context_limit':self.context_tokens}
        if count>self.input_tokens or count+output+self.safety_tokens>self.context_tokens:
            raise ReviewError('CONTEXT_BUDGET_EXCEEDED','Split the task or resume in a fresh context; source content must not be silently truncated',result)
        return result


def local_tokenizer_counter(directory):
    """Use only a pre-existing company tokenizer and its actual chat template.

    transformers is optional. No remote model/tokenizer ID is downloaded.
    The company must confirm that these assets match its served model.
    """
    from pathlib import Path
    path=Path(directory).expanduser().resolve()
    if not path.is_dir():
        raise ReviewError('TOKENIZER_MISSING','Local tokenizer directory does not exist')
    try:
        from transformers import AutoTokenizer
    except ImportError as exc:
        raise ReviewError('TOKENIZER_DEPENDENCY_MISSING','Install company-approved transformers to use local tokenizer assets') from exc
    tokenizer=AutoTokenizer.from_pretrained(str(path),local_files_only=True,trust_remote_code=False)
    def count(messages,tools):
        kwargs={'tokenize':True,'add_generation_prompt':True}
        if tools:kwargs['tools']=tools
        ids=tokenizer.apply_chat_template(messages,**kwargs)
        if isinstance(ids,dict):ids=ids['input_ids']
        if not isinstance(ids,list) or (ids and isinstance(ids[0],list)):
            raise ReviewError('TOKEN_COUNTER_INVALID','Expected one flat token ID list from chat template')
        return len(ids)
    return count
