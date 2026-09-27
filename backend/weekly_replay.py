"""Offline, reproducible retrospective diagnostic. Never writes the app database.

Run: python -m backend.weekly_replay
Inputs are a deliberately incomplete, source-attributed research sample.
Historical timestamps below are replay assumptions, not historic model provenance.
"""
import csv
import hashlib
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from .db import dump, insert, rows
from .engine import HORIZONS, REGIMES, run_agent, evaluate
from .ingest import ingest
from .seed import ASSETS, FACTORS, MODELS, coefficient

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'research' / 'week_20260921'


def registries(c, at):
    # Copy fixed current MVP hypotheses, never seed synthetic news/outcomes.
    for a in ASSETS:
        insert(c, 'assets', **dict(zip(['id','name','asset_class','currency','target_unit'], a)))
    for f in FACTORS:
        insert(c,'factors',id=f[0],name=f[1],category=f[2],state=f[3],
               description='Current MVP hypothesis replayed retrospectively',transform='tanh',lag_days=0)
    for m in MODELS:
        insert(c,'models',id=m[0],name=m[1],version='1.0-retrospective',family=m[2],role=m[3],
               config=dump({'trained':False,'historically_frozen':False}),created_at=at)
        for a in ASSETS:
            for f in FACTORS:
                for h in HORIZONS:
                    for regime in REGIMES:
                        w=coefficient(a[0],f[0])
                        if m[0]=='benchmark': w=0
                        if m[0]=='regime': w*=1.3 if regime=='Risk-off' and f[0] in ('geo','liquidity') else .9
                        if m[0]=='explore': w*=1.25 if f[3]=='experimental' else .85
                        if m[0]=='nonlinear': w*=-.55 if f[0]=='geo' else 1.1
                        insert(c,'factor_asset',model_id=m[0],model_version='1.0-retrospective',
                               factor_id=f[0],asset_id=a[0],horizon=h,regime=regime,weight=w,known_at=at)
    for pid,name,method in [('equal','等权研究组合','equal_weight'),('signal','信号倾斜 + 现金','signal_tilt')]:
        insert(c,'portfolio_models',id=pid,name=name,method=method,config='{}')


def paper_position(capital, weight, entry, exit_price, fee=.0003, slippage=.0005, sell_tax=.0005):
    """Single A-share position, 100-share lots, assumed fees not broker quote."""
    buy=entry*(1+slippage)
    shares=int((capital*weight)/(buy*(1+fee))/100)*100
    if shares and shares*buy+max(5,shares*buy*fee)>capital*weight:
        shares-=100
    buy_fee=max(5,shares*buy*fee) if shares else 0
    cash=capital-shares*buy-buy_fee
    sell=exit_price*(1-slippage)
    sell_fee=max(5,shares*sell*fee) if shares else 0
    final=cash+shares*sell-sell_fee-shares*sell*sell_tax
    return dict(shares=shares,requested_weight=weight,buy_fill=buy,sell_fill=sell,
                buy_fee=buy_fee,sell_fee=sell_fee,sell_tax=shares*sell*sell_tax,
                initial_cash=capital,final_cash=final,pnl=final-capital,net_return=final/capital-1)


