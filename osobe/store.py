"""osobe.db: wallets grouped into "osobe" (persons), their profiles, the probable links to tracked X accounts and the
group call power (27.11., vlasnik: "Grupiraj novčanike u osobe, prikaži profil osobe, daj svakoj izmišljeno ime ...
pokušaj korelacije s Twitter profilima: vjerojatnost čiji bi to novčanik mogao biti"; i bundleovi, grupe
influencera koje zovu isti token i koliko to mijenja cijenu).

Own file, one writer (run_osobe.py noc, the night job of run_sched.py): every other module only reads. Under
DATA_DIR when it is set (the persistent disk, like insajderi.db), so start.sh needs no new link.

Tables:
  os_links    one row per wallet pair with a link: confidence and the evidence list (JSON)
  os_persons  one row per person: members, confidence, nickname, the profile (JSON)
  os_member   wallet -> person
  os_names    the nickname given to a person id the first time (kept, so a name never changes between nights)
  os_xlinks   person x tracked X account: probability and the evidence (owner-only view, see osobe/xveza.py)
  os_hidden   links the owner hid (never shown again, whatever a later night computes)
  os_kv       the group call power result, the last pass summary
"""
import json
import os
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SCHEMA = """
CREATE TABLE IF NOT EXISTS os_links (a TEXT, b TEXT, conf REAL, kinds TEXT, evidence TEXT, updated INTEGER,
    PRIMARY KEY (a, b));
CREATE TABLE IF NOT EXISTS os_persons (pid TEXT PRIMARY KEY, members TEXT, n_wallets INTEGER, conf REAL, nickname TEXT,
    traits TEXT, profile TEXT, pnl_sol REAL, first_ts INTEGER, last_ts INTEGER, updated INTEGER);
CREATE TABLE IF NOT EXISTS os_member (wallet TEXT PRIMARY KEY, pid TEXT, conf REAL);
CREATE INDEX IF NOT EXISTS os_member_pid ON os_member (pid);
CREATE TABLE IF NOT EXISTS os_names (pid TEXT PRIMARY KEY, name TEXT UNIQUE, ts INTEGER);
CREATE TABLE IF NOT EXISTS os_xlinks (pid TEXT, handle TEXT, prob REAL, evidence TEXT, updated INTEGER,
    PRIMARY KEY (pid, handle));
CREATE TABLE IF NOT EXISTS os_hidden (pid TEXT, handle TEXT, who TEXT, ts INTEGER, PRIMARY KEY (pid, handle));
CREATE TABLE IF NOT EXISTS os_kv (key TEXT PRIMARY KEY, value TEXT);
"""


def db_path():
    if os.environ.get("OSOBE_DB"):
        return os.environ["OSOBE_DB"]
    data = os.environ.get("DATA_DIR")
    if data and os.path.isdir(data):
        return os.path.join(data, "osobe.db")
    return os.path.join(ROOT, "osobe.db")


def connect(path=None):
    con = sqlite3.connect(path or db_path(), timeout=60)
    con.executescript(SCHEMA)
    return con


def ro(path):
    """Read-only handle, None when the file is missing or empty (another module's database we only read)."""
    if not path or not os.path.exists(path) or not os.path.getsize(path):
        return None
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error:
        return None


def q(con, sql, args=()):
    """Rows, or [] when the connection is None or the table is missing (an older database)."""
    if con is None:
        return []
    try:
        return con.execute(sql, args).fetchall()
    except sqlite3.Error:
        return []


def kv(con, key, value=None):
    if value is None:
        r = q(con, "SELECT value FROM os_kv WHERE key = ?", (key,))
        try:
            return json.loads(r[0][0]) if r else None
        except (ValueError, TypeError):
            return None
    con.execute("INSERT OR REPLACE INTO os_kv VALUES (?, ?)", (key, json.dumps(value, ensure_ascii=False)))
    return value


def paths(**over):
    """Every database read here, by the owning modules' own rules (insajderi/store.paths) + osobe.db."""
    try:
        from insajderi import store as istore
        p = istore.paths()
    except Exception:  # noqa: BLE001 - a module that cannot be imported: only what we can name ourselves
        p = {}
    p["osobe_db"] = db_path()
    p.update({k: v for k, v in over.items() if v is not None})
    return p
