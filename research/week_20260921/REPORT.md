# 上周流程测试：2026-09-21—09-25

**结论：流程回放成功；完整模拟盘与预测有效性验证未通过数据门槛。**

这是事后研究诊断。模型使用当前示例权重，新闻仅有跨月的少量原文摘录，不能称作历史时点无偏回测。
A 股 9 月 25 日中秋休市，期末使用 9 月 24 日；美股参考值使用 9 月 25 日。
公历“上周”也可能指 9 月 14–18 日；本报告按最近已结束交易周解释。

五次 Active Set 更新，每次 192 条预测；一次全量运行 240 条；合计 1200 条。
1W、1M、3M 共三个期限，Neutral 为预设情景，未用周末结果选择市场状态。
1W 最早于 9 月 28 日到期；Outcome 和竞技场排名均未提前结算。

## 局部模拟：水晶光电仓位 + 现金

起始资金 100,000 元。数据门槛未通过，两种组合均保留 100% 现金；因此零收益只表示未开仓，不能证明策略有效。原始研究权重保存在隔离库的 details.research_weights。
9 月 21 日开盘参考 25.60 元，9 月 24 日收盘参考 25.17 元；买卖均加 5bp 滑点，佣金单边 3bp 最低 5 元，卖出税费假设 5bp，100 股一手。费用为压力测试假设。
这是数据覆盖受限的反事实小实验：未核验公司行动和真实成交条件；不得替代完整组合业绩。

|组合规则|水晶光电目标权重|股数|期末资金（元）|盈亏（元）|净收益|
|---|---:|---:|---:|---:|---:|
|equal|0.00%|0|100000.00|0.00|0.000%|
|signal|0.00%|0|100000.00|0.00|0.000%|
|cash|0.00%|0|100000.00|0.00|0.000%|

## 行情参考（不可冒充成交收益）

|资产|上期收盘/净值|期末|变动|
|---|---:|---:|---:|
|SPX|7650.5|7743.41|1.214%|
|002273|25.47|25.17|-1.178%|
|601975|4.64|4.47|-3.664%|
|600887|26.6|26.9|1.128%|
|518880|9.0081|8.8065|-2.238%|

## 测试发现

- Sparse June–September excerpts collected; no claim of comprehensive three-month coverage.
- Current hand-authored model retrospectively applied; not an archived ex-ante model.
- Pipeline repairs are assigned negative supply/logistics impacts because eased modifies oil price; sentence-wide polarity is wrong.
- Unreviewed claims generate diagnostic scores only; live portfolio allocation is blocked by readiness gate.
- Nominal Treasury yields must not be silently mapped to real yields.
- SPX is an index reference, Gold/Oil have no instrument contract mapping, FX conversion is absent.
- Only 002273 has candidate equity execution prices; corporate actions and limit/auction execution not independently verified.
- All other hypothetical sleeves stay cash in the partial experiment; this is not full portfolio performance.
- Week-end marks precede 1W due dates; no early Outcome writes or model promotion.
- Rank IC, calibration, diversity and stability cannot establish effectiveness from this sample.

## 数据与复跑

inputs.json 保存来源链接、价格口径、出版日期假设和原文摘录。原文摘录完整保存，但没有保存新闻全文，不满足全文无损归档目标。
所有网页于 2026-09-27 检索，历史页面是否修订无法验证。发布时间只有日期时保守延迟到次日末；抓取时间不伪装为当时已抓取。
results.json 是计算结果，CSV 是证据和预测账本，replay.sqlite3 是隔离回放库。

```bash
python -m backend.weekly_replay
```

新增真实新闻入口仍为 backend/providers.py 的 NewsProvider，行情入口为 MarketProvider；完整回测还需带历史版本的新闻档案、交易日历、复权日线、实际交易载体和汇率。

## 来源

- https://www.yallstreetetfs.com/news-resources/gold-price-holds-near-4380-after-fed-rate-hike/
- https://linzhi.gov.cn/zfxxgkpt/c105932/202606/c7ed761bd923454e9ad1ec158d1a7de1.shtml
- https://www.stats.gov.cn/xxgk/sjfb/zxfb2020/202607/t20260715_1964121.html
- https://www.stats.gov.cn/zwfwck/sjfb/202608/t20260817_1965064.html
- https://www.stats.gov.cn/sj/zxfbhjd/202609/t20260915_1965332.html
- https://www.investing.com/indices/us-spx-500-historical-data?cid=40826
- https://cn.investing.com/equities/crystal-optech-a-historical-data
- https://wap.stockstar.com/detail/RB2026092500009226
- https://wap.stockstar.com/detail/RB2026092500008644
- https://fund.stockstar.com/funds/f10/fundjz_518880.html
- https://www.sse.com.cn/disclosure/dealinstruc/closed/c/c_20251222_10802510.shtml
