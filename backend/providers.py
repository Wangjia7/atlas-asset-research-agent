"""Replace these adapters when connecting authorized real data providers.
No web access or credentials are required by the offline MVP.
"""
import hashlib
import math
import re
from typing import Protocol, Iterable


class NewsProvider(Protocol):
    def fetch(self, since: str) -> Iterable[dict]: ...


class MarketProvider(Protocol):
    # Return point-in-time outcomes with asset_id, issued_at, due_at, value,
    # unit, observed_at, source. US10Y uses yield change in basis points.
    def outcomes(self, predictions: list) -> Iterable[dict]: ...


class Extractor(Protocol):
    def extract(self, text: str) -> list: ...


def embedding(text, dimensions=64):
    """Deterministic signed character hash; NOT a semantic embedding model."""
    vector = [0.0] * dimensions
    for token in re.findall(r'\w', text.lower()):
        h = hashlib.sha256(token.encode()).digest()
        vector[int.from_bytes(h[:2], 'big') % dimensions] += 1 if h[2] % 2 else -1
    length = math.sqrt(sum(x*x for x in vector)) or 1
    return [round(x/length, 6) for x in vector]


# Independent Event→Factor hypotheses; never write asset predictions here.
RULES = [
    (r'管道|pipeline', 'oil_supply', .6, ['Energy','Logistics'], '供应恢复可能改善原油可得性'),
    (r'管道|pipeline', 'logistics', .8, ['Energy','Shipping'], '替代运输能力变化'),
    (r'实际利率|real yield', 'real_yield', .6, ['Macro','Rates'], '实际利率状态变化'),
    (r'美元|dollar|DXY', 'usd', .5, ['Macro','FX'], '美元强弱变化'),
    (r'地缘|冲突|geopolit', 'geo', .6, ['Geopolitics','Energy'], '地缘风险溢价假说'),
    (r'流动性|liquidity', 'liquidity', .5, ['Macro','Liquidity'], '融资与风险承受能力变化'),
    (r'算力需求|AI.{0,8}需求|ai demand|数据中心.{0,8}需求', 'ai_demand', .6, ['AI','Capex','Technology'], '算力需求变化'),
    (r'信用利差|credit spread', 'ai_credit', .6, ['Credit','AI','Leverage'], '融资成本变化'),
    (r'消费|consumer', 'consumption', .5, ['Consumer','China'], '消费需求变化'),
    (r'运价|航运|shipping', 'freight', .5, ['Shipping','Energy'], '运价/吨海里需求变化'),
    (r'黄金ETF|黄金 ETF|gold ETF', 'gold_flow', .5, ['Gold','Flows'], '资金流量变化'),
    (r'通胀|inflation', 'inflation', .5, ['Macro','Inflation'], '通胀预期变化'),
]


class RuleExtractor:
    version = 'offline-rules-v1.2'

    def extract(self, text):
        result = []
        # Preserve exact Unicode code-point offsets. Clause splitting is only a
        # candidate atomic segmentation and every candidate requires review.
        for m in re.finditer(r'[^。！？!?；;\n]+[。！？!?；;]?', text):
            sentence = m.group(0)
            trim = len(sentence) - len(sentence.lstrip())
            sentence = sentence.strip()
            if not sentence:
                continue
            start, end = m.start()+trim, m.start()+trim+len(sentence)
            low = sentence.lower()
            conditional = bool(re.search(r'如果|若|一旦|if\b', low))
            possible = bool(re.search(r'可能|预计|预测|预期|may\b|could\b|expect', low))
            proposal = bool(re.search(r'提议|讨论|拟|proposal|proposed|consider', low))
            rumor = bool(re.search(r'传闻|未经证实|未.{0,5}确认|尚无最终|尚不清楚|rumou?r', low))
            mechanism = bool(re.search(r'影响判断|历史类比|导致|从而|意味着|机制|because|→|\\rightarrow', low))
            claim_type = 'validation_condition' if '下一验证点' in sentence else 'forecast' if possible or conditional else 'inference' if mechanism else 'observation'
            status = 'unverified' if rumor else 'proposed' if proposal else 'reported'
            modality = 'conditional' if conditional else 'possible' if possible or proposal or rumor else 'asserted'
            matches, tags = [], set()
            for pattern, factor, value, labels, mechanism_text in RULES:
                if re.search(pattern, low, re.I):
                    unchanged = bool(re.search(r'没有下降|未下降|没有上升|未上升|未变化|保持不变|unchanged|not (?:fall|declin)', low))
                    sign = 0 if unchanged else -1 if re.search(r'下降|减少|收缩|缓解|回落|降温|走弱|fall|declin|eas', low) else 1
                    matches.append(dict(factor_id=factor, impact=sign*value, mechanism=mechanism_text))
                    tags.update(labels)
            result.append(dict(text=sentence, claim_type=claim_type, status=status, modality=modality,
                               tags=sorted(tags), entities=re.findall(r'Gold|Oil|DXY|US10Y|SPX|BTC|AI|美国|中国|欧洲|沙特|招商南油|中科曙光', sentence),
                               geography=[x for x in ['美国','中国','欧洲','沙特'] if x in sentence],
                               sectors=[x for x in ['Energy','Shipping','Consumer','Technology'] if x in tags],
                               evidence_start=start, evidence_end=end, evidence_text=text[start:end],
                               novelty=None, surprise=None, persistence='unknown', horizons=['1W','1M','3M'],
                               confidence=.45 if modality != 'asserted' else .6,
                               scenario=sentence if conditional else None,
                               validation_condition='待人工补充可观测验证条件', semantic_residual=sentence,
                               relations=matches))
        return result
