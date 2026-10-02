"""Public, token-free Upstox research cache. All results are EXPLORATORY.

Current index constituents produce survivorship bias. Candles are not certified adjusted
for corporate actions. No authentication, token, websocket or order endpoint is used.
"""
from __future__ import annotations
import argparse
import calendar
import csv
from datetime import date, datetime, time as dt_time, timedelta, timezone
import gzip
import hashlib
import io
import json
from pathlib import Path
import time
from urllib.parse import quote
from zoneinfo import ZoneInfo
import pyarrow as pa
import pyarrow.parquet as pq
import requests

UA = 'orderflow-zero-edge-scout/0.1 (public historical research; no trading)'
IST = ZoneInfo('Asia/Kolkata')
ASSETS = 'https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz'
N200 = 'https://www.niftyindices.com/IndexConstituent/ind_nifty200list.csv'
N50 = 'https://www.niftyindices.com/IndexConstituent/ind_nifty50list.csv'
SECTORS = {
 'Automobile and Auto Components': ('NIFTY_AUTO','Nifty Auto'),
 'Capital Goods': ('NIFTY_INFRA','Nifty Infra'),
 'Chemicals': ('NIFTY_CHEMICALS','Nifty Chemicals'),
 'Construction': ('NIFTY_INFRA','Nifty Infra'),
 'Construction Materials': ('NIFTY_INFRA','Nifty Infra'),
 'Consumer Durables': ('NIFTY_CONSUMPTION','Nifty Consumption'),
 'Consumer Services': ('NIFTY_CONSUMPTION','Nifty Consumption'),
 'Fast Moving Consumer Goods': ('NIFTY_FMCG','Nifty FMCG'),
 'Financial Services': ('NIFTY_FIN_SERVICE','Nifty Fin Service'),
 'Healthcare': ('NIFTY_HEALTHCARE','NIFTY HEALTHCARE'),
 'Information Technology': ('NIFTY_IT','Nifty IT'),
 'Metals & Mining': ('NIFTY_METAL','Nifty Metal'),
 'Oil Gas & Consumable Fuels': ('NIFTY_OIL_GAS','NIFTY OIL AND GAS'),
 'Power': ('NIFTY_ENERGY','Nifty Energy'),
 'Realty': ('NIFTY_REALTY','Nifty Realty'),
 'Services': ('NIFTY_SERVICES','Nifty Serv Sector'),
 'Telecommunication': ('NIFTY_INFRA','Nifty Infra'),
 'Textiles': ('NIFTY_CONSUMPTION','Nifty Consumption'),
}
SCHEMA=pa.schema([('symbol',pa.string()),('instrument_key',pa.string()),('ts',pa.timestamp('us',tz='UTC')),('source_ts',pa.timestamp('us',tz='UTC')),('session_date',pa.date32()),('open',pa.float64()),('high',pa.float64()),('low',pa.float64()),('close',pa.float64()),('volume',pa.float64()),('source_sha256',pa.string()),('available_at',pa.timestamp('us',tz='UTC')),('quality_flags',pa.list_(pa.string()))])

class _Unauthenticated(requests.auth.AuthBase):
    """Prevent requests from consulting netrc or attaching an Authorization header."""
    def __call__(self,request):
        request.headers.pop('Authorization',None)
        return request


class PublicSession(requests.Session):
    """Keep environment proxy support while explicitly disabling implicit credentials."""
    def __init__(self):
        super().__init__()
        self.auth=_Unauthenticated()
    def rebuild_auth(self,prepared_request,response):
        prepared_request.headers.pop('Authorization',None)


