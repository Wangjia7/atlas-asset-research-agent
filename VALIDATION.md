# 验证记录

验证日期：2026-09-27。Python 3.9.6 / FastAPI 0.128.8 / SQLite / macOS。

## 自动化

命令：`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q`

结果：**14 passed in 4.03s**。

覆盖原文无损、Unicode 证据偏移、幂等与数据集隔离、不可覆盖账本、独立关系矩阵、Active/Full 集合、原始权重与人工倍率分离、撤销与到期、point-in-time、Outcome 到期校验和配对、指标手算、因子状态快照、组合预算、输入和同源校验、否定与 AI 信用语义区分、关系版本时点选择。

JavaScript：`node --check static/app.js` 通过。

## 浏览器

本地服务在 `http://127.0.0.1:8765` 成功启动。

- Dashboard：资产计数、预测、组合与运行信息显示。
- Matrix：Factor→Asset 热力表显示；点击 -0.850 单元格能展开模型版本和原始权重。
- News/Event：原文与候选 Claim、状态/模态/标签、独立关系显示；点击 `[35,51)` 高亮「如果限制实施，欧洲供应可能减少。」。
- Factor Arena：12 个因子及 core/experimental/dormant 状态显示。
- Leaderboard：Gold×1M×Neutral 的5个模型、样本数和指标显示。
- Prediction Ledger、What Changed、Human Override：页面及相应主表/表单完成加载。
- 后台页面检查未捕获浏览器 error 日志。

本次验证覆盖本地合成数据流程。没有验证外部新闻/行情 API、语义模型精度或真实投资预测效果。
