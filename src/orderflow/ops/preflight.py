"""Preflight hard/soft gates with injectable delays and no import-time network."""
from collections.abc import Callable
from dataclasses import dataclass, field
from time import sleep as real_sleep
from orderflow.auth.core import Api, AuthError


@dataclass(frozen=True)
class PreflightReport:
    """Read-only readiness report; soft alerts never prevent recording."""
    ready: bool
    hard_errors: list[str] = field(default_factory=list)
    soft_alerts: list[str] = field(default_factory=list)


def preflight(api: Api, *, attempts: int = 3, retry_seconds: float = 30,
              sleep: Callable[[float], None] = real_sleep,
              soft_checks: dict[str, Callable[[], str | None]] | None = None) -> PreflightReport:
    """Section 1 rule 5: only token/authorize failures are hard gates.

    The 08:30–09:10 retry window is controlled by the scheduled ops entry point;
    this bounded primitive never sleeps past a caller-supplied attempt limit.
    """
    if attempts < 1 or retry_seconds < 0:
        raise ValueError('invalid preflight retry policy')
    alerts = []
    for name, check in (soft_checks or {}).items():
        try:
            message = check()
        except Exception:
            message = 'check failed'
        if message:
            alerts.append(f'{name}: {message}')
    try:
        api.token_file.read(api.now())
    except AuthError as error:
        return PreflightReport(False, [str(error)], alerts)
    for attempt in range(attempts):
        try:
            api.authorize()
            return PreflightReport(True, [], alerts)
        except AuthError as error:
            last_error = str(error)
            if attempt + 1 < attempts:
                sleep(retry_seconds)
    return PreflightReport(False, [last_error], alerts)
