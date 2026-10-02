"""BOOTSTRAP 4.7: causal zones are location context, never layer votes."""
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from typing import Any

import pyarrow as pa
from orderflow.auth.core import aware
from orderflow.schema import BAR_SCHEMA,FEATURE_SCHEMA,LEVEL_SCHEMA,PROFILE_SCHEMA,ZONE_SCHEMA


@dataclass(frozen=True)
class ZonePolicy:
    """Explicit choices where section 4.7 gives no linkage/lifecycle algorithm.

    single_linkage connects neighboring intervals transitively; complete_linkage
    requires each pair in a cluster to be within tolerance. Touches count entry
    episodes or every intersecting closed bar. Invalidation is strict closing
    beyond the serving edge, or entirely delegated to the originating layers.
    No expiry is inferred unless max_age_minutes is explicitly supplied.
    """
    linkage: str
    touch_policy: str
    invalidation_policy: str
    side_policy: str
    freshness_policy: str
    max_age_minutes: float | None = None

    def __post_init__(self) -> None:
        """Reject implicit or unsupported definitions rather than invent defaults."""
        options={
            'linkage':{'single_linkage','complete_linkage'},
            'touch_policy':{'entry_episode','every_intersecting_bar'},
            'invalidation_policy':{'close_beyond_edge','source_only'},
            'side_policy':{'source_side_else_creation_close'},
            'freshness_policy':{'cluster_formation','oldest_component'},
        }
        for name,allowed in options.items():
            if getattr(self,name) not in allowed:
                raise ValueError(f'explicit valid {name} required')
        if self.max_age_minutes is not None and self.max_age_minutes<0:
            raise ValueError('nonnegative explicit maximum age required')


def _distance(left: dict[str,Any],right: dict[str,Any]) -> Decimal:
    """Minimum price distance between closed intervals; overlapping is zero."""
    return max(Decimal(0),left['low']-right['high'],right['low']-left['high'])


def cluster_intervals(components: list[dict[str,Any]], *, tolerance: Decimal,
                      linkage: str) -> list[list[dict[str,Any]]]:
    """Cluster section 4.7 intervals at inclusive distance <=0.25*ATR by default.

    Caller explicitly chooses linkage; output and identities are deterministic
    under input permutation. Intervals retain all component fields unchanged.
    Components supplied together must belong to the same instrument/session.
    """
    if linkage not in {'single_linkage','complete_linkage'}:
        raise ValueError('explicit valid linkage required')
    if not tolerance.is_finite() or tolerance<0:
        raise ValueError('finite nonnegative tolerance required')
    if any(row['low']>row['high'] for row in components):
        raise ValueError('component low must not exceed high')
    groups: list[list[dict[str,Any]]]=[]
    for component in sorted(components,key=lambda r:(r['low'],r['high'],r['record_id'])):
        if not groups:
            groups.append([component]);continue
        nearby=groups[-1]
        distances=[_distance(component,member) for member in nearby]
        close=(min(distances)<=tolerance if linkage=='single_linkage'
               else max(distances)<=tolerance)
        if close:nearby.append(component)
        else:groups.append([component])
    return groups


def _reference(row: dict[str,Any],record_id: str) -> dict[str,Any]:
    """Attach the direct source's actual availability, not its origin time."""
    return dict(record_id=record_id,available_at=row['available_at'])


def _causal_inputs(row: dict[str,Any]) -> list[dict[str,Any]]:
    """Reject contradictory source provenance stamped after source availability."""
    if any(r['available_at']>row['available_at'] for r in row['inputs']):
        raise ValueError('source has a future input timestamp')
    return list(row['inputs'])


