import json
import unittest
from pathlib import Path
from pilotage.po import accepted, report, validate

class POTests(unittest.TestCase):
    def setUp(self):
        self.b=json.loads(Path(__file__).with_name('github-backlog.json').read_text(encoding='utf-8'))
        self.sha='a'*40
        self.c={'id':'DEV-001:AC1','verified':True,'evidence':'E1','requires_real':True}
        self.e={'E1':{'result':'passed','commit':self.sha,'criteria':['DEV-001:AC1'],'reviewer':'human','url':'https://github.com/richardyoann/saas-directeur-editorial/issues/3','mode':'real','at':'2026-10-10T12:00:00Z'}}
    def test_no_claim_from_open_backlog(self):
        result=report(self.b,{},self.sha)
        self.assertEqual(result['accepted'],0)
        self.assertEqual(result['total'],48)
        self.assertIn('DEV-003',result['blocked'])
    def test_real_evidence_and_stale_commit(self):
        self.assertTrue(accepted(self.c,self.e,self.sha))
        self.assertFalse(accepted(self.c,self.e,'b'*40))
        self.e['E1']['mode']='automated'
        self.assertFalse(accepted(self.c,self.e,self.sha))
    def test_future_and_incomplete_evidence(self):
        self.e['E1']['at']='2999-01-01T00:00:00Z'
        self.assertFalse(accepted(self.c,self.e,self.sha))
        self.e['E1'].pop('at')
        self.assertFalse(accepted(self.c,self.e,self.sha))
    def test_wrong_repo_and_cycles(self):
        self.b['repository_id']=1
        with self.assertRaises(ValueError):validate(self.b)
        self.b['repository_id']=1411435489
        next(i for i in self.b['items'] if i['id']=='DEV-001')['dependencies']=['DEV-003']
        with self.assertRaises(ValueError):validate(self.b)
    def test_story_count_only(self):
        i=next(i for i in self.b['items'] if i['id']=='DEV-001')
        i['criteria'][0]=self.c
        result=report(self.b,self.e,self.sha)
        self.assertEqual(result['accepted'],1)
        self.assertEqual(result['total'],48)
