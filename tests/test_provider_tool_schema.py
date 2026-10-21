"""Zero-API strict-tool wire tests using real LangChain/OpenRouter binding."""
from copy import deepcopy
import json
from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import patch

import httpx
from langchain_core.messages import HumanMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field, ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/literature-review/scripts/runtime'))
from litreview_core.provider_tool_schema import (STRICT_TOOL_MODE, project_cerebras_schema,
    project_submit_tools, schema_sha256)
from litreview_core.qwen_transport import create_model
from litreview_core.request_governor import ContextCapacityError, RequestGovernor, ThroughputConfig
from litreview_core.native_reading import reader_tool_schema


class ScientificData(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    status: str = Field(min_length=2)
    labels: list[str] = Field(min_length=1, max_length=3)


def function_tool(schema=None, name='submit_result'):
    return {'type': 'function', 'function': {'name': name, 'description': 'Offline tool',
        'parameters': schema or ScientificData.model_json_schema()}}


class ProviderToolSchemaTests(unittest.TestCase):
    def setUp(self):
        self.network = patch.object(socket.socket, 'connect', side_effect=AssertionError('Network forbidden'))
        self.network.start()
        self.env = patch.dict('os.environ', {'OPENROUTER_API_KEY': 'offline-test-key'})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.network.stop()

    def model(self, **kwargs):
        options = dict(force_submit=True, strict_tool_mode=STRICT_TOOL_MODE,
            provider_preferences={'only': ['cerebras'], 'allow_fallbacks': False},
            governor=RequestGovernor(ThroughputConfig()))
        options.update(kwargs)
        return create_model(**options)

    def test_ast_preserves_same_named_scientific_properties_and_data(self):
        schema = {'type': 'object', 'additionalProperties': False,
            'properties': {
                'minLength': {'type': 'string', 'minLength': 3},
                'required': {'type': 'array', 'items': {'type': 'string'}, 'uniqueItems': True},
                'pattern': {'type': 'string', 'enum': ['minLength', 'maxItems'],
                    'default': {'minLength': 9, 'properties': {'pattern': 'scientific data'}}},
                'items': {'anyOf': [{'type': 'string', 'pattern': '^s'}, {'type': 'null'}]},
                'values': {'type': 'array', 'minItems': 1, 'maxItems': 2,
                    'items': {'type': 'integer', 'minimum': 1, 'maximum': 10}}},
            'required': ['minLength', 'required', 'pattern', 'items', 'values']}
        original = deepcopy(schema)
        projected, audit = project_cerebras_schema(schema)
        self.assertEqual(schema, original)
        self.assertEqual(set(projected['properties']), set(schema['properties']))
        self.assertEqual(projected['required'], schema['required'])
        self.assertEqual(projected['properties']['pattern'], schema['properties']['pattern'])
        self.assertEqual(projected['properties']['values']['items'], schema['properties']['values']['items'])
        self.assertEqual(audit['removed_json_paths'], [
            '/properties/items/anyOf/0/pattern', '/properties/minLength/minLength',
            '/properties/required/uniqueItems', '/properties/values/maxItems', '/properties/values/minItems'])
        self.assertEqual(audit['canonical_schema_sha256'], schema_sha256(original))
        self.assertEqual(audit['projected_schema_sha256'], schema_sha256(projected))

    def test_unsafe_structural_keywords_open_objects_and_external_refs_fail_closed(self):
        for extra in ({'allOf': [{'properties': {'science': {'enum': ['important']}}}]},
                {'oneOf': [{'required': ['science']}]}, {'if': {'type': 'object'}},
                {'$ref': 'https://example.invalid/schema'}, {'nullable': True}, {'additionalProperties': True}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                project_cerebras_schema({'type': 'object', 'properties': {},
                    'additionalProperties': False, **extra})
        with self.assertRaisesRegex(ValueError, 'Recursive'):
            project_cerebras_schema({'type': 'object', 'properties': {}, 'additionalProperties': False,
                '$defs': {'cycle': {'$ref': '#/$defs/cycle'}}})

    def test_local_defs_ast_and_json_pointer_escaping(self):
        schema = {'type': 'object', 'properties': {'a/b~c': {'$ref': '#/$defs/detail'}},
            'additionalProperties': False, '$defs': {'detail': {'type': 'string', 'maxLength': 2}}}
        projected, audit = project_cerebras_schema(schema)
        self.assertEqual(projected['$defs']['detail'], {'type': 'string'})
        self.assertEqual(audit['removed_json_paths'], ['/$defs/detail/maxLength'])
        schema['properties']['a/b~c'] = {'type': 'string', 'minLength': 1}
        self.assertIn('/properties/a~1b~0c/minLength', project_cerebras_schema(schema)[1]['removed_json_paths'])

    def test_only_submit_is_projected_and_canonical_host_gate_is_unchanged(self):
        tools = [function_tool(), function_tool(name='read_file')]
        original = deepcopy(tools)
        projected, audit = project_submit_tools(tools)
        self.assertEqual(tools, original)
        self.assertEqual(projected[1], original[1])
        self.assertTrue(projected[0]['function']['strict'])
        self.assertNotIn('minLength', projected[0]['function']['parameters']['properties']['status'])
        self.assertIn('minLength', original[0]['function']['parameters']['properties']['status'])
        with self.assertRaises(ValidationError):
            ScientificData.model_validate({'status': 'x', 'labels': []}, strict=True)
        with self.assertRaises(ValueError):
            project_submit_tools([function_tool(), function_tool()])
        strict_other = function_tool(name='read_file')
        strict_other['function']['strict'] = True
        with self.assertRaisesRegex(ValueError, 'Only submit_result'):
            project_submit_tools([function_tool(), strict_other])
        self.assertNotEqual(audit['canonical_schema_sha256'], audit['projected_schema_sha256'])

    def test_off_wire_matches_legacy_binding_exactly(self):
        a = create_model(force_submit=True)
        b = create_model(force_submit=True, strict_tool_mode='off')
        tool = StructuredTool.from_function(lambda **kw: kw, name='submit_result',
            description='Offline', args_schema=ScientificData)
        left = a._payload([HumanMessage(content='same')], None, a.bind_tools([tool]).kwargs)
        right = b._payload([HumanMessage(content='same')], None, b.bind_tools([tool]).kwargs)
        self.assertEqual(left, right)
        self.assertEqual(left['tool_choice'], {'type': 'function', 'function': {'name': 'submit_result'}})
        self.assertNotIn('strict', left['tools'][0]['function'])
        self.assertNotIn('metadata', left)
        self.assertNotIn('parallel_tool_calls', left)
        self.assertEqual(a.tool_schema_audits, {})

    def test_real_sdk_bind_to_mock_http_retains_audit_and_usage(self):
        captured = []
        counted = []
        def count(payload):
            counted.append(deepcopy(payload))
            return len(json.dumps(payload, ensure_ascii=False))
        governor = RequestGovernor(ThroughputConfig(token_counter=count))
        model = self.model(governor=governor, max_tokens=2048)
        submit = StructuredTool.from_function(lambda **kw: kw, name='submit_result',
            description='Offline', args_schema=ScientificData.model_json_schema())
        other = StructuredTool.from_function(lambda text: text, name='read_file', description='Offline read')
        def respond(request):
            captured.append(json.loads(request.content))
            return httpx.Response(200, json={'id': 'offline-response', 'provider': 'Cerebras',
                'model': 'qwen/qwen3.8-27b', 'choices': [{'index': 0, 'finish_reason': 'tool_calls',
                'message': {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 't1',
                    'type': 'function', 'function': {'name': 'submit_result',
                    'arguments': '{"status":"ok","labels":["a"]}'}}]}}],
                'usage': {'prompt_tokens': 12, 'completion_tokens': 8, 'total_tokens': 20, 'cost': 0}})
        with httpx.Client(transport=httpx.MockTransport(respond)) as client, patch(
                'litreview_core.qwen_transport._HTTP_CLIENTS.sync_client', return_value=client):
            result = model.bind_tools([submit, other]).invoke([HumanMessage(content='Scientific source')])
        self.assertEqual(len(captured), 1)
        wire = captured[0]
        self.assertEqual(wire, counted[-1])
        self.assertTrue(wire['tools'][0]['function']['strict'])
        self.assertNotIn('strict', wire['tools'][1]['function'])
        self.assertFalse(wire['parallel_tool_calls'])
        self.assertFalse(wire['provider']['allow_fallbacks'])
        self.assertTrue(wire['provider']['require_parameters'])
        self.assertEqual(wire['provider']['only'], ['cerebras/fp16'])
        self.assertEqual(wire['metadata']['tool_schema_mode'], STRICT_TOOL_MODE)
        audit = result.response_metadata['tool_schema_projection']
        self.assertEqual(audit['projected_schema_sha256'], schema_sha256(wire['tools'][0]['function']['parameters']))
        self.assertTrue(audit['removed_json_paths'])
        self.assertEqual(result.response_metadata['token_usage']['cost'], 0)
        event = governor.snapshot()['events'][-1]
        self.assertEqual(event['reservation'], len(json.dumps(wire, ensure_ascii=False)) + 2048 + 8000)
        self.assertEqual(event['response_id'], 'offline-response')
        audits = model.tool_schema_audits
        audits.clear()
        self.assertTrue(model.tool_schema_audits)

    def test_actual_reader_schema_bind_is_supported_without_altering_original(self):
        model = self.model(max_tokens=2048)
        schema = reader_tool_schema()
        original = deepcopy(schema)
        submit = StructuredTool.from_function(lambda **kw: kw, name='submit_result',
            description='Full scientific reader', args_schema=schema)
        wire = model._payload([HumanMessage(content='original')], None, model.bind_tools([submit]).kwargs)
        self.assertTrue(wire['tools'][0]['function']['strict'])
        self.assertEqual(schema, original)
        self.assertTrue(model.tool_schema_audits)

    def test_sdk_open_schema_is_not_silently_closed_by_projection(self):
        # Current StructuredTool Pydantic-class conversion drops the model's
        # top-level extra=forbid. Production raw-dict schemas retain it.
        model = self.model()
        submit = StructuredTool.from_function(lambda **kw: kw, name='submit_result',
            description='Offline', args_schema=ScientificData)
        with self.assertRaisesRegex(ValueError, 'additionalProperties=False'):
            model._payload([HumanMessage(content='x')], None, model.bind_tools([submit]).kwargs)

    def test_strict_mode_rejects_unknown_routes_fallbacks_and_bypass(self):
        for provider in (None, {}, {'only': ['cerebras']},
                {'only': ['cerebras'], 'allow_fallbacks': True},
                {'only': ['cerebras/fp8'], 'allow_fallbacks': False},
                {'only': ['modelrun'], 'allow_fallbacks': False},
                {'only': ['cerebras', 'deepinfra'], 'allow_fallbacks': False}):
            with self.subTest(provider=provider), self.assertRaises(ValueError):
                self.model(provider_preferences=provider)
        for options in ({'force_submit': False}, {'governor': None}, {'strict_tool_mode': 'strict'}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.model(**options)
        model = self.model()
        kwargs = model.bind_tools([function_tool()]).kwargs
        for override in ({'provider': {'only': ['deepinfra'], 'allow_fallbacks': False}},
                         {'response_format': {'type': 'json_object'}}, {'model': 'another-model'}):
            with self.subTest(override=override), self.assertRaises(ValueError):
                model._payload([HumanMessage(content='x')], None, {**kwargs, **override})

    def test_complete_projected_request_obeys_endpoint_and_global_budget(self):
        model = self.model()
        kwargs = model.bind_tools([function_tool()]).kwargs
        for length in (60_000, 200_001):
            with self.subTest(length=length), self.assertRaises(ContextCapacityError):
                model._payload([HumanMessage(content='x' * length)], None, kwargs)
        with self.assertRaises(ContextCapacityError):
            model._payload([HumanMessage(content='x')], None, {**kwargs, 'max_tokens': 32769})
        self.assertEqual(model._request_governor.snapshot()['active_requests'], 0)


if __name__ == '__main__':
    unittest.main()