def _latest_levels(rows: list[dict[str,Any]],cutoff: datetime) -> list[dict[str,Any]]:
    """Choose one last available revision per identity; future state never leaks."""
    latest: dict[tuple,dict[str,Any]]={}
    for row in rows:
        if row['available_at']>cutoff or row['created_at']>cutoff:
            continue
        key=(row['instrument_key'],row['session_date'],row['record_id'])
        before=latest.get(key)
        if before is None or row['available_at']>before['available_at']:
            latest[key]=row
        elif row['available_at']==before['available_at']:
            fields=('type','low','high','side','created_at','invalidated_at','state')
            if any(row[name]!=before[name] for name in fields):
                raise ValueError(f"contradictory source identity {row['record_id']}")
    active=[]
    for row in latest.values():
        invalidated=row['invalidated_at']
        if invalidated is not None and invalidated<=cutoff:continue
        if row['state'] in {'EXPIRED','FILLED','FULLY_FILLED','TOUCHED','INCOMPLETE'}:continue
        if row['type'].startswith('OR') and row['type'].endswith('_INCOMPLETE'):continue
        if row['state']=='INVALIDATED' and invalidated is None:continue
        _causal_inputs(row)
        active.append(row)
    return active


def _source_side(components: list[dict[str,Any]],bars: list[dict[str,Any]],
                 formed: datetime) -> str:
    """Respect unanimous explicit source sides; otherwise creation-close location.

    Mixed components never vote. Price at or above the interval midpoint serves
    support; below serves resistance. Without a creation-time close, the caller
    must supply explicit source sides rather than use a future price.
    """
    mapping={'BUY':'SUPPORT','LONG':'SUPPORT','SUPPORT':'SUPPORT',
             'SELL':'RESISTANCE','SHORT':'RESISTANCE','RESISTANCE':'RESISTANCE'}
    sides={mapping[row['side']] for row in components if row['side'] in mapping}
    all_explicit=all(row['side'] in mapping for row in components)
    if len(sides)==1 and all_explicit:return next(iter(sides))
    prior=[bar for bar in bars if bar['bar_end']<=formed and bar['available_at']<=formed]
    if not prior:raise ValueError('explicit source side or available creation-time close required')
    price=max(prior,key=lambda b:(b['bar_end'],b['available_at']))['close']
    midpoint=(min(row['low'] for row in components)+max(row['high'] for row in components))/2
    return 'SUPPORT' if price>=midpoint else 'RESISTANCE'


