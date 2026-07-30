"""SQLite 存储层：单文件 DB + 全局写锁（FastAPI 线程池并发安全）。
本版新增：users/sessions（多用户与数据隔离）、settings（自动抓取与集成配置）、
r_papers.fulltext / r_evidence.location·reviewer（全文证据定位与核验人）、events.user。
旧库自动迁移（ALTER TABLE 幂等执行）。"""
import sqlite3, json, os, time, threading
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "studio.db"

_conn, _lock = None, threading.RLock()

def conn():
    global _conn
    with _lock:
        if _conn is None:
            _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
            _conn.row_factory = sqlite3.Row
            _conn.execute("PRAGMA journal_mode=WAL")
            _conn.executescript(SCHEMA)
            _migrate(_conn)
            _conn.commit()
        return _conn

SCHEMA = """
-- ============ 共同：用户 / 会话 / 设置 / 操作留痕 ============
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, username TEXT UNIQUE, pw_hash TEXT, salt TEXT, created_at REAL
);
CREATE TABLE IF NOT EXISTS sessions(
  token TEXT PRIMARY KEY, user_id INTEGER, created_at REAL
);
CREATE TABLE IF NOT EXISTS settings(          -- key 形如 mkt_schedule:{user_id}
  key TEXT PRIMARY KEY, value TEXT
);
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY, module TEXT, action TEXT, detail TEXT, user TEXT DEFAULT '', ts REAL
);

-- ============ 任务一：游戏营销热点工作流 ============
CREATE TABLE IF NOT EXISTS hotspots(
  id INTEGER PRIMARY KEY, owner_id INTEGER DEFAULT 0, source TEXT, title TEXT, url TEXT,
  published_at TEXT, fetched_at TEXT, game TEXT, extra TEXT,
  UNIQUE(owner_id, url)
);
CREATE TABLE IF NOT EXISTS topics(
  id INTEGER PRIMARY KEY, owner_id INTEGER DEFAULT 0, title TEXT, summary TEXT, hotspot_ids TEXT,
  game TEXT, status TEXT DEFAULT 'candidate',  -- candidate/confirmed/rejected
  match_json TEXT, created_at REAL
);
CREATE TABLE IF NOT EXISTS briefs(
  id INTEGER PRIMARY KEY, owner_id INTEGER DEFAULT 0, topic_id INTEGER, game TEXT, platform TEXT,
  audience TEXT, goal TEXT, constraints TEXT, created_at REAL
);
CREATE TABLE IF NOT EXISTS scripts(
  id INTEGER PRIMARY KEY, brief_id INTEGER, version INTEGER, parent_id INTEGER,
  content_json TEXT, eval_json TEXT,
  status TEXT DEFAULT 'draft',  -- draft/evaluated/confirmed
  created_at REAL
);

-- ============ 任务二：AI 漫剧工作流 ============
CREATE TABLE IF NOT EXISTS d_projects(
  id INTEGER PRIMARY KEY, owner_id INTEGER DEFAULT 0, title TEXT, lang TEXT, spec_json TEXT,
  status TEXT DEFAULT 'active', created_at REAL
);
CREATE TABLE IF NOT EXISTS d_scripts(
  id INTEGER PRIMARY KEY, project_id INTEGER, version INTEGER,
  raw_text TEXT, struct_json TEXT, status TEXT DEFAULT 'draft', created_at REAL
);
CREATE TABLE IF NOT EXISTS d_assets(
  id INTEGER PRIMARY KEY, project_id INTEGER, kind TEXT, name TEXT,
  version INTEGER DEFAULT 1, prompt TEXT, params TEXT, image_path TEXT,
  status TEXT DEFAULT 'draft',  -- draft/locked
  notes TEXT, created_at REAL
);
CREATE TABLE IF NOT EXISTS d_shots(
  id INTEGER PRIMARY KEY, project_id INTEGER, seq INTEGER, scene TEXT,
  shot_json TEXT, asset_ids TEXT, status TEXT DEFAULT 'draft',  -- draft/confirmed/discarded
  created_at REAL
);
CREATE TABLE IF NOT EXISTS d_tasks(
  id INTEGER PRIMARY KEY, shot_id INTEGER, kind TEXT,  -- keyframe/video
  version INTEGER DEFAULT 1, parent_id INTEGER,
  prompt TEXT, params TEXT, mode TEXT DEFAULT 'external',  -- external/comfyui/simulated
  status TEXT DEFAULT 'pending',  -- pending/submitted/generated/failed/adopted/discarded
  result_path TEXT, fail_reason TEXT, eval_json TEXT, created_at REAL
);

-- ============ 任务三：AI 科研协作平台 ============
CREATE TABLE IF NOT EXISTS r_tasks(
  id INTEGER PRIMARY KEY, owner_id INTEGER DEFAULT 0, question TEXT, scope_json TEXT,
  stage TEXT DEFAULT 'setup', created_at REAL
);
CREATE TABLE IF NOT EXISTS r_papers(
  id INTEGER PRIMARY KEY, task_id INTEGER, source TEXT, ext_id TEXT,
  title TEXT, authors TEXT, year TEXT, abstract TEXT, fulltext TEXT DEFAULT '', url TEXT,
  relevance_json TEXT, status TEXT DEFAULT 'candidate',  -- candidate/included/excluded
  created_at REAL, UNIQUE(task_id, url)
);
CREATE TABLE IF NOT EXISTS r_evidence(
  id INTEGER PRIMARY KEY, task_id INTEGER, paper_id INTEGER,
  claim TEXT, quote TEXT, note TEXT, location TEXT DEFAULT '',   -- 命中位置：abstract / fulltext 第N段
  reviewer TEXT DEFAULT '', reviewed_at REAL,
  status TEXT DEFAULT 'proposed',  -- proposed/approved/rejected
  created_at REAL
);
CREATE TABLE IF NOT EXISTS r_synth(
  id INTEGER PRIMARY KEY, task_id INTEGER, version INTEGER,
  content_md TEXT, status TEXT DEFAULT 'draft',  -- draft/approved
  created_at REAL
);
"""