class PublicCache:
    """Hash-verified immutable response cache with explicit UA, <=5 requests/s, two attempts."""
    def __init__(self,path:Path,*,session=None,rate:float=5):
        if not 0<rate<=5: raise ValueError('rate must be in (0,5]')
        self.path=Path(path); self.path.mkdir(parents=True,exist_ok=True)
        self.session=session or PublicSession();self.interval=1/rate;self.last=0.
        self.manifest_path=self.path/'manifest.json'
        self.manifest=json.loads(self.manifest_path.read_text()) if self.manifest_path.exists() else {}
    def get(self,url:str)->bytes:
        key=hashlib.sha256(url.encode()).hexdigest();entry=self.manifest.get(key)
        if entry:
            path=self.path/entry['path']
            if path.exists():
                data=path.read_bytes()
                if hashlib.sha256(data).hexdigest()==entry['sha256']: return data
        for attempt in range(2):
            time.sleep(max(0.,self.last+self.interval-time.monotonic()));self.last=time.monotonic()
            try:
                response=self.session.get(url,headers={'User-Agent':UA,'Accept':'application/json,text/csv,*/*'},timeout=60)
                if response.status_code!=200: raise RuntimeError(f'HTTP {response.status_code}: {response.content[:400].decode(errors="replace")}')
                data=response.content;path=self.path/'raw'/f'{key}.bin';path.parent.mkdir(exist_ok=True)
                tmp=path.with_suffix('.tmp');tmp.write_bytes(data);tmp.replace(path)
                self.manifest[key]={'url':url,'path':str(path.relative_to(self.path)),'sha256':hashlib.sha256(data).hexdigest(),'fetched_at':datetime.now(timezone.utc).isoformat(),'status':200}
                tmp=self.manifest_path.with_suffix('.tmp');tmp.write_text(json.dumps(self.manifest,indent=2));tmp.replace(self.manifest_path)
                return data
            except (requests.RequestException,RuntimeError):
                if attempt: raise
                time.sleep(1.)
        raise AssertionError('unreachable')

