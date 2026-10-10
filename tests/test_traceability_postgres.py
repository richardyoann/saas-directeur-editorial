"""Opt-in against an ALREADY migrated dedicated database. No migration or cleanup."""
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

from traceability import store
from traceability.worker import run_once
from concurrent.futures import ThreadPoolExecutor
import asyncio
import httpx
from apps.api.main import app, get_llm_client


@unittest.skipUnless(os.environ.get('TRACE_TEST_DATABASE_URL'),'dedicated migrated PostgreSQL not configured')
class PostgresTraceTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ,{'TRACE_DATABASE_URL':os.environ['TRACE_TEST_DATABASE_URL']})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_atomic_rollback_and_deduplication(self):
        key = 'test:'+str(uuid4())
        cid = uuid4()
        args = dict(source_key=key,correlation_id=cid,event_type='generation.completed',data={'status_code':200})
        with self.assertRaises(RuntimeError):
            with store.connect() as conn:
                store.emit(conn,**args)
                raise RuntimeError('rollback')
        with store.connect() as conn:
            self.assertEqual(conn.execute('SELECT count(*) AS n FROM trace_audit WHERE source_key=%s',(key,)).fetchone()['n'],0)
        first = store.record(**args)
        self.assertEqual(first,store.record(**args))
        with self.assertRaises(store.Conflict):
            store.record(**(args | {'data':{'status_code':500}}))
        with store.connect() as conn:
            self.assertEqual(conn.execute('SELECT count(*) AS n FROM trace_outbox WHERE event_id=%s',(first,)).fetchone()['n'],1)

    def test_hierarchy_and_optimistic_lock(self):
        base = int(uuid4().hex[:8],16)
        root = f'EPIC-{base:010d}'
        child = f'DEV-{base:010d}'
        cid = uuid4()
        item = dict(id=root,kind='epic',parent_id=None,status='todo')
        event = store.create_item(item,cid)
        self.assertEqual(event,store.create_item(item,cid))
        with self.assertRaises(ValueError):
            store.create_item(dict(id=child,kind='task',parent_id=root,status='todo'),cid)
        store.create_item(dict(id=child,kind='story',parent_id=root,status='todo'),cid)
        store.update_item(child,'done',1,cid)
        with self.assertRaises(store.Conflict):
            store.update_item(child,'blocked',1,cid)

    def test_worker_claim_concurrency_and_sent_no_resend(self):
        event = store.record(source_key='worker-test:'+str(uuid4()),correlation_id=uuid4(),event_type='generation.completed',data={'status_code':200})
        # Isolate the worker's queue to this test without removing any audit data.
        with store.connect() as conn:
            conn.execute("UPDATE trace_outbox SET next_attempt_at=now()+interval '1 day' WHERE state='pending' AND event_id<>%s",(event,))
        with patch.dict(os.environ,{'TRACE_SLACK_BOT_TOKEN':'synthetic'}), patch('traceability.worker.deliver',return_value=('sent',None,0,'123.456')) as deliver:
            with ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(lambda _:run_once(),range(2)))
            self.assertEqual(deliver.call_count,1)
            self.assertFalse(run_once())
        with store.connect() as conn:
            row = conn.execute('SELECT state,attempts FROM trace_outbox WHERE event_id=%s',(event,)).fetchone()
            self.assertEqual(row,{'state':'sent','attempts':1})

    def test_expired_claim_becomes_uncertain_without_send(self):
        event = store.record(source_key='crash-test:'+str(uuid4()),correlation_id=uuid4(),event_type='generation.completed',data={'status_code':200})
        with store.connect() as conn:
            conn.execute("UPDATE trace_outbox SET state='sending',claimed_at=now()-interval '6 minutes' WHERE event_id=%s",(event,))
            conn.execute("UPDATE trace_outbox SET next_attempt_at=now()+interval '1 day' WHERE state='pending'")
        with patch.dict(os.environ,{'TRACE_SLACK_BOT_TOKEN':'synthetic'}), patch('traceability.worker.deliver') as deliver:
            self.assertFalse(run_once())
            deliver.assert_not_called()
        with store.connect() as conn:
            self.assertEqual(conn.execute('SELECT state FROM trace_outbox WHERE event_id=%s',(event,)).fetchone()['state'],'uncertain')

    def test_fastapi_generation_real_audit_without_content(self):
        async def scenario():
            async def model():
                async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request:httpx.Response(200,json={'model':'test','choices':[{'message':{'content':'private-response'}}]}))) as client:
                    yield client
            app.dependency_overrides[get_llm_client] = model
            try:
                with patch.dict(os.environ,{'TRACE_ENABLED':'1','LLM_BASE_URL':'http://model.test'}):
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://api.test') as client:
                        response = await client.post('/ai/generate',json={'prompt':'private-prompt'})
                        self.assertEqual(response.status_code,200)
                        return response.headers['X-Correlation-ID']
            finally:
                app.dependency_overrides.pop(get_llm_client,None)
        cid = asyncio.run(scenario())
        with store.connect() as conn:
            rows = conn.execute('SELECT event_type,data FROM trace_audit WHERE correlation_id=%s ORDER BY occurred_at',(cid,)).fetchall()
            self.assertEqual([r['event_type'] for r in rows],['generation.requested','generation.completed'])
            self.assertNotIn('private',str(rows))
            count = conn.execute('SELECT count(*) AS n FROM trace_outbox JOIN trace_audit USING(event_id) WHERE correlation_id=%s',(cid,)).fetchone()['n']
            self.assertEqual(count,2)
