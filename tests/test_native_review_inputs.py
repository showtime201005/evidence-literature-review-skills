from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
import asyncio
from unittest.mock import patch, Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/literature-review/scripts/runtime'))
from litreview_core.native_review import markdown_sources, review_throughput_config, role_reasoning_enabled, timed_stage, review_provider_preferences
from litreview_core.native_review import validated_review_protocol, review_delivery_flags, make_review_workflow


class NativeStageTimingTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_and_negative_result_preserve_receipt_and_timing(self):
        for passed in (True,False):
            stages=[]
            result={'passed':passed,'receipts':['unchanged']}
            async def operation():
                return result
            with patch('litreview_core.native_review.time.monotonic',side_effect=[12,19]):
                actual=await timed_stage('reading',operation,stages,10)
            self.assertIs(actual,result)
            self.assertEqual(stages,[{'stage':'reading','started_after_seconds':2,
                'elapsed_seconds':7,'status':'completed' if passed else 'failed','result':result}])

    async def test_exception_keeps_elapsed_and_propagates_original_error(self):
        stages=[]
        error=RuntimeError('provider failed')
        async def operation():
            raise error
        with patch('litreview_core.native_review.time.monotonic',side_effect=[20,25]):
            with self.assertRaises(RuntimeError) as caught:
                await timed_stage('cards',operation,stages,10)
        self.assertIs(caught.exception,error)
        self.assertEqual(stages[0]['elapsed_seconds'],5)
        self.assertEqual(stages[0]['status'],'failed')
        self.assertNotIn('result',stages[0])

    async def test_outer_cancellation_is_recorded_without_swallowing_it(self):
        stages=[]
        async def operation():
            raise asyncio.CancelledError()
        with patch('litreview_core.native_review.time.monotonic',side_effect=[30,38]):
            with self.assertRaises(asyncio.CancelledError):
                await timed_stage('independent-proofs-0',operation,stages,10)
        self.assertEqual(stages[0]['status'],'cancelled')
        self.assertEqual(stages[0]['elapsed_seconds'],8)
        self.assertEqual(stages[0]['error']['type'],'CancelledError')


