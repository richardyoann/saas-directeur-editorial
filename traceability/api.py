import hashlib
import hmac
import json
import os
import re
from typing import Literal
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field

from traceability import store
from traceability.events import ITEM_ID

router = APIRouter(prefix='/trace')


def authorized(x_trace_key: str = Header(default='')):
    expected = os.environ.get('TRACE_API_KEY', '')
    if not expected:
        raise HTTPException(503, 'Trace API disabled')
    if not hmac.compare_digest(x_trace_key.encode(), expected.encode()):
        raise HTTPException(401, 'Unauthorized')


class Item(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(pattern=ITEM_ID.pattern)
    kind: Literal['epic','story','task','subtask']
    parent_id: str | None = Field(default=None, pattern=ITEM_ID.pattern)
    status: Literal['todo','in_progress','done','blocked'] = 'todo'


class Update(BaseModel):
    model_config = ConfigDict(extra='forbid')
    status: Literal['todo','in_progress','done','blocked']
    expected_version: int = Field(ge=1, le=2147483646)


def db_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except store.Conflict:
        raise HTTPException(409, 'Conflicting version or idempotency key') from None
    except ValueError:
        raise HTTPException(422, 'Invalid hierarchy or metadata') from None
    except (psycopg.Error, KeyError):
        raise HTTPException(503, 'Trace persistence unavailable') from None


@router.post('/work-items', dependencies=[Depends(authorized)])
def create(item: Item, request: Request):
    return {'event_id':db_call(store.create_item, item.model_dump(), request.state.correlation_id)}


@router.patch('/work-items/{item_id}', dependencies=[Depends(authorized)])
def update(item_id: str, item: Update, request: Request):
    if not ITEM_ID.fullmatch(item_id):
        raise HTTPException(422, 'Invalid ID')
    return {'event_id':db_call(store.update_item, item_id, item.status, item.expected_version, request.state.correlation_id)}


def verify_signature(body, signature, secret):
    expected = 'sha256=' + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post('/github')
async def github(request: Request):
    secret = os.environ.get('TRACE_GITHUB_WEBHOOK_SECRET', '')
    if not secret:
        raise HTTPException(503, 'Webhook disabled')
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 1048576:
            raise HTTPException(413, 'Payload too large')
    if not verify_signature(bytes(body), request.headers.get('x-hub-signature-256',''), secret):
        raise HTTPException(401, 'Invalid signature')
    try:
        delivery = str(UUID(request.headers.get('x-github-delivery','')))
        payload = json.loads(body)
        repo = payload['repository']
        if repo['full_name'] != 'richardyoann/saas-directeur-editorial' or repo['id'] != 1411435489:
            raise HTTPException(403, 'Unexpected repository')
        if request.headers.get('x-github-event') != 'pull_request':
            return {'ignored':True}
        pr = payload['pull_request']
        ids = sorted(set(re.findall(r'\b[A-Z][A-Z0-9]{1,15}-[0-9]{3,10}\b', str(pr.get('title',''))+' '+str(pr.get('body','')))))
        data = {'number':payload['number'],'action':payload['action'],'merged':pr.get('merged',False),'work_item_ids':ids}
        # Unknown linked IDs remain metadata; the event itself has no invented FK.
        event = await run_in_threadpool(db_call, store.record, source_key='github:'+delivery,
                                       correlation_id=delivery,event_type='github.pull_request',data=data)
        return {'event_id':event}
    except (ValueError, KeyError, TypeError):
        raise HTTPException(422, 'Invalid webhook payload') from None


def install(app):
    app.include_router(router)

    @app.middleware('http')
    async def correlation_and_business_audit(request, call_next):
        # A request ID is distinct from GitHub delivery IDs and source keys.
        request.state.correlation_id = str(uuid4())
        cid = request.state.correlation_id
        enabled = os.environ.get('TRACE_ENABLED') == '1' and request.url.path == '/ai/generate' and request.method == 'POST'
        if enabled:
            try:
                await run_in_threadpool(store.record, source_key='generation:'+cid+':requested',
                                        correlation_id=cid,event_type='generation.requested',data={})
            except (psycopg.Error, KeyError, ValueError):
                from fastapi.responses import JSONResponse
                return JSONResponse({'detail':'Trace persistence unavailable'}, status_code=503, headers={'X-Correlation-ID':cid})
        try:
            response = await call_next(request)
        except Exception:
            if enabled:
                try:
                    await run_in_threadpool(store.record, source_key='generation:'+cid+':result',correlation_id=cid,
                                            event_type='generation.failed',data={'status_code':500})
                except (psycopg.Error, KeyError, ValueError):
                    pass  # Requested event remains durable and visibly incomplete.
            raise
        if enabled:
            try:
                kind = 'completed' if response.status_code < 400 else 'failed'
                await run_in_threadpool(store.record, source_key='generation:'+cid+':result',correlation_id=cid,
                                        event_type='generation.'+kind,data={'status_code':response.status_code})
            except (psycopg.Error, KeyError, ValueError):
                from fastapi.responses import JSONResponse
                return JSONResponse({'detail':'Generation outcome could not be audited; inspect correlation ID before retry'}, status_code=503, headers={'X-Correlation-ID':cid})
        response.headers['X-Correlation-ID'] = cid
        return response
