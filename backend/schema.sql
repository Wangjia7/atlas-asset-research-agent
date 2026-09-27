PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS raw_sources(
 id INTEGER PRIMARY KEY, title TEXT NOT NULL, publisher TEXT NOT NULL, url TEXT,
 published_at TEXT NOT NULL, known_at TEXT NOT NULL, raw_text TEXT NOT NULL,
 content_hash TEXT NOT NULL, embedding TEXT NOT NULL, embedding_model TEXT NOT NULL,
 metadata TEXT NOT NULL, is_demo INTEGER NOT NULL DEFAULT 0, UNIQUE(content_hash,is_demo)
);
CREATE TABLE IF NOT EXISTS claims(
 id INTEGER PRIMARY KEY, source_id INTEGER NOT NULL REFERENCES raw_sources(id), text TEXT NOT NULL,
 claim_type TEXT NOT NULL, status TEXT NOT NULL, modality TEXT NOT NULL,
 tags TEXT NOT NULL, entities TEXT NOT NULL, geography TEXT NOT NULL, sectors TEXT NOT NULL,
 novelty REAL NOT NULL, surprise REAL, persistence TEXT NOT NULL, horizons TEXT NOT NULL,
 confidence REAL NOT NULL, evidence_start INTEGER NOT NULL, evidence_end INTEGER NOT NULL,
 evidence_text TEXT NOT NULL, scenario TEXT, validation_condition TEXT, semantic_residual TEXT NOT NULL,
 embedding TEXT NOT NULL, extractor_version TEXT NOT NULL, review_status TEXT NOT NULL,
 CHECK(evidence_start>=0 AND evidence_end>evidence_start), CHECK(confidence BETWEEN 0 AND 1)
);
CREATE TABLE IF NOT EXISTS events(
 id INTEGER PRIMARY KEY, source_id INTEGER NOT NULL REFERENCES raw_sources(id), title TEXT NOT NULL,
 occurred_at TEXT NOT NULL, known_at TEXT NOT NULL, tags TEXT NOT NULL, entities TEXT NOT NULL,
 event_cluster TEXT NOT NULL, actions TEXT NOT NULL, objects TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS event_claims(event_id INTEGER REFERENCES events(id),claim_id INTEGER REFERENCES claims(id),PRIMARY KEY(event_id,claim_id));
CREATE TABLE IF NOT EXISTS factors(
 id TEXT PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('core','experimental','dormant')),
 description TEXT NOT NULL, transform TEXT NOT NULL, lag_days INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS assets(id TEXT PRIMARY KEY,name TEXT NOT NULL,asset_class TEXT NOT NULL,currency TEXT NOT NULL,target_unit TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS models(
 id TEXT PRIMARY KEY,name TEXT NOT NULL,version TEXT NOT NULL,family TEXT NOT NULL,
 role TEXT NOT NULL CHECK(role IN ('Champion','Challenger','Benchmark','Exploration','Dormant')),
 config TEXT NOT NULL,created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS event_factor(
 id INTEGER PRIMARY KEY,event_id INTEGER NOT NULL REFERENCES events(id),claim_id INTEGER NOT NULL REFERENCES claims(id),
 factor_id TEXT NOT NULL REFERENCES factors(id),horizon TEXT NOT NULL,regime TEXT NOT NULL,
 region TEXT NOT NULL,impact REAL NOT NULL,confidence REAL NOT NULL,mechanism TEXT NOT NULL,
 version TEXT NOT NULL,known_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS factor_asset(
 id INTEGER PRIMARY KEY,model_id TEXT NOT NULL REFERENCES models(id),model_version TEXT NOT NULL,
 factor_id TEXT NOT NULL REFERENCES factors(id),asset_id TEXT NOT NULL REFERENCES assets(id),
 horizon TEXT NOT NULL,regime TEXT NOT NULL,weight REAL NOT NULL,known_at TEXT NOT NULL,
 UNIQUE(model_id,model_version,factor_id,asset_id,horizon,regime)
);
CREATE TABLE IF NOT EXISTS human_overrides(
 id INTEGER PRIMARY KEY,factor_id TEXT NOT NULL REFERENCES factors(id),asset_id TEXT REFERENCES assets(id),
 multiplier REAL NOT NULL CHECK(multiplier BETWEEN 0 AND 3),reason TEXT NOT NULL,
 created_at TEXT NOT NULL,expires_at TEXT,revokes_id INTEGER REFERENCES human_overrides(id)
);
CREATE TABLE IF NOT EXISTS runs(
 id INTEGER PRIMARY KEY,created_at TEXT NOT NULL,mode TEXT NOT NULL,regime TEXT NOT NULL,
 snapshot TEXT NOT NULL,changes TEXT NOT NULL,is_demo INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS predictions(
 id INTEGER PRIMARY KEY,run_id INTEGER NOT NULL REFERENCES runs(id),model_id TEXT NOT NULL REFERENCES models(id),
 model_version TEXT NOT NULL,asset_id TEXT NOT NULL REFERENCES assets(id),horizon TEXT NOT NULL,regime TEXT NOT NULL,
 issued_at TEXT NOT NULL,due_at TEXT NOT NULL,original REAL NOT NULL,adjusted REAL NOT NULL,
 probability_up REAL NOT NULL,adjusted_probability_up REAL NOT NULL,contributions TEXT NOT NULL,
 UNIQUE(run_id,model_id,asset_id,horizon,regime)
);
CREATE TABLE IF NOT EXISTS outcomes(
 id INTEGER PRIMARY KEY,asset_id TEXT NOT NULL REFERENCES assets(id),issued_at TEXT NOT NULL,due_at TEXT NOT NULL,
 value REAL NOT NULL,unit TEXT NOT NULL,observed_at TEXT NOT NULL,source TEXT NOT NULL,is_demo INTEGER NOT NULL,
 UNIQUE(asset_id,issued_at,due_at)
);
CREATE TABLE IF NOT EXISTS evaluations(
 id INTEGER PRIMARY KEY,evaluated_at TEXT NOT NULL,asset_id TEXT NOT NULL REFERENCES assets(id),horizon TEXT NOT NULL,
 regime TEXT NOT NULL,model_id TEXT NOT NULL REFERENCES models(id),model_version TEXT NOT NULL,
 cohort TEXT NOT NULL,metrics TEXT NOT NULL,score REAL,role TEXT NOT NULL,sample_count INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS portfolio_models(id TEXT PRIMARY KEY,name TEXT NOT NULL,method TEXT NOT NULL,config TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS portfolio_snapshots(id INTEGER PRIMARY KEY,run_id INTEGER REFERENCES runs(id),portfolio_model_id TEXT REFERENCES portfolio_models(id),weights TEXT NOT NULL,details TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS prediction_slice ON predictions(asset_id,horizon,regime,issued_at);
CREATE INDEX IF NOT EXISTS evaluation_slice ON evaluations(asset_id,horizon,regime,evaluated_at);
CREATE INDEX IF NOT EXISTS event_factor_slice ON event_factor(horizon,regime,known_at);
