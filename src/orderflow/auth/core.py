"""Section 1: explicit User-Agent, secure file tokens and sanitized failures."""
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

LOG = logging.getLogger(__name__)
USER_AGENT = 'orderflow-zero/0.1.0'
BASE_URL = 'https://api.upstox.com'


class AuthError(RuntimeError):
    """Sanitized authentication or authorization failure."""


def aware(value: datetime) -> datetime:
    """Section 1 rule 8: reject naive timestamps and compare in UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('timestamp must be timezone-aware')
    return value.astimezone(timezone.utc)


def atomic_file(path: Path, content: bytes, mode: int = 0o600) -> None:
    """Replace an fsynced same-directory temporary file, then fsync the directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, 'wb') as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def secure_json(path: Path) -> dict[str, Any]:
    """Section 1 rule 2: read a regular 0600 file without following symlinks."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, 'r') as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
                raise AuthError('credential file must be a regular 0600 file')
            data = json.load(handle)
        if not isinstance(data, dict):
            raise AuthError('credential document must be an object')
        return data
    except (OSError, ValueError) as error:
        raise AuthError('credential file missing, unsafe or invalid') from None


class TokenFile:
    """Section 1 rule 2: tokens are read at connect time, never environment handoffs."""
    def __init__(self, path: Path | str):
        self.path = Path(path)

    def read(self, now: datetime) -> str:
        """Read an unexpired token from a regular 0600 JSON file."""
        data = secure_json(self.path)
        try:
            expiry = aware(datetime.fromisoformat(data['expires_at']))
            token = data['access_token']
            if not isinstance(token, str) or not token:
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise AuthError('invalid token document') from None
        if expiry <= aware(now):
            raise AuthError('token expired')
        return token

    def write(self, token: str, expires_at: datetime) -> None:
        """Atomically write daily access token + aware expiry with mode 0600."""
        if not token:
            raise AuthError('empty token')
        expiry = aware(expires_at)
        atomic_file(self.path, json.dumps({'access_token': token,
                    'expires_at': expiry.isoformat()}).encode())


def sanitized_body(response: Any, secrets: tuple[str, ...]) -> str:
    """Section 1 rule 4: retain failure body/status while redacting credentials."""
    def clean(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: '[REDACTED]' if re.search(
                r'token|secret|password|authorization|code|api.?key', str(key), re.I)
                else clean(item) for key, item in value.items()}
        if isinstance(value, list):
            return [clean(item) for item in value]
        text = str(value)
        for secret in secrets:
            if secret:
                text = text.replace(secret, '[REDACTED]')
        return re.sub(r'(?i)bearer\s+\S+', 'Bearer [REDACTED]', text)
    try:
        body = response.json()
    except Exception:
        body = response.text
    return json.dumps(clean(body))[:2048]


class Api:
    """Injected HTTP; every request sets User-Agent and reads token at call time."""
    def __init__(self, http: Any, token_file: TokenFile, *,
                 now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 timeout: float = 15):
        self.http, self.token_file, self.now, self.timeout = http, token_file, now, timeout

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        """Section 1 rule 2: on 401/403 reread the token once and retry once."""
        for attempt in range(2):
            token = self.token_file.read(self.now())
            headers = dict(kwargs.pop('headers', {}))
            headers.update({'User-Agent': USER_AGENT, 'Authorization': 'Bearer ' + token})
            try:
                response = self.http.request(method, BASE_URL + path, headers=headers,
                                             timeout=self.timeout, **kwargs)
            except Exception:
                LOG.error('connect failure status=unavailable body="transport failure"')
                raise AuthError('HTTP transport failure') from None
            if response.status_code == 200:
                return response
            LOG.error('auth/connect failure status=%s body=%s', response.status_code,
                      sanitized_body(response, (token,)))
            if response.status_code not in (401, 403) or attempt == 1:
                raise AuthError(f'HTTP failure status={response.status_code}')
        raise AssertionError('unreachable')

    def authorize(self) -> str:
        """Section 2: feed authorize returns the sole recorder websocket URL."""
        response = self.request('GET', '/v3/feed/market-data-feed/authorize')
        try:
            url = response.json()['data']['authorized_redirect_uri']
            if not isinstance(url, str) or not url.startswith(('wss://', 'simulator://')):
                raise ValueError()
            return url
        except (KeyError, TypeError, ValueError):
            LOG.error('connect failure status=200 body="invalid authorization response"')
            raise AuthError('invalid authorization response') from None


class OAuth:
    """OAuth authorization-code exchange; no unsupported refresh-token grant.

    Upstox daily renewal needs a new owner-approved authorization code. The daily
    job exchanges a fresh code-file and writes the token file; it cannot bypass
    login/2FA or reuse yesterday's one-use code. RUNBOOK explains this constraint.
    """
    def __init__(self, http: Any, *, client_id: str, client_secret: str, redirect_uri: str):
        self.http, self.client_id = http, client_id
        self.client_secret, self.redirect_uri = client_secret, redirect_uri

    def login_url(self, state: str) -> str:
        """Construct browser authorization URL with caller-managed CSRF state."""
        if not state:
            raise ValueError('OAuth state required')
        return BASE_URL + '/v2/login/authorization/dialog?' + urlencode(dict(
            response_type='code', client_id=self.client_id,
            redirect_uri=self.redirect_uri, state=state))

    def exchange(self, code: str, target: TokenFile, *, now: datetime) -> None:
        """Exchange a fresh code; expire the stored token at next 03:30 IST."""
        now = aware(now)
        try:
            response = self.http.request('POST', BASE_URL + '/v2/login/authorization/token',
                headers={'User-Agent': USER_AGENT, 'Accept': 'application/json'}, timeout=15,
                data=dict(code=code, client_id=self.client_id, client_secret=self.client_secret,
                          redirect_uri=self.redirect_uri, grant_type='authorization_code'))
        except Exception:
            LOG.error('auth failure status=unavailable body="transport failure"')
            raise AuthError('OAuth transport failure') from None
        if response.status_code != 200:
            LOG.error('auth failure status=%s body=%s', response.status_code,
                      sanitized_body(response, (code, self.client_secret)))
            raise AuthError(f'OAuth failed status={response.status_code}')
        try:
            token = response.json()['access_token']
            if not isinstance(token, str) or not token:
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            LOG.error('auth failure status=200 body="invalid token response"')
            raise AuthError('invalid OAuth response') from None
        local = now.astimezone(ZoneInfo('Asia/Kolkata'))
        expiry = local.replace(hour=3, minute=30, second=0, microsecond=0)
        if expiry <= local:
            expiry += timedelta(days=1)
        target.write(token, expiry)
