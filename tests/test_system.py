import json
import sqlite3
from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient
from backend import db
from backend.app import app
from backend.engine import run_agent, active_overrides, factor_values
from backend.metrics import metrics, corr

@pytest.fixture(scope='module')
def client(tmp_path_factory):
    db.DB_PATH=tmp_path_factory.mktemp('research')/'test.sqlite3'
    import os
    os.environ['AGENT_SCHEDULER']='0'
    with TestClient(app) as client:
        yield client


def test_seed_and_pages(client):
    assert client.get('/').status_code==200
    assert client.get('/static/app.js').status_code==200
    assert client.get('/api/health').json()['execution'] is False
    c=client.get('/api/catalog').json()
    assert len(c['assets'])==16
    assert {m['role'] for m in c['models']}=={'Champion','Challenger','Benchmark','Exploration','Dormant'}
    assert client.get('/api/dashboard').json()['counts']['outcomes']==36*16*3
    for endpoint in ['/api/sources','/api/leaderboard','/api/predictions','/api/overrides','/api/runs','/api/matrix']:
        assert client.get(endpoint).status_code==200
    d=client.get('/api/leaderboard?asset=Gold&horizon=1M&regime=Neutral').json()
    assert len(d)==5 and all(r['sample_count']==12 for r in d)
    assert client.get('/api/leaderboard?cohort=live').json()==[]


def test_lossless_evidence_unicode_and_idempotence(client):
    raw='  原文 🧪\n如果美元下降，黄金可能上涨；AI 算力需求增加。\n保留尾部空白  '
    data=dict(title='Unicode test',raw_text=raw,publisher='Test',is_demo=False)
    r=client.post('/api/sources',json=data)
    assert r.status_code==200
    sid=r.json()['source_id']
    assert client.post('/api/sources',json=data).json()['duplicate'] is True
    source=client.get(f'/api/sources/{sid}').json()
    assert source['source']['raw_text']==raw
    for c in source['claims']:
        assert raw[c['evidence_start']:c['evidence_end']]==c['evidence_text']==c['text']
    conditional=next(c for c in source['claims'] if '如果' in c['text'])
    assert conditional['modality']=='conditional' and conditional['claim_type']=='forecast'
    assert conditional['surprise'] is None
    assert 'non-semantic' in source['source']['embedding_model']


def test_immutable_ledger_and_separate_matrices(client):
    with db.connect() as c:
        with pytest.raises(sqlite3.IntegrityError): c.execute("UPDATE raw_sources SET raw_text='lost' WHERE id=1")
        with pytest.raises(sqlite3.IntegrityError): c.execute('DELETE FROM predictions WHERE id=1')
    ef=client.get('/api/matrix?kind=event_factor').json()['records']
    fa=client.get('/api/matrix?kind=factor_asset').json()['records']
    assert ef and fa and 'claim_id' in ef[0] and 'raw_weight' not in ef[0]
    assert 'model_id' in fa[0] and 'event_id' not in fa[0]
    all_h=client.get('/api/matrix?kind=factor_asset&horizon=&model=').json()['records']
    assert {x['horizon'] for x in all_h}=={'1W','1M','3M'}


def test_active_and_full_sets(client):
    a=client.post('/api/runs',json={'mode':'active','is_demo':False}).json()
    assert 'nonlinear' not in a['model_ids'] and a['prediction_count']==16*3*4
    f=client.post('/api/runs',json={'mode':'full','is_demo':False}).json()
    assert 'nonlinear' in f['model_ids'] and f['prediction_count']==16*3*5
    assert f['evaluation']['evaluations']==0


def test_overrides_preserve_originals(client):
    with db.connect() as c:
        before=[dict(r) for r in c.execute('SELECT * FROM factor_asset')]
        at=db.now()
        p1=run_agent(c,'full',at=at,is_demo=True)
        oid=db.insert(c,'human_overrides',factor_id='ai_demand',asset_id='603019',multiplier=0,reason='test mute',created_at=at,expires_at=None,revokes_id=None)
        p2=run_agent(c,'full',at=at,is_demo=True)
        sql="SELECT * FROM predictions WHERE run_id=? AND model_id='linear' AND asset_id='603019' AND horizon='1M'"
        a=c.execute(sql,(p1['run_id'],)).fetchone()
        b=c.execute(sql,(p2['run_id'],)).fetchone()
        assert a['original']==b['original'] and b['adjusted']!=b['original']
        assert before==[dict(r) for r in c.execute('SELECT * FROM factor_asset')]
    assert client.post(f'/api/overrides/{oid}/revoke').status_code==200
    assert not any(o['id']==oid for o in client.get('/api/overrides').json()['active'])
    assert client.post('/api/overrides',json={'factor_id':'geo','multiplier':4,'reason':'invalid'}).status_code==422


def test_expiry_and_known_time(client):
    with db.connect() as c:
        at=db.now()
        past=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat(timespec='microseconds')
        oid=db.insert(c,'human_overrides',factor_id='geo',asset_id='Gold',multiplier=0,reason='expired',created_at=past,expires_at=past,revokes_id=None)
        assert not any(o['id']==oid for o in active_overrides(c,at))
        live,_=factor_values(c,at,'1M','Neutral',False)
        demo,_=factor_values(c,at,'1M','Neutral',True)
        assert live!=demo
        early=(datetime.now(timezone.utc)-timedelta(days=1000)).isoformat(timespec='microseconds')
        vals,evidence=factor_values(c,early,'1M','Neutral',True)
        assert not evidence and all(v==0 for v in vals.values())