class NativeReviewInputTests(unittest.TestCase):
    def test_v2_protocol_is_explicit_and_rejects_v1_only_flags(self):
        self.assertEqual(validated_review_protocol(SimpleNamespace()),'v1')
        self.assertEqual(validated_review_protocol(SimpleNamespace(review_protocol='v2')),'v2')
        for changes in ({'source_quote_witness':True},{'merge_full_source':True},
                        {'proof_max_units':96}):
            with self.assertRaisesRegex(ValueError,'V1 witness'):
                validated_review_protocol(SimpleNamespace(review_protocol='v2',**changes))
        with self.assertRaises(ValueError):
            validated_review_protocol(SimpleNamespace(review_protocol='other'))

    def test_v2_export_completion_never_promotes_publication_or_quality(self):
        for delivered in (False,True):
            flags=review_delivery_flags('v2',delivered)
            self.assertEqual(flags['protocol_completed_experimental'],delivered)
            self.assertFalse(flags['publication_verified'])
            self.assertFalse(flags['quality_validated'])
            self.assertEqual(review_delivery_flags('v1',delivered)['publication_verified'],delivered)

    def test_v2_workflow_receives_original_deadline_without_v1_packing_flags(self):
        factory=Mock(return_value=object())
        counter=SimpleNamespace(tokenizer=SimpleNamespace(encode=lambda *a,**k:SimpleNamespace(ids=[1,2])))
        args=SimpleNamespace(review_protocol='v2',group_size=4)
        with patch.dict(sys.modules,{'litreview_core.review_workflow_v2':SimpleNamespace(ReviewWorkflowV2=factory)}):
            actual=make_review_workflow(args,'store',['source'],['question'],counter,123.45)
        self.assertIs(actual,factory.return_value)
        positional,keywords=factory.call_args
        self.assertEqual(positional,('store',['source'],['question']))
        self.assertEqual(set(keywords),{'group_size','token_counter','deadline_at','observation_mode','closed_checks'})
        self.assertFalse(keywords['closed_checks'])
        self.assertEqual(keywords['observation_mode'],'quotes')
        self.assertEqual(keywords['deadline_at'],123.45)
        self.assertEqual(keywords['token_counter']('text'),2)

    def test_whole_unit_observations_require_v2_and_reach_actual_workflow(self):
        for protocol in ('v1','v2'):
            args=SimpleNamespace(review_protocol=protocol,review_observations='whole-unit',group_size=4)
            if protocol=='v1':
                with self.assertRaisesRegex(ValueError,'require experimental'):
                    validated_review_protocol(args)
                continue
            factory=Mock(return_value=object())
            with patch.dict(sys.modules,{'litreview_core.review_workflow_v2':SimpleNamespace(ReviewWorkflowV2=factory)}):
                make_review_workflow(args,'store',[],[],Mock(),456.7)
            self.assertEqual(factory.call_args.kwargs['observation_mode'],'whole-unit-selectors/1')
            self.assertEqual(factory.call_args.kwargs['deadline_at'],456.7)
        with self.assertRaises(ValueError):
            validated_review_protocol(SimpleNamespace(review_protocol='v2',review_observations='coerce'))

    def test_closed_local_checks_are_v2_only_and_reach_workflow(self):
        with self.assertRaisesRegex(ValueError,'Closed local'):
            validated_review_protocol(SimpleNamespace(review_protocol='v1',closed_checks=True))
        factory=Mock(return_value=object())
        args=SimpleNamespace(review_protocol='v2',closed_checks=True,group_size=4)
        with patch.dict(sys.modules,{'litreview_core.review_workflow_v2':SimpleNamespace(ReviewWorkflowV2=factory)}):
            make_review_workflow(args,'store',[],[],Mock(),123.4)
        self.assertTrue(factory.call_args.kwargs['closed_checks'])

    def test_coordinator_route_override_does_not_change_worker_routing(self):
        self.assertEqual(review_provider_preferences(SimpleNamespace()),{'coordinator':None,'worker':None})
        inherited=review_provider_preferences(SimpleNamespace(provider='chutes/fp8'))
        self.assertEqual(inherited,{'coordinator':{'only':['chutes/fp8'],'allow_fallbacks':False},
                                   'worker':{'only':['chutes/fp8'],'allow_fallbacks':False}})
        routed=review_provider_preferences(SimpleNamespace(provider='chutes/fp8',coordinator_provider='cerebras/fp16'))
        self.assertEqual(routed['worker'],inherited['worker'])
        self.assertEqual(routed['coordinator'],{'only':['cerebras/fp16'],'allow_fallbacks':False})
        automatic_workers=review_provider_preferences(SimpleNamespace(coordinator_provider='cerebras/fp16'))
        self.assertIsNone(automatic_workers['worker'])
        self.assertEqual(automatic_workers['coordinator'],routed['coordinator'])

    def test_experimental_role_reasoning_does_not_disable_readers_or_coordinator(self):
        for role in ('reader','coordinator','writer','comparer','verifier','assembly-auditor'):
            self.assertTrue(role_reasoning_enabled(role))
            self.assertEqual(role_reasoning_enabled(role,reviewer_mode='off'),
                             role not in ('verifier','assembly-auditor'))
            self.assertEqual(role_reasoning_enabled(role,writer_mode='off'),
                             role not in ('writer','comparer'))
        with self.assertRaises(ValueError):
            role_reasoning_enabled('verifier',reviewer_mode='unknown')

    def test_aggregate_budget_is_configurable_without_raising_request_context(self):
        counter=lambda payload:17
        for limit in (200000,1000000,2000000,6400000):
            config=review_throughput_config(SimpleNamespace(workers=16,active_token_limit=limit),counter,5400)
            self.assertEqual(config.active_token_limit,limit)
            self.assertEqual(config.context_limit,200000)
            self.assertEqual(config.context_margin,8000)
            self.assertIs(config.token_counter,counter)
        self.assertEqual(review_throughput_config(SimpleNamespace(workers=8),counter,5400).active_token_limit,1000000)
        for limit in (True,199999,6400001,1.5):
            with self.assertRaisesRegex(ValueError,'Aggregate active-token'):
                review_throughput_config(SimpleNamespace(workers=8,active_token_limit=limit),counter,5400)

    def test_reader_reasoning_opt_in_is_independent_and_coordinator_stays_enabled(self):
        for role in ('reader','coordinator','writer','comparer','verifier','assembly-auditor'):
            self.assertEqual(role_reasoning_enabled(role,reader_mode='off'),role!='reader')
            self.assertEqual(role_reasoning_enabled(role,'off','off','off'),role=='coordinator')
        with self.assertRaises(ValueError):
            role_reasoning_enabled('reader',reader_mode='unknown')

    def test_markdown_extensions_and_stable_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name in ('b.MD','A.markdown','c.MarkDown','ignore.pdf'):
                (root/name).write_text('Original paper',encoding='utf-8')
            (root/'not-a-paper.md').mkdir()
            self.assertEqual([p.name for p in markdown_sources(root)],['A.markdown','b.MD','c.MarkDown'])

    def test_ambiguous_paper_ids_rejected_before_tasks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name in ('Paper.md','paper.markdown'):
                (root/name).write_text('Original paper',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'stems must be unique'):
                markdown_sources(root)

    def test_nonexistent_empty_and_over_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for path in (root/'missing',root):
                with self.assertRaises(ValueError):
                    markdown_sources(path)
            for i in range(101):
                (root/(str(i)+'.md')).write_text('Original paper',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'1..100'):
                markdown_sources(root)


if __name__=='__main__':
    unittest.main()
