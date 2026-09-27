import hashlib
import json
from .db import dump, insert, now, rows
from .providers import RuleExtractor, embedding


def ingest(conn, title, raw_text, publisher='Manual', url='', published_at=None, is_demo=False, known_at=None, asset_ids=None):
    known = known_at or now()
    published = published_at or known
    digest = hashlib.sha256(raw_text.encode('utf-8')).hexdigest()
    existing = conn.execute('SELECT id FROM raw_sources WHERE content_hash=? AND is_demo=?', (digest,int(is_demo))).fetchone()
    if existing:
        return {'source_id': existing['id'], 'duplicate': True, 'claims': 0}
    source_id = insert(conn, 'raw_sources', title=title, publisher=publisher, url=url,
                       published_at=published, known_at=known, raw_text=raw_text, content_hash=digest,
                       embedding=dump(embedding(raw_text)), embedding_model='char-hash-64-v1 (non-semantic)',
                       metadata=dump({'asset_ids':asset_ids or [],'encoding':'unicode','extraction':'offline candidate claims','surprise_basis':None}), is_demo=int(is_demo))
    previous = {r['text'] for r in rows(conn, 'SELECT c.text FROM claims c JOIN raw_sources s ON s.id=c.source_id WHERE s.is_demo=?', (int(is_demo),))}
    candidates = RuleExtractor().extract(raw_text)
    for claim in candidates:
        relations = claim.pop('relations')
        assert raw_text[claim['evidence_start']:claim['evidence_end']] == claim['evidence_text']
        claim['novelty'] = 0.0 if claim['text'] in previous else 1.0
        for key in ['tags','entities','geography','sectors','horizons']:
            claim[key] = dump(claim[key])
        claim_id = insert(conn, 'claims', source_id=source_id, **claim,
                          embedding=dump(embedding(claim['text'])), extractor_version=RuleExtractor.version,
                          review_status='needs_review')
        event_id = insert(conn, 'events', source_id=source_id, title=claim['text'][:100], occurred_at=published,
                          known_at=known, tags=claim['tags'], entities=claim['entities'], event_cluster=dump([title]),
                          actions=dump(['unresolved']), objects=claim['entities'])
        insert(conn, 'event_claims', event_id=event_id, claim_id=claim_id)
        # Polarity and relation magnitude are demo hypotheses, not established causality.
        # Uncertain language is explicitly retained and downweighted.
        discount = .35 if claim['modality'] != 'asserted' else 1
        for relation in relations:
            for horizon in json.loads(claim['horizons']):
                insert(conn, 'event_factor', event_id=event_id, claim_id=claim_id, factor_id=relation['factor_id'],
                       horizon=horizon, regime='all', region=claim['geography'], impact=relation['impact']*discount,
                       confidence=claim['confidence'], mechanism=relation['mechanism'],
                       version=RuleExtractor.version, known_at=known)
    return {'source_id':source_id, 'duplicate':False, 'claims':len(candidates)}
