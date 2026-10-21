"""Explicit Cerebras Qwen strict-tool candidate; never a host-schema rewrite.

Official subset (checked 2026-10-21):
https://inference-docs.cerebras.ai/capabilities/structured-outputs
https://inference-docs.cerebras.ai/capabilities/tool-use

Only scalar validation keywords can be removed. Unsupported composition is
rejected, since removing its children could discard scientific fields/enums.
Provider acceptance/quality still requires an actual isolated experiment.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json

STRICT_TOOL_MODE = 'strict-supported-subset/1'

# Unlisted keywords are unsupported in the provider's published subset. These
# assertions contain no property schemas, so removing them preserves all fields.
REMOVABLE_VALIDATION_KEYWORDS = frozenset({
    'minLength', 'maxLength', 'pattern', 'format', 'minItems', 'maxItems',
    'uniqueItems', 'minProperties', 'maxProperties',
})
_SUPPORTED = frozenset({
    'type', 'properties', 'required', 'additionalProperties', 'items', 'prefixItems',
    'anyOf', '$defs', '$ref', 'enum', 'const', 'minimum', 'maximum',
    'exclusiveMinimum', 'exclusiveMaximum', 'multipleOf',
    'description', 'title', '$schema', 'default',
})


def schema_sha256(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def _pointer(path, key):
    return path + '/' + str(key).replace('~', '~0').replace('/', '~1')


def validate_strict_provider(provider):
    """No auto route, fallback, unknown variant, or broader base inheritance."""
    if (not isinstance(provider, dict) or provider.get('allow_fallbacks') is not False
            or provider.get('only') not in (['cerebras'], ['cerebras/fp16'])):
        raise ValueError(STRICT_TOOL_MODE + ' requires explicit only=[cerebras] '
            'or only=[cerebras/fp16] and allow_fallbacks=False')
    if 'order' in provider and provider['order'] not in ([], ['cerebras'], ['cerebras/fp16']):
        raise ValueError('Strict tool mode cannot order an unverified or non-Cerebras route')


def project_cerebras_schema(schema):
    """Return a fresh wire schema and a complete, deterministic host audit.

    Traversal follows schema positions, not arbitrary JSON dictionaries. In
    particular property names, enum literals and annotation/default data are
    never interpreted as schema keywords. Open objects and unsafe constructs
    fail closed rather than silently adding constraints or losing their fields.
    """
    if not isinstance(schema, dict) or schema.get('type') != 'object' or not isinstance(schema.get('properties'), dict):
        raise ValueError('Strict submit_result parameters must be an object with properties')
    removed = []

    def visit(node, path):
        if not isinstance(node, dict):
            raise ValueError('Expected a JSON Schema object at ' + (path or '/'))
        unknown = set(node) - _SUPPORTED - REMOVABLE_VALIDATION_KEYWORDS
        if unknown:
            raise ValueError('Unsafe/unsupported strict schema keywords at ' + (path or '/')
                + ': ' + ', '.join(sorted(unknown)))
        if ('properties' in node or node.get('type') == 'object') and node.get('additionalProperties') is not False:
            raise ValueError('Strict object requires existing additionalProperties=False at ' + (path or '/'))
        if node.get('type') == 'array':
            if not (isinstance(node.get('items'), dict) or
                    node.get('items') is False and isinstance(node.get('prefixItems'), list)):
                raise ValueError('Strict array requires items schema or prefixItems/items=False at ' + path)
        out = {}
        for key, value in node.items():
            here = _pointer(path, key)
            if key in REMOVABLE_VALIDATION_KEYWORDS:
                removed.append(here)
            elif key in ('properties', '$defs'):
                if not isinstance(value, dict):
                    raise ValueError('Expected schema-name map at ' + here)
                out[key] = {name: visit(child, _pointer(here, name)) for name, child in value.items()}
            elif key in ('anyOf', 'prefixItems'):
                if not isinstance(value, list) or not value:
                    raise ValueError('Expected nonempty schema list at ' + here)
                out[key] = [visit(child, _pointer(here, i)) for i, child in enumerate(value)]
            elif key == 'items' and isinstance(value, dict):
                out[key] = visit(value, here)
            elif key == '$ref':
                if not isinstance(value, str) or not value.startswith('#/$defs/'):
                    raise ValueError('Only local nonrecursive $defs references are supported at ' + here)
                out[key] = value
            else:
                out[key] = deepcopy(value)
        return out

    projected = visit(schema, '')
    if 'anyOf' in projected:
        raise ValueError('Strict root anyOf is unsupported')
    # Resolve references and reject recursion; never drop the referenced science.
    def resolve(ref):
        value = schema
        for part in ref[2:].split('/'):
            part = part.replace('~1', '/').replace('~0', '~')
            if not isinstance(value, dict) or part not in value:
                raise ValueError('Unknown local schema reference: ' + ref)
            value = value[part]
        return value

    def check_refs(node, stack=()):
        if '$ref' in node:
            ref = node['$ref']
            if ref in stack:
                raise ValueError('Recursive strict schema reference: ' + ref)
            check_refs(resolve(ref), stack + (ref,))
        for key in ('properties', '$defs'):
            for child in node.get(key, {}).values():
                check_refs(child, stack)
        for key in ('anyOf', 'prefixItems'):
            for child in node.get(key, []):
                check_refs(child, stack)
        if isinstance(node.get('items'), dict):
            check_refs(node['items'], stack)

    check_refs(schema)
    removed.sort()
    return projected, {'mode': STRICT_TOOL_MODE,
        'canonical_schema_sha256': schema_sha256(schema),
        'projected_schema_sha256': schema_sha256(projected),
        'removed_json_paths': removed,
        'removed_json_paths_sha256': schema_sha256(removed)}


def project_submit_tools(tools):
    """Project exactly one formatted submit_result; other tools are verbatim."""
    if not isinstance(tools, list):
        raise ValueError('Strict tool mode requires a tools list')
    result = deepcopy(tools)
    matches = [tool for tool in result if isinstance(tool, dict)
        and tool.get('type') == 'function'
        and isinstance(tool.get('function'), dict)
        and tool['function'].get('name') == 'submit_result']
    if len(matches) != 1:
        raise ValueError('Strict tool mode requires exactly one submit_result function')
    if any(isinstance(tool, dict) and isinstance(tool.get('function'), dict)
            and tool['function'].get('name') != 'submit_result'
            and tool['function'].get('strict') is True for tool in result):
        raise ValueError('Only submit_result may use strict in this candidate')
    function = matches[0]['function']
    function['parameters'], audit = project_cerebras_schema(function.get('parameters'))
    function['strict'] = True
    return result, audit


def audit_request_metadata(audit):
    """Legal OpenRouter string metadata; full JSON paths stay in host audit."""
    return {'tool_schema_mode': audit['mode'],
        'canonical_schema_sha256': audit['canonical_schema_sha256'],
        'projected_schema_sha256': audit['projected_schema_sha256'],
        'removed_json_paths_sha256': audit['removed_json_paths_sha256'],
        'removed_json_paths_count': str(len(audit['removed_json_paths']))}
