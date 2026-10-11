import os
import unittest
from pathlib import Path
from uuid import uuid4
import httpx
from pilotage.notify import classify,payload

class NotifyTests(unittest.TestCase):
    def test_whitelist_and_digest(self):
        p=payload(uuid4(),[('prompt','created')]*3+[('scene','deleted')])
        self.assertIn('prompt.created=3',p['text'])
        self.assertEqual(p['channel'],'C0C883XR3DF')
        with self.assertRaises(ValueError):payload(uuid4(),[('secret prompt text','created')])
    def test_rate_limit_and_uncertain(self):
        self.assertEqual(classify(httpx.Response(429,headers={'Retry-After':'120'}))[:3],('pending','rate_limit',120))
        self.assertEqual(classify(httpx.Response(500))[0],'uncertain')
        self.assertEqual(classify(httpx.Response(200,json={'ok':True}))[0],'dead')
        self.assertEqual(classify(httpx.Response(200,json={'ok':True,'ts':'1.2'}))[0],'sent')

@unittest.skipUnless(os.environ.get('PO_TEST_DATABASE_URL'),'dedicated database not configured')
class PostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        cls.db=psycopg.connect(os.environ['PO_TEST_DATABASE_URL'])
        # Only the explicit ephemeral CI test target is migrated by this suite.
        if os.environ.get('PO_ALLOW_TEST_MIGRATION')!='yes':raise RuntimeError('test migration not authorized')
        cls.db.execute(Path(__file__).with_name('migration.sql').read_text(encoding='utf-8'))
        cls.db.commit()
    @classmethod
    def tearDownClass(cls):cls.db.close()
    def args(self,kind='prompt'):
        return dict(tenant_id=uuid4(),actor_id=uuid4(),kind=kind,entity_id=uuid4(),operation='created',expected_version=0,content={'text':'sensitive content'},source_key=uuid4(),correlation_id=uuid4())
    def test_crud_all_kinds_and_replay(self):
        from pilotage.audit import mutate
        for kind in ['prompt','treatment','scenario','scene','result']:
            args=self.args(kind)
            with self.db.transaction():
                first=mutate(self.db,**args)
                self.assertEqual(first,mutate(self.db,**args))
                for version,op in [(1,'updated'),(2,'deleted')]:
                    mutate(self.db,**(args|dict(operation=op,expected_version=version,content={} if op=='deleted' else {'text':'changed'},source_key=uuid4())))
                self.assertEqual(self.db.execute('SELECT count(*) FROM po_audit WHERE entity_id=%s',(args['entity_id'],)).fetchone()[0],3)
                self.assertEqual(self.db.execute('SELECT count(*) FROM po_outbox o JOIN po_audit a USING(event_id) WHERE a.entity_id=%s',(args['entity_id'],)).fetchone()[0],3)
    def test_atomic_rollback(self):
        from pilotage.audit import mutate
        args=self.args()
        with self.assertRaises(RuntimeError):
            with self.db.transaction():
                mutate(self.db,**args)
                raise RuntimeError('abort')
        self.assertEqual(self.db.execute('SELECT count(*) FROM po_audit WHERE source_key=%s',(args['source_key'],)).fetchone()[0],0)
        self.assertEqual(self.db.execute('SELECT count(*) FROM po_entity WHERE entity_id=%s',(args['entity_id'],)).fetchone()[0],0)
        self.db.commit()
    def test_stale_version_and_cross_tenant(self):
        from pilotage.audit import mutate
        args=self.args()
        with self.db.transaction():mutate(self.db,**args)
        for update in [dict(expected_version=3),dict(tenant_id=uuid4(),expected_version=1)]:
            with self.assertRaises(ValueError):
                with self.db.transaction():mutate(self.db,**(args|dict(operation='updated',source_key=uuid4())|update))
    def test_audit_is_immutable(self):
        from pilotage.audit import mutate
        args=self.args()
        with self.db.transaction():mutate(self.db,**args)
        with self.assertRaises(Exception):
            with self.db.transaction():self.db.execute('DELETE FROM po_audit WHERE source_key=%s',(args['source_key'],))
