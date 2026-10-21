import concurrent.futures
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/literature-review/scripts/runtime'))
from litreview_core.task_store import TaskStore, ScopedTaskStore


class TaskStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = TaskStore(self.tmp.name)

    def test_dependencies_and_integrity(self):
        first = self.store.create('reader', {'paper': '完整原文'})
        second = self.store.create('writer', {}, [first])
        self.assertEqual([x['id'] for x in self.store.ready()], [first])
        lease = self.store.claim(first, 'reader', 'runtime-reader')
        with self.assertRaises(ValueError):
            self.store.accept(first, 'forged', lease['lease'], {}, validator=lambda a,b: None)
        receipt = self.store.accept(first, 'runtime-reader', lease['lease'], {'facts': [1]}, validator=lambda a,b: None)
        self.assertEqual([x['id'] for x in self.store.ready()], [second])
        with self.assertRaises(ValueError):
            self.store.accept(first, 'runtime-reader', lease['lease'], {}, validator=lambda a,b: None)
        path = Path(self.tmp.name)/'objects'/(receipt['output_hash']+'.json')
        path.write_text('{}', encoding='utf-8')
        with self.assertRaises(ValueError):
            self.store.get(receipt['output_hash'])

    def test_concurrent_claim_and_semantic_failure(self):
        ticket = self.store.create('reader', {})
        def claim(n):
            try:
                return self.store.claim(ticket, 'reader', str(n))
            except ValueError:
                return None
        with concurrent.futures.ThreadPoolExecutor(8) as pool:
            claims = [v for v in pool.map(claim, range(8)) if v]
        self.assertEqual(len(claims), 1)
        claim = claims[0]
        def reject(a,b):
            raise ValueError('missing source coverage')
        with self.assertRaises(ValueError):
            self.store.accept(ticket, claim['context'], claim['lease'], {}, validator=reject)
        self.assertEqual(self.store.status()[0]['status'], 'running')
        self.store.fail(ticket, claim['context'], claim['lease'], {'unsupported': True})
        self.assertEqual(self.store.status()[0]['status'], 'failed')
        self.assertEqual(self.store.ready(), [])

    def test_scoped_revision_preserves_failed_accepted_and_obsolete_history(self):
        failed = self.store.create('verifier', {'old': True})
        accepted = self.store.create('reader', {'old': True})
        obsolete = self.store.create('writer', {'superseded': True})
        lease = self.store.claim(failed, 'verifier', 'original-verifier')
        self.store.fail(failed, lease['context'], lease['lease'], {'honest_negative': True})
        lease = self.store.claim(accepted, 'reader', 'original-reader')
        self.store.accept(accepted, lease['context'], lease['lease'], {'record': True}, validator=lambda a,b: None)
        history = self.store.status()
        revision = self.store.create('writer', {'revision': 1}, [accepted])
        view = ScopedTaskStore(self.store, [revision])
        self.assertEqual([r['id'] for r in view.ready()], [revision])
        lease = self.store.claim(revision, 'writer', 'actual-new-native-worker')
        self.store.accept(revision, lease['context'], lease['lease'], {'revised': True}, validator=lambda a,b: None)
        self.assertEqual([r['status'] for r in view.status()], ['accepted'])
        self.assertEqual(self.store.status()[:3], history)
        self.assertEqual(self.store.status()[2]['id'], obsolete)
        self.assertFalse(hasattr(view, 'accept'), 'The view must not become a host acceptance shortcut')

    def test_scope_does_not_bypass_unaccepted_external_dependencies(self):
        failed = self.store.create('verifier', {})
        dependent = self.store.create('writer', {}, [failed])
        view = ScopedTaskStore(self.store, [dependent])
        self.assertEqual(view.ready(), [])
        lease = self.store.claim(failed, 'verifier', 'real-negative-context')
        self.store.fail(failed, lease['context'], lease['lease'], {'needs_revision': True})
        self.assertEqual(view.ready(), [])
        self.assertEqual(view.status()[0]['status'], 'pending')
        with self.assertRaises(ValueError):
            self.store.claim(dependent, 'writer', 'cannot-bypass')

    def test_scope_filters_before_page_limit_and_is_fixed(self):
        for index in range(105):
            self.store.create('reader', {'unrelated': index})
        scoped = [self.store.create('verifier', {'selected': index}) for index in range(3)]
        view = ScopedTaskStore(self.store, reversed(scoped))
        later = self.store.create('writer', {'later-stage': True})
        self.assertEqual([r['id'] for r in view.ready(2)], scoped[:2])
        self.assertEqual([r['id'] for r in view.status()], scoped)
        self.assertNotIn(later, view.tickets)

    def test_scope_rejects_unknown_duplicate_and_invalid_ticket_inputs(self):
        ticket = self.store.create('reader', {})
        for value in ([ticket, ticket], ['missing'], [None]):
            with self.assertRaises(ValueError):
                ScopedTaskStore(self.store, value)
        with self.assertRaises(TypeError):
            ScopedTaskStore(self.store, ticket)
        empty = ScopedTaskStore(self.store, [])
        self.assertEqual(empty.ready(), [])
        self.assertEqual(empty.status(), [])


if __name__ == '__main__':
    unittest.main()
