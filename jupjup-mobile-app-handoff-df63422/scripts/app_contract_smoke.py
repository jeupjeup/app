#!/usr/bin/env python3
"""Exercise the mobile API against a running server using only the standard library."""
import argparse
import json
import sys
import uuid
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', required=True, help='API base URL, including /api')
    base = parser.parse_args().base_url.rstrip('/')
    token = ''

    def call(method: str, path: str, body: dict | None = None) -> dict:
        headers = {'Accept': 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        data = None
        if body is not None:
            headers['Content-Type'] = 'application/json'
            data = json.dumps(body).encode()
        request = Request(base + path, data=data, headers=headers, method=method)
        with urlopen(request, timeout=15) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}

    email = f'mobile+smoke-{uuid.uuid4().hex}@example.com'
    password = 'SmokeTest1!'
    try:
        assert call('GET', '/health')['status'] == 'ok'
        session = call('POST', '/auth/register', {'email': email, 'password': password, 'nickname': 'Smoke',
                       'requiredConsent': True, 'notificationsEnabled': False})
        token = session['token']
        session = call('POST', '/auth/login', {'email': email, 'password': password})
        token = session['token']
        content = call('POST', '/contents', {'url': f'https://example.com/{uuid.uuid4().hex}'})
        state = call('GET', '/state')
        assert any(item['id'] == content['id'] for item in state['contents'])
        print('PASS: health, register, login, create and state')
    except (HTTPError, URLError, ValueError, KeyError, AssertionError) as exc:
        print(f'FAIL: {type(exc).__name__}', file=sys.stderr)
        return 1
    finally:
        if token:
            try:
                call('DELETE', '/me')
            except (HTTPError, URLError):
                print('FAIL: test account cleanup', file=sys.stderr)
                return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
