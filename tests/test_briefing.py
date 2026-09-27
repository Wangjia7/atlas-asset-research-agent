from backend.briefing import annotate, is_briefing
from backend.providers import RuleExtractor


def test_lossless_sections_and_exact_offsets():
    raw='中文晨间深度简报\n一、科技\n1. 示例\n相比前次新增：待核验。影响判断：可能上涨。下一验证点是公告。Reuters\n2. 其他\n历史类比：不等于预测。'
    doc=annotate(raw)
    assert is_briefing(raw)
    assert ''.join(s['raw_text'] for s in doc['sections'])==raw
    for s in doc['sections']:
        assert raw[s['start']:s['end']]==s['raw_text']
        assert s['verification_status']=='needs_primary_source_verification'
        for m in s['markers']: assert raw[m['start']:m['end']]==m['text']
    assert any(s['source_labels']==['Reuters'] and s['source_urls']==[] for s in doc['sections'])


def test_uncertainty_and_validation_not_confirmed():
    claims=RuleExtractor().extract('具体路径尚未被独立确认。下一验证点是最终公告。影响判断：供应增加→价格下降。')
    assert claims[0]['status']=='unverified'
    assert claims[0]['modality']=='possible'
    assert claims[1]['claim_type']=='validation_condition'
    assert claims[2]['claim_type']=='inference'


def test_full_user_briefing_ingestion_preserves_provenance():
    import json
    import sqlite3
    from pathlib import Path
    from backend.ingest import ingest
    root=Path(__file__).resolve().parents[1]
    raw=(root/'research/briefing_20260927/raw.txt').read_text()
    c=sqlite3.connect(':memory:'); c.row_factory=sqlite3.Row
    c.executescript((root/'backend/schema.sql').read_text())
    from backend.weekly_replay import registries
    registries(c,'2026-09-27T00:00:00+00:00')
    result=ingest(c,'用户晨报',raw,publisher='用户提供，原始出处待核验')
    source=c.execute('SELECT * FROM raw_sources').fetchone()
    assert source['raw_text']==raw
    sections=json.loads(source['metadata'])['briefing']['sections']
    assert ''.join(s['raw_text'] for s in sections)==raw
    assert result['claims']>0
    assert all(raw[r['evidence_start']:r['evidence_end']]==r['evidence_text'] for r in c.execute('SELECT * FROM claims'))
    c.close()
