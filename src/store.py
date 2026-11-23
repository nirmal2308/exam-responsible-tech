"""Role-controlled marks store (SQLite) with versioned records, workflow states,
three audit-log variants for comparison, a hash-chained audit trail, privacy-preserving
redaction and a retry-safe outbox for the external credential-verification service.
"""
import hashlib, json, os, sqlite3, time, secrets
from .rubric_engine import grade_band

GENESIS = "0" * 64

PERMS = {
    "examiner":        {"submit_marks", "view_assigned"},
    "moderator":       {"moderate", "revalue", "view_assigned"},
    "controller":      {"approve", "publish", "view_all", "redact", "approve_correction", "create_record"},
    "administrator":   {"manage_users", "view_all", "create_record"},  # deliberately NO mark-decision permissions
    "student":         {"view_own", "request_revaluation"},
    "department_head": {"view_dept_report"},
    "external_verifier": {"verify_credential"},
}
ACTIONS = ["create_record", "submit_marks", "moderate", "revalue", "approve", "publish", "redact",
           "request_revaluation", "view_all", "manage_users", "verify_credential"]


class Denied(Exception): pass
class Invalid(Exception): pass
class ServiceDown(Exception): pass
class TimeoutAfterProcessing(Exception): pass


def _h(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


class Store:
    def __init__(self, path=":memory:"):
        self.path = path
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self._init()

    # ------------------------------------------------------------------ schema
    def _init(self):
        c = self.db
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(user TEXT PRIMARY KEY, role TEXT NOT NULL, dept TEXT);
        CREATE TABLE IF NOT EXISTS marks(record_id TEXT PRIMARY KEY, student_ref TEXT, exam TEXT,
            dept TEXT, max_mark REAL, mark REAL, grade TEXT, status TEXT, version INTEGER,
            suggestion REAL, examiner TEXT, moderator TEXT, approver TEXT);
        CREATE TABLE IF NOT EXISTS mark_versions(record_id TEXT, version INTEGER, mark REAL,
            grade TEXT, status TEXT, actor TEXT, reason TEXT, ts REAL);
        CREATE TABLE IF NOT EXISTS audit_plain(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL,
            actor TEXT, action TEXT, entity TEXT, detail TEXT);
        CREATE TABLE IF NOT EXISTS audit_trig(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL,
            actor TEXT, action TEXT, entity TEXT, detail TEXT);
        CREATE TRIGGER IF NOT EXISTS audit_trig_no_update BEFORE UPDATE ON audit_trig
            BEGIN SELECT RAISE(ABORT, 'audit_trig is append-only'); END;
        CREATE TRIGGER IF NOT EXISTS audit_trig_no_delete BEFORE DELETE ON audit_trig
            BEGIN SELECT RAISE(ABORT, 'audit_trig is append-only'); END;
        CREATE TABLE IF NOT EXISTS audit_chain(seq INTEGER PRIMARY KEY, ts REAL, actor TEXT,
            action TEXT, entity TEXT, payload_hash TEXT, prev_hash TEXT, entry_hash TEXT);
        CREATE TABLE IF NOT EXISTS audit_payload(seq INTEGER PRIMARY KEY, salt TEXT, payload TEXT);
        CREATE TABLE IF NOT EXISTS outbox(id INTEGER PRIMARY KEY AUTOINCREMENT, idem_key TEXT UNIQUE,
            payload TEXT, status TEXT, attempts INTEGER DEFAULT 0, last_error TEXT);
        """)
        c.commit()

    # ------------------------------------------------------------------ audit
    def audit(self, actor, action, entity, detail):
        ts = time.time()
        d = json.dumps(detail, sort_keys=True)
        c = self.db
        c.execute("INSERT INTO audit_plain(ts,actor,action,entity,detail) VALUES (?,?,?,?,?)", (ts, actor, action, entity, d))
        c.execute("INSERT INTO audit_trig(ts,actor,action,entity,detail) VALUES (?,?,?,?,?)", (ts, actor, action, entity, d))
        row = c.execute("SELECT seq, entry_hash FROM audit_chain ORDER BY seq DESC LIMIT 1").fetchone()
        seq, prev = (row["seq"] + 1, row["entry_hash"]) if row else (1, GENESIS)
        salt = secrets.token_hex(8)
        payload_hash = _h(salt + d)
        entry_hash = _h("|".join([str(seq), repr(ts), actor, action, entity, payload_hash, prev]))
        c.execute("INSERT INTO audit_chain VALUES (?,?,?,?,?,?,?,?)", (seq, ts, actor, action, entity, payload_hash, prev, entry_hash))
        c.execute("INSERT INTO audit_payload VALUES (?,?,?)", (seq, salt, d))
        c.commit()
        return seq

    def verify_chain(self, anchor=None):
        rows = self.db.execute("SELECT * FROM audit_chain ORDER BY seq").fetchall()
        pay = {r["seq"]: r for r in self.db.execute("SELECT * FROM audit_payload")}
        prev = GENESIS
        for i, r in enumerate(rows, start=1):
            if r["seq"] != i:
                return False, f"sequence gap or reorder at position {i} (seq {r['seq']})"
            if r["prev_hash"] != prev:
                return False, f"broken link at seq {r['seq']}"
            expect = _h("|".join([str(r["seq"]), repr(r["ts"]), r["actor"], r["action"], r["entity"], r["payload_hash"], r["prev_hash"]]))
            if expect != r["entry_hash"]:
                return False, f"entry hash mismatch at seq {r['seq']}"
            p = pay.get(r["seq"])
            if p is not None and p["payload"] is not None and _h(p["salt"] + p["payload"]) != r["payload_hash"]:
                return False, f"payload altered at seq {r['seq']}"
            prev = r["entry_hash"]
        if anchor:
            if len(rows) < anchor["seq"]:
                return False, f"truncation: chain has {len(rows)} entries, anchor expects {anchor['seq']}"
            if rows[anchor["seq"] - 1]["entry_hash"] != anchor["hash"]:
                return False, "anchor hash mismatch"
        return True, "chain intact"

    def head_anchor(self):
        r = self.db.execute("SELECT seq, entry_hash FROM audit_chain ORDER BY seq DESC LIMIT 1").fetchone()
        return {"seq": r["seq"], "hash": r["entry_hash"]} if r else {"seq": 0, "hash": GENESIS}

    def redact(self, actor, seq, reason):
        self._need(actor, "redact")
        if not reason:
            raise Invalid("redaction requires a recorded reason")
        self.db.execute("UPDATE audit_payload SET payload=NULL, salt=NULL WHERE seq=?", (seq,))
        self.db.commit()
        return self.audit(actor, "REDACT_PAYLOAD", f"audit#{seq}", {"reason": reason})

    # ------------------------------------------------------------------ users / permissions
    def add_user(self, user, role, dept=None):
        self.db.execute("INSERT OR REPLACE INTO users VALUES (?,?,?)", (user, role, dept)); self.db.commit()

    def role_of(self, user):
        r = self.db.execute("SELECT role FROM users WHERE user=?", (user,)).fetchone()
        if not r:
            raise Denied(f"unknown user {user}")
        return r["role"]

    def _need(self, actor, action):
        role = self.role_of(actor)
        if action not in PERMS.get(role, set()):
            self.audit(actor, "DENIED", action, {"role": role})
            raise Denied(f"{actor} ({role}) may not {action}")

    # ------------------------------------------------------------------ marks workflow
    def _validate_mark(self, mark, max_mark):
        if isinstance(mark, bool) or not isinstance(mark, (int, float)):
            raise Invalid("mark must be numeric")
        if mark < 0 or mark > max_mark:
            raise Invalid(f"mark {mark} outside 0..{max_mark}")
        if (mark * 2) != int(mark * 2):
            raise Invalid("marks are awarded in steps of 0.5")

    def _version(self, rid, mark, status, actor, reason):
        r = self.db.execute("SELECT version, max_mark FROM marks WHERE record_id=?", (rid,)).fetchone()
        v = r["version"]
        self.db.execute("INSERT INTO mark_versions VALUES (?,?,?,?,?,?,?,?)",
                        (rid, v, mark, grade_band(mark, r["max_mark"]), status, actor, reason, time.time()))

    def create_record(self, actor, rid, student_ref, exam, dept, max_mark=5):
        self._need(actor, "create_record")
        self.db.execute("INSERT INTO marks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (rid, student_ref, exam, dept, max_mark, None, None, "DRAFT", 1, None, None, None, None))
        self.db.commit()
        self.audit(actor, "CREATE_RECORD", rid, {"exam": exam})

    def get(self, rid):
        return dict(self.db.execute("SELECT * FROM marks WHERE record_id=?", (rid,)).fetchone())

    def submit_mark(self, actor, rid, mark, suggestion=None, reason=None):
        self._need(actor, "submit_marks")
        rec = self.get(rid)
        if rec["status"] != "DRAFT":
            raise Invalid(f"cannot submit marks in status {rec['status']}")
        self._validate_mark(mark, rec["max_mark"])
        if suggestion is not None and mark != suggestion and not reason:
            raise Invalid("overriding a suggestion requires a recorded reason")
        self.db.execute("UPDATE marks SET mark=?, grade=?, status='EVALUATED', suggestion=?, examiner=? WHERE record_id=?",
                        (mark, grade_band(mark, rec["max_mark"]), suggestion, actor, rid))
        self._version(rid, mark, "EVALUATED", actor, reason)
        self.db.commit()
        self.audit(actor, "SUBMIT_MARK", rid, {"mark": mark, "suggestion": suggestion, "override_reason": reason})

    def moderate(self, actor, rid, new_mark=None, reason=None):
        self._need(actor, "moderate")
        rec = self.get(rid)
        if rec["status"] not in ("EVALUATED", "REVAL_REQUESTED"):
            raise Invalid(f"cannot moderate in status {rec['status']}")
        if actor == rec["examiner"]:
            self.audit(actor, "DENIED", "moderate_own_mark", {"record": rid})
            raise Denied("separation of duties: examiner cannot moderate own evaluation")
        mark = rec["mark"] if new_mark is None else new_mark
        self._validate_mark(mark, rec["max_mark"])
        if mark != rec["mark"] and not reason:
            raise Invalid("changing a mark during moderation requires a reason")
        nxt = "MODERATED"
        self.db.execute("UPDATE marks SET mark=?, grade=?, status=?, moderator=?, version=version+1 WHERE record_id=?",
                        (mark, grade_band(mark, rec["max_mark"]), nxt, actor, rid))
        self._version(rid, mark, nxt, actor, reason)
        self.db.commit()
        self.audit(actor, "MODERATE", rid, {"from": rec["mark"], "to": mark, "reason": reason})

    def approve(self, actor, rid):
        self._need(actor, "approve")
        rec = self.get(rid)
        if rec["status"] != "MODERATED":
            raise Invalid(f"cannot approve in status {rec['status']}")
        if actor in (rec["examiner"], rec["moderator"]):
            raise Denied("separation of duties: approver must differ from examiner and moderator")
        self.db.execute("UPDATE marks SET status='APPROVED', approver=?, version=version+1 WHERE record_id=?", (actor, rid))
        self._version(rid, rec["mark"], "APPROVED", actor, None)
        self.db.commit()
        self.audit(actor, "APPROVE", rid, {"mark": rec["mark"]})

    def publish(self, actor, rid):
        self._need(actor, "publish")
        rec = self.get(rid)
        if rec["status"] != "APPROVED":
            self.audit(actor, "DENIED", "publish_unapproved", {"record": rid, "status": rec["status"]})
            raise Invalid(f"cannot publish in status {rec['status']}")
        self.db.execute("UPDATE marks SET status='PUBLISHED', version=version+1 WHERE record_id=?", (rid,))
        self._version(rid, rec["mark"], "PUBLISHED", actor, None)
        self.db.commit()
        self.audit(actor, "PUBLISH", rid, {"mark": rec["mark"], "grade": rec["grade"]})

    def request_revaluation(self, actor, rid, reason):
        self._need(actor, "request_revaluation")
        rec = self.get(rid)
        if rec["student_ref"] != actor:
            self.audit(actor, "DENIED", "revaluation_not_own_record", {"record": rid})
            raise Denied("students may challenge only their own record")
        if rec["status"] != "PUBLISHED":
            raise Invalid("only published results can be challenged")
        self.db.execute("UPDATE marks SET status='REVAL_REQUESTED', version=version+1 WHERE record_id=?", (rid,))
        self._version(rid, rec["mark"], "REVAL_REQUESTED", actor, reason)
        self.db.commit()
        self.audit(actor, "REQUEST_REVALUATION", rid, {"reason": reason})

    # ------------------------------------------------------------------ outbox (retry-safe integration)
    def enqueue(self, key, payload):
        try:
            self.db.execute("INSERT INTO outbox(idem_key,payload,status) VALUES (?,?,'PENDING')", (key, json.dumps(payload)))
            self.db.commit()
        except sqlite3.IntegrityError:
            pass  # idempotent: same key is never queued twice

    def flush_outbox(self, send, max_attempts=6):
        sent = 0
        for r in self.db.execute("SELECT * FROM outbox WHERE status='PENDING'").fetchall():
            try:
                send(r["idem_key"], json.loads(r["payload"]))
                self.db.execute("UPDATE outbox SET status='SENT', attempts=attempts+1 WHERE id=?", (r["id"],)); sent += 1
            except (ServiceDown, TimeoutAfterProcessing) as e:
                st = "FAILED" if r["attempts"] + 1 >= max_attempts else "PENDING"
                self.db.execute("UPDATE outbox SET attempts=attempts+1, status=?, last_error=? WHERE id=?", (st, type(e).__name__, r["id"]))
        self.db.commit()
        return sent

    def close(self):
        self.db.close()
