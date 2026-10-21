"""Immutable observation transport checks; no scientific quality claim."""
import copy
import unittest

import test_paper_review_v2 as paper_fixture
from litreview_core.hierarchical_proof import payload_hash
from litreview_core.paper_review_v2 import plan_paper_review_v2, restore_paper_review_v2, PaperReviewSubmissionV2
from litreview_core.review_observation_selectors import (
    WHOLE_UNITS, expand_selector_submission, selection_attestation_fields, replay_selection_attestation)


class SelectorTransportTests(unittest.TestCase):
    def setUp(self):
        fixture=paper_fixture.PaperReviewV2Tests()
        fixture.setUp()
        self.bundle=plan_paper_review_v2(fixture.source,fixture.record,fixture.card,observation_mode=WHOLE_UNITS)
        self.canonical=paper_fixture.scripted_v2(self.bundle)
        self.raw={'data':paper_fixture.selected_submission(self.bundle,self.canonical)}

    def test_roundtrip_exact_bytes_and_raw_is_not_mutated(self):
        before=copy.deepcopy(self.raw)
        self.assertEqual(restore_paper_review_v2(self.bundle['wire']),self.bundle['payload'])
        self.assertEqual(expand_selector_submission(self.bundle,self.raw),{'data':self.canonical})
        self.assertEqual(self.raw,before)

    def test_unknown_duplicate_borrowed_and_legacy_observations_rejected(self):
        check=self.raw['data']['unit_verdicts'][0]['claim_checks'][0]
        own=check['observations'][0]['selector_id']
        unit=self.bundle['payload']['required_units'][0]
        other=next(r['selector_id'] for r in self.bundle['wire']['selector_index']
                   if r['source_ref'] not in unit['source_refs'])
        for observations in ([{'selector_id':'absent'}],
                             [{'selector_id':own},{'selector_id':own}],
                             [{'selector_id':other}],
                             self.canonical['unit_verdicts'][0]['claim_checks'][0]['observations']):
            raw=copy.deepcopy(self.raw)
            raw['data']['unit_verdicts'][0]['claim_checks'][0]['observations']=observations
            with self.subTest(observations=observations),self.assertRaises(ValueError):
                expand_selector_submission(self.bundle,raw)

    def test_changed_index_with_recomputed_hash_is_rejected(self):
        bundle=copy.deepcopy(self.bundle)
        bundle['wire']['selector_index'][0]['text_sha256']='changed'
        bundle['wire']['selector_index_sha256']=payload_hash(bundle['wire']['selector_index'])
        with self.assertRaises(ValueError):restore_paper_review_v2(bundle['wire'])
        with self.assertRaises(ValueError):expand_selector_submission(bundle,self.raw)

    def test_fresh_replay_rejects_changed_raw_scientific_judgment(self):
        normalize=lambda v:PaperReviewSubmissionV2.model_validate(v).model_dump()
        payload={'submission':normalize(self.canonical),**selection_attestation_fields(self.bundle,self.raw)}
        replay_selection_attestation(self.bundle,payload,normalize=normalize)
        payload['observation_selection']['raw_tool_arguments']['data']['unit_verdicts'][0]['reason']='Changed reason'
        with self.assertRaisesRegex(ValueError,'differ from fresh'):
            replay_selection_attestation(self.bundle,payload,normalize=normalize)


if __name__=='__main__':unittest.main()
