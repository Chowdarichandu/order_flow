"""T02 token permissions, retry, redaction, OAuth and preflight contracts."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path

import pytest
from orderflow.auth.core import TokenFile, Api, OAuth, AuthError
from orderflow.ops.preflight import preflight

NOW = datetime(2026, 10, 1, 3, 0, tzinfo=timezone.utc)


class Reply:
    def __init__(self, status, body):
        self.status_code = status
        self.body = body
    def json(self):
        return self.body
    @property
    def text(self):
        return json.dumps(self.body)


class HTTP:
    def __init__(self, replies, hook=None):
        self.replies = iter(replies)
        self.calls = []
        self.hook = hook
    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if self.hook:
            self.hook(len(self.calls))
        return next(self.replies)


def token(tmp_path, value='private-token', expiry=NOW + timedelta(hours=12)):
    store = TokenFile(tmp_path / 'token.json')
    store.write(value, expiry)
    return store


def test_secure_atomic_token_round_trip(tmp_path):
    store = token(tmp_path)
    assert store.read(NOW) == 'private-token'
    assert store.path.stat().st_mode & 0o777 == 0o600
    store.write('second-token', NOW + timedelta(hours=1))
    assert store.read(NOW) == 'second-token'
    assert not list(tmp_path.glob('*.tmp'))


@pytest.mark.parametrize('mode', [0o644, 0o666, 0o400])
def test_non_600_token_is_rejected(tmp_path, mode):
    store = token(tmp_path)
    os.chmod(store.path, mode)
    with pytest.raises(AuthError):
        store.read(NOW)


def test_missing_expired_and_naive_token_rejected(tmp_path):
    with pytest.raises(AuthError):
        TokenFile(tmp_path / 'absent').read(NOW)
    store = token(tmp_path, expiry=NOW)
    with pytest.raises(AuthError, match='expired'):
        store.read(NOW)
    with pytest.raises(ValueError, match='aware'):
        store.write('x', NOW.replace(tzinfo=None))


def test_symlink_token_rejected(tmp_path):
    store = token(tmp_path)
    link = tmp_path / 'link'
    link.symlink_to(store.path)
    with pytest.raises(AuthError):
        TokenFile(link).read(NOW)


@pytest.mark.parametrize('code', [401, 403])
def test_token_reread_exactly_once_and_no_token_log(tmp_path, code, caplog):
    store = token(tmp_path)
    http = HTTP([Reply(code, {'error': 'private-token', 'access_token': 'leaked'}),
                 Reply(200, {'data': {'authorized_redirect_uri': 'wss://example.test'}})],
                hook=lambda n: store.write('rotated-token', NOW + timedelta(hours=1)) if n == 1 else None)
    api = Api(http, store, now=lambda: NOW)
    assert api.authorize() == 'wss://example.test'
    assert [c[2]['headers']['Authorization'] for c in http.calls] == [
        'Bearer private-token', 'Bearer rotated-token']
    assert all(c[2]['headers']['User-Agent'] for c in http.calls)
    assert 'private-token' not in caplog.text and 'leaked' not in caplog.text
    assert str(code) in caplog.text and 'error' in caplog.text


def test_persistent_failure_logs_both_attempts(tmp_path, caplog):
    http = HTTP([Reply(403, {'error': 'denied'}), Reply(403, {'error': 'denied again'})])
    with pytest.raises(AuthError):
        Api(http, token(tmp_path), now=lambda: NOW).authorize()
    assert len(http.calls) == 2
    assert caplog.text.count('status=403') == 2


def test_non_auth_error_is_not_retried_in_api(tmp_path):
    http = HTTP([Reply(500, {'error': 'unavailable'})])
    with pytest.raises(AuthError):
        Api(http, token(tmp_path), now=lambda: NOW).authorize()
    assert len(http.calls) == 1


def test_preflight_hard_and_soft_gates(tmp_path):
    api = Api(HTTP([Reply(200, {'data': {'authorized_redirect_uri': 'simulator://feed'}})]),
              token(tmp_path), now=lambda: NOW)
    report = preflight(api, soft_checks={'disk': lambda: 'low space'}, attempts=1)
    assert report.ready and report.soft_alerts == ['disk: low space']
    absent = Api(HTTP([]), TokenFile(tmp_path / 'absent'), now=lambda: NOW)
    assert not preflight(absent, attempts=1).ready


def test_preflight_retries_with_injected_sleep_and_soft_exception(tmp_path):
    http = HTTP([Reply(500, {}), Reply(200, {'data': {'authorized_redirect_uri': 'simulator://feed'}})])
    delays = []
    report = preflight(Api(http, token(tmp_path), now=lambda: NOW), attempts=2,
                       retry_seconds=7, sleep=delays.append,
                       soft_checks={'calendar': lambda: 1/0})
    assert report.ready and delays == [7]
    assert report.soft_alerts and len(http.calls) == 2


def test_oauth_state_code_exchange_and_daily_expiry(tmp_path):
    http = HTTP([Reply(200, {'access_token': 'fresh'})])
    oauth = OAuth(http, client_id='id', client_secret='secret', redirect_uri='http://localhost/callback')
    url = oauth.login_url('state-nonce')
    assert 'response_type=code' in url and 'state=state-nonce' in url
    store = TokenFile(tmp_path / 'newtoken')
    oauth.exchange('daily-code', store, now=NOW)
    assert store.read(NOW) == 'fresh'
    body = json.loads(store.path.read_text())
    # NOW=08:30 IST; daily expiry is the following 03:30 IST (22:00 UTC).
    assert datetime.fromisoformat(body['expires_at']) == datetime(2026, 10, 1, 22, tzinfo=timezone.utc)
    call = http.calls[0]
    assert call[2]['data']['grant_type'] == 'authorization_code'
    assert call[2]['headers']['User-Agent']


def test_oauth_failure_redacts_code_and_secret(tmp_path, caplog):
    oauth = OAuth(HTTP([Reply(400, {'error': 'secret daily-code', 'access_token': 'fresh'})]),
                  client_id='id', client_secret='secret', redirect_uri='http://localhost/callback')
    with pytest.raises(AuthError):
        oauth.exchange('daily-code', TokenFile(tmp_path/'token'), now=NOW)
    assert all(value not in caplog.text for value in ('secret', 'daily-code', 'fresh'))
    assert 'status=400' in caplog.text
