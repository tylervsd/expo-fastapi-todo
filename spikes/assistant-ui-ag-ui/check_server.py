"""Run with the app's Python environment; no running server required."""
import json
from fastapi.testclient import TestClient
from server import app

client = TestClient(app)
body = {'threadId': 'check', 'runId': 'check', 'messages': [{'id': 'u', 'role': 'user', 'content': 'party'}]}
assert client.post('/agent', json=body).status_code == 401
headers = {'Authorization': 'Bearer fixture-only'}
assert client.post('/agent', headers=headers, json={}).status_code == 422
response = client.post('/agent', headers=headers, json=body)
events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
assert [event['type'] for event in events] == ['RUN_STARTED', 'TOOL_CALL_START', 'TOOL_CALL_ARGS', 'TOOL_CALL_END', 'RUN_FINISHED']
body['messages'].append({'id': 't', 'role': 'tool', 'toolCallId': events[1]['toolCallId'], 'content': '{"answer":"Saturday"}'})
response = client.post('/agent', headers=headers, json=body)
assert 'Saturday' in response.text and 'TEXT_MESSAGE_CONTENT' in response.text
print('Fixture auth, event sequence, and tool-result continuation passed')
