import sqlite3
from backend.weekly_replay import paper_position, registries, ROOT
from backend.ingest import ingest
from backend.engine import run_agent


def test_lot_size_budget_and_costs():
    p=paper_position(100000,1/14,25.60,25.17)
    assert p['shares']==200
    assert p['shares']*p['buy_fill']+p['buy_fee']<=100000/14
    assert abs(p['pnl']-(-103.5927415))<1e-7
    assert paper_position(100000,0,25.60,25.17)['net_return']==0


def test_future_news_not_used_and_dormant_not_in_active_set():
    c=sqlite3.connect(':memory:'); c.row_factory=sqlite3.Row
    c.executescript((ROOT/'backend/schema.sql').read_text())
    at='2026-09-21T00:00:00.000000+00:00'
    registries(c,at)
    ingest(c,'future','AI 算力需求增加。',known_at='2026-09-22T00:00:00.000000+00:00')
    r=run_agent(c,at=at)
    assert r['prediction_count']==192
    assert 'nonlinear' not in r['model_ids']
    assert c.execute('SELECT MAX(ABS(original)) FROM predictions').fetchone()[0]==0
    c.close()


def test_calendar_lookback_and_live_abstention():
    import json
    from backend.readiness import lookback_start
    assert lookback_start('2026-05-31T00:00:00+00:00').startswith('2026-02-28')
    c=sqlite3.connect(':memory:'); c.row_factory=sqlite3.Row
    c.executescript((ROOT/'backend/schema.sql').read_text())
    at='2026-09-21T00:00:00.000000+00:00'; registries(c,at)
    ingest(c,'old','原油供应增加。',asset_ids=['Oil'],published_at='2026-05-01T00:00:00+00:00',known_at='2026-05-01T00:00:00+00:00')
    ingest(c,'future','原油供应增加。',asset_ids=['Oil'],published_at='2026-09-18T00:00:00+00:00',known_at='2026-09-22T00:00:00+00:00')
    r=run_agent(c,at=at)
    snapshot=json.loads(c.execute('SELECT snapshot FROM runs WHERE id=?',(r['run_id'],)).fetchone()[0])
    a=snapshot['readiness']['Oil:1W:linear']
    assert a['news_count']==0 and a['investment_probability'] is None
    assert a['lookback_start'].startswith('2026-06-21')
    assert all(json.loads(x[0])=={'CASH':1.0} for x in c.execute('SELECT weights FROM portfolio_snapshots'))
    c.close()
