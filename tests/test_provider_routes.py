"""Pinned route admission only; no endpoint or paid model calls."""
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'skills/literature-review/scripts/runtime'))
from langchain_core.messages import HumanMessage
from litreview_core.provider_routes import ROUTES,CATALOG_FETCHED_UTC,CATALOG_RESPONSE_SHA256,resolve_routes
from litreview_core.request_governor import ContextCapacityError,RequestGovernor,ThroughputConfig
from litreview_core.qwen_transport import OpenRouterJSONModel


class ProviderRouteTests(unittest.TestCase):
    def setUp(self):
        self.governor=RequestGovernor()

    def test_registry_exactly_matches_pinned_official_capabilities(self):
        snapshot=json.loads((ROOT/'docs/provider-metadata/openrouter-qwen3.8-20261019.json').read_text(encoding='utf-8'))
        self.assertEqual(snapshot['fetched_utc'],CATALOG_FETCHED_UTC)
        self.assertEqual(snapshot['response_sha256'],CATALOG_RESPONSE_SHA256)
        endpoints={e['tag']:e for e in snapshot['response']['data']['endpoints']}
        for tag,route in ROUTES.items():
            entry=endpoints[tag]
            self.assertEqual(route.context_length,entry['context_length'])
            self.assertEqual(route.max_completion_tokens,entry['max_completion_tokens'])
            self.assertTrue(entry['supports_tool_choice']['function'])
            self.assertTrue({'tools','tool_choice','max_tokens','reasoning'}<=set(entry['supported_parameters']))

    def test_existing_three_provider_auto_pool_stays_unchanged(self):
        result=self.governor.provider_preferences(None,40000,max_tokens=16384)
        self.assertEqual(result['only'],['cerebras/fp16','modelrun/fp4','deepinfra/bf16'])
        self.assertFalse(any(tag.startswith(('near-ai/','chutes/')) for tag in result['only']))
        long=self.governor.provider_preferences(None,183306,max_tokens=32768)
        self.assertEqual(long['only'],['modelrun/fp4','deepinfra/bf16'])

    def test_two_new_routes_require_explicit_selection_and_preserve_preferences(self):
        for base,tag in [('near-ai','near-ai/fp8'),('chutes','chutes/fp8')]:
            for selected in (base,tag):
                result=self.governor.provider_preferences({'only':[selected],'allow_fallbacks':False,
                    'sort':'throughput','require_parameters':False},183306,max_tokens=32768)
                self.assertEqual(result['only'],[tag])
                self.assertEqual(result['order'],[tag])
                self.assertFalse(result['allow_fallbacks'])
                self.assertEqual(result['sort'],'throughput')
                self.assertTrue(result['require_parameters'])

    def test_unknown_provider_or_variant_never_inherits_base_capacity(self):
        for name in ('near-ai/unknown','chutes/fp4','deepinfra/turbo','modelrun/unknown','unreviewed'):
            with self.subTest(name=name),self.assertRaises(ContextCapacityError):
                self.governor.provider_preferences({'only':[name]},40000,max_tokens=16384)
        self.assertEqual(resolve_routes('DeepInfra'),['deepinfra/bf16'])

    def test_output_budget_is_checked_separately_from_context(self):
        for tag,output in [('cerebras',32769),('near-ai/fp8',65537),('chutes/fp8',65537)]:
            with self.subTest(tag=tag),self.assertRaises(ContextCapacityError):
                self.governor.provider_preferences({'only':[tag]},50000,max_tokens=output)

    def test_declared_route_capacity_cannot_override_the_pinned_maximum(self):
        governor=RequestGovernor(ThroughputConfig(provider_contexts={'cerebras':1000000}))
        with self.assertRaises(ContextCapacityError):
            governor.provider_preferences(None,180000,max_tokens=32768)

    def test_exact_order_ignore_and_base_aliases_are_resolved(self):
        result=self.governor.provider_preferences({'only':['deepinfra','modelrun'],
            'order':['modelrun/fp4'],'ignore':['deepinfra/bf16']},100000,max_tokens=32768)
        self.assertEqual(result['only'],['modelrun/fp4'])
        self.assertEqual(result['order'],['modelrun/fp4'])

    def test_real_transport_payload_passes_output_cap_and_requires_parameters(self):
        model=OpenRouterJSONModel(model='qwen/qwen3.8-27b',api_key='offline-dummy-key',
            max_tokens=65537,openrouter_provider={'only':['near-ai/fp8']})
        model._request_governor=RequestGovernor(ThroughputConfig(token_counter=lambda p:100))
        with self.assertRaises(ContextCapacityError):
            model._payload([HumanMessage(content='offline')],None,{})
        model.max_tokens=32768
        payload=model._payload([HumanMessage(content='offline')],None,{})
        self.assertEqual(payload['provider']['only'],['near-ai/fp8'])
        self.assertTrue(payload['provider']['require_parameters'])
        self.assertEqual(payload['max_tokens'],32768)


if __name__=='__main__':
    unittest.main()
