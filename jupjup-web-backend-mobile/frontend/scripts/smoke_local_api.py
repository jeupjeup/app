"""Loopback-only text smoke against the dedicated integration API + worker.

Run: python3 frontend/scripts/smoke_local_api.py
Uses its own user, creates unique text, and deletes only resources it created.
No source URL fetch, model download, or external service is involved.
"""
import json
import time
import uuid
import urllib.error
import urllib.request

BASE = 'http://127.0.0.1:5177/api'
USER = 'u_frontend_smoke'
created = []

def call(method, path, body=None, key=None, etag=None, user=USER, expected=200):
    headers = {'X-User-Id': user, 'Content-Type': 'application/json'}
    if key: headers['Idempotency-Key'] = key
    if etag: headers['If-Match'] = etag
    request = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None, headers=headers, method=method)
    try:
        response = urllib.request.urlopen(request, timeout=10)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        assert response.status == expected, (method, path, response.status)
        raw = response.read()
        return (json.loads(raw) if raw else None), response.headers

def wait_job(job_id, desired):
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        job, _ = call('GET', '/v1/jobs/' + job_id)
        if job['status'] in desired: return job
        assert job['status'] not in ['failed', 'needs_review', 'cancelled'], job['status']
        time.sleep(.2)
    raise AssertionError('Worker did not reach the expected state')

def main():
    text = '서울 성수동 카페 여행 기록. 주말에 커피와 빵을 먹고 창가에서 독서했습니다. 통합검증 ' + uuid.uuid4().hex
    body = {'source': {'kind': 'text', 'text': text}, 'automation_level': 'confirm'}
    key = uuid.uuid4().hex
    submit, _ = call('POST', '/v1/contents', body, key, expected=202)
    cid, jid = submit['content_id'], submit['job_id']
    created.append(cid)
    replay, headers = call('POST', '/v1/contents', body, key, expected=202)
    assert replay == submit and headers['Idempotency-Replayed'] == 'true'
    conflict, _ = call('POST', '/v1/contents', {**body, 'automation_level': 'auto'}, key, expected=409)
    assert conflict['error']['code'] == 'IDEMPOTENCY_CONFLICT'
    wait_job(jid, {'awaiting_confirmation'})
    detail, headers = call('GET', '/v1/contents/' + cid)
    assert detail['snapshot']['text'] == text
    assert {'id', 'text', 'ocr_text', 'captured_at', 'content_hash', 'truncated'} <= detail['snapshot'].keys()
    job, _ = call('GET', '/v1/jobs/' + jid)
    assert {'stage', 'status', 'attempts', 'started_at', 'finished_at', 'duration_ms', 'error'} <= job['steps'][0].keys()
    candidate = detail['analysis']['candidate']['id']
    call('POST', '/v1/contents/' + cid + ':review', {'candidate_id': candidate, 'decision': 'approve'}, expected=202)
    wait_job(jid, {'succeeded'})
    detail, headers = call('GET', '/v1/contents/' + cid)
    stale = headers['ETag']
    patched, headers = call('PATCH', '/v1/contents/' + cid, {'summary': '성수동 카페에서 커피를 마시며 독서한 사용자 여행 요약입니다.', 'representative_tags': ['성수동', '카페'], 'detail_tags': {'topics': ['독서', '주말']}}, etag=stale)
    assert patched['summary']['source'] == 'user'
    call('PATCH', '/v1/contents/' + cid, {'summary': '경쟁 수정'}, etag=stale, expected=409)
    call('GET', '/v1/contents/' + cid, user='u_other_frontend', expected=404)
    retry, _ = call('POST', '/v1/contents/' + cid + ':reanalyze', {'automation_level': 'confirm'}, uuid.uuid4().hex, expected=202)
    wait_job(retry['job_id'], {'awaiting_confirmation'})
    detail, _ = call('GET', '/v1/contents/' + cid)
    call('POST', '/v1/contents/' + cid + ':review', {'candidate_id': detail['analysis']['candidate']['id'], 'decision': 'reject'})
    detail, headers = call('GET', '/v1/contents/' + cid)
    assert detail['status'] == 'analysis_rejected' and detail['summary']['user'] == patched['summary']['user']
    assert detail['detail_tags']['effective']['topics'] == ['독서', '주말']
    result, _ = call('POST', '/v1/search', {'query': '성수동 카페', 'limit': 30})
    assert cid in [row['content_id'] for row in result['results']]
    ranks = [row['rank'] for row in result['results']]
    assert ranks == sorted(ranks)
    hidden, headers = call('PATCH', '/v1/contents/' + cid, {'hidden': True}, etag=headers['ETag'])
    result, _ = call('POST', '/v1/search', {'query': '성수동 카페'})
    assert cid not in [row['content_id'] for row in result['results']]
    call('PATCH', '/v1/contents/' + cid, {'hidden': False}, etag=headers['ETag'])
    call('DELETE', '/v1/contents/' + cid, expected=204)
    call('GET', '/v1/contents/' + cid, expected=404)
    created.remove(cid)
    print('PASS: proxy, save/replay/conflict, real worker, snapshot/steps schema, approve, ETag PATCH/conflict, user isolation, reanalyze/reject, search, hide/unhide, delete')

try:
    main()
finally:
    for content_id in created:
        call('DELETE', '/v1/contents/' + content_id, expected=204)
