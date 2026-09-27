import json
import math
from datetime import datetime, timedelta
from statistics import mean
from .db import dump, insert, now, rows
from .metrics import metrics, score
from .readiness import assess

HORIZONS = {'1W':7,'1M':30,'3M':90}
REGIMES = ['Neutral','Risk-off','Inflation']
ACTIVE_ROLES = {'Champion','Challenger','Benchmark','Exploration'}


def active_overrides(conn, at):
    records=rows(conn,'SELECT * FROM human_overrides WHERE created_at<=? ORDER BY id',(at,))
    revoked={r['revokes_id'] for r in records if r['revokes_id']}
    latest={}
    for r in records:
        if r['id'] not in revoked and not r['revokes_id'] and (not r['expires_at'] or r['expires_at']>at):
            latest[(r['factor_id'],r['asset_id'])]=r
    return list(latest.values())


def factor_values(conn, at, horizon, regime, is_demo=False):
    values={r['id']:0.0 for r in rows(conn,'SELECT id FROM factors')}
    evidence=[]
    for r in rows(conn,'''SELECT ef.*,c.novelty,c.modality FROM event_factor ef
                         JOIN claims c ON c.id=ef.claim_id JOIN raw_sources s ON s.id=c.source_id
                         WHERE ef.known_at<=? AND ef.horizon=? AND s.is_demo=?
                         AND ef.regime IN ('all',?) AND NOT EXISTS (SELECT 1 FROM event_factor newer
                         WHERE newer.event_id=ef.event_id AND newer.factor_id=ef.factor_id
                         AND newer.horizon=ef.horizon AND newer.regime=ef.regime AND newer.region=ef.region
                         AND newer.id>ef.id AND newer.known_at<=?)''',(at,horizon,int(is_demo),regime,at)):
        age=max(0,(datetime.fromisoformat(at)-datetime.fromisoformat(r['known_at'])).total_seconds()/86400)
        decay=math.exp(-age/HORIZONS[horizon])
        contribution=r['impact']*r['confidence']*r['novelty']*decay
        values[r['factor_id']]+=contribution
        evidence.append({'relation_id':r['id'],'factor_id':r['factor_id'],'value':contribution})
    return {k:math.tanh(v) for k,v in values.items()}, evidence


def latest_evaluations(conn, asset=None, horizon=None, regime=None, cohort='demo'):
    # Only one latest evaluation batch per slice, retaining every model in that batch.
    data=rows(conn,'''SELECT * FROM evaluations WHERE cohort=? AND (? IS NULL OR asset_id=?)
                     AND (? IS NULL OR horizon=?) AND (? IS NULL OR regime=?) ORDER BY id DESC''',
              (cohort,asset,asset,horizon,horizon,regime,regime))
    selected={}
    for r in data:
        key=(r['asset_id'],r['horizon'],r['regime'],r['model_id'])
        if key not in selected:
            r['metrics']=json.loads(r['metrics'])
            selected[key]=r
    return list(selected.values())


