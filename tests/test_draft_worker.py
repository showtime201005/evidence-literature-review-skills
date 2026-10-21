import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/literature-review/scripts/runtime'))
from litreview_core.draft_worker import DraftArguments, draft_worker
from litreview_core.draft_submission_wire import alias_obligations
from litreview_core.task_store import TaskStore
import test_review_artifacts as fixtures


def grouped_arguments(packet,value):
    _,aliases=alias_obligations(packet)
    inverse={original:alias for alias,original in aliases.items()}
    return {'data':{'claims':value['claims'],'cells':value['cells'],
        'retention_groups':[{'obligation_ids':[inverse[r['obligation_id']]],
            **{k:r[k] for k in ('status','claim_ids','reason')}} for r in value['retention']]}}


class DraftWorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store=TaskStore(self.tmp.name)
        fixture=fixtures.ReviewArtifactTests()
        fixture.setUp()
        self.packet,self.value=fixture.packet,fixture.value
        self.identity=SimpleNamespace(role='writer',context_id='writer-runtime')

    def test_accepts_typed_json_without_self_approval(self):
        ticket=self.store.create('writer',self.packet)
        worker=draft_worker(self.store,self.identity,ticket)
        receipt=worker.accept(grouped_arguments(self.packet,self.value),self.identity)
        section=self.store.get(receipt['output_hash'])
        self.assertEqual(section['verification_status'],'unverified')
        self.assertEqual(section['writer_execution_id'],'writer-runtime')

    def test_card_tool_schema_exposes_claim_limit_and_citation_index(self):
        ticket=self.store.create('writer',self.packet)
        worker=draft_worker(self.store,self.identity,ticket)
        schema=worker.submission_schema
        self.assertEqual(schema['$defs']['CardGroupedDraftSubmission']['properties']['claims']['maxItems'],12)
        self.assertEqual(worker.inputs['citation-index.json'],sorted(self.packet['sources']))
        self.assertTrue(worker.raw_tool_arguments)

    def test_raw_schema_error_is_compact_and_never_echoes_draft(self):
        ticket=self.store.create('writer',self.packet)
        worker=draft_worker(self.store,self.identity,ticket)
        raw=grouped_arguments(self.packet,self.value)
        raw['data']['undeclared_note']='DO_NOT_ECHO_PRIVATE_DRAFT_'*1000
        with self.assertRaisesRegex(ValueError,'extra_forbidden') as caught:
            worker.accept(raw,self.identity)
        self.assertNotIn('DO_NOT_ECHO_PRIVATE_DRAFT',str(caught.exception))
        self.assertLess(len(str(caught.exception)),300)
        self.assertEqual(self.store.status()[0]['status'],'running')
        worker.accept(grouped_arguments(self.packet,self.value),self.identity)

    def test_raw_envelope_and_nested_data_are_not_coerced(self):
        ticket=self.store.create('writer',self.packet)
        worker=draft_worker(self.store,self.identity,ticket)
        for raw in ({'data':json.dumps(self.value)}, {'data':self.value,'extra':1},self.value):
            with self.subTest(raw_type=list(raw)),self.assertRaises(ValueError):worker.accept(raw,self.identity)
        self.assertEqual(self.store.status()[0]['status'],'running')

    def test_invalid_role_releases_claim(self):
        ticket=self.store.create('comparer',self.packet)
        with self.assertRaises(ValueError):
            draft_worker(self.store,SimpleNamespace(role='comparer',context_id='x'),ticket)
        self.assertEqual(self.store.status()[0]['status'],'failed')

    def test_failure_and_foreign_submission(self):
        ticket=self.store.create('writer',self.packet)
        worker=draft_worker(self.store,self.identity,ticket)
        with self.assertRaises(ValueError):
            worker.accept(grouped_arguments(self.packet,self.value),SimpleNamespace(context_id='foreign'))
        worker.on_finish(self.identity,{'accepted':False,'reason':'provider failed'})
        self.assertEqual(self.store.status()[0]['status'],'failed')

    def test_downstream_error_preserves_unverified_draft(self):
        ticket=self.store.create('writer',self.packet)
        def broken(*args):
            raise RuntimeError('downstream failure')
        worker=draft_worker(self.store,self.identity,ticket,on_accepted=broken)
        with self.assertRaises(RuntimeError):
            worker.accept(grouped_arguments(self.packet,self.value),self.identity)
        worker.on_finish(self.identity,{'accepted':False,'reason':'downstream failure'})
        self.assertEqual(self.store.status()[0]['status'],'accepted')
        section=self.store.get(self.store.status()[0]['output_hash'])
        self.assertEqual(section['verification_status'],'unverified')


if __name__=='__main__':
    unittest.main()
