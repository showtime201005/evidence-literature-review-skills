"""Validate our published schema subset without runtime third-party dependencies.

Not a general JSON Schema implementation. Fail closed on unknown keywords.
The exported schemas can also be validated by a Draft 2020-12 implementation.
"""
from importlib.resources import files
import json
import re
from ..errors import ReviewError

SCHEMA = json.loads(files(__package__).joinpath('contracts.schema.json').read_text())
SCHEMA2 = json.loads(files(__package__).joinpath('contracts-v2.schema.json').read_text())
KEYWORDS = {'$schema','$id','$defs','$ref','type','const','enum','required','properties',
            'additionalProperties','items','minItems','minLength','minimum','maximum','pattern','anyOf'}


def _errors(value, rule, path='$', schema=None):
    schema = schema or SCHEMA
    unknown = set(rule) - KEYWORDS
    if unknown:
        raise ReviewError('UNSUPPORTED_SCHEMA', 'Unsupported schema keyword', sorted(unknown))
    if '$ref' in rule:
        name = rule['$ref'].removeprefix('#/$defs/')
        yield from _errors(value, schema['$defs'][name], path, schema)
        return
    if 'anyOf' in rule:
        variants = [list(_errors(value, item, path, schema)) for item in rule['anyOf']]
        if all(variants):
            yield path + ': no matching alternative'
        return
    if 'const' in rule and (type(value) is not type(rule['const']) or value != rule['const']):
        yield path + ': incorrect constant'
    if 'enum' in rule and value not in rule['enum']:
        yield path + ': invalid enum value'
    kind = rule.get('type')
    types = {'object':dict,'array':list,'string':str,'integer':int,'number':(int,float),'boolean':bool}
    if kind and (not isinstance(value,types[kind]) or (kind in ('integer','number') and isinstance(value,bool))):
        yield path + ': expected ' + kind
        return
    if isinstance(value,dict):
        for field in rule.get('required',[]):
            if field not in value:
                yield path + ': missing ' + field
        properties=rule.get('properties',{})
        for field,item in value.items():
            spec=properties.get(field,rule.get('additionalProperties',True))
            if spec is False:
                yield path+'.'+field+': unexpected field'
            elif isinstance(spec,dict):
                yield from _errors(item,spec,path+'.'+field,schema)
    if isinstance(value,list):
        if len(value)<rule.get('minItems',0):
            yield path+': too few items'
        for i,item in enumerate(value):
            yield from _errors(item,rule.get('items',{}),f'{path}[{i}]',schema)
    if isinstance(value,str):
        if len(value)<rule.get('minLength',0):
            yield path+': string too short'
        if 'pattern' in rule and not re.search(rule['pattern'],value):
            yield path+': pattern mismatch'
    if isinstance(value,(int,float)) and not isinstance(value,bool):
        if 'minimum' in rule and value<rule['minimum']:
            yield path+': below minimum'
        if 'maximum' in rule and value>rule['maximum']:
            yield path+': above maximum'


def validate_object(kind,value,version='1.0.0'):
    if not isinstance(version,str) or not (re.fullmatch(r'1\.\d+\.\d+',version) or version=='2.0.0'):
        raise ReviewError('UNSUPPORTED_SCHEMA_VERSION','Supported schemas are 1.x and 2.0.0',version)
    schema=SCHEMA2 if version=='2.0.0' else SCHEMA
    if kind not in schema['$defs']:
        raise ReviewError('UNKNOWN_ARTIFACT_TYPE','Unknown public contract',kind)
    errors=list(_errors(value,schema['$defs'][kind],schema=schema))
    if errors:
        raise ReviewError('SCHEMA_INVALID','Contract validation failed',errors)
    return value


def validate(artifact):
    if not isinstance(artifact,dict):
        raise ReviewError('SCHEMA_INVALID','Artifact must be an object')
    version=artifact.get('schema_version','')
    if not isinstance(version,str) or not (re.fullmatch(r'1\.\d+\.\d+',version) or version=='2.0.0'):
        raise ReviewError('UNSUPPORTED_SCHEMA_VERSION','Supported schemas are 1.x and 2.0.0',version)
    for key in ('artifact_id','artifact_type','payload'):
        if key not in artifact:
            raise ReviewError('SCHEMA_INVALID','Missing envelope field',key)
    if not isinstance(artifact['artifact_id'],str) or not artifact['artifact_id']:
        raise ReviewError('SCHEMA_INVALID','artifact_id must be a nonempty string')
    if 'producer' in artifact and not isinstance(artifact['producer'],dict):
        raise ReviewError('SCHEMA_INVALID','producer must be an object')
    schema=SCHEMA2 if version=='2.0.0' else SCHEMA
    allowed = {r['properties']['artifact_type']['const'] for r in schema['anyOf']}
    if not isinstance(artifact['artifact_type'],str) or artifact['artifact_type'] not in allowed:
        raise ReviewError('UNKNOWN_ARTIFACT_TYPE','Not an envelope artifact',artifact['artifact_type'])
    validate_object(artifact['artifact_type'],artifact['payload'],version)
    if version=='2.0.0':
        from ..capabilities import check_invariants
        check_invariants(artifact)
    return artifact


def migrate(artifact,target='1.0.0'):
    """Only identity migration exists in v0.1; never guess cross-major semantics."""
    validate(artifact)
    if artifact['schema_version']!=target:
        raise ReviewError('MIGRATION_UNAVAILABLE','No registered migration',{'from':artifact['schema_version'],'to':target})
    return artifact
