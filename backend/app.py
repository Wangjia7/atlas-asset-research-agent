import asyncio
import json
import os
import sqlite3
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field, field_validator

from .db import ROOT, connect, dump, initialize, insert, now, rows
from .engine import HORIZONS, REGIMES, active_overrides, evaluate, latest_evaluations, run_agent
from .ingest import ingest
from .seed import seed

WRITE_LOCK=threading.Lock()
JSON_FIELDS={'embedding','metadata','tags','entities','geography','sectors','horizons','event_cluster','actions',
             'objects','config','snapshot','changes','contributions','metrics','weights','details'}


def decode(row):
    return {k:json.loads(v) if k in JSON_FIELDS and isinstance(v,str) else v for k,v in dict(row).items()}


def iso(value):
    dt=datetime.fromisoformat(value.replace('Z','+00:00'))
    if dt.tzinfo is None:
        raise ValueError('时间必须包含时区，例如 +08:00 或 Z')
    return dt.astimezone(timezone.utc).isoformat(timespec='microseconds')


def scheduled_tick():
    with WRITE_LOCK, connect() as conn:
        current=now()
        last=conn.execute("SELECT value FROM meta WHERE key='last_full_evaluation'").fetchone()
        full=not last or datetime.fromisoformat(current)-datetime.fromisoformat(last[0])>=timedelta(days=7)
        demo=os.environ.get('AGENT_COHORT','demo')=='demo'
        if full:
            for regime in REGIMES:
                run_agent(conn,'full',regime,is_demo=demo)
            evaluate(conn,cohort='demo' if demo else 'live')
            conn.execute("INSERT OR REPLACE INTO meta VALUES('last_full_evaluation',?)",(current,))
        else:
            run_agent(conn,'active',is_demo=demo)


async def scheduler():
    interval=max(10,int(os.environ.get('AGENT_INTERVAL_SECONDS','900')))
    while True:
        await asyncio.sleep(interval)
        try:
            await asyncio.to_thread(scheduled_tick)
        except Exception:
            import logging
            logging.exception('Agent scheduled run failed')


@asynccontextmanager
async def lifespan(app):
    initialize()
    with WRITE_LOCK, connect() as conn:
        seed(conn)
    task=asyncio.create_task(scheduler()) if os.environ.get('AGENT_SCHEDULER','1')=='1' else None
    yield
    if task:
        task.cancel()
        try: await task
        except asyncio.CancelledError: pass


app=FastAPI(title='Atlas · Local Research Agent',version='0.1.0',lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware,allowed_hosts=['localhost','127.0.0.1','testserver'])


@app.middleware('http')
async def same_origin(request: Request, call_next):
    origin=request.headers.get('origin')
    if request.method not in ('GET','HEAD','OPTIONS') and origin and origin!=str(request.base_url).rstrip('/'):
        return JSONResponse({'detail':'只接受同源本地写入'},status_code=403)
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    return response


@app.exception_handler(sqlite3.IntegrityError)
async def integrity_error(request, exc):
    return JSONResponse({'detail':'记录冲突或引用无效；历史记录不可覆盖。'},status_code=409)


class SourceInput(BaseModel):
    title: str=Field(min_length=1,max_length=300)
    raw_text: str=Field(min_length=1,max_length=200000)
    publisher: str=Field(default='Manual',max_length=200)
    url: str=Field(default='',max_length=2000)
    published_at: Optional[str]=None
    is_demo: bool=False

    @field_validator('title','raw_text')
    @classmethod
    def not_blank(cls,v):
        if not v.strip(): raise ValueError('不能为空')
        return v

    @field_validator('published_at')
    @classmethod
    def timestamp(cls,v): return iso(v) if v else None


class RunInput(BaseModel):
    mode: Literal['active','full']='active'
    regime: Literal['Neutral','Risk-off','Inflation']='Neutral'
    is_demo: bool=True


class OverrideInput(BaseModel):
    factor_id: str
    asset_id: Optional[str]=None
    multiplier: float=Field(ge=0,le=3,allow_inf_nan=False)
    reason: str=Field(min_length=3,max_length=2000)
    expires_at: Optional[str]=None

    @field_validator('expires_at')
    @classmethod
    def timestamp(cls,v):
        if not v: return None
        v=iso(v)
        if v<=now(): raise ValueError('到期时间必须在未来')
        return v


