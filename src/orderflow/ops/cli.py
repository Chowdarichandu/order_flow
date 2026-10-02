"""Owner-only operations entry point; network adapters constructed only in main."""
import argparse
import asyncio
from datetime import date, datetime, timedelta, timezone
import hmac
import json
from pathlib import Path
import secrets
import signal
import time
from typing import Any
from zoneinfo import ZoneInfo

import yaml
from orderflow.auth.core import Api, OAuth, TokenFile, AuthError, secure_json, atomic_file
from orderflow.ops.runtime import Calendar, alert, write_status, job_allowed
from orderflow.ops.preflight import preflight
from orderflow.ingest.recorder import FeedClient, FeedLock, Recorder
from orderflow.ingest.history import HistoryDownloader, import_recordings
from orderflow.decode.feed import Decoder


def instrument_map(path:Path) -> dict[str,str]:
    """Read instrument keys/symbols for stocks, indices and VIX without a feed call."""
    data=json.loads(Path(path).read_text())
    if not isinstance(data,dict) or not data or not all(isinstance(k,str) and isinstance(v,str) for k,v in data.items()):
        raise ValueError('instrument file must be a nonempty key-to-symbol object')
    return data


def load_config(path:Path) -> dict[str,Any]:
    """Read explicit owner paths and operational parameters, never token environment variables."""
    config=yaml.safe_load(Path(path).read_text())
    for name in ('data_root','token_file','credentials_file','code_file','state_file',
                 'webhook_file','calendar_file','instruments_file','status_file'):
        config[name]=Path(config[name]).expanduser()
    return config