def zone_snapshot(levels: pa.Table,bars: pa.Table,atr_features: pa.Table, *,
                  as_of: datetime,policy: ZonePolicy,
                  cluster_atr_multiple: Decimal = Decimal('0.25'),
                  atr_feature_name: str = 'ATR_14_5M') -> pa.Table:
    """Collect active components each minute and cluster within 0.25*ATR(14,5m).

    Every source must satisfy its canonical schema. ATR is a canonical feature
    with explicit availability. Distinct types, creation/freshness, closed-bar
    touches, serving side and invalidation are metadata, never strength votes.
    Source-invalidated/expired components disappear; price-invalidated zones
    remain with invalidated_at for audit and must be excluded by consumers.
    """
    cutoff=aware(as_of)
    if not (levels.schema.equals(LEVEL_SCHEMA) and bars.schema.equals(BAR_SCHEMA)
            and atr_features.schema.equals(FEATURE_SCHEMA)):
        raise ValueError('canonical level, bar and ATR feature schemas required')
    if not isinstance(policy,ZonePolicy):raise ValueError('explicit ZonePolicy required')
    if not cluster_atr_multiple.is_finite() or cluster_atr_multiple<0:
        raise ValueError('finite nonnegative clustering multiple required')
    groups: dict[tuple,list[dict[str,Any]]]=defaultdict(list)
    for row in _latest_levels(levels.to_pylist(),cutoff):
        groups[(row['instrument_key'],row['session_date'])].append(row)
    closed: dict[tuple,list[dict[str,Any]]]=defaultdict(list)
    for bar in bars.to_pylist():
        if bar['available_at']<=cutoff and bar['bar_end']<=cutoff:
            _causal_inputs(bar)
            closed[(bar['instrument_key'],bar['session_date'])].append(bar)
    atrs: dict[tuple,dict[str,Any]]={}
    for feature in atr_features.to_pylist():
        if (feature['name']==atr_feature_name and feature['available_at']<=cutoff
                and feature['minute']<=cutoff and feature['value'] is not None):
            key=(feature['instrument_key'],feature['session_date'])
            if key not in atrs or feature['available_at']>atrs[key]['available_at']:
                _causal_inputs(feature);atrs[key]=feature
    output=[]
    for key,components in sorted(groups.items()):
        feature=atrs.get(key)
        if feature is None or feature['value']<0:
            raise ValueError(f'available ATR required for {key[0]}')
        tolerance=Decimal(str(feature['value']))*cluster_atr_multiple
        history=sorted(closed[key],key=lambda b:(b['bar_end'],b['available_at']))
        # A logical bar received twice contributes once, rather than extra touches.
        unique_bars={}
        for bar in history:unique_bars[(bar['bar_start'],bar['bar_end'],bar['timeframe_minutes'])]=bar
        history=list(unique_bars.values())
        side_history=sorted([bar for (instrument,_),records in closed.items()
                             if instrument==key[0] for bar in records],
                            key=lambda b:(b['bar_end'],b['available_at']))
        for group in cluster_intervals(components,tolerance=tolerance,linkage=policy.linkage):
            formed=max(max(row['created_at'],row['available_at']) for row in group)
            created=(formed if policy.freshness_policy=='cluster_formation'
                     else min(row['created_at'] for row in group))
            freshness=(cutoff-created).total_seconds()/60
            if policy.max_age_minutes is not None and freshness>policy.max_age_minutes:
                continue
            side=_source_side(group,side_history,formed)
            low=min(r['low'] for r in group);high=max(r['high'] for r in group)
            invalidation=low if side=='SUPPORT' else high
            touched=False;touches=0;invalidated=None
            contributing=[]
            for bar in history:
                if bar['bar_start']<formed:continue
                contributing.append(bar)
                hit=bar['low']<=high and bar['high']>=low
                if hit and (policy.touch_policy=='every_intersecting_bar' or not touched):
                    touches+=1
                touched=hit
                broken=(bar['close']<low if side=='SUPPORT' else bar['close']>high)
                if policy.invalidation_policy=='close_beyond_edge' and broken:
                    invalidated=bar['available_at'];break
            # Creation-time close is a causal input if the side was price-derived.
            mapping={'BUY','LONG','SUPPORT','SELL','SHORT','RESISTANCE'}
            if not all(r['side'] in mapping for r in group) or len({r['side'] for r in group})>1:
                prior=[b for b in side_history if b['bar_end']<=formed and b['available_at']<=formed]
                if prior:contributing.append(max(prior,key=lambda b:(b['bar_end'],b['available_at'])))
            references=[]
            flags=set(feature['flags'])
            for row in group:
                flags.update(row['flags']);references.extend(_causal_inputs(row))
                references.append(_reference(row,row['record_id']))
            references.extend(_causal_inputs(feature))
            references.append(_reference(feature,f"{key[0]}:{feature['name']}:{feature['minute'].isoformat()}"))
            for bar in contributing:
                flags.update(bar['flags']);references.extend(_causal_inputs(bar))
                references.append(_reference(bar,f"{key[0]}:bar:{bar['bar_start'].isoformat()}:{bar['timeframe_minutes']}"))
            if not history:flags.add('NO_CLOSED_BARS')
            unique_refs={(r['record_id'],r['available_at']):r for r in references}
            identity='|'.join(f"{r['record_id']}:{r['low']}:{r['high']}" for r in sorted(group,key=lambda r:r['record_id']))
            identifier=sha256(f'{key[0]}:{key[1]}:{identity}'.encode()).hexdigest()[:24]
            methods={r['method'] for r in group}|{feature['method']}
            method='APPROXIMATE' if 'APPROXIMATE' in methods else 'ESTIMATE'
            first=group[0]
            output.append(dict(symbol=first['symbol'],instrument_key=key[0],session_date=key[1],
                zone_id=identifier,minute=cutoff,low=low,high=high,
                components=[{name:r[name] for name in
                            ('record_id','type','low','high','created_at','available_at')}
                            for r in sorted(group,key=lambda r:r['record_id'])],
                distinct_types=len({r['type'] for r in group}),created_at=created,
                freshness_minutes=freshness,touches=touches,side=side,
                invalidation_price=invalidation,invalidated_at=invalidated,
                source=first['source'],method=method,confidence='LOW',flags=sorted(flags),
                available_at=cutoff,inputs=list(unique_refs.values())))
    return pa.Table.from_pylist(output,schema=ZONE_SCHEMA)