def period_windows(start:date,end:date,*,months:int)->list[tuple[date,date]]:
    """Inclusive adjacent windows of a fixed number of calendar months; no dropped date."""
    if months<=0: raise ValueError('months must be positive')
    result=[];current=start
    while current<=end:
        absolute=current.year*12+current.month-1+months
        nxt=date(absolute//12,absolute%12+1,min(current.day,calendar.monthrange(absolute//12,absolute%12+1)[1]))
        last=min(end,nxt-timedelta(days=1));result.append((current,last));current=last+timedelta(days=1)
    return result

def map_universe(rows:list[dict],instruments:list[dict])->tuple[list[dict],list[dict]]:
    """Map current constituent ISINs to NSE_EQ; explicitly return unmapped constituents."""
    lookup={x.get('isin'):x for x in instruments if x.get('segment')=='NSE_EQ' and x.get('instrument_type','EQ')=='EQ'}
    mapped=[];missing=[]
    for row in rows:
        isin=row['ISIN Code'];symbol=row['Symbol'];item=lookup.get(isin)
        if item is None: missing.append({'symbol':symbol,'isin':isin,'reason':'ISIN_NOT_IN_PUBLIC_NSE_EQ_FILE'});continue
        industry=row['Industry'];sector=SECTORS.get(industry)
        mapped.append({'symbol':symbol,'isin':isin,'industry':industry,'sector_index':sector[0] if sector else '', 'instrument_key':item['instrument_key']})
    return mapped,missing

def normalize_candles(candles:list,*,symbol:str,instrument_key:str,timeframe:str,source_sha256:str)->tuple[pa.Table,dict]:
    """UTC OHLCV with availability at regular close or capped hourly close; duplicates audited."""
    rows={};quality={'duplicates':0,'out_of_order':0,'invalid':0,'outside_regular_session':0,'conflicting_duplicates':0};prev=None
    for candle in candles:
        ts=datetime.fromisoformat(candle[0])
        if ts.tzinfo is None or ts.utcoffset() is None:raise ValueError('source timestamp requires timezone')
        local=ts.astimezone(IST);source_ts=ts.astimezone(timezone.utc)
        key=(datetime.combine(local.date(),dt_time(0),IST).astimezone(timezone.utc) if timeframe=='daily' else source_ts)
        if prev is not None and key>prev: quality['out_of_order']+=1
        prev=key
        o,h,l,c,v=map(float,candle[1:6])
        if key in rows:
            quality['duplicates']+=1
            if [rows[key][field] for field in ('open','high','low','close','volume')]!=[o,h,l,c,v]:
                quality['conflicting_duplicates']+=1
                rows[key]['quality_flags'].append('CONFLICTING_DUPLICATE_CANDLE')
            continue
        if min(o,h,l,c)<=0 or h<max(o,c,l) or l>min(o,c,h) or v<0: quality['invalid']+=1;continue
        close=datetime.combine(local.date(),dt_time(15,30),IST)
        regular=dt_time(9,15)<=local.timetz().replace(tzinfo=None)<dt_time(15,30)
        if timeframe=='hourly' and not regular: quality['outside_regular_session']+=1
        available=close if timeframe=='daily' else (min(local+timedelta(hours=1),close) if regular else local+timedelta(hours=1))
        rows[key]={'symbol':symbol,'instrument_key':instrument_key,'ts':key,'source_ts':source_ts,'session_date':local.date(),'open':o,'high':h,'low':l,'close':c,'volume':v,'source_sha256':source_sha256,'available_at':available.astimezone(timezone.utc),'quality_flags':['OUTSIDE_REGULAR_SESSION'] if timeframe=='hourly' and not regular else []}
    return pa.Table.from_pylist([rows[k] for k in sorted(rows)],schema=SCHEMA),quality

def load_cached(cache_dir:Path,timeframe:str)->pa.Table:
    """Load the consolidated, UTC-aware long candle table from the resumable cache."""
    return pq.read_table(Path(cache_dir)/f'candles_{timeframe}.parquet')

def download(cache_dir:Path=Path('data/edge_scout'),*,through:date=date(2026,10,1))->dict:
    """Download every current constituent and its index proxies; enumerate missing periods."""
    cache=PublicCache(cache_dir);assets=cache.get(ASSETS);instruments=json.loads(gzip.decompress(assets))
    n200=cache.get(N200);n50=cache.get(N50)
    current=list(csv.DictReader(io.StringIO(n200.decode('utf-8-sig'))));members50={r['ISIN Code'] for r in csv.DictReader(io.StringIO(n50.decode('utf-8-sig')))}
    universe,mapping_missing=map_universe(current,instruments)
    for row in universe: row['nifty50']=row['isin'] in members50
    with (cache_dir/'universe.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=['symbol','isin','industry','sector_index','instrument_key','nifty50']);writer.writeheader();writer.writerows(universe)
    index_lookup={x['name']:x for x in instruments if x.get('instrument_type')=='INDEX'}
    indices={'NIFTY_50':'Nifty 50',**{s:n for s,n in SECTORS.values()}}
    jobs=list(universe)
    missing=[{'symbol':x['symbol'],'timeframe':'mapping','start':'','end':'','reason':x['reason']} for x in mapping_missing]
    for symbol,name in indices.items():
        item=index_lookup.get(name)
        if item: jobs.append({'symbol':symbol,'instrument_key':item['instrument_key']})
        else: missing.append({'symbol':symbol,'timeframe':'mapping','start':'','end':'','reason':f'INDEX_NOT_FOUND:{name}'})
    quality=[];tables={'daily':[],'hourly':[]};coverage=[]
    for timeframe,unit,start,months in [('daily','days',date(1990,1,1),120),('hourly','hours',date(2022,1,1),3)]:
        for number,item in enumerate(jobs,1):
            symbol=item['symbol'];key=item['instrument_key']
            parts=[]
            for left,right in period_windows(start,through,months=months):
                url=f'https://api.upstox.com/v3/historical-candle/{quote(key,safe="")}/{unit}/1/{right}/{left}'
                try:
                    raw=cache.get(url);body=json.loads(raw)
                    if body.get('status')!='success': raise ValueError(f'API status {body.get("status")}')
                    candles=body.get('data',{}).get('candles',[])
                    table,q=normalize_candles(candles,symbol=symbol,instrument_key=key,timeframe=timeframe,source_sha256=hashlib.sha256(raw).hexdigest());parts.append(table)
                    quality.append({'symbol':symbol,'timeframe':timeframe,'start':str(left),'end':str(right),**q})
                    if not candles: missing.append({'symbol':symbol,'timeframe':timeframe,'start':str(left),'end':str(right),'reason':'EMPTY_RESPONSE_NOT_PROOF_OF_PRE_LISTING_OR_RETENTION'})
                except (requests.RequestException,RuntimeError,ValueError) as error:
                    missing.append({'symbol':symbol,'timeframe':timeframe,'start':str(left),'end':str(right),'reason':str(error)[:400]})
            combined=pa.concat_tables(parts) if parts else pa.Table.from_pylist([],schema=SCHEMA)
            tables[timeframe].append(combined)
            if combined.num_rows:
                days=combined.column('session_date').to_pylist();coverage.append({'symbol':symbol,'timeframe':timeframe,'rows':combined.num_rows,'first':str(min(days)),'last':str(max(days))})
            path=cache_dir/'normalized'/timeframe/f'{symbol}.parquet';path.parent.mkdir(parents=True,exist_ok=True);pq.write_table(combined,path)
            print(f'DOWNLOADED {timeframe} {number}/{len(jobs)} {symbol}',flush=True)
            (cache_dir/'progress.json').write_text(json.dumps({'timeframe':timeframe,'completed':number,'total':len(jobs),'coverage':coverage,'missing':missing},indent=2))
        pq.write_table(pa.concat_tables(tables[timeframe]),cache_dir/f'candles_{timeframe}.parquet')
        print(f'CONSOLIDATED {timeframe}',flush=True)
    summary={'as_of':str(through),'fetched_at':datetime.now(timezone.utc).isoformat(),'current_nifty200_count':len(current),'mapped_equities':len(universe),'index_count':len(jobs)-len(universe),'coverage':coverage,'quality':quality,'missing':missing,'limitations':['CURRENT_CONSTITUENTS_SURVIVORSHIP_BIAS','RAW_OHLCV_ADJUSTMENT_UNCERTIFIED','INDUSTRY_PROXY_MAPPING_NOT_HISTORICAL_SECTOR_MEMBERSHIP','PRE_FIRST_RECORD_LISTING_STATUS_UNKNOWN','DAILY_REQUESTS_START_1990_EARLIER_RETENTION_NOT_ASSERTED']}
    (cache_dir/'summary.json').write_text(json.dumps(summary,indent=2));return summary



def missing_observations(rows:list[dict],reference:list[datetime],*,timeframe:str,through:datetime|None=None)->list[dict]:
    """Enumerate observed-calendar gaps after the first record, optionally through requested end."""
    by_symbol={}
    for row in rows: by_symbol.setdefault(row['symbol'],set()).add(datetime.combine(row['session_date'],dt_time(0),IST).astimezone(timezone.utc) if timeframe=='daily' else row['ts'])
    gaps=[]
    for symbol,seen in by_symbol.items():
        first,available_last=min(seen),max(seen);last=through or available_last
        expected={datetime.combine(t.astimezone(IST).date(),dt_time(0),IST).astimezone(timezone.utc) for t in reference} if timeframe=='daily' else set(reference)
        for ts in sorted(expected-seen):
            if first<=ts<=last:
                when=str(ts.astimezone(IST).date()) if timeframe=='daily' else ts.astimezone(IST).isoformat()
                reason=('ABSENT_ON_OBSERVED_NIFTY_50_SESSION' if timeframe=='daily' else 'ABSENT_AT_OBSERVED_NIFTY_50_HOURLY_TIMESTAMP')
                if ts>available_last:reason='AFTER_LAST_AVAILABLE_UNKNOWN_ON_OBSERVED_NIFTY_50_SESSION' if timeframe=='daily' else 'AFTER_LAST_AVAILABLE_UNKNOWN_AT_OBSERVED_NIFTY_50_HOURLY_TIMESTAMP'
                gaps.append({'symbol':symbol,'timeframe':timeframe,'start':when,'end':when,'reason':reason})
    return gaps


def hourly_session_gaps(rows:list[dict],daily_sessions:list[date])->list[dict]:
    """Detect missing entire hourly sessions, including gaps in the hourly index itself."""
    by_symbol={}
    for row in rows:by_symbol.setdefault(row['symbol'],set()).add(row['session_date'])
    missing=[]
    for symbol,seen in by_symbol.items():
        first,last=min(seen),max(seen)
        for day in sorted(set(daily_sessions)-seen):
            if first<=day<=last:missing.append({'symbol':symbol,'timeframe':'hourly','start':str(day),'end':str(day),'reason':'ENTIRE_HOURLY_SESSION_ABSENT_ON_OBSERVED_NIFTY_50_DAILY_SESSION'})
    return missing


def coverage_boundaries(rows:list[dict],*,timeframe:str,requested_start:date,through:date)->list[dict]:
    """Expose unknown leading/trailing coverage without asserting listing or delisting dates."""
    by_symbol={}
    for row in rows:by_symbol.setdefault(row['symbol'],set()).add(row['session_date'])
    missing=[]
    for symbol,seen in sorted(by_symbol.items()):
        first,last=min(seen),max(seen)
        if first>requested_start:missing.append({'symbol':symbol,'timeframe':timeframe,'start':str(requested_start),'end':str(first-timedelta(days=1)),'reason':'BEFORE_FIRST_AVAILABLE_UNKNOWN'})
        if last<through:missing.append({'symbol':symbol,'timeframe':timeframe,'start':str(last+timedelta(days=1)),'end':str(through),'reason':'AFTER_LAST_AVAILABLE_UNKNOWN'})
    return missing


def audit_cache(cache_dir:Path=Path('data/edge_scout'),docs_dir:Path=Path('docs'))->dict:
    """Write full coverage and EVERY empty/error/gap period; no inferred prelisting gaps."""
    summary=json.loads((cache_dir/'summary.json').read_text());missing=list(summary['missing']);stats={}
    daily_sessions=[]
    for timeframe in ('daily','hourly'):
        table=load_cached(cache_dir,timeframe);rows=table.to_pylist()
        reference=[row['ts'] for row in rows if row['symbol']=='NIFTY_50']
        through=date.fromisoformat(summary['as_of'])
        requested_end=datetime.combine(through,dt_time(23,59,59),IST).astimezone(timezone.utc)
        gaps=missing_observations(rows,reference,timeframe=timeframe,through=requested_end);missing.extend(gaps)
        missing.extend(coverage_boundaries(rows,timeframe=timeframe,requested_start=date(1990,1,1) if timeframe=='daily' else date(2022,1,1),through=through))
        if timeframe=='hourly':missing.extend(hourly_session_gaps(rows,daily_sessions))
        for row in rows:
            if 'CONFLICTING_DUPLICATE_CANDLE' in row.get('quality_flags',[]):
                when=str(row['session_date']);missing.append({'symbol':row['symbol'],'timeframe':timeframe,'start':when,'end':when,'reason':'CONFLICTING_DUPLICATE_CANDLE_UNRESOLVED'})
        stats[timeframe]={'rows':table.num_rows,'symbols':len(set(table.column('symbol').to_pylist())),'intraperiod_gaps':len(gaps),'sha256':hashlib.sha256((cache_dir/f'candles_{timeframe}.parquet').read_bytes()).hexdigest()}
        if timeframe=='daily':
            observed=sorted({t.astimezone(IST).date() for t in reference});daily_sessions=observed
            holidays=[]
            if observed:
                actual=set(observed);day=observed[0]
                while day<=observed[-1]:
                    if day.weekday()<5 and day not in actual:holidays.append(str(day))
                    day+=timedelta(days=1)
            (cache_dir/'observed_calendar.json').write_text(json.dumps({'source':'OBSERVED_NIFTY_50_CANDLES_NOT_OFFICIAL_HOLIDAY_CALENDAR','sessions':[str(d) for d in observed],'missing_weekdays':holidays},indent=2))
    with (docs_dir/'EDGE_SCOUT_MISSING.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=['symbol','timeframe','start','end','reason']);writer.writeheader();writer.writerows(missing)
    (cache_dir/'audit.json').write_text(json.dumps({'stats':stats,'missing_count':len(missing)},indent=2))
    return {'stats':stats,'missing_count':len(missing)}




def renormalize_cached(cache_dir:Path,timeframe:str)->dict:
    """Rebuild normalized tables from SHA-verified raw bodies without issuing any HTTP call."""
    manifest=json.loads((cache_dir/'manifest.json').read_text());unit='days' if timeframe=='daily' else 'hours'
    quality=[];all_tables=[]
    for path in sorted((cache_dir/'normalized'/timeframe).glob('*.parquet')):
        existing=pq.read_table(path,columns=['instrument_key']);key=existing.column('instrument_key')[0].as_py() if existing.num_rows else None
        if key is None: continue
        prefix=f'https://api.upstox.com/v3/historical-candle/{quote(key,safe="")}/{unit}/1/'
        entries=[entry for entry in manifest.values() if entry['url'].startswith(prefix)]
        parts=[]
        for entry in entries:
            raw=(cache_dir/entry['path']).read_bytes()
            if hashlib.sha256(raw).hexdigest()!=entry['sha256']:raise ValueError(f'Corrupt cache for {entry["url"]}')
            table,q=normalize_candles(json.loads(raw)['data']['candles'],symbol=path.stem,instrument_key=key,timeframe=timeframe,source_sha256=entry['sha256'])
            parts.append(table);quality.append({'symbol':path.stem,'url':entry['url'],**q})
        table=pa.concat_tables(parts) if parts else pa.Table.from_pylist([],schema=SCHEMA)
        pq.write_table(table,path);all_tables.append(table)
    output=pa.concat_tables(all_tables) if all_tables else pa.Table.from_pylist([],schema=SCHEMA)
    target=cache_dir/f'candles_{timeframe}.parquet';tmp=target.with_suffix('.tmp');pq.write_table(output,tmp);tmp.replace(target)
    (cache_dir/f'quality_{timeframe}.json').write_text(json.dumps(quality,indent=2))
    return {'rows':output.num_rows,'symbols':len(all_tables),'quality':quality}

def align_daily_availability(daily:pa.Table,market_hourly:pa.Table)->tuple[pa.Table,int]:
    """Delay daily availability when an observed Nifty hourly session closes after 15:30."""
    closes={}
    for row in market_hourly.to_pylist():
        if row['symbol']=='NIFTY_50':closes[row['session_date']]=max(closes.get(row['session_date'],row['available_at']),row['available_at'])
    rows=daily.to_pylist();changed=0
    for row in rows:
        close=closes.get(row['session_date'])
        if close is not None and close>row['available_at']:
            row['available_at']=close
            if 'SPECIAL_SESSION_CLOSE_FROM_HOURLY_INDEX' not in row['quality_flags']:row['quality_flags'].append('SPECIAL_SESSION_CLOSE_FROM_HOURLY_INDEX')
            changed+=1
    return pa.Table.from_pylist(rows,schema=SCHEMA),changed


def align_cached_availability(cache_dir:Path)->int:
    """Write index-session availability refinement after both cached timeframes exist."""
    daily=load_cached(cache_dir,'daily');market=pq.read_table(cache_dir/'normalized'/'hourly'/'NIFTY_50.parquet')
    table,count=align_daily_availability(daily,market)
    target=cache_dir/'candles_daily.parquet';tmp=target.with_suffix('.tmp');pq.write_table(table,tmp);tmp.replace(target)
    (cache_dir/'availability_alignment.json').write_text(json.dumps({'changed_daily_rows':count,'source_index_hourly_sha256':hashlib.sha256((cache_dir/'normalized'/'hourly'/'NIFTY_50.parquet').read_bytes()).hexdigest(),'pre_2022_special_session_closes':'UNVERIFIED_REGULAR_CLOSE_ASSUMPTION_NEXT_SESSION_ENTRY_REQUIRED'},indent=2))
    return count


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--cache-dir',type=Path,default=Path('data/edge_scout'));parser.add_argument('--through',type=date.fromisoformat,default=date(2026,10,1));args=parser.parse_args();download(args.cache_dir,through=args.through);renormalize_cached(args.cache_dir,'daily');renormalize_cached(args.cache_dir,'hourly');align_cached_availability(args.cache_dir);audit_cache(args.cache_dir)
