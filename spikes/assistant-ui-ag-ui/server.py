"""Disposable AG-UI fixture. No database, secrets, or LLM calls."""
import asyncio
import json
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=['http://localhost:8082', 'http://127.0.0.1:8082'], allow_methods=['POST'], allow_headers=['authorization', 'content-type'])

@app.post('/agent')
async def agent(request: Request):
    if request.headers.get('authorization') != 'Bearer fixture-only':
        raise HTTPException(401)
    body = await request.json()
    if not all(k in body for k in ('threadId', 'runId', 'messages')):
        raise HTTPException(422)
    async def events():
        def event(kind, **kwargs):
            return 'data: ' + json.dumps({'type': kind, **kwargs}) + '\n\n'
        ids = {k: body[k] for k in ('threadId', 'runId')}
        yield event('RUN_STARTED', **ids)
        last = body['messages'][-1]
        print('fixture request:', last, flush=True)
        if last['role'] == 'tool' or last.get('content') == 'slow':
            mid = str(uuid4())
            yield event('TEXT_MESSAGE_START', messageId=mid, role='assistant')
            yield event('TEXT_MESSAGE_CONTENT', messageId=mid, delta='Received: ')
            await asyncio.sleep(10 if last.get('content') == 'slow' else .3)
            yield event('TEXT_MESSAGE_CONTENT', messageId=mid, delta=last['content'])
            yield event('TEXT_MESSAGE_END', messageId=mid)
        else:
            tid = str(uuid4())
            yield event('TOOL_CALL_START', toolCallId=tid, toolCallName='clarify_plan')
            yield event('TOOL_CALL_ARGS', toolCallId=tid, delta='{"field":"date"}')
            yield event('TOOL_CALL_END', toolCallId=tid)
        yield event('RUN_FINISHED', **ids)
    return StreamingResponse(events(), media_type='text/event-stream')