def collect_zone_levels(levels: pa.Table,profiles: pa.Table,features: pa.Table, *,
                        as_of: datetime,
                        feature_types: dict[str,str] | None = None) -> pa.Table:
    """Convert available profile/VWAP snapshots to canonical section 4.7 levels.

    Latest versions are chosen before examining nullable values: a null latest
    value cannot resurrect a stale level. POC/VAH/VAL/HVN are profile components;
    a NAKED profile's POC is NAKED_POC. VWAP and anchor/band feature names are
    recognized from the canonical T10 producer, or explicitly mapped by caller.
    Sigma is a distance, not a price interval, and never becomes a component.
    Source sides are neutral for derived point levels; the zone policy must use
    a creation-time close to locate support/resistance. Source incomplete opening
    range diagnostics are excluded. All conversions preserve source provenance.
    """
    cutoff=aware(as_of)
    if not (levels.schema.equals(LEVEL_SCHEMA) and profiles.schema.equals(PROFILE_SCHEMA)
            and features.schema.equals(FEATURE_SCHEMA)):
        raise ValueError('canonical level, profile and feature schemas required')
    output=_latest_levels(levels.to_pylist(),cutoff)

    def append(row: dict[str,Any],record: str,kind: str,price: Decimal) -> None:
        _causal_inputs(row)
        # Creation is when this developing snapshot actually becomes available.
        created=max(row['minute'],row['available_at'])
        output.append(dict(symbol=row['symbol'],instrument_key=row['instrument_key'],
            session_date=row['session_date'],record_id=record,type=kind,timeframe_minutes=None,
            low=price,high=price,side='NEUTRAL',origin_at=row['minute'],created_at=created,
            invalidated_at=None,mitigated_at=None,state='ACTIVE',source=row['source'],
            method=row['method'],confidence=row['confidence'],flags=list(row['flags']),
            available_at=row['available_at'],
            inputs=_causal_inputs(row)+[_reference(row,record+':'+row['minute'].isoformat())]))

    latest_profiles={}
    for row in profiles.to_pylist():
        if row['available_at']>cutoff or row['minute']>cutoff:continue
        key=(row['instrument_key'],row['session_date'],row['profile_kind'],row['sessions'])
        if key not in latest_profiles or row['available_at']>latest_profiles[key]['available_at']:
            latest_profiles[key]=row
    for key,row in sorted(latest_profiles.items()):
        scope=f"profile:{key[0]}:{key[1]}:{key[2]}:{key[3]}"
        for field in ('poc','vah','val'):
            if row[field] is None:continue
            kind='NAKED_POC' if field=='poc' and 'NAKED' in row['profile_kind'].upper() else field.upper()
            append(row,f'{scope}:{field}',kind,row[field])
        for index,price in enumerate(row['hvn']):
            append(row,f'{scope}:hvn:{index}','HVN',price)

    latest_features={}
    for row in features.to_pylist():
        if row['available_at']>cutoff or row['minute']>cutoff:continue
        key=(row['instrument_key'],row['session_date'],row['name'],row['level'])
        if key not in latest_features or row['available_at']>latest_features[key]['available_at']:
            latest_features[key]=row
    for key,row in sorted(latest_features.items(),key=lambda item:repr(item[0])):
        name=row['name']
        if name.endswith('_SIGMA') or row['value'] is None:continue
        if feature_types is not None:
            kind=feature_types.get(name)
        elif name.endswith('_VWAP'):
            kind='ANCHORED_VWAP' if name.startswith('ANCHOR_') else 'VWAP'
        elif '_BAND_UP_' in name or '_BAND_DOWN_' in name:
            kind='VWAP_BAND'
        else:kind=None
        if kind is None:continue
        price=Decimal(str(row['value']))
        if not price.is_finite():raise ValueError('finite feature price required')
        append(row,f'feature:{key[0]}:{key[1]}:{name}:{row["level"]}',kind,price)
    return pa.Table.from_pylist(output,schema=LEVEL_SCHEMA)
