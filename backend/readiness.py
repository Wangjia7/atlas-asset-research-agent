"""Conservative data gates. Thresholds are policy defaults, not proof of skill."""
import calendar
import json
import math
from datetime import datetime, timedelta


def lookback_start(at):
    dt=datetime.fromisoformat(at)
    month=dt.year*12+dt.month-1-3
    year,month=divmod(month,12)
    return dt.replace(year=year,month=month+1,day=min(dt.day,calendar.monthrange(year,month+1)[1])).isoformat(timespec='microseconds')


def assess(conn,asset,horizon,regime,model,at):
    start=lookback_start(at)
    news=[]
    for r in conn.execute('SELECT * FROM raw_sources WHERE is_demo=0 AND known_at<=? AND published_at>=? AND published_at<=?',(at,start,at)):
        meta=json.loads(r['metadata'])
        if asset in meta.get('asset_ids',[]): news.append(r)
    reviewed=0
    for r in news:
        claims=conn.execute('SELECT review_status FROM claims WHERE source_id=?',(r['id'],)).fetchall()
        reviewed+=bool(claims) and all(x[0]=='approved' for x in claims)
    days={r['published_at'][:10] for r in news}
    months={d[:7] for d in days}
    reasons=[]
    if len(news)<20 or len(days)<15 or len(months)<3: reasons.append('相关新闻不足：需要至少20篇、15个日期且覆盖3个月')
    if len({r['publisher'] for r in news})<3: reasons.append('独立来源不足3个（来源独立性仍需人工核验）')
    if reviewed<len(news) or not news: reasons.append('新闻证据尚未全部审阅')
    if not news or min(r['published_at'] for r in news)> (datetime.fromisoformat(start)+timedelta(days=7)).isoformat(timespec='microseconds'):
        reasons.append('历史起点未覆盖三个月回读窗口')
    if not news or max(r['published_at'] for r in news)<(datetime.fromisoformat(at)-timedelta(days=7)).isoformat(timespec='microseconds'):
        reasons.append('近期新闻缺失或过期')
    # No price history adapter in current MVP. Outcomes alone are not daily bars.
    reasons.append('缺少可核验的三个月行情、交易日历、复权及交易成本数据')
    records=conn.execute('''SELECT p.*,o.value FROM predictions p JOIN runs r ON r.id=p.run_id
      JOIN outcomes o ON o.asset_id=p.asset_id AND o.issued_at=p.issued_at AND o.due_at=p.due_at
      WHERE r.is_demo=0 AND o.is_demo=0 AND p.asset_id=? AND p.horizon=? AND p.regime=?
      AND p.model_id=? AND p.model_version=? AND p.due_at<=? AND o.observed_at<=?
      ORDER BY p.issued_at''',(asset,horizon,regime,model['id'],model['version'],at,at)).fetchall()
    independent=[]; end=''
    for r in records:
        if r['issued_at']>=end:
            independent.append(r); end=r['due_at']
    n=len(independent)
    if n<30: reasons.append('同资产×期限×状态×版本的非重叠到期样本不足30个；需更长验证历史')
    successes=sum(r['value']>0 for r in independent)
    interval=None
    if n:
        p=successes/n; z=1.96; den=1+z*z/n
        center=(p+z*z/(2*n))/den
        half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
        interval=[center-half,center+half]
    return dict(status='insufficient_data',risk='高：证据不足，无法量化投资胜率',
      lookback_start=start,as_of=at,news_count=len(news),reviewed_sources=reviewed,
      source_count=len({r['publisher'] for r in news}),news_days=len(days),news_months=len(months),
      independent_outcomes=n,historical_up_frequency=successes/n if n else None,
      historical_frequency_interval_95=interval,investment_probability=None,
      recommended_action='暂缓新增仓位，补充数据后复评',reasons=reasons,
      probability_definition='未来指定期限扣除交易成本后的正收益概率；当前尚不可估计',
      note='历史上涨频率仅作诊断，不是模型条件概率；数据充足也不保证预测可靠')