class FactorState(BaseModel):
    state: Literal['core','experimental','dormant']


class OutcomeInput(BaseModel):
    prediction_id: int
    value: float=Field(allow_inf_nan=False)
    source: str=Field(min_length=3,max_length=500)


@app.get('/')
def home(): return FileResponse(ROOT/'static'/'index.html')


@app.get('/api/health')
def health(): return {'ok':True,'schema_version':1,'execution':False}


@app.get('/api/catalog')
def catalog():
    with connect() as conn:
        return {**{t:[decode(r) for r in rows(conn,f'SELECT * FROM {t}')] for t in ['assets','factors','models','portfolio_models']},
                'horizons':list(HORIZONS),'regimes':REGIMES,'scheduler':os.environ.get('AGENT_SCHEDULER','1')=='1',
                'interval_seconds':max(10,int(os.environ.get('AGENT_INTERVAL_SECONDS','900')))}


@app.get('/api/dashboard')
def dashboard(cohort: Literal['demo','live']='demo', horizon:str='1M', regime:str='Neutral'):
    with connect() as conn:
        demo=int(cohort=='demo')
        last=conn.execute('SELECT * FROM runs WHERE is_demo=? AND regime=? ORDER BY id DESC LIMIT 1',(demo,regime)).fetchone()
        counts={t:conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in ['assets','factors','models']}
        counts['raw_sources']=conn.execute('SELECT COUNT(*) FROM raw_sources WHERE is_demo=?',(demo,)).fetchone()[0]
        counts['predictions']=conn.execute('SELECT COUNT(*) FROM predictions p JOIN runs r ON r.id=p.run_id WHERE r.is_demo=?',(demo,)).fetchone()[0]
        counts['outcomes']=conn.execute('SELECT COUNT(*) FROM outcomes WHERE is_demo=?',(demo,)).fetchone()[0]
        last_id=last['id'] if last else -1
        portfolios=[decode(r) for r in rows(conn,'SELECT ps.*,pm.name FROM portfolio_snapshots ps JOIN portfolio_models pm ON pm.id=ps.portfolio_model_id WHERE run_id=?',(last_id,))]
        preds=[decode(r) for r in rows(conn,'SELECT p.*,a.target_unit FROM predictions p JOIN assets a ON a.id=p.asset_id WHERE run_id=? AND horizon=?',(last_id,horizon))]
        return dict(counts=counts,last_run=decode(last) if last else None,portfolios=portfolios,predictions=preds,
                    overrides=active_overrides(conn,now()),cohort=cohort)


@app.post('/api/sources')
def add_source(body: SourceInput):
    with WRITE_LOCK,connect() as conn:
        return ingest(conn,**body.model_dump())


@app.get('/api/sources')
def sources(cohort: Literal['demo','live']='demo'):
    with connect() as conn:
        return rows(conn,'SELECT id,title,publisher,published_at,known_at,is_demo,content_hash FROM raw_sources WHERE is_demo=? ORDER BY id DESC',(int(cohort=='demo'),))


@app.get('/api/sources/{source_id}')
def source_detail(source_id:int):
    with connect() as conn:
        source=conn.execute('SELECT * FROM raw_sources WHERE id=?',(source_id,)).fetchone()
        if not source: raise HTTPException(404,'原文不存在')
        return {'source':decode(source),'claims':[decode(r) for r in rows(conn,'SELECT * FROM claims WHERE source_id=?',(source_id,))],
                'events':[decode(r) for r in rows(conn,'SELECT * FROM events WHERE source_id=?',(source_id,))],
                'relations':rows(conn,'SELECT ef.* FROM event_factor ef JOIN events e ON e.id=ef.event_id WHERE e.source_id=?',(source_id,))}


@app.post('/api/runs')
def run(body: RunInput):
    with WRITE_LOCK,connect() as conn:
        result=run_agent(conn,**body.model_dump())
        if body.mode=='full':
            result['evaluation']=evaluate(conn,cohort='demo' if body.is_demo else 'live')
            conn.execute("INSERT OR REPLACE INTO meta VALUES('last_full_evaluation',?)",(now(),))
        return result


