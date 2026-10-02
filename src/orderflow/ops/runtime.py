"""Holiday-aware owner runtime, file-only alerts and atomic status board."""
from datetime import date, datetime, timezone
import json
import logging
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo
from orderflow.auth.core import atomic_file, secure_json, USER_AGENT, aware

LOG=logging.getLogger(__name__)


class Calendar:
    """Section 1 rule 7: skip weekends and owner-supplied official NSE holidays.

    Missing calendars are a SOFT alert, consistent with recording hard gates;
    weekdays are not guessed to be holidays. Owner must provision the complete
    official holiday list and update it annually before enabling schedules.
    """
    def __init__(self,path:Path):
        self.alert=None
        try:
            data=json.loads(Path(path).read_text())
            self.holidays={date.fromisoformat(day) for day in data['holidays']}
        except (OSError,KeyError,ValueError,TypeError):
            self.holidays=set()
            self.alert='NSE holiday calendar missing or invalid; owner update required'

    def trading_day(self, day:date) -> bool:
        """True only for weekdays not declared official exchange holidays."""
        return day.weekday()<5 and day not in self.holidays


def job_allowed(calendar:Calendar, now:datetime) -> bool:
    """Section 1 rules 7/8: scheduled jobs use the IST trading date, not UTC date."""
    return calendar.trading_day(aware(now).astimezone(ZoneInfo('Asia/Kolkata')).date())


def alert(http:Any, webhook_file:Path, message:str) -> bool:
    """Send a Discord alert using a 0600 file; never print the webhook URL."""
    try:
        url=secure_json(Path(webhook_file))['url']
        from urllib.parse import urlparse
        parsed=urlparse(url)
        if parsed.scheme!='https' or parsed.hostname not in ('discord.com','discordapp.com'):
            raise ValueError()
        response=http.request('POST',url,headers={'User-Agent':USER_AGENT},
                              json={'content':message[:1900]},timeout=10)
        if response.status_code not in (200,204):
            LOG.error('alert failure status=%s body="delivery failed"',response.status_code)
            return False
        return True
    except Exception:
        LOG.warning('alert unavailable; verify webhook file and connectivity')
        return False


def write_status(path:Path, *, state:str, details:dict[str,Any]) -> None:
    """Atomic read-only status board with UTC availability, including HOLIDAY state."""
    body=dict(state=state,details=details,available_at=datetime.now(timezone.utc).isoformat())
    atomic_file(Path(path),json.dumps(body,indent=2,default=str).encode(),mode=0o644)