def test_maturity_and_pairing(client):
    latest=client.get('/api/predictions?cohort=live').json()['items'][0]
    assert client.post('/api/outcomes',json={'prediction_id':latest['id'],'value':.02,'source':'market provider'}).status_code==422
    at=(datetime.now(timezone.utc)-timedelta(days=10)).isoformat(timespec='microseconds')
    with db.connect() as c:
        r=run_agent(c,'full',at=at,is_demo=False)
        p=c.execute("SELECT id FROM predictions WHERE run_id=? AND asset_id='Gold' AND horizon='1W'",(r['run_id'],)).fetchone()
    data={'prediction_id':p['id'],'value':.02,'source':'Test observed return'}
    assert client.post('/api/outcomes',json=data).status_code==200
    assert client.post('/api/outcomes',json=data).status_code==409
    ranks=client.get('/api/leaderboard?cohort=live&asset=Gold&horizon=1W').json()
    assert all(r['sample_count']==1 and r['score'] is None for r in ranks)


def test_metrics_hand_computable():
    ps=[dict(original=x,value=y,adjusted=x,probability_up=.8 if x>0 else .2,adjusted_probability_up=.8 if x>0 else .2,issued_at=str(i)) for i,(x,y) in enumerate([(1,2),(-1,-2),(2,1),(-2,-1)])]
    bm={p['issued_at']:{**p,'original':0} for p in ps}
    m=metrics(ps,bm,[])
    assert m['direction_accuracy']==1 and m['mae']==1 and m['rmse']==1
    assert m['brier']==pytest.approx(.04)
    assert m['incremental_contribution']==pytest.approx(1/3)
    assert m['diversity'] is None and m['stability'] is None
    assert corr([1,1,1],[1,2,3]) is None
    assert m['rank_ic']==pytest.approx(.6)


def test_state_snapshot_and_portfolio_budget(client):
    assert client.patch('/api/factors/ai_credit',json={'state':'dormant'}).status_code==200
    r=client.post('/api/runs',json={'is_demo':True}).json()
    detail=client.get('/api/runs/'+str(r['run_id'])).json()
    assert next(f for f in detail['snapshot']['factors'] if f['id']=='ai_credit')['state']=='dormant'
    dash=client.get('/api/dashboard').json()
    assert len(dash['portfolios'])==2
    for p in dash['portfolios']:
        assert sum(p['weights'].values())==pytest.approx(1)
        assert all(v>=0 for v in p['weights'].values())
        assert 'US10Y' not in p['weights'] and 'DXY' not in p['weights']


def test_validation(client):
    assert client.post('/api/sources',json={'title':' ','raw_text':'x'}).status_code==422
    assert client.post('/api/sources',json={'title':'test','raw_text':'x','published_at':'2026-01-01'}).status_code==422
    assert client.post('/api/runs',json={},headers={'Origin':'https://other.example'}).status_code==403
    assert client.post('/api/overrides',json={'factor_id':'missing','multiplier':1,'reason':'unknown factor'}).status_code==409


def test_negation_preserves_zero_change():
    from backend.providers import RuleExtractor
    claim=RuleExtractor().extract('地缘紧张度没有下降。')[0]
    assert claim['relations'][0]['impact']==0


def test_identical_text_across_cohorts(client):
    text='同一文本的独立数据集测试：美元上升。'
    demo=client.post('/api/sources',json={'title':'test','raw_text':text,'is_demo':True}).json()
    live=client.post('/api/sources',json={'title':'test','raw_text':text,'is_demo':False}).json()
    assert demo['source_id']!=live['source_id']
    assert not demo['duplicate'] and not live['duplicate']


def test_credit_does_not_imply_ai_demand():
    from backend.providers import RuleExtractor
    c=RuleExtractor().extract('AI 信用利差扩大。')[0]
    assert {r['factor_id'] for r in c['relations']}=={'ai_credit'}


def test_relation_revision_is_point_in_time(client):
    with db.connect() as c:
        relation=dict(c.execute("SELECT ef.* FROM event_factor ef JOIN events e ON e.id=ef.event_id JOIN raw_sources s ON s.id=e.source_id WHERE s.is_demo=0 AND ef.horizon='1M' LIMIT 1").fetchone())
        old_id=relation.pop('id')
        before=db.now()
        after=(datetime.now(timezone.utc)+timedelta(seconds=1)).isoformat(timespec='microseconds')
        relation.update(impact=0,version='reviewed-v2',known_at=after)
        new_id=db.insert(c,'event_factor',**relation)
        _,old_e=factor_values(c,before,'1M','Neutral',False)
        _,new_e=factor_values(c,after,'1M','Neutral',False)
        assert old_id in {r['relation_id'] for r in old_e}
        assert new_id not in {r['relation_id'] for r in old_e}
        assert new_id in {r['relation_id'] for r in new_e}
        assert old_id not in {r['relation_id'] for r in new_e}
