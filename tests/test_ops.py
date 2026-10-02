"""T18 holiday schedules, file-only alerts/status and clean-home install dry run."""
from datetime import date, datetime, timezone
import json
from pathlib import Path
import subprocess

import pytest
from orderflow.ops.runtime import Calendar, alert, write_status, job_allowed
from orderflow.auth.core import atomic_file

ROOT=Path(__file__).resolve().parents[1]


def test_weekends_holidays_and_ist_day(tmp_path):
    path=tmp_path/'calendar.json'
    path.write_text(json.dumps({'holidays':['2026-10-02']}))
    calendar=Calendar(path)
    assert not calendar.trading_day(date(2026,10,2))
    assert not calendar.trading_day(date(2026,10,3))
    assert calendar.trading_day(date(2026,10,1))
    assert not job_allowed(calendar,datetime(2026,10,1,23,tzinfo=timezone.utc)) # Oct 2 IST.


def test_missing_calendar_is_soft_and_weekends_still_skipped(tmp_path):
    calendar=Calendar(tmp_path/'absent')
    assert calendar.alert
    assert not calendar.trading_day(date(2026,10,3))
    assert calendar.trading_day(date(2026,10,1))


def test_discord_webhook_from_file_and_explicit_user_agent(tmp_path):
    secret=tmp_path/'webhook.json'
    atomic_file(secret,json.dumps({'url':'https://discord.com/api/webhooks/synthetic'}).encode())
    class HTTP:
        calls=[]
        def request(self,*args,**kwargs):
            self.calls.append((args,kwargs))
            return type('Reply',(),{'status_code':204})()
    http=HTTP()
    assert alert(http,secret,'Recording healthy')
    assert http.calls[0][1]['headers']['User-Agent']
    assert http.calls[0][1]['json']['content']=='Recording healthy'


def test_status_atomic_and_holiday_has_no_failed_day(tmp_path):
    path=tmp_path/'status.json'
    write_status(path,state='HOLIDAY',details={'recording':False})
    data=json.loads(path.read_text())
    assert data['state']=='HOLIDAY' and 'failure' not in data
    assert datetime.fromisoformat(data['available_at']).tzinfo is not None
    assert not list(tmp_path.glob('*.tmp'))


def test_install_script_dry_run_on_empty_home(tmp_path):
    result=subprocess.run(['bash',str(ROOT/'scripts/install.sh'),'--dry-run','--home',str(tmp_path)],
                          capture_output=True,text=True)
    assert result.returncode == 0, result.stderr
    assert 'orderflow-recorder.service' in result.stdout
    assert '03:45' in result.stdout and 'Asia/Kolkata' in result.stdout
    assert list(tmp_path.iterdir()) == []


def test_all_scheduled_jobs_use_holiday_aware_entrypoint():
    for path in (ROOT/'ops/systemd').glob('*.service'):
        text=path.read_text()
        if path.name != 'orderflow-stop.service':
            assert 'orderflow.ops.cli' in text and '--scheduled' in text
    assert len(list((ROOT/'ops/systemd').glob('*.timer'))) >= 5


def test_scheduler_defines_recorder_stop_and_rescue():
    units=ROOT/'ops/systemd'
    assert '15:35' in (units/'orderflow-stop.timer').read_text()
    assert '08:00' in (units/'orderflow-rescue.timer').read_text()
    assert '08:30' in (units/'orderflow-preflight.timer').read_text()


def test_rendered_systemd_units_verify(tmp_path):
    import shutil, sys
    if not shutil.which('systemd-analyze'):
        pytest.skip('systemd-analyze unavailable on this non-Linux runner')
    (tmp_path/'.venv/bin').mkdir(parents=True)
    (tmp_path/'.venv/bin/python').symlink_to(sys.executable)
    units=tmp_path/'units';units.mkdir()
    for source in (ROOT/'ops/systemd').iterdir():
        (units/source.name).write_text(source.read_text().replace('@ROOT@',str(tmp_path)))
    result=subprocess.run(['systemd-analyze','verify',*map(str,units.iterdir())],capture_output=True,text=True)
    assert result.returncode == 0, result.stderr
