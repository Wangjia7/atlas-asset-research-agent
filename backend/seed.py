"""Synthetic fixture only. No prices, events or metrics are real market records."""
import hashlib
import math
from datetime import datetime, timedelta, timezone
from .db import dump, insert, now
from .engine import HORIZONS, REGIMES, evaluate, run_agent
from .ingest import ingest

ASSETS=[('Gold','黄金','commodity','USD','return'),('Oil','原油','commodity','USD','return'),
 ('DXY','美元指数','indicator','USD','return'),('US10Y','美国十年期收益率','indicator','USD','bp'),
 ('SPX','标普500','index','USD','return'),('BTC','比特币','crypto','USD','return'),
 ('601975','招商南油','equity','CNY','return'),('603019','中科曙光','equity','CNY','return'),
 ('000651','格力电器','equity','CNY','return'),('600887','伊利股份','equity','CNY','return'),
 ('002273','水晶光电','equity','CNY','return'),('603629','利通电子','equity','CNY','return'),
 ('002847','盐津铺子','equity','CNY','return'),('518880','黄金ETF（示例代码）','etf','CNY','return'),
 ('601899','紫金矿业','equity','CNY','return'),('600690','海尔智家','equity','CNY','return')]
FACTORS=[('real_yield','实际利率','Macro','core'),('usd','美元强度','Macro','core'),
 ('oil_supply','原油可得性','Energy','core'),('logistics','替代运输能力','Energy','core'),
 ('geo','地缘紧张度','Geopolitics','core'),('liquidity','流动性','Macro','core'),
 ('ai_demand','AI 算力需求','Technology','core'),('ai_credit','AI 信用利差','Credit','experimental'),
 ('consumption','国内消费需求','Consumer','core'),('freight','成品油运价','Shipping','core'),
 ('gold_flow','黄金 ETF 资金流','Flows','experimental'),('inflation','通胀预期','Macro','dormant')]
MODELS=[('linear','结构线性模型','linear','Champion'),('regime','状态条件模型','regime','Challenger'),
 ('benchmark','零变化基准','benchmark','Benchmark'),('explore','实验因子模型','experimental','Exploration'),
 ('nonlinear','非线性候选','nonlinear','Dormant')]


def coefficient(asset,factor):
    targeted={
      'Gold':{'real_yield':-.85,'usd':-.65,'geo':.6,'gold_flow':.8},
      'Oil':{'oil_supply':-.9,'geo':.8,'logistics':-.45,'consumption':.5},
      'DXY':{'real_yield':.7,'liquidity':-.6,'geo':.3},
      'US10Y':{'real_yield':.8,'inflation':.6,'geo':-.4},
      'SPX':{'liquidity':.7,'real_yield':-.5,'ai_demand':.6,'ai_credit':-.7},
      'BTC':{'liquidity':1.0,'real_yield':-.6,'geo':-.3},
      '601975':{'freight':.95,'logistics':-.35,'oil_supply':.15},
      '603019':{'ai_demand':.95,'ai_credit':-.65},'002273':{'ai_demand':.6},'603629':{'ai_demand':.8,'ai_credit':-.7},
      '518880':{'real_yield':-.8,'usd':-.4,'geo':.7,'gold_flow':.8},
      '601899':{'geo':.35,'real_yield':-.6,'consumption':.4},
    }
    default=.5 if factor=='consumption' and asset[0].isdigit() else .1
    return targeted.get(asset,{}).get(factor,default)


def seed(conn):
    if conn.execute('SELECT COUNT(*) FROM assets').fetchone()[0]:
        return
    base=datetime.now(timezone.utc)-timedelta(days=480)
    stamp=base.isoformat(timespec='microseconds')
    for a in ASSETS:
        insert(conn,'assets',**dict(zip(['id','name','asset_class','currency','target_unit'],a)))
    for f in FACTORS:
        insert(conn,'factors',id=f[0],name=f[1],category=f[2],state=f[3],description='示范研究因子；输入为衰减事件冲击，非实测水平',transform='tanh(decayed event sum)',lag_days=0)
    for m in MODELS:
        insert(conn,'models',id=m[0],name=m[1],version='1.0-demo',family=m[2],role=m[3],config=dump({'trained':False,'weights':'hand-authored fixture'}),created_at=stamp)
        for a in ASSETS:
            for f in FACTORS:
                for h in HORIZONS:
                    for regime in REGIMES:
                        weight=coefficient(a[0],f[0])
                        if m[0]=='benchmark': weight=0
                        if m[0]=='regime': weight*=1.3 if regime=='Risk-off' and f[0] in ('geo','liquidity') else .9
                        if m[0]=='explore': weight*=1.25 if f[3]=='experimental' else .85
                        if m[0]=='nonlinear': weight*=-.55 if f[0]=='geo' else 1.1
                        insert(conn,'factor_asset',model_id=m[0],model_version='1.0-demo',factor_id=f[0],asset_id=a[0],horizon=h,regime=regime,weight=weight,known_at=stamp)
    insert(conn,'portfolio_models',id='equal',name='等权研究组合',method='equal_weight',config=dump({}))
    insert(conn,'portfolio_models',id='signal',name='信号倾斜 + 现金',method='signal_tilt',config=dump({'max_weight':.15,'budget':.8}))
    templates=[
      '沙特替代管道恢复运行。原油供应可能增加；如果供应持续恢复，需验证库存变化。',
      '美国实际利率上升。美元走强。市场讨论未来流动性收缩。',
      '地缘冲突缓解。黄金 ETF 资金流入增加。成品油运价下降。',
      '中国消费需求增加。AI 算力需求上升。AI 信用利差扩大。',
      '美国实际利率下降。流动性增加。美元走弱。',
      '地缘冲突升级。航运运价上涨。通胀预期上升。',
    ]
    # 36 synthetic origin dates; all 3M targets mature before today.
    for day in range(36):
        dt=base+timedelta(days=day*9)
        at=dt.isoformat(timespec='microseconds')
        text=f'【合成演示第 {day+1} 期】\n'+templates[day%len(templates)]
        ingest(conn,f'合成演示 · 研究简报 {day+1}',text,publisher='Synthetic fixture',published_at=at,known_at=at,is_demo=True)
        result=run_agent(conn,'full',REGIMES[day%3],at,is_demo=True,create_portfolios=False)
        # Outcomes generated independently of predictions. Do not interpret seed
        # leaderboard as evidence of investment skill.
        for i,a in enumerate(ASSETS):
            for h,days in HORIZONS.items():
                scale=(6 if a[0]=='US10Y' else .012)*math.sqrt(days/7)
                value=scale*(math.sin(day*.73+i*.61)+.35*math.cos(day*1.19+i))
                due=(dt+timedelta(days=days)).isoformat(timespec='microseconds')
                insert(conn,'outcomes',asset_id=a[0],issued_at=at,due_at=due,value=value,unit=a[4],observed_at=due,source='Synthetic sine fixture',is_demo=1)
    evaluate(conn,cohort='demo')
    current=now()
    ingest(conn,'当前演示 · 两条不同传导链','【合成演示，不代表真实新闻】\n沙特管道恢复运行。美国讨论限制柴油出口；如果限制实施，欧洲供应可能减少。地缘紧张度没有下降。AI 算力需求增加。AI 信用利差扩大。',publisher='Synthetic fixture',published_at=current,known_at=current,is_demo=True)
    run_agent(conn,'active','Neutral',is_demo=True)
    conn.execute("INSERT OR REPLACE INTO meta VALUES('last_full_evaluation',?)",(current,))