def evaluate(conn, at=None, cohort='demo'):
    at=at or now()
    data=rows(conn,'''SELECT p.*,o.value FROM predictions p JOIN runs r ON r.id=p.run_id
       JOIN outcomes o ON o.asset_id=p.asset_id AND o.issued_at=p.issued_at AND o.due_at=p.due_at
       WHERE p.due_at<=? AND o.observed_at<=? AND r.is_demo=? AND o.is_demo=? ORDER BY p.issued_at''',
       (at,at,int(cohort=='demo'),int(cohort=='demo')))
    grouped={}
    # Current model versions only; older versions remain in immutable ledger.
    models=rows(conn,'SELECT * FROM models')
    versions={m['id']:m['version'] for m in models}
    for p in data:
        if p['model_version']==versions[p['model_id']]:
            grouped.setdefault((p['asset_id'],p['horizon'],p['regime']),{}).setdefault(p['model_id'],[]).append(p)
    count=0
    for (asset,horizon,regime),by_model in grouped.items():
        available={mid:len(points) for mid,points in by_model.items()}
        common=set.intersection(*[{p['issued_at'] for p in points} for points in by_model.values()])
        by_model={mid:[p for p in points if p['issued_at'] in common] for mid,points in by_model.items()}
        bench={p['issued_at']:p for p in by_model.get('benchmark',[])}
        results=[]
        for model in models:
            mid=model['id']
            peers=[{p['issued_at']:p for p in group} for other,group in by_model.items() if other!=mid]
            m=metrics(by_model.get(mid,[]),bench,peers)
            m['available_n']=available.get(mid,0)
            m['sample_policy']='common issued_at across models with matured observations'
            results.append((model,m,score(m)))
        competitors=sorted([r for r in results if r[0]['role']!='Benchmark' and r[2] is not None], key=lambda r:r[2],reverse=True)
        ranked={r[0]['id']:i for i,r in enumerate(competitors)}
        for model,m,s in results:
            if model['role']=='Benchmark':
                role='Benchmark'
            elif model['id'] in ranked:
                role=['Champion','Challenger','Exploration'][ranked[model['id']]] if ranked[model['id']]<3 else 'Dormant'
            else:
                role=model['role']
            insert(conn,'evaluations',evaluated_at=at,asset_id=asset,horizon=horizon,regime=regime,
                   model_id=model['id'],model_version=model['version'],cohort=cohort,metrics=dump(m),
                   score=s,role=role,sample_count=m['n'])
            count+=1
    return {'evaluated_slices':len(grouped),'evaluations':count,'cohort':cohort,'as_of':at}


def probability(value, scale):
    return 1/(1+math.exp(-max(-20,min(20,value/scale))))