# 旧库迁移：给早期版本补列（列已存在时 sqlite 抛错，忽略即可）
_MIGRATIONS = [
    "ALTER TABLE events ADD COLUMN user TEXT DEFAULT ''",
    "ALTER TABLE hotspots ADD COLUMN owner_id INTEGER DEFAULT 0",
    "ALTER TABLE topics ADD COLUMN owner_id INTEGER DEFAULT 0",
    "ALTER TABLE briefs ADD COLUMN owner_id INTEGER DEFAULT 0",
    "ALTER TABLE d_projects ADD COLUMN owner_id INTEGER DEFAULT 0",
    "ALTER TABLE r_tasks ADD COLUMN owner_id INTEGER DEFAULT 0",
    "ALTER TABLE r_papers ADD COLUMN fulltext TEXT DEFAULT ''",
    "ALTER TABLE r_evidence ADD COLUMN location TEXT DEFAULT ''",
    "ALTER TABLE r_evidence ADD COLUMN reviewer TEXT DEFAULT ''",
    "ALTER TABLE r_evidence ADD COLUMN reviewed_at REAL",
]

def _migrate(c):
    for sql in _MIGRATIONS:
        try:
            c.execute(sql)
        except sqlite3.OperationalError:
            pass

# ---------------- 通用访问（全部串行化，线程安全） ----------------

def log(module, action, detail="", user=""):
    with _lock:
        c = conn()
        c.execute("INSERT INTO events(module,action,detail,user,ts) VALUES(?,?,?,?,?)",
                  (module, action, detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False),
                   user, time.time()))
        c.commit()

def rows(sql, args=()):
    with _lock:
        return [dict(r) for r in conn().execute(sql, args).fetchall()]

def one(sql, args=()):
    with _lock:
        r = conn().execute(sql, args).fetchone()
        return dict(r) if r else None

def run(sql, args=()):
    """执行写语句，返回 lastrowid。"""
    with _lock:
        c = conn()
        cur = c.execute(sql, args)
        c.commit()
        return cur.lastrowid

def insert_ignore(sql, args=()):
    """INSERT OR IGNORE，返回是否真正插入（用于准确统计新增数，修复旧版计数虚高）。"""
    with _lock:
        c = conn()
        cur = c.execute(sql, args)
        c.commit()
        return cur.rowcount > 0

# ---------------- settings ----------------

def setting_get(key, default=None):
    r = one("SELECT value FROM settings WHERE key=?", (key,))
    return json.loads(r["value"]) if r else default

def setting_set(key, value):
    run("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, json.dumps(value, ensure_ascii=False)))
