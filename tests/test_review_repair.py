import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/literature-review/scripts/runtime'))
from litreview_core.review_repair import reusable_nodes, revision_targets
from litreview_core.hierarchical_proof import DIMENSIONS, seal_node, ProofError


class RepairTests(unittest.TestCase):
    def setUp(self):
        coverage={d:[] for d in DIMENSIONS}
        self.specs={n:{'node_id':n,'kind':k,'inputs':{'m':'0'*64},'coverage':coverage,
                       'dependencies':deps,'section_id':n} for n,k,deps in
                    [('leaf','source',[]),('parent','cross_group',['leaf'])]}
        self.nodes={}
        for nid,s in self.specs.items():
            self.nodes[nid]=seal_node(nid,s['kind'],'ctx-'+nid,s['inputs'],
                {d:self.nodes[d]['payload_hash'] for d in s['dependencies']},coverage,'passed','Offline fixture')
        self.bundle={'node_specs':self.specs,'root_section_ids':['parent'],'materials':{
            n:{'schema':'review-section/1','section_id':n,'premise_section_ids':s['dependencies']} for n,s in self.specs.items()}}

    def test_changed_input_invalidates_all_dependent_proofs(self):
        self.assertEqual(set(reusable_nodes(self.bundle,self.nodes)),{'leaf','parent'})
        self.specs['leaf']['inputs']={'m':'1'*64}
        self.assertEqual(reusable_nodes(self.bundle,self.nodes),{})

    def test_rejection_targets_exact_dependency_closure(self):
        s=self.specs['leaf']
        self.nodes['leaf']=seal_node('leaf','source','ctx-negative',s['inputs'],{},s['coverage'],
                                    'needs_revision','Persistent failure omitted')
        direct,affected=revision_targets(self.bundle,self.nodes)
        self.assertEqual(set(direct),{'leaf'})
        self.assertEqual(affected,{'leaf','parent'})
        self.assertEqual(reusable_nodes(self.bundle,self.nodes),{})

    def test_planner_order_reuses_original_canonical_proofs_without_resealing(self):
        for spec in self.specs.values():
            spec['coverage']=copy.deepcopy(spec['coverage'])
            spec['coverage']['claims']=['claim-z','claim-a']
            spec['coverage']['obligations']=['duty-2','duty-1']
        for nid,spec in self.specs.items():
            self.nodes[nid]=seal_node(nid,spec['kind'],'ctx-'+nid,spec['inputs'],
                {d:self.nodes[d]['payload_hash'] for d in spec['dependencies']},spec['coverage'],
                'passed','Offline canonical-order fixture')
        before=copy.deepcopy(self.nodes)
        result=reusable_nodes(self.bundle,self.nodes)
        self.assertEqual(set(result),{'leaf','parent'})
        self.assertEqual(self.nodes,before)
        for nid in result:
            self.assertIs(result[nid],self.nodes[nid])
        self.specs['leaf']['coverage']['claims'].append('new-required-claim')
        self.assertEqual(reusable_nodes(self.bundle,self.nodes),{})

    def test_duplicate_or_unknown_coverage_cannot_be_hidden_by_canonicalization(self):
        for mutation in ('duplicate','unknown','missing'):
            bundle=copy.deepcopy(self.bundle)
            coverage=bundle['node_specs']['leaf']['coverage']
            if mutation=='duplicate':coverage['claims']=['claim-a','claim-a']
            elif mutation=='unknown':coverage['invented_dimension']=[]
            else:coverage.pop('claims')
            with self.subTest(mutation=mutation),self.assertRaises(ProofError):
                reusable_nodes(bundle,self.nodes)


if __name__=='__main__':
    unittest.main()