def run_agent(conn, mode='active', regime='Neutral', at=None, is_demo=False, create_portfolios=True):
    at=at or now()
    models=rows(conn,'SELECT * FROM models')
    assets=rows(conn,'SELECT * FROM assets')
    factors=rows(conn,'SELECT * FROM factors')
    overrides=active_overrides(conn,at)
    cohort='demo' if is_demo else 'live'
    assignments={(r['asset_id'],r['horizon'],r['model_id']):r['role']
                 for r in latest_evaluations(conn,regime=regime,cohort=cohort)}
    values={}
    evidence={}
    for h in HORIZONS:
        values[h],evidence[h]=factor_values(conn,at,h,regime,is_demo)
    readiness={} if is_demo else {f"{a['id']}:{h}:{m['id']}":assess(conn,a['id'],h,regime,m,at)
                                  for a in assets for h in HORIZONS for m in models}
    snapshot={'readiness':readiness,'factors':factors,'values':values,'evidence':evidence,'overrides':overrides,
              'models':models,'assignments':[{ 'asset':k[0],'horizon':k[1],'model':k[2],'role':v} for k,v in assignments.items()],
              'formula':'sum(tanh(decayed event impacts) * model weight * horizon scale)',
              'cohort':cohort,'target_units':{a['id']:a['target_unit'] for a in assets}}
    previous=conn.execute('SELECT * FROM runs WHERE regime=? AND is_demo=? ORDER BY id DESC LIMIT 1',(regime,int(is_demo))).fetchone()
    old_values=json.loads(previous['snapshot'])['values'] if previous else {}
    changes={'previous_run':previous['id'] if previous else None,'factor_changes':[], 'forecast_changes':[]}
    for h in HORIZONS:
        for f,v in values[h].items():
            old=old_values.get(h,{}).get(f)
            if old is None or abs(v-old)>1e-8:
                changes['factor_changes'].append({'factor':f,'horizon':h,'before':old,'after':v,'delta':v-(old or 0)})
    planned=[]
    for asset in assets:
        for h,days in HORIZONS.items():
            for model in models:
                role=assignments.get((asset['id'],h,model['id']),model['role'])
                if mode=='active' and role not in ACTIVE_ROLES:
                    continue
                weights=rows(conn,'''SELECT factor_id,weight,id FROM factor_asset WHERE model_id=? AND model_version=?
                              AND asset_id=? AND horizon=? AND regime=? AND known_at<=?''',
                             (model['id'],model['version'],asset['id'],h,regime,at))
                scale=(4.0 if asset['id']=='US10Y' else .006)*math.sqrt(days/7)
                contributions=[]
                for w in weights:
                    factor=next(f for f in factors if f['id']==w['factor_id'])
                    used=factor['state']=='core' or (factor['state']=='experimental' and model['family']=='experimental')
                    multiplier=1.0
                    matching=[o for o in overrides if o['factor_id']==w['factor_id'] and o['asset_id'] in (None,asset['id'])]
                    # A scoped override takes precedence over global override; never multiply twice.
                    if matching:
                        matching.sort(key=lambda o:(o['asset_id'] is not None,o['id']))
                        multiplier=matching[-1]['multiplier']
                    base=values[h][w['factor_id']]*w['weight']*scale if used else 0
                    if model['family']=='nonlinear':
                        base=math.tanh(base/scale)*scale
                    contributions.append({'factor_id':w['factor_id'],'weight_id':w['id'],'raw_weight':w['weight'],
                                          'factor_value':values[h][w['factor_id']],'enabled':used,'multiplier':multiplier,
                                          'original':base,'adjusted':base*multiplier,
                                          'override_ids':[o['id'] for o in matching]})
                original=sum(c['original'] for c in contributions)
                adjusted=sum(c['adjusted'] for c in contributions)
                pred=dict(model_id=model['id'],model_version=model['version'],asset_id=asset['id'],horizon=h,
                          regime=regime,issued_at=at,due_at=(datetime.fromisoformat(at)+timedelta(days=days)).isoformat(timespec='microseconds'),
                          original=original,adjusted=adjusted,probability_up=probability(original,scale),
                          adjusted_probability_up=probability(adjusted,scale),contributions=dump(contributions))
                if previous:
                    old=conn.execute('SELECT adjusted FROM predictions WHERE run_id=? AND model_id=? AND asset_id=? AND horizon=?',
                                     (previous['id'],model['id'],asset['id'],h)).fetchone()
                    if old and abs(adjusted-old[0])>1e-10:
                        changes['forecast_changes'].append({'model':model['id'],'asset':asset['id'],'horizon':h,
                                                           'before':old[0],'after':adjusted,'delta':adjusted-old[0]})
                planned.append(pred)
    changes['factor_changes'].sort(key=lambda x:abs(x['delta']),reverse=True)
    changes['forecast_changes'].sort(key=lambda x:abs(x['delta']),reverse=True)
    run_id=insert(conn,'runs',created_at=at,mode=mode,regime=regime,snapshot=dump(snapshot),changes=dump(changes),is_demo=int(is_demo))
    for pred in planned:
        insert(conn,'predictions',run_id=run_id,**pred)
    if create_portfolios:
        portfolios(conn,run_id,planned,readiness if not is_demo else None)
    return {'run_id':run_id,'mode':mode,'prediction_count':len(planned),'model_ids':sorted({p['model_id'] for p in planned}), 'cohort':cohort}


def portfolios(conn,run_id,predictions,readiness=None):
    # Unit-consistent investable subset: DXY and US10Y are indicators, not holdings.
    eligible=[a['id'] for a in rows(conn,"SELECT id FROM assets WHERE asset_class!='indicator'")]
    signals={a:mean([p['adjusted'] for p in predictions if p['asset_id']==a and p['horizon']=='1M'] or [0]) for a in eligible}
    for model in rows(conn,'SELECT * FROM portfolio_models'):
        if model['method']=='equal_weight':
            weights={a:1/len(eligible) for a in eligible}
        else:
            # Cash-inclusive, long-only score allocation; deliberately no optimized risk claims.
            scores={a:max(0,s) for a,s in signals.items()}
            total=sum(scores.values())
            weights={a:min(.15,.8*s/total) if total>0 else 0 for a,s in scores.items()}
            weights['CASH']=1-sum(weights.values())
        research_weights=dict(weights)
        if readiness is not None:
            weights={'CASH':1.0}
        insert(conn,'portfolio_snapshots',run_id=run_id,portfolio_model_id=model['id'],weights=dump(weights),
               details=dump({'research_weights':research_weights,'data_gate':'blocked' if readiness is not None else 'demo',
                             'method':model['method'],'signals':signals,'currency_policy':'demo normalized signals; no FX hedge',
                             'execution':False,'note':'示范研究权重；未估计协方差、成本、可交易性及跨境约束'}))
