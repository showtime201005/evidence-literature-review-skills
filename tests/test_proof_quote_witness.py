"""Strict literal-witness adversaries. No scientific approval or provider calls."""
import copy
from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'skills/literature-review/scripts/runtime'))
sys.path.insert(0,str(ROOT/'tests'))
from litreview_core.hierarchical_proof import payload_hash
from litreview_core.proof_citation_view import build_citation_view
from litreview_core.proof_quote_witness import (validate_source_witness_submission,
    WitnessValidationError,semantic_negative_detected)
from litreview_core.proof_worker import ProofSubmission
import test_proof_citation_view as citation_fixtures


class QuoteWitnessTests(unittest.TestCase):
    def setUp(self):
        fixture=citation_fixtures.CitationViewTests();fixture.setUp()
        self.packet=fixture.packet()
        self.source_a,self.source_b=fixture.a,fixture.b
        self.addCleanup(patch.stopall)
        patch.object(socket,'create_connection',side_effect=AssertionError('No network in quote-witness tests')).start()
        import httpx
        patch.object(httpx.Client,'send',side_effect=AssertionError('No provider in quote-witness tests')).start()
        patch.object(httpx.AsyncClient,'send',side_effect=AssertionError('No provider in quote-witness tests')).start()
        rows={row['claim_id']:row for row in build_citation_view(self.packet)['claim_rows']}
        self.value={'checked':copy.deepcopy(self.packet['coverage']),
            'verdicts':[], 'status':'passed','reason':'Literal fixture only; no semantic approval.', 'issues':[]}
        for cid in self.packet['coverage']['claims']:
            row=rows[cid];part=row['declared_parts'][0]
            self.value['verdicts'].append({'unit_id':cid,'verdict':'passed',
                'reason':'Keep this exact per-unit reason.', 'clause_checks':[{
                    'start_char':0,'end_char':len(row['text']),'clause':row['text'],
                    'relation':'explicit_support','reason':'Literal fixture, not logical entailment.',
                    'witnesses':[{'ref':part['ref'],'start_byte':part['start_byte'],
                        'end_byte':part['end_byte'],'quote':part['text']}]}]})
        self.value['verdicts'].append({'unit_id':'o1','verdict':'passed',
                                       'reason':'Unchanged obligation reason; no invented witness.'})

    def check(self,value=None,packet=None,**kwargs):
        return validate_source_witness_submission(self.packet if packet is None else packet,
            self.value if value is None else value,**kwargs)

    def reject(self,code,value=None,packet=None):
        with self.assertRaises(WitnessValidationError) as caught:
            self.check(value,packet)
        self.assertEqual(caught.exception.code,code,caught.exception.as_dict())
        return caught.exception

    def clause(self,value=None):return (self.value if value is None else value)['verdicts'][0]['clause_checks'][0]
    def quote(self,value=None):return self.clause(value)['witnesses'][0]

    def change_claim(self,text):
        self.packet['materials']['claim/S%2Fc1']['text']=text
        self.packet['material_hashes']['claim/S%2Fc1']=payload_hash(self.packet['materials']['claim/S%2Fc1'])
        self.clause().update(start_char=0,end_char=len(text),clause=text)

    def test_literal_success_keeps_existing_gate_shape_all_reasons_and_inputs(self):
        packet,value=copy.deepcopy(self.packet),copy.deepcopy(self.value)
        result=self.check(expected_material_hashes=self.packet['material_hashes'])
        self.assertTrue(result['literal_checks_completed'])
        self.assertFalse(result['semantic_entailment_proven'])
        self.assertFalse(result['publication_verified'])
        self.assertEqual(result['clause_count'],2)
        self.assertEqual(result['witness_count'],2)
        ProofSubmission.model_validate(result['proof_submission'])
        self.assertEqual([item['reason'] for item in result['proof_submission']['verdicts']],
                         [item['reason'] for item in value['verdicts']])
        self.assertEqual(result['witness_submission'],value)
        self.assertEqual(self.packet,packet);self.assertEqual(self.value,value)

    def test_exact_quote_does_not_prove_logical_event_order(self):
        # The fixture claim strengthens the source's event order. Its quote is
        # nevertheless an exact real substring. No entailment proof is asserted.
        self.assertEqual(self.clause()['clause'],'Digest recording preceded freezing.')
        result=self.check()
        self.assertTrue(result['literal_checks_completed'])
        self.assertFalse(result['semantic_entailment_proven'])

    def test_malformed_material_context_still_retains_original_negative(self):
        # Even a bad canonical context must not leak an unannotated exception
        # which a future caller could treat as an ordinary retryable format error.
        self.value['status']='needs_revision'
        self.packet['materials'][7]={'invalid':'non-string material identifier'}
        self.packet['material_hashes'][7]=payload_hash(self.packet['materials'][7])
        error=self.reject('WITNESS_SOURCE_CONTEXT_INVALID')
        self.assertTrue(error.semantic_negative_detected)
        self.assertEqual(error.original_submission,self.value)

    def test_codepoint_not_utf8_or_utf16_indices(self):
        self.change_claim('研究🙂未測量成本。')
        self.check()
        original=copy.deepcopy(self.value)
        for end in (len(self.clause()['clause'].encode('utf-8')),
                    len(self.clause()['clause'].encode('utf-16-le'))//2):
            value=copy.deepcopy(original);self.clause(value)['end_char']=end
            self.reject('WITNESS_CLAUSE_TEXT_MISMATCH',value)

    def test_claim_qualifier_gap_and_trailing_text_cannot_be_skipped(self):
        text='Result improves; cost remains unmeasured.';self.change_claim(text)
        clause=self.clause();clause.update(end_char=len('Result improves;'),clause='Result improves;')
        self.reject('WITNESS_UNCOVERED_CLAIM_TEXT')
        self.change_claim(text)
        first=copy.deepcopy(self.clause());first.update(end_char=6,clause=text[:6])
        second=copy.deepcopy(self.clause());start=text.index('cost');second.update(start_char=start,clause=text[start:])
        self.value['verdicts'][0]['clause_checks']=[first,second]
        self.reject('WITNESS_UNCOVERED_CLAIM_TEXT')

    def test_overlapping_duplicate_clauses_rejected(self):
        self.value['verdicts'][0]['clause_checks'].append(copy.deepcopy(self.clause()))
        self.reject('WITNESS_OVERLAPPING_CLAUSES')

    def test_nonoverlapping_out_of_order_clauses_preserved_and_whitespace_gaps_allowed(self):
        self.change_claim('  Digest recording preceded freezing.  ')
        text=self.clause()['clause'];cut=text.index(' preceded')
        first=copy.deepcopy(self.clause());first.update(start_char=2,end_char=cut,clause=text[2:cut])
        second=copy.deepcopy(self.clause());second.update(start_char=cut+1,end_char=len(text)-2,clause=text[cut+1:-2])
        self.value['verdicts'][0]['clause_checks']=[second,first]
        result=self.check()
        self.assertEqual(result['witness_submission']['verdicts'][0]['clause_checks'],[second,first])

    def test_altered_clause_text_and_empty_clause_checks_rejected(self):
        self.clause()['clause']='This was not the actual claim.'
        self.reject('WITNESS_CLAUSE_TEXT_MISMATCH')
        self.value['verdicts'][0]['clause_checks']=[]
        self.reject('WITNESS_MISSING_CLAUSES')

    def test_boolean_float_string_indices_and_extra_fields_rejected(self):
        for field,bad in [('start_char',False),('end_char',3.0),('end_char','3')]:
            value=copy.deepcopy(self.value);self.clause(value)[field]=bad
            with self.subTest(field=field,bad=bad):self.reject('WITNESS_SCHEMA_INVALID',value)
        for field,bad in [('start_byte',False),('end_byte',3.0),('end_byte','3')]:
            value=copy.deepcopy(self.value);self.quote(value)[field]=bad
            with self.subTest(field=field,bad=bad):self.reject('WITNESS_SCHEMA_INVALID',value)
        value=copy.deepcopy(self.value);self.quote(value)['source_sha256']='model-supplied-version'
        self.reject('WITNESS_SCHEMA_INVALID',value)

    def test_unknown_or_undeclared_ref_cannot_borrow_support_elsewhere(self):
        row=build_citation_view(self.packet)['claim_rows'][1]['declared_parts'][0]
        self.quote().update(ref=row['ref'],start_byte=row['start_byte'],end_byte=row['end_byte'],quote=row['text'])
        self.reject('WITNESS_UNDECLARED_REF')
        self.quote()['ref']='unknown/p99'
        self.reject('WITNESS_UNDECLARED_REF')

    def test_quote_absolute_byte_bounds_and_utf8_boundaries(self):
        for start,end in [(0,10**6),(1,self.quote()['end_byte'])]:
            value=copy.deepcopy(self.value);self.quote(value).update(start_byte=start,end_byte=end)
            self.reject('WITNESS_BYTE_RANGE' if end==10**6 else 'WITNESS_UTF8_BOUNDARY',value)
        # p2 begins after p1; source-relative zero cannot pretend to be p2-local.
        self.value['verdicts'][1]['clause_checks'][0]['witnesses'][0]['start_byte']=0
        self.reject('WITNESS_BYTE_RANGE')

    def test_quote_text_normalization_and_duplicate_witness_rejected(self):
        self.quote()['quote']=self.quote()['quote'].replace('\r\n','\n')
        self.reject('WITNESS_QUOTE_MISMATCH')
        self.quote()['quote']=self.source_a
        self.clause()['witnesses'].append(copy.deepcopy(self.quote()))
        self.reject('WITNESS_DUPLICATE_QUOTE')

    def test_wrong_source_version_or_trusted_hash_rejected(self):
        packet=copy.deepcopy(self.packet)
        key='locator/paper%2Fp1';packet['materials'][key]['source_sha256']='0'*64
        packet['material_hashes'][key]=payload_hash(packet['materials'][key])
        self.reject('WITNESS_SOURCE_CONTEXT_INVALID',packet=packet)
        expected={**self.packet['material_hashes'],'original/paper':'1'*64}
        with self.assertRaises(WitnessValidationError) as caught:self.check(expected_material_hashes=expected)
        self.assertEqual(caught.exception.code,'WITNESS_INPUT_BINDING_MISMATCH')

    def test_original_absent_and_non_source_alias_wire_rejected(self):
        packet=copy.deepcopy(self.packet);del packet['materials']['original/paper'];del packet['material_hashes']['original/paper']
        self.reject('WITNESS_ORIGINAL_NOT_DELIVERED',packet=packet)
        self.reject('WITNESS_UNSUPPORTED_SCOPE',packet={**self.packet,'kind':'cross_group'})
        self.reject('WITNESS_NONCANONICAL_INPUT',packet={**self.packet,'responsibility_encoding':'proof-unit-aliases/1'})

    def test_passed_requires_explicit_support_and_exact_quote_for_every_clause(self):
        self.clause()['witnesses']=[]
        self.reject('WITNESS_EXPLICIT_WITHOUT_QUOTE')
        for relation in ('topic_only','not_reported','contradicted','unresolved'):
            value=copy.deepcopy(self.value);self.clause(value)['relation']=relation
            error=self.reject('WITNESS_PASSED_CONTRADICTS_CLAUSE',value)
            self.assertTrue(error.semantic_negative_detected)

    def test_valid_negatives_are_not_dropped_or_promoted_in_base_proof_shape(self):
        self.value['status']='needs_revision';self.value['verdicts'][0]['verdict']='needs_revision'
        self.value['verdicts'][-1]['verdict']='unresolved'
        self.clause().update(relation='not_reported',witnesses=[],reason='Unreported relation remains unresolved.')
        self.value['issues']=[{'unit_ids':['S/c1'],'description':'Preserve this actual negative.',
                               'correction':'Require revision; do not resample a pass.'}]
        result=self.check()
        self.assertTrue(result['semantic_negative_detected'])
        self.assertEqual(result['proof_submission']['status'],'needs_revision')
        self.assertEqual(result['proof_submission']['verdicts'][0]['verdict'],'needs_revision')
        self.assertEqual(result['proof_submission']['verdicts'][-1]['verdict'],'unresolved')
        self.assertEqual(result['proof_submission']['issues'],self.value['issues'])
        self.assertEqual(result['witness_submission'],self.value)

    def test_negative_plus_schema_error_keeps_deep_snapshot_and_terminal_flag(self):
        self.value['status']='needs_revision';self.value['verdicts'][0]['verdict']='needs_revision'
        self.quote()['start_byte']=False
        error=self.reject('WITNESS_SCHEMA_INVALID')
        self.assertTrue(error.semantic_negative_detected)
        self.assertEqual(error.original_submission,self.value)
        self.value['verdicts'][0]['reason']='later mutation must not alter saved negative'
        self.assertNotEqual(error.original_submission,self.value)
        exported=error.as_dict();exported['original_submission']['status']='passed'
        self.assertEqual(error.original_submission['status'],'needs_revision')

    def test_negative_plus_source_or_quote_format_error_is_not_hidden(self):
        for position in ('status','verdict','relation','issue'):
            value=copy.deepcopy(self.value)
            if position=='status':value['status']='unresolved'
            elif position=='verdict':value['verdicts'][0]['verdict']='needs_revision'
            elif position=='relation':self.clause(value)['relation']='contradicted'
            else:value['issues']=[{'unit_ids':['S/c1'],'description':'Negative','correction':'Revise'}]
            self.quote(value)['ref']='not-declared/p9'
            with self.subTest(position=position):
                error=self.reject('WITNESS_UNDECLARED_REF' if position!='relation' else 'WITNESS_PASSED_CONTRADICTS_CLAUSE',value)
                self.assertTrue(error.semantic_negative_detected)
                self.assertEqual(error.original_submission,value)

    def test_whole_pass_cannot_hide_negative_unit_or_issue(self):
        self.value['verdicts'][-1]['verdict']='unresolved'
        self.reject('WITNESS_PASSED_CONTRADICTS_NEGATIVE')
        self.value['verdicts'][-1]['verdict']='passed'
        self.value['issues']=[{'unit_ids':['S/c1'],'description':'Known problem','correction':'Revise'}]
        self.reject('WITNESS_PASSED_CONTRADICTS_NEGATIVE')

    def test_full_canonical_inventory_and_nonclaim_scope_preserved(self):
        value=copy.deepcopy(self.value);value['verdicts']=value['verdicts'][:-1]
        self.reject('WITNESS_VERDICT_INVENTORY',value)
        value=copy.deepcopy(self.value);value['verdicts'].append(copy.deepcopy(value['verdicts'][0]))
        self.reject('WITNESS_VERDICT_INVENTORY',value)
        value=copy.deepcopy(self.value);value['checked']['claims'].append('S/c1')
        self.reject('WITNESS_CHECKED_MISMATCH',value)
        value=copy.deepcopy(self.value);value['verdicts'][-1]['clause_checks']=[copy.deepcopy(self.clause())]
        self.reject('WITNESS_CLAUSES_WRONG_SCOPE',value)

    def test_malformed_negative_fields_do_not_crash_detection(self):
        self.assertFalse(semantic_negative_detected({'status':[]}))
        self.assertFalse(semantic_negative_detected({'verdicts':[{'verdict':{},'clause_checks':[{'relation':[]}]}]}))
        value=copy.deepcopy(self.value);value['status']=[]
        error=self.reject('WITNESS_SCHEMA_INVALID',value)
        self.assertFalse(error.semantic_negative_detected)


if __name__=='__main__':unittest.main()
