from pathlib import Path
import sys
import unittest
import httpx
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/literature-review/scripts/runtime'))
from litreview_core.request_governor import RequestGovernor, ThroughputConfig, ContextCapacityError
from litreview_core.qwen_transport import OpenRouterJSONModel, ProviderGenerationError, create_model
from langchain_core.messages import HumanMessage, AIMessage


class TransportTests(unittest.TestCase):
    def test_http_rate_limit_diagnostics_redact_key_and_honor_retry_after(self):
        model = OpenRouterJSONModel(model='qwen/qwen3.8-27b', api_key='private-key')
        response = httpx.Response(429, request=httpx.Request('POST', 'https://example.invalid'),
            headers={'Retry-After': '90'}, json={'error': {'code': 429,
                'message': 'Limit for private-key', 'metadata': {'provider_name': 'test',
                    'raw': '{"error":{"message":"Token quota for private-key"}}'}}})
        governor = RequestGovernor(ThroughputConfig())
        with self.assertRaises(httpx.HTTPStatusError) as caught:
            with governor.request({'messages': [], 'max_tokens': 10}) as permit:
                model._response_data(response, permit)
        event = governor.snapshot()['events'][-1]
        self.assertEqual(event['http_status'], 429)
        self.assertEqual(event['retry_after'], '90')
        self.assertIn('Token quota', event['provider_error']['upstream_message'])
        self.assertNotIn('private-key', str(event['provider_error']))
        delay = model._retry_delay(caught.exception)
        self.assertGreaterEqual(delay, 90)
        self.assertLessEqual(delay, 90.3)

    def test_retry_delay_cannot_extend_original_deadline(self):
        governor = RequestGovernor(ThroughputConfig(deadline_seconds=1))
        with self.assertRaises(TimeoutError):
            governor.note_retry(RuntimeError('rate limited'), 90, attempt=2)
        snapshot = governor.snapshot()
        self.assertEqual(snapshot['transport_retries'], 0)
        self.assertEqual(snapshot['adaptive_events'][-1]['kind'], 'retry_exceeds_deadline')

    def test_only_exact_duplicate_plain_reasoning_is_removed_from_wire(self):
        model = OpenRouterJSONModel(model='qwen/qwen3.8-27b', api_key='offline')
        details = [{'type': 'reasoning.text', 'text': 'same text', 'index': 0},
                   {'type': 'reasoning.encrypted', 'data': 'opaque', 'index': 1}]
        message = AIMessage(content='scientific answer', additional_kwargs={
            'reasoning_content': 'same text', 'reasoning_details': details})
        wire = model._payload([message], None, {})['messages'][0]
        self.assertNotIn('reasoning', wire)
        self.assertEqual(wire['reasoning_details'], details)
        self.assertEqual(wire['content'], 'scientific answer')
        self.assertEqual(message.additional_kwargs['reasoning_content'], 'same text')
        message = AIMessage(content='answer', additional_kwargs={
            'reasoning_content': 'different text', 'reasoning_details': details})
        self.assertEqual(model._payload([message], None, {})['messages'][0]['reasoning'], 'different text')

    def test_reasoning_observation_does_not_infer_disabled_from_zero(self):
        model = OpenRouterJSONModel(model='qwen/qwen3.8-27b', api_key='offline')
        details = [{'type': 'reasoning.text', 'text': 'private reasoning', 'index': 0}]
        data = {'choices': [{'index': 0, 'finish_reason': 'stop', 'message': {
            'role': 'assistant', 'content': 'answer', 'reasoning_details': details}}],
            'usage': {'prompt_tokens': 4, 'completion_tokens': 5, 'total_tokens': 9,
                      'completion_tokens_details': {'reasoning_tokens': 0}}}
        governor = RequestGovernor(ThroughputConfig())
        with governor.request({'messages': [], 'max_tokens': 10}) as permit:
            result = model._result(data, permit)
        observed = permit.reasoning_observation
        self.assertEqual(observed, {'details_present': True, 'text_present': False,
                                   'reported_reasoning_tokens': 0, 'zero_with_details': True,
                                   'reported_completion_tokens': 5, 'reasoning_exceeds_completion': False})
        self.assertNotIn('private reasoning', str(observed))
        self.assertEqual(result.generations[0].message.additional_kwargs['reasoning_details'], details)
        self.assertEqual(governor.snapshot()['events'][-1]['reasoning_observation'], observed)

    def test_reasoning_observation_preserves_missing_usage_on_http_error(self):
        model = OpenRouterJSONModel(model='qwen/qwen3.8-27b', api_key='offline')
        permit = SimpleNamespace()
        response = httpx.Response(502, request=httpx.Request('POST', 'https://example.invalid'),
            json={'choices': [{'message': {'reasoning': 'private text'}}]})
        with self.assertRaises(httpx.HTTPStatusError):
            model._response_data(response, permit)
        self.assertEqual(permit.reasoning_observation, {
            'details_present': False, 'text_present': True,
            'reported_reasoning_tokens': None, 'zero_with_details': False,
            'reported_completion_tokens': None, 'reasoning_exceeds_completion': False})

    def test_inconsistent_provider_counts_are_observed_without_rewriting_usage(self):
        model = OpenRouterJSONModel(model='qwen/qwen3.8-27b', api_key='offline')
        permit = SimpleNamespace()
        usage = {'completion_tokens': 16384,
                 'completion_tokens_details': {'reasoning_tokens': 18349}, 'cost': 0}
        with self.assertRaises(ProviderGenerationError):
            model._result({'choices': [{'finish_reason': 'error'}], 'usage': usage}, permit)
        self.assertTrue(permit.reasoning_observation['reasoning_exceeds_completion'])
        self.assertEqual(permit.reasoning_observation['reported_completion_tokens'], 16384)
        self.assertEqual(permit.usage, usage)

    def test_explicit_low_effort_is_sent_without_unsupported_fixed_budget(self):
        with patch.dict('os.environ',{'OPENROUTER_API_KEY':'offline-test-key'}):
            model=create_model(reasoning_effort='low',max_tokens=16384)
        payload=model._payload([HumanMessage(content='q')],None,{})
        self.assertEqual(payload['reasoning'],{'enabled':True,'effort':'low'})
        self.assertEqual(payload['max_tokens'],16384)

    def test_observed_521_is_retryable_but_read_timeout_and_generation_are_not(self):
        response=httpx.Response(521,request=httpx.Request('POST','https://example.invalid/chat'))
        error=httpx.HTTPStatusError('origin failure',request=response.request,response=response)
        self.assertIsNotNone(OpenRouterJSONModel._retry_delay(error))
        self.assertIsNone(OpenRouterJSONModel._retry_delay(httpx.ReadTimeout('uncertain completion')))
        self.assertIsNone(OpenRouterJSONModel._retry_delay(ProviderGenerationError('incomplete output')))

    def test_reasoning_roundtrip_and_parent_tool_choice(self):
        model = OpenRouterJSONModel(model='qwen/qwen3.8-27b', api_key='offline',
            reasoning={'enabled': True}, max_tokens=4096)
        details = [{'type': 'reasoning.text', 'text': 'opaque provider detail', 'index': 0}]
        result = model._result({'id':'test', 'model':'qwen/qwen3.8-27b',
            'choices':[{'index':0,'finish_reason':'stop','message':{
                'role':'assistant','content':'answer','reasoning_details':details}}],
            'usage':{'prompt_tokens':4,'completion_tokens':5,'total_tokens':9}})
        payload = model._payload([HumanMessage(content='q'), result.generations[0].message,
                                  HumanMessage(content='continue')], None, {})
        self.assertEqual(payload['messages'][1]['reasoning_details'], details)
        self.assertTrue(payload['reasoning']['enabled'])
        self.assertEqual(payload['max_tokens'],4096)
        self.assertNotIn('tool_choice', payload)

    def test_hard_deadline_and_oversize(self):
        governor = RequestGovernor(ThroughputConfig(deadline_seconds=1))
        with patch('litreview_core.request_governor.time.monotonic', return_value=governor._started_at+2):
            with self.assertRaises(TimeoutError):
                governor.acquire({'messages':[], 'max_tokens':10})
        with self.assertRaises(ContextCapacityError):
            governor.reservation_for({'messages':[{'content':'x'*200001}], 'max_tokens':10})
        self.assertEqual(governor.snapshot()['active_requests'],0)

    def test_provider_failure_is_not_a_scientific_completion(self):
        model = OpenRouterJSONModel(model='qwen/qwen3.8-27b',api_key='offline')
        permit=SimpleNamespace()
        usage={'prompt_tokens':100,'completion_tokens':200,'total_tokens':300}
        with self.assertRaises(ProviderGenerationError):
            model._result({'id':'failed','provider':'test','usage':usage,
                           'choices':[{'finish_reason':'error'}]},permit)
        self.assertEqual(permit.usage,usage)
        self.assertEqual(permit.response_id,'failed')

    def test_only_explicit_failed_generation_is_retryable(self):
        model = OpenRouterJSONModel(model='qwen/qwen3.8-27b',api_key='offline')
        for data, retryable in (({'choices':[{'finish_reason':'error'}]},True),
                                ({'choices':[]},False)):
            with self.assertRaises(ProviderGenerationError) as caught:
                model._result(data)
            self.assertEqual(OpenRouterJSONModel._retry_delay(caught.exception) is not None,retryable)

    def test_explicit_generation_failure_has_only_one_retry(self):
        model = OpenRouterJSONModel(model='qwen/qwen3.8-27b',api_key='offline')
        failure=ProviderGenerationError('explicit provider failure',retryable=True)
        with patch.object(OpenRouterJSONModel,'_post',side_effect=failure) as post, \
             patch('litreview_core.qwen_transport.time.sleep'):
            with self.assertRaises(ProviderGenerationError):
                model._generate([HumanMessage(content='q')])
        self.assertEqual(post.call_count,2)

    def test_provider_error_diagnostic_retains_reason_without_key(self):
        model=OpenRouterJSONModel(model='qwen/qwen3.8-27b',api_key='private-test-key')
        with self.assertRaises(ProviderGenerationError) as caught:
            model._result({'error':{'code':400,'message':'Unsupported mode; key private-test-key'}})
        self.assertIn('Unsupported mode',str(caught.exception))
        self.assertIn('400',str(caught.exception))
        self.assertNotIn('private-test-key',str(caught.exception))
        self.assertFalse(caught.exception.retryable)


if __name__ == '__main__':
    unittest.main()
