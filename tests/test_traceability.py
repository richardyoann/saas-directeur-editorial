import hashlib
import hmac
import json
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

import httpx

from apps.api.main import app
from traceability.api import verify_signature
from traceability.events import safe_data, slack_payload
from traceability.worker import deliver, outcome


class TraceTests(unittest.TestCase):
    def row(self):
        return dict(event_id=uuid4(),correlation_id=uuid4(),channel_id='C0C883XR3DF',
                    work_item_id='DEV-004',event_type='work_item.created',
                    data=dict(kind='story',parent_id='EPIC-001',status='todo',version=1))

    def test_payload_stable_event_and_correlation(self):
        row = self.row()
        self.assertEqual(slack_payload(row), slack_payload(row))
        self.assertEqual(slack_payload(row)['client_msg_id'],str(row['event_id']))
        self.assertIn(str(row['correlation_id']),slack_payload(row)['text'])

    def test_secrets_and_free_text_rejected_before_storage(self):
        for key in ('password','authorization','token','prompt','response','title','url'):
            with self.subTest(key=key), self.assertRaises(ValueError):
                safe_data('generation.completed', {'status_code':200,key:'sensitive'})
        with self.assertRaises(ValueError):
            safe_data('work_item.created',{'kind':'Bearer private'})

    def test_signature_tampering(self):
        body = b'{"action":"opened"}'
        signature = 'sha256='+hmac.new(b'synthetic-key',body,hashlib.sha256).hexdigest()
        self.assertTrue(verify_signature(body,signature,'synthetic-key'))
        self.assertFalse(verify_signature(body+b' ',signature,'synthetic-key'))
        self.assertFalse(verify_signature(body,signature,'different-key'))

    def test_slack_failure_classification(self):
        cases = [
            (httpx.Response(200,json={'ok':True,'ts':'123.456'}),'sent'),
            (httpx.Response(429,headers={'Retry-After':'120'}),'pending'),
            (httpx.Response(500),'uncertain'),
            (httpx.Response(200,text='invalid'),'uncertain'),
            (httpx.Response(200,json={'ok':True}),'uncertain'),
            (httpx.Response(200,json={'ok':False,'error':'invalid_auth'}),'dead'),
            (httpx.Response(200,json={'ok':False,'error':'internal_error'}),'uncertain'),
        ]
        for response, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(outcome(response)[0],expected)
        self.assertEqual(outcome(cases[1][0])[2],120)

    def test_connect_retry_but_read_timeout_uncertain(self):
        for exception, expected in [(httpx.ConnectError,'pending'),(httpx.ReadTimeout,'uncertain'),(httpx.WriteTimeout,'uncertain')]:
            def handler(request):
                raise exception('private token must never persist',request=request)
            with httpx.Client(transport=httpx.MockTransport(handler)) as client:
                result = deliver(client,self.row(),'synthetic-token')
                self.assertEqual(result[0],expected)
                self.assertNotIn('private',str(result))


class TraceApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.env = patch.dict(os.environ,{'TRACE_API_KEY':'synthetic','TRACE_ENABLED':'0','TRACE_GITHUB_WEBHOOK_SECRET':'synthetic'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://api.test')
        self.addAsyncCleanup(self.client.aclose)

    async def test_auth_and_validation_precede_database(self):
        with patch('traceability.store.create_item') as create:
            response = await self.client.post('/trace/work-items',json={'id':'EPIC-001','kind':'epic'})
            self.assertEqual(response.status_code,401)
            response = await self.client.post('/trace/work-items',headers={'X-Trace-Key':'synthetic'},json={'id':'EPIC-001','kind':'epic','password':'hidden'})
            self.assertEqual(response.status_code,422)
            create.assert_not_called()

    async def test_create_persists_with_server_correlation(self):
        with patch('traceability.store.create_item',return_value='event') as create:
            response = await self.client.post('/trace/work-items',headers={'X-Trace-Key':'synthetic'},json={'id':'EPIC-001','kind':'epic'})
            self.assertEqual(response.status_code,200)
            self.assertEqual(create.call_args.args[1],response.headers['X-Correlation-ID'])

    async def test_disabled_configuration_is_closed(self):
        with patch.dict(os.environ,{'TRACE_API_KEY':''}):
            response = await self.client.post('/trace/work-items',json={'id':'EPIC-001','kind':'epic'})
            self.assertEqual(response.status_code,503)

    async def test_unavailable_audit_blocks_generation(self):
        with patch.dict(os.environ,{'TRACE_ENABLED':'1'}), patch('traceability.store.record',side_effect=KeyError('database')), patch('httpx.AsyncClient.post'):
            # Use request() so the upstream post patch doesn't mock our ASGI request.
            response = await self.client.request('POST','/ai/generate',json={'prompt':'hello'})
            self.assertEqual(response.status_code,503)

    async def test_signed_pr_and_delivery_deduplication_key(self):
        delivery = str(uuid4())
        body = json.dumps({'repository':{'id':1411435489,'full_name':'richardyoann/saas-directeur-editorial'},'number':7,'action':'opened','pull_request':{'title':'DEV-004 password=private','body':'EPIC-001','merged':False}}).encode()
        signature = 'sha256='+hmac.new(b'synthetic',body,hashlib.sha256).hexdigest()
        headers = {'X-GitHub-Delivery':delivery,'X-GitHub-Event':'pull_request','X-Hub-Signature-256':signature}
        with patch('traceability.store.record',return_value='event') as record:
            for _ in range(2):
                response = await self.client.post('/trace/github',content=body,headers=headers)
                self.assertEqual(response.status_code,200)
                self.assertEqual(record.call_args.kwargs['source_key'],'github:'+delivery)
                self.assertNotIn('private',str(record.call_args))
            response = await self.client.post('/trace/github',content=body+b' ',headers=headers)
            self.assertEqual(response.status_code,401)

    async def test_foreign_repository_rejected(self):
        body = json.dumps({'repository':{'id':1,'full_name':'another/repo'}}).encode()
        signature = 'sha256='+hmac.new(b'synthetic',body,hashlib.sha256).hexdigest()
        response = await self.client.post('/trace/github',content=body,headers={'X-GitHub-Delivery':str(uuid4()),'X-Hub-Signature-256':signature})
        self.assertEqual(response.status_code,403)
