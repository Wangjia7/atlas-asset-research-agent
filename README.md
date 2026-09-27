# Atlas Asset Research Agent

本地多维资产研究 MVP：HTML/JS + FastAPI + SQLite，包含新闻证据、Claim、事件与因子矩阵、模型竞技场、预测账本、人工调整和多种组合规则。

## 启动

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.lock.txt
./start.sh
```

启动地址和端口见 start.sh。初次启动会生成合成演示数据；演示排名不代表真实预测能力。

## 上周回放测试

```bash
python -m backend.weekly_replay
python -m pytest -q
```

结果见 [2026-09-21—25 测试报告](research/week_20260921/REPORT.md)。本次是数据覆盖受限的事后诊断，不是完整组合回测；隔离数据库不会污染主应用。

## 数据与流程

Schema 位于 backend/schema.sql。RawSource→Claim→Event→event_factor→Factor，独立的 factor_asset 保存 Model×Asset×horizon×regime 权重；Prediction 记录原始与人工调整值，Outcome 记录到期结果，HumanOverride 采用追加记录。portfolio_models 和 portfolio_snapshots 保存组合规则与权重。

backend/ingest.py 保存原文与证据位置；backend/engine.py 运行 Active Set 或全量模型、生成组合并评估到期预测；backend/metrics.py 计算条件化指标。少于 8 个样本不输出排名分数。当前新闻提取为规则候选，embedding 为字符哈希，模型权重是手工示例。

真实新闻与行情适配位置：backend/providers.py 中的 NewsProvider、MarketProvider 和 Extractor。接入历史数据须区分发布时间、抓取时间、可用时间和修订版本，并明确合约、复权、交易日历、汇率与成交假设。

## 数据充分性与概率（新增）

`GET /api/readiness?asset=Gold&horizon=1W&regime=Neutral&model=linear` 返回三个月回读窗口、缺口、风险和概率可用状态。每次真实运行冻结同样的诊断快照；演示数据不计入门槛。回读起点按公历减三个月，回放只读取决策前可用的信息。

当前最低研究政策：每资产至少20篇相关新闻、15个日期、3个月、3个独立来源，全部证据通过审阅；窗口首尾7天内有信息。同资产×期限×状态×模型版本至少30个非重叠到期样本，且需要可核验的行情、交易日历、复权和成本。这些是保守默认值，不是统计可靠性的证明，周/月期限往往需要远超三个月的校准历史。

**当前版本没有完整行情适配器与经过验证的概率校准器，因此真实组合一律被门槛拦截，建议新增配置保留现金。** `investment_probability=null` 表示不可估计，不是0%。模型原有 probability_up 仅为未校准分数；历史上涨频率及 Wilson 区间仅用于诊断，不能冒充扣费后获利概率。不能据此评价现有持仓应否卖出。

新闻导入可用 `asset_ids` 记录关联资产；人工标注的宏观相关性不等于已证实的因果关系。规则提取仍是待审候选。现已按用户粘贴的晨间简报实现无损栏目与编辑层标注，见 research/briefing_20260927/README.md；原始来源和内容尚未独立核验。后续需接入不可变的审阅记录、真实行情适配器和独立样本外校准产物，才能解锁概率输出；不能仅调低门槛。

本次回读检索窗口为2026-06-21至2026-09-21，收录6月、7月、8月、9月官方摘录及一条原油报道；仍缺逐日行情、公司级新闻与独立验证样本。报告明确输出“证据不足”，不输出虚构投资胜率。
