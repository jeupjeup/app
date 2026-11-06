import hashlib
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from jupjup.app_api.http import create_api
from jupjup.cli import app
from jupjup.storage.db import create_db_engine


def test_spec_is_frozen() -> None:
    spec = Path('specs/app_api_openapi.json').read_bytes()
    assert hashlib.sha256(spec).hexdigest() == 'cd18e859669a75280dd8d130150a96a2a0966855911d3b175fbaabaea651194d'


def test_unknown_routes_and_head() -> None:
    engine = create_db_engine(None)
    with TestClient(create_api(engine)) as client:
        response = client.get('/health/')
        assert response.status_code == 404
        assert response.json()['error']['code'] == 'NOT_FOUND'
        assert client.head('/health').status_code == 404
    engine.dispose()


def test_external_bind_policy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr('uvicorn.run', lambda application, **kwargs: calls.append({'app': application, **kwargs}))
    monkeypatch.setenv('JUPJUP_DB_PATH', str(tmp_path / 'test.db'))
    runner = CliRunner()
    args = ['api', 'serve', '--host', '0.0.0.0', '--no-worker']
    monkeypatch.setenv('JUPJUP_AUTH_BACKEND', 'dev_header')
    assert runner.invoke(app, [*args, '--allow-external-bind']).exit_code == 2
    monkeypatch.setenv('JUPJUP_AUTH_BACKEND', 'app_session')
    assert runner.invoke(app, args).exit_code == 2
    result = runner.invoke(app, [*args, '--allow-external-bind'])
    assert result.exit_code == 0, result.output
    assert calls[0]['host'] == '0.0.0.0'
    assert not calls[0]['app'].state.container.settings.admin_api_enabled
    assert '<LAN-IP>:8000/api' in result.output