@app.get('/api/runs')
def runs(cohort: Literal['demo','live']='demo'):
    with connect() as conn:
        return rows(conn,'SELECT id,created_at,mode,regime,is_demo FROM runs WHERE is_demo=? ORDER BY id DESC LIMIT 200',(int(cohort=='demo'),))


@app.get('/api/runs/{run_id}')
def run_detail(run_id:int):
    with connect() as conn:
        r=conn.execute('SELECT * FROM runs WHERE id=?',(run_id,)).fetchone()
        if not r: raise HTTPException(404,'运行不存在')
        return decode(r)


@app.get('/api/leaderboard')
def leaderboard(asset:str='Gold',horizon:str='1M',regime:str='Neutral',cohort:Literal['demo','live']='demo'):
    with connect() as conn:
        result=latest_evaluations(conn,asset,horizon,regime,cohort)
        return sorted(result,key=lambda r:r['score'] if r['score'] is not None else -1,reverse=True)


@app.post('/api/evaluate')
def evaluate_now(cohort:Literal['demo','live']='demo'):
    with WRITE_LOCK,connect() as conn: return evaluate(conn,cohort=cohort)


@app.get('/api/predictions')
def predictions(asset:Optional[str]=None,horizon:Optional[str]=None,regime:Optional[str]=None,
                cohort:Literal['demo','live']='demo',limit:int=Query(default=100,ge=1,le=500),offset:int=Query(default=0,ge=0)):
    with connect() as conn:
        where='r.is_demo=? AND (? IS NULL OR p.asset_id=?) AND (? IS NULL OR p.horizon=?) AND (? IS NULL OR p.regime=?)'
        params=(int(cohort=='demo'),asset,asset,horizon,horizon,regime,regime)
        total=conn.execute(f'SELECT COUNT(*) FROM predictions p JOIN runs r ON r.id=p.run_id WHERE {where}',params).fetchone()[0]
        records=rows(conn,f'''SELECT p.*,a.target_unit,o.value AS outcome,o.source AS outcome_source FROM predictions p
           JOIN runs r ON r.id=p.run_id JOIN assets a ON a.id=p.asset_id
           LEFT JOIN outcomes o ON o.asset_id=p.asset_id AND o.issued_at=p.issued_at AND o.due_at=p.due_at
           WHERE {where} ORDER BY p.id DESC LIMIT ? OFFSET ?''',params+(limit,offset))
        return {'total':total,'items':[decode(r) for r in records]}


@app.post('/api/outcomes')
def add_outcome(body:OutcomeInput):
    with WRITE_LOCK,connect() as conn:
        p=conn.execute('SELECT p.*,r.is_demo,a.target_unit FROM predictions p JOIN runs r ON r.id=p.run_id JOIN assets a ON a.id=p.asset_id WHERE p.id=?',(body.prediction_id,)).fetchone()
        if not p: raise HTTPException(404,'预测不存在')
        if p['due_at']>now(): raise HTTPException(422,'预测尚未到期，不能回填结果')
        oid=insert(conn,'outcomes',asset_id=p['asset_id'],issued_at=p['issued_at'],due_at=p['due_at'],value=body.value,
                   unit=p['target_unit'],observed_at=now(),source=body.source,is_demo=p['is_demo'])
        return {'id':oid,'evaluation':evaluate(conn,cohort='demo' if p['is_demo'] else 'live')}


@app.get('/api/overrides')
def overrides():
    with connect() as conn:
        return {'active':active_overrides(conn,now()),'history':rows(conn,'SELECT * FROM human_overrides ORDER BY id DESC')}


@app.post('/api/overrides')
def add_override(body:OverrideInput):
    with WRITE_LOCK,connect() as conn:
        return {'id':insert(conn,'human_overrides',**body.model_dump(),created_at=now(),revokes_id=None)}