def main():
    data=json.loads((OUT/'inputs.json').read_text())
    at=data['period']['decision_at']
    c=sqlite3.connect(':memory:')
    c.row_factory=sqlite3.Row
    c.executescript((ROOT/'backend/schema.sql').read_text())
    registries(c,at)
    for n in sorted(data['news'],key=lambda n:n['known_at']):
        assert n['known_at']<=at
        ingest(c,**{k:n[k] for k in ['title','raw_text','publisher','url','published_at','known_at','asset_ids']})
    first=run_agent(c,at=at)
    # Replay daily scheduling with no invented new news. Missing days stay missing.
    for day in range(1,5):
        stamp=(datetime.fromisoformat(at)+timedelta(days=day)).isoformat(timespec='microseconds')
        run_agent(c,at=stamp)
    full=run_agent(c,mode='full',at='2026-09-26T00:00:00.000000+00:00')
    evaluations=evaluate(c,at='2026-09-27T00:00:00.000000+00:00',cohort='live')
    assert evaluations['evaluations']==0  # 1W targets mature Sep 28 or later.
    claims=rows(c,'SELECT * FROM claims')
    for cl in claims:
        raw=c.execute('SELECT raw_text FROM raw_sources WHERE id=?',(cl['source_id'],)).fetchone()[0]
        assert raw[cl['evidence_start']:cl['evidence_end']]==cl['evidence_text']
    preds=rows(c,'SELECT * FROM predictions WHERE run_id=?',(first['run_id'],))
    weights={p['portfolio_model_id']:json.loads(p['weights']) for p in rows(c,
        'SELECT * FROM portfolio_snapshots WHERE run_id=?',(first['run_id'],))}
    # Freeze original full-universe weights first. No renormalization to available winners.
    obs={x['asset']:x for x in data['observations']}
    stock=obs['002273']
    experiments={pid:paper_position(100000,w.get('002273',0),stock['entry'],stock['exit'])
                 for pid,w in weights.items()}
    experiments['cash']=paper_position(100000,0,stock['entry'],stock['exit'])
    references=[dict(asset=x['asset'],kind=x['kind'],start=x['prior_close'],end=x['exit'],
                     reference_return=x['exit']/x['prior_close']-1,url=x['url']) for x in obs.values()]
    issues=[
        'Sparse June–September excerpts collected; no claim of comprehensive three-month coverage.',
        'Current hand-authored model retrospectively applied; not an archived ex-ante model.',
        'Pipeline repairs are assigned negative supply/logistics impacts because eased modifies oil price; sentence-wide polarity is wrong.',
        'Unreviewed claims generate diagnostic scores only; live portfolio allocation is blocked by readiness gate.',
        'Nominal Treasury yields must not be silently mapped to real yields.',
        'SPX is an index reference, Gold/Oil have no instrument contract mapping, FX conversion is absent.',
        'Only 002273 has candidate equity execution prices; corporate actions and limit/auction execution not independently verified.',
        'All other hypothetical sleeves stay cash in the partial experiment; this is not full portfolio performance.',
        'Week-end marks precede 1W due dates; no early Outcome writes or model promotion.',
        'Rank IC, calibration, diversity and stability cannot establish effectiveness from this sample.'
    ]
    result=dict(period=data['period'],input_sha256=hashlib.sha256((OUT/'inputs.json').read_bytes()).hexdigest(),
                readiness=json.loads(c.execute('SELECT snapshot FROM runs WHERE id=?',(first['run_id'],)).fetchone()[0])['readiness'],active_run=first,full_run=full,claims=len(claims),prediction_count=c.execute('SELECT count(*) FROM predictions').fetchone()[0],
                evaluations=evaluations,full_portfolio_return=None,weights=weights,
                partial_paper_experiments=experiments,market_references=references,issues=issues,
                metric_status={'direction_accuracy':None,'mae':None,'rmse':None,'rank_ic':None,'probability_calibration':None,
                               'stability':None,'incremental_contribution':None,'diversity':None},
                exclusions=data['exclusions'])
    (OUT/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    for name,records in [('predictions',rows(c,'SELECT * FROM predictions')),('claims',claims),
                         ('event_factor',rows(c,'SELECT * FROM event_factor'))]:
        with (OUT/(name+'.csv')).open('w',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=list(records[0]))
            writer.writeheader(); writer.writerows(records)
    c.commit()
    # A separate artifact DB, never the live app DB.
    db=OUT/'replay.sqlite3'
    if db.exists(): db.unlink()
    dest=sqlite3.connect(db); c.backup(dest); dest.close(); c.close()
    report=['# 上周流程测试：2026-09-21—09-25','',
       '**结论：流程回放成功；完整模拟盘与预测有效性验证未通过数据门槛。**','',
       '这是事后研究诊断。模型使用当前示例权重，新闻仅有跨月的少量原文摘录，不能称作历史时点无偏回测。',
       'A 股 9 月 25 日中秋休市，期末使用 9 月 24 日；美股参考值使用 9 月 25 日。',
       '公历“上周”也可能指 9 月 14–18 日；本报告按最近已结束交易周解释。','',
       f"五次 Active Set 更新，每次 {first['prediction_count']} 条预测；一次全量运行 {full['prediction_count']} 条；合计 {result['prediction_count']} 条。",
       '1W、1M、3M 共三个期限，Neutral 为预设情景，未用周末结果选择市场状态。',
       '1W 最早于 9 月 28 日到期；Outcome 和竞技场排名均未提前结算。','',
       '## 局部模拟：水晶光电仓位 + 现金','',
       '起始资金 100,000 元。数据门槛未通过，两种组合均保留 100% 现金；因此零收益只表示未开仓，不能证明策略有效。原始研究权重保存在隔离库的 details.research_weights。',
       '9 月 21 日开盘参考 25.60 元，9 月 24 日收盘参考 25.17 元；买卖均加 5bp 滑点，佣金单边 3bp 最低 5 元，卖出税费假设 5bp，100 股一手。费用为压力测试假设。',
       '这是数据覆盖受限的反事实小实验：未核验公司行动和真实成交条件；不得替代完整组合业绩。','',
       '|组合规则|水晶光电目标权重|股数|期末资金（元）|盈亏（元）|净收益|',
       '|---|---:|---:|---:|---:|---:|']
    for pid,x in experiments.items():
        report.append(f"|{pid}|{x['requested_weight']:.2%}|{x['shares']}|{x['final_cash']:.2f}|{x['pnl']:.2f}|{x['net_return']:.3%}|")
    report+=['','## 行情参考（不可冒充成交收益）','','|资产|上期收盘/净值|期末|变动|','|---|---:|---:|---:|']
    for x in references: report.append(f"|{x['asset']}|{x['start']}|{x['end']}|{x['reference_return']:.3%}|")
    report+=['','## 测试发现','']+['- '+x for x in issues]
    report+=['','## 数据与复跑','',
       'inputs.json 保存来源链接、价格口径、出版日期假设和原文摘录。原文摘录完整保存，但没有保存新闻全文，不满足全文无损归档目标。',
       '所有网页于 2026-09-27 检索，历史页面是否修订无法验证。发布时间只有日期时保守延迟到次日末；抓取时间不伪装为当时已抓取。',
       'results.json 是计算结果，CSV 是证据和预测账本，replay.sqlite3 是隔离回放库。','',
       '```bash','python -m backend.weekly_replay','```','',
       '新增真实新闻入口仍为 backend/providers.py 的 NewsProvider，行情入口为 MarketProvider；完整回测还需带历史版本的新闻档案、交易日历、复权日线、实际交易载体和汇率。','',
       '## 来源','']
    for url in dict.fromkeys([n['url'] for n in data['news']]+[x['url'] for x in obs.values()]+[data['calendar_url']]):
        report.append('- '+url)
    (OUT/'REPORT.md').write_text('\n'.join(report)+'\n')
    print(json.dumps({'predictions':result['prediction_count'],'experiments':experiments,'report':str(OUT/'REPORT.md')},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
