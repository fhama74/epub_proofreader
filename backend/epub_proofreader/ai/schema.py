import json, os
from pathlib import Path
from uuid import uuid4
from ..editing import timestamp

def ensure(con):
    # Kept additive so existing Phase 1–3 libraries remain readable.
    if 'owner_id' not in {r[1] for r in con.execute('PRAGMA table_info(books)')}:
        con.execute("ALTER TABLE books ADD COLUMN owner_id TEXT NOT NULL DEFAULT 'local'")
    con.execute("CREATE TABLE IF NOT EXISTS ai_engines(id TEXT PRIMARY KEY,owner_id TEXT NOT NULL,config TEXT NOT NULL,key_cipher TEXT,created_at TEXT NOT NULL)")
    con.execute("CREATE TABLE IF NOT EXISTS ai_acl(engine_id TEXT NOT NULL,user_id TEXT NOT NULL,PRIMARY KEY(engine_id,user_id))")
    con.execute("CREATE TABLE IF NOT EXISTS ai_jobs(id TEXT PRIMARY KEY,book_id TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,owner_id TEXT NOT NULL,engine_id TEXT NOT NULL,config TEXT NOT NULL,scope TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,finished_at TEXT,request_id TEXT NOT NULL,budget REAL,error TEXT,UNIQUE(book_id,request_id))")
    con.execute("CREATE TABLE IF NOT EXISTS ai_items(job_id TEXT NOT NULL REFERENCES ai_jobs(id) ON DELETE CASCADE,ordinal INTEGER NOT NULL,paragraph_id TEXT NOT NULL,chapter_id TEXT NOT NULL,payload TEXT NOT NULL,status TEXT NOT NULL,error TEXT,PRIMARY KEY(job_id,ordinal))")
    con.execute("CREATE TABLE IF NOT EXISTS ai_results(id TEXT PRIMARY KEY,job_id TEXT NOT NULL REFERENCES ai_jobs(id) ON DELETE CASCADE,book_id TEXT NOT NULL,owner_id TEXT NOT NULL,engine_id TEXT NOT NULL,model_name TEXT NOT NULL,paragraph_id TEXT NOT NULL,chapter_id TEXT NOT NULL,data TEXT NOT NULL,source_hash TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,command_id TEXT,UNIQUE(job_id,paragraph_id,data))")
    con.execute("CREATE TABLE IF NOT EXISTS ai_cleared_results(result_id TEXT PRIMARY KEY REFERENCES ai_results(id) ON DELETE CASCADE)")
    con.execute("CREATE TABLE IF NOT EXISTS ai_decisions(id TEXT PRIMARY KEY,result_id TEXT NOT NULL REFERENCES ai_results(id) ON DELETE CASCADE,owner_id TEXT NOT NULL,action TEXT NOT NULL,created_at TEXT NOT NULL)")
    con.execute("CREATE TABLE IF NOT EXISTS ai_usage(id TEXT PRIMARY KEY,job_id TEXT NOT NULL REFERENCES ai_jobs(id) ON DELETE CASCADE,owner_id TEXT NOT NULL,input_tokens INTEGER,output_tokens INTEGER,cost REAL,created_at TEXT NOT NULL)")
    con.execute("CREATE INDEX IF NOT EXISTS ai_results_book ON ai_results(book_id,created_at)")
    con.execute("CREATE INDEX IF NOT EXISTS ai_items_status ON ai_items(job_id,status,ordinal)")
    con.execute("CREATE TABLE IF NOT EXISTS ai_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
    if not con.execute("SELECT 1 FROM ai_settings WHERE key='initialized'").fetchone():
        cfg=json.loads((Path(__file__).resolve().parents[3]/'config/initial-engines.json').read_text())
        for e in cfg['engines']:
            con.execute('INSERT INTO ai_engines VALUES (?,?,?,?,?)',(str(uuid4()),'local',json.dumps(e),None,timestamp()))
        con.execute("INSERT INTO ai_settings VALUES ('initialized','1')")