@app.post('/api/overrides/{override_id}/revoke')
def revoke_override(override_id:int):
    with WRITE_LOCK,connect() as conn:
        r=conn.execute('SELECT * FROM human_overrides WHERE id=?',(override_id,)).fetchone()
        if not r or r['revokes_id']: raise HTTPException(404,'调整不存在')
        if conn.execute('SELECT id FROM human_overrides WHERE revokes_id=?',(override_id,)).fetchone():
            raise HTTPException(409,'已撤销')
        return {'id':insert(conn,'human_overrides',factor_id=r['factor_id'],asset_id=r['asset_id'],multiplier=1,
                            reason='撤销调整 #'+str(override_id),created_at=now(),expires_at=None,revokes_id=override_id)}


@app.patch('/api/factors/{factor_id}')
def factor_state(factor_id:str,body:FactorState):
    with WRITE_LOCK,connect() as conn:
        if not conn.execute('SELECT id FROM factors WHERE id=?',(factor_id,)).fetchone(): raise HTTPException(404,'因子不存在')
        conn.execute('UPDATE factors SET state=? WHERE id=?',(body.state,factor_id))
        return {'id':factor_id,'state':body.state,'note':'仅影响未来运行；历史快照保留旧状态'}


@app.get('/api/matrix')
def matrix(kind:Literal['factor_asset','event_factor','predictions']='factor_asset',horizon:Optional[str]='1M',
           regime:str='Neutral',model:Optional[str]='linear',cohort:Literal['demo','live']='demo',run_id:Optional[int]=None):
    horizon = horizon or None
    model = model or None
    with connect() as conn:
        if kind=='factor_asset':
            records=rows(conn,'''SELECT fa.*,fa.factor_id AS factor,fa.asset_id AS asset,fa.model_id AS model,
                fa.weight AS value,fa.known_at AS time FROM factor_asset fa JOIN models m ON m.id=fa.model_id AND m.version=fa.model_version
                WHERE (? IS NULL OR fa.horizon=?) AND fa.regime=? AND (? IS NULL OR fa.model_id=?)''',(horizon,horizon,regime,model,model))
            return {'dimensions':['factor','asset','model','horizon','regime'],'records':records,'unit':'raw weight','note':'原始模型权重；未应用 human multiplier'}
        if kind=='event_factor':
            records=rows(conn,'''SELECT ef.*,ef.event_id AS event,ef.factor_id AS factor,ef.impact AS value,e.title,
                ef.known_at AS time,e.source_id FROM event_factor ef JOIN events e ON e.id=ef.event_id
                JOIN raw_sources s ON s.id=e.source_id WHERE (? IS NULL OR ef.horizon=?) AND ef.regime IN ('all',?)
                AND s.is_demo=? AND NOT EXISTS (SELECT 1 FROM event_factor newer WHERE newer.event_id=ef.event_id AND newer.factor_id=ef.factor_id AND newer.horizon=ef.horizon AND newer.regime=ef.regime AND newer.region=ef.region AND newer.id>ef.id) ORDER BY ef.id DESC LIMIT 600''',(horizon,horizon,regime,int(cohort=='demo')))
            return {'dimensions':['event','factor','horizon','regime','time'],'records':records,'unit':'event impact','note':'最新 600 条证据关系；规则假说，待人工审阅'}
        if run_id is None:
            r=conn.execute('SELECT id FROM runs WHERE is_demo=? AND regime=? ORDER BY id DESC LIMIT 1',(int(cohort=='demo'),regime)).fetchone()
            run_id=r['id'] if r else -1
        records=rows(conn,'''SELECT p.*,p.asset_id AS asset,p.model_id AS model,p.adjusted AS value,p.issued_at AS time,a.target_unit
             FROM predictions p JOIN assets a ON a.id=p.asset_id JOIN runs r ON r.id=p.run_id
             WHERE p.run_id=? AND r.is_demo=? AND (? IS NULL OR p.horizon=?) AND (? IS NULL OR p.model_id=?)''',
             (run_id,int(cohort=='demo'),horizon,horizon,model,model))
        return {'dimensions':['asset','horizon','model','regime','time'],'records':[decode(r) for r in records],
                'unit':'per-asset target','note':'收益率以小数存储；US10Y 为 bp，不能混合求均值','run_id':run_id}


app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')