def run_job(args:argparse.Namespace, config:dict[str,Any], http:Any) -> int:
    """Dispatch holiday-aware jobs; live adapters are injected and never imported by tests."""
    now=datetime.now(timezone.utc)
    calendar=Calendar(config['calendar_file'])
    state=lambda label,details:write_status(config['status_file'],state=label,details=details)
    if (args.scheduled or args.job=='record') and not job_allowed(calendar,now):
        state('HOLIDAY',{'job':args.job,'recording':False})
        return 0
    store=TokenFile(config['token_file'])
    if args.job in ('oauth-url','refresh'):
        credentials=secure_json(config['credentials_file'])
        oauth=OAuth(http,client_id=credentials['client_id'],client_secret=credentials['client_secret'],
                    redirect_uri=credentials['redirect_uri'])
        if args.job=='oauth-url':
            nonce=secrets.token_urlsafe(32)
            atomic_file(config['state_file'],json.dumps(dict(state=nonce,
                        expires_at=(now+timedelta(minutes=10)).isoformat())).encode())
            print(oauth.login_url(nonce))
            return 0
        # Daily job can reuse a still-valid file, but never a previous OAuth code.
        try:
            store.read(now)
            state('TOKEN_VALID',{})
            return 0
        except AuthError:
            pass
        try:
            code=secure_json(config['code_file'])
            pending=secure_json(config['state_file'])
            if not hmac.compare_digest(code['state'],pending['state']):
                raise AuthError('OAuth state mismatch')
            if datetime.fromisoformat(pending['expires_at'])<=now:
                raise AuthError('OAuth state expired')
            oauth.exchange(code['code'],store,now=now)
            config['code_file'].unlink(missing_ok=True)
            config['state_file'].unlink(missing_ok=True)
            state('TOKEN_REFRESHED',{})
            return 0
        except (AuthError,KeyError,TypeError,ValueError):
            state('WAITING_LOGIN',{'action':'Fresh owner-approved OAuth code required'})
            alert(http,config['webhook_file'],'orderflow: daily OAuth login is required before recording')
            return 1
    instruments=instrument_map(config['instruments_file']) if args.job in ('record','history','import','replay') else {}
    if args.job=='import':
        stats=import_recordings(Path(args.source),config['data_root'],Decoder(instruments))
        state('IMPORTED',stats);print(json.dumps(stats));return 0
    if args.job=='replay':
        stats=import_recordings(config['data_root']/'raw',config['data_root']/'replay',Decoder(instruments))
        state('REPLAY_DECODED',stats);print(json.dumps(stats));return 0
    api=Api(http,store)
    if args.job=='preflight':
        retry=config['preflight_retry_seconds']
        local=now.astimezone(ZoneInfo('Asia/Kolkata'))
        deadline=local.replace(hour=9,minute=10,second=0,microsecond=0)
        while True:
            report=preflight(api,attempts=1,soft_checks={'calendar':lambda:calendar.alert})
            state('READY' if report.ready else 'HARD_GATE',dict(
                  hard_errors=report.hard_errors,soft_alerts=report.soft_alerts))
            if report.ready or not args.scheduled or datetime.now(timezone.utc)>=deadline:
                if not report.ready:
                    alert(http,config['webhook_file'],'orderflow: preflight hard gate; check token and authorization')
                return 0 if report.ready else 1
            time.sleep(min(retry,max(0,(deadline-datetime.now(timezone.utc)).total_seconds())))
    if args.job=='history':
        downloader=HistoryDownloader(api,config['data_root'],throttle_seconds=config['history_throttle_seconds'])
        end=date.fromisoformat(args.end) if args.end else now.astimezone(ZoneInfo('Asia/Kolkata')).date()
        start=date.fromisoformat(args.start) if args.start else end
        results={symbol:downloader.range(symbol,key,start,end,is_trading_day=calendar.trading_day)
                 for key,symbol in instruments.items()}
        state('HISTORY_FINISHED',results);return 0 if all(not v.get('ERROR') for v in results.values()) else 1
    if args.job=='record':
        # Only the specified hard gates prevent connecting. Calendar absence is soft.
        report=preflight(api,attempts=1,soft_checks={'calendar':lambda:calendar.alert})
        if not report.ready:
            state('HARD_GATE',{'hard_errors':report.hard_errors,'soft_alerts':report.soft_alerts})
            return 1
        import websockets
        async def connect(url):
            return await websockets.connect(url,additional_headers={'User-Agent':'orderflow-zero/0.1.0'},
                     ping_interval=config['heartbeat_seconds'],ping_timeout=config['heartbeat_seconds'],
                     close_timeout=10,max_size=16*1024*1024)
        decoder=Decoder(instruments,gap_seconds=config['gap_seconds'])
        recorder=Recorder(config['data_root'],capacity=config['queue_capacity'],
                          batch_size=config['batch_size'],flush_seconds=config['flush_seconds'],decoder=decoder,
                          on_flush=lambda metrics:state('RECORDING',metrics))
        client=FeedClient(api,connect,recorder,instruments=list(instruments),mode=config['feed_mode'],
                          retry_seconds=config['reconnect_seconds'])
        async def run():
            task=asyncio.current_task()
            loop=asyncio.get_running_loop()
            for sig in (signal.SIGTERM,signal.SIGINT):
                loop.add_signal_handler(sig,task.cancel)
            await client.run()
        try:
            with FeedLock(config['data_root']/'feed.lock'),recorder:
                state('RECORDING',{'instruments':len(instruments),'soft_alerts':report.soft_alerts})
                try:
                    asyncio.run(run())
                except asyncio.CancelledError:
                    pass
        finally:
            state('STOPPED',recorder.quality())
            atomic_file(config['data_root']/'quality'/f'{now.astimezone(ZoneInfo("Asia/Kolkata")).date()}.json',
                        json.dumps(recorder.quality(),indent=2).encode())
        return 0
    raise ValueError('unknown job')


def main() -> int:
    """Owner CLI: tests call injected run_job, never create requests/websockets sessions."""
    parser=argparse.ArgumentParser()
    parser.add_argument('job',choices=['oauth-url','refresh','preflight','record','history','import','replay'])
    parser.add_argument('--config',default=str(Path.home()/'.config/orderflow/config.yaml'))
    parser.add_argument('--scheduled',action='store_true')
    parser.add_argument('--source');parser.add_argument('--start');parser.add_argument('--end')
    args=parser.parse_args()
    if args.job=='import' and not args.source:
        parser.error('--source required for import')
    import requests
    try:
        with requests.Session() as http:
            return run_job(args,load_config(Path(args.config)),http)
    except (AuthError,ValueError,OSError):
        # Do not include URLs, codes, credentials or response text in uncaught errors.
        print('Operation failed; verify configuration, private files and status board.')
        return 1


if __name__=='__main__':
    raise SystemExit(main())
