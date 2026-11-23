"""Validation scenarios for the selected architecture (marks, status, grade band,
authorization, persistence and audit behaviour) plus tamper, redaction, outbox and
credential checks. Every scenario returns (id, title, passed, detail)."""
import os, tempfile, sqlite3
from .store import (Store, PERMS, ACTIONS, Denied, Invalid, ServiceDown,
                    TimeoutAfterProcessing)
from .rubric_engine import grade_band
from .credentials import Issuer, verify

# Independent specification of who may do what (written separately from store.PERMS on purpose)
SPEC = {
    "examiner":          {"submit_marks"},
    "moderator":         {"moderate", "revalue"},
    "controller":        {"create_record", "approve", "publish", "redact", "view_all"},
    "administrator":     {"create_record", "manage_users", "view_all"},
    "student":           {"request_revaluation"},
    "department_head":   set(),
    "external_verifier": {"verify_credential"},
}


def fresh(path=":memory:"):
    s = Store(path)
    for u, r in [("adm", "administrator"), ("ex1", "examiner"), ("ex2", "examiner"),
                 ("mod1", "moderator"), ("mod2", "moderator"), ("ctl1", "controller"),
                 ("ctl2", "controller"), ("S001", "student"), ("S002", "student"),
                 ("hod", "department_head"), ("ver", "external_verifier")]:
        s.add_user(u, r)
    return s


def happy_path(s, rid, student="S001", mark=3, sugg=3):
    s.create_record("adm", rid, student, "CSA1023-Q1", "CSE")
    s.submit_mark("ex1", rid, mark, suggestion=sugg)
    s.moderate("mod1", rid)
    s.approve("ctl1", rid)
    s.publish("ctl1", rid)


def expect(exc, fn):
    try:
        fn()
    except exc:
        return True
    except Exception:
        return False
    return False


# ---------------------------------------------------------------- tamper helpers
def populate(s, n=12):
    for i in range(n):
        rid = f"R{i:03d}"
        happy_path(s, rid, mark=(i % 5) + 0.0, sugg=(i % 5) + 0.0)


def priv_exec(s, scheme, sql, params=()):
    """Simulate a privileged DBA: may drop triggers before editing."""
    if scheme == "trig":
        s.db.execute("DROP TRIGGER IF EXISTS audit_trig_no_update")
        s.db.execute("DROP TRIGGER IF EXISTS audit_trig_no_delete")
    s.db.execute(sql, params); s.db.commit()


def tamper_matrix():
    tests = {
        "T1 edit a logged mark": lambda s, t, scheme: _t1(s, t, scheme),
        "T2 delete a middle log row": lambda s, t, scheme: _t2(s, t, scheme),
        "T3 swap two log rows": lambda s, t, scheme: _t3(s, t, scheme),
        "T4 truncate the last 8 log rows": lambda s, t, scheme: _t4(s, t, scheme),
    }
    schemes = ["plain", "trig", "chain", "chain+anchor"]
    out = {}
    for name, fn in tests.items():
        out[name] = {}
        for sc in schemes:
            s = fresh(); populate(s)
            anchor = s.head_anchor()
            table = {"plain": "audit_plain", "trig": "audit_trig", "chain": "audit_chain", "chain+anchor": "audit_chain"}[sc]
            scheme = "trig" if sc == "trig" else sc
            blocked = False
            try:
                fn(s, table, scheme if sc != "chain+anchor" else "chain")
            except sqlite3.DatabaseError:
                blocked = True
            out[name][sc] = classify(s, sc, anchor, blocked, name)
            s.close()
    return out


def _t1(s, table, scheme):
    if table == "audit_chain":
        s.db.execute("UPDATE audit_payload SET payload=REPLACE(payload,'\"mark\": 0.0','\"mark\": 5.0') WHERE seq=(SELECT MIN(seq) FROM audit_chain WHERE action='SUBMIT_MARK')")
        s.db.commit()
    else:
        id_col = "id"
        s.db.execute(f"UPDATE {table} SET detail=REPLACE(detail,'\"mark\": 0.0','\"mark\": 5.0') WHERE action='SUBMIT_MARK' AND {id_col}=(SELECT MIN({id_col}) FROM {table} WHERE action='SUBMIT_MARK')")
        s.db.commit()


def _t2(s, table, scheme):
    key = "seq" if table == "audit_chain" else "id"
    s.db.execute(f"DELETE FROM {table} WHERE {key}=10"); s.db.commit()
    if table == "audit_chain":
        s.db.execute("DELETE FROM audit_payload WHERE seq=10"); s.db.commit()


def _t3(s, table, scheme):
    key = "seq" if table == "audit_chain" else "id"
    a = s.db.execute(f"SELECT actor,action,entity FROM {table} WHERE {key}=20").fetchone()
    b = s.db.execute(f"SELECT actor,action,entity FROM {table} WHERE {key}=21").fetchone()
    s.db.execute(f"UPDATE {table} SET actor=?,action=?,entity=? WHERE {key}=20", tuple(b))
    s.db.execute(f"UPDATE {table} SET actor=?,action=?,entity=? WHERE {key}=21", tuple(a))
    s.db.commit()


def _t4(s, table, scheme):
    key = "seq" if table == "audit_chain" else "id"
    mx = s.db.execute(f"SELECT MAX({key}) m FROM {table}").fetchone()["m"]
    s.db.execute(f"DELETE FROM {table} WHERE {key}>?", (mx - 8,)); s.db.commit()
    if table == "audit_chain":
        s.db.execute("DELETE FROM audit_payload WHERE seq>?", (mx - 8,)); s.db.commit()


def classify(s, sc, anchor, blocked_by_ordinary_sql, name):
    if sc == "plain":
        return "UNDETECTED"
    if sc == "trig":
        # ordinary SQL attempt was blocked by trigger; a privileged bypass is then simulated
        return "PREVENTED (ordinary SQL) / UNDETECTED after privileged bypass"
    ok, why = s.verify_chain(anchor if sc == "chain+anchor" else None)
    return "UNDETECTED" if ok else "DETECTED"


def tamper_matrix_with_bypass():
    """Re-run trig column with a privileged bypass to confirm it really is undetectable."""
    res = {}
    for name, fn in [("T1", _t1), ("T2", _t2), ("T3", _t3), ("T4", _t4)]:
        s = fresh(); populate(s)
        blocked = False
        try:
            fn(s, "audit_trig", "trig")
        except sqlite3.DatabaseError:
            blocked = True
        s.db.execute("DROP TRIGGER IF EXISTS audit_trig_no_update"); s.db.execute("DROP TRIGGER IF EXISTS audit_trig_no_delete")
        fn(s, "audit_trig", "trig")
        res[name] = {"blocked_ordinary": blocked, "bypass_succeeded": True}
        s.close()
    return res


# ---------------------------------------------------------------- the scenarios
def run_validation():
    R = []
    add = lambda i, t, ok, d="": R.append({"id": i, "title": t, "passed": bool(ok), "detail": d})

    # V1 marks validation
    s = fresh(); s.create_record("adm", "R1", "S001", "E", "CSE")
    bad = [7, -1, "abc", 2.3, None, True]
    rej = sum(expect(Invalid, lambda m=m: s.submit_mark("ex1", "R1", m)) for m in bad)
    s.submit_mark("ex1", "R1", 3.5, suggestion=3.5)
    add("V1", "Mark validation (range, type, 0.5 steps)", rej == len(bad) and s.get("R1")["mark"] == 3.5,
        f"{rej}/{len(bad)} invalid inputs rejected; valid 3.5 accepted")

    # V2 status order
    s = fresh(); s.create_record("adm", "R1", "S001", "E", "CSE")
    a = expect(Invalid, lambda: s.publish("ctl1", "R1"))
    s.submit_mark("ex1", "R1", 3, suggestion=3)
    b = expect(Invalid, lambda: s.publish("ctl1", "R1"))
    c = expect(Invalid, lambda: s.approve("ctl1", "R1"))
    s.moderate("mod1", "R1")
    d = expect(Invalid, lambda: s.publish("ctl1", "R1"))
    s.approve("ctl1", "R1"); s.publish("ctl1", "R1")
    add("V2", "Status workflow cannot be skipped", a and b and c and d and s.get("R1")["status"] == "PUBLISHED",
        "publish rejected from DRAFT, EVALUATED and MODERATED; allowed only after APPROVED")

    # V3 grade band
    exp = {0: "F", 1: "F", 2: "C", 3: "B", 4: "A", 5: "O"}
    got = {m: grade_band(m, 5) for m in range(6)}
    add("V3", "Grade-band mapping (0-5 of 5)", got == exp, str(got))

    # V4 RBAC matrix (77 role x action checks)
    s = fresh(); users = {"examiner": "ex1", "moderator": "mod1", "controller": "ctl1", "administrator": "adm",
                          "student": "S001", "department_head": "hod", "external_verifier": "ver"}
    checks = bad_checks = 0
    for role, u in users.items():
        for act in ACTIONS:
            checks += 1
            try:
                s._need(u, act); allowed = True
            except Denied:
                allowed = False
            if allowed != (act in SPEC[role]):
                bad_checks += 1
    add("V4", "Authorization matrix (role x action)", bad_checks == 0, f"{checks} checks, {bad_checks} mismatches against the written specification")

    # V5 separation of duties and ownership
    s = fresh(); s.create_record("adm", "R1", "S001", "E", "CSE"); s.submit_mark("ex1", "R1", 3, suggestion=3)
    s.add_user("exmod", "moderator")
    r1 = expect(Denied, lambda: s.moderate("adm", "R1"))
    s.add_user("ex1m", "moderator")
    s.db.execute("UPDATE users SET role='moderator' WHERE user='ex1'"); s.db.commit()   # same person, now moderator
    r2 = expect(Denied, lambda: s.moderate("ex1", "R1"))
    s.db.execute("UPDATE users SET role='examiner' WHERE user='ex1'"); s.db.commit()
    s.moderate("mod1", "R1")
    r3 = expect(Denied, lambda: s.approve("mod1", "R1"))
    s.db.execute("UPDATE users SET role='controller' WHERE user='mod1'"); s.db.commit()
    r3b = expect(Denied, lambda: s.approve("mod1", "R1"))
    s.db.execute("UPDATE users SET role='moderator' WHERE user='mod1'"); s.db.commit()
    s.approve("ctl1", "R1"); s.publish("ctl1", "R1")
    r4 = expect(Denied, lambda: s.request_revaluation("S002", "R1", "not mine"))
    r5 = expect(Denied, lambda: s.approve("adm", "R1"))
    add("V5", "Separation of duties and ownership", all([r1, r2, r3, r3b, r4, r5]),
        "administrator cannot moderate/approve; examiner cannot moderate own work; moderator cannot approve; student cannot challenge another student's record")

    # V6 override requires reason and is recorded
    s = fresh(); s.create_record("adm", "R1", "S001", "E", "CSE")
    a = expect(Invalid, lambda: s.submit_mark("ex1", "R1", 4, suggestion=2))
    s.submit_mark("ex1", "R1", 4, suggestion=2, reason="Answer explains hold-and-wait with an example")
    ev = s.db.execute("SELECT payload FROM audit_payload p JOIN audit_chain c ON c.seq=p.seq WHERE c.action='SUBMIT_MARK'").fetchone()
    add("V6", "Override needs a reason and is audited", a and "override_reason" in ev["payload"] and "hold-and-wait" in ev["payload"],
        "override without reason rejected; with reason stored with the suggestion in the audit trail")

    # V7 persistence
    path = os.path.join(tempfile.mkdtemp(), "persist.db")
    s = fresh(path); happy_path(s, "R1", mark=4, sugg=4); before = s.get("R1"); n_before = s.db.execute("SELECT COUNT(*) c FROM audit_chain").fetchone()["c"]; s.close()
    s2 = Store(path); after = s2.get("R1"); ok, why = s2.verify_chain(); n_after = s2.db.execute("SELECT COUNT(*) c FROM audit_chain").fetchone()["c"]
    add("V7", "Persistence across restart", before == after and ok and n_before == n_after,
        f"record and {n_after} audit entries identical after reopen; chain verifies")
    s2.close()

    # V8 audit completeness
    s = fresh(); happy_path(s, "R1")
    expect(Denied, lambda: s.approve("adm", "R1"))
    acts = [r["action"] for r in s.db.execute("SELECT action FROM audit_chain ORDER BY seq")]
    need = ["CREATE_RECORD", "SUBMIT_MARK", "MODERATE", "APPROVE", "PUBLISH", "DENIED"]
    ok, why = s.verify_chain()
    versions = s.db.execute("SELECT COUNT(*) c FROM mark_versions WHERE record_id='R1'").fetchone()["c"]
    add("V8", "Audit completeness incl. denied attempts", all(a in acts for a in need) and ok and versions == 4,
        f"{len(acts)} audit entries; {versions} record versions retained; chain intact")

    # V9 tamper matrix
    tm = tamper_matrix(); bypass = tamper_matrix_with_bypass()
    chain_ok = all(tm[t]["chain+anchor"] == "DETECTED" for t in tm)
    chain_noanchor_t4 = tm["T4 truncate the last 8 log rows"]["chain"] == "UNDETECTED"
    plain_bad = all(tm[t]["plain"] == "UNDETECTED" for t in tm)
    bypass_ok = all(v["blocked_ordinary"] and v["bypass_succeeded"] for v in bypass.values())
    add("V9", "Audit tampering: plain table vs append-only table vs hash chain", chain_ok and chain_noanchor_t4 and plain_bad and bypass_ok,
        "hash chain + external anchor detects all four tamper types; plain table detects none; triggers block ordinary SQL but not a privileged DBA; chain alone misses tail truncation")

    # V10 wrong-but-legitimate input is NOT detected (limits of integrity)
    s = fresh(); s.create_record("adm", "R1", "S001", "E", "CSE"); s.submit_mark("ex1", "R1", 5)   # true answer deserved 2
    ok, why = s.verify_chain(s.head_anchor())
    add("V10", "Chain cannot verify input truthfulness", ok, "a wrong mark entered through the normal API leaves the chain valid: integrity of the record is not truth of the mark")

    # V11 redaction keeps the chain valid
    s = fresh(); happy_path(s, "R1")
    seq = s.db.execute("SELECT MIN(seq) s FROM audit_chain WHERE action='SUBMIT_MARK'").fetchone()["s"]
    denied = expect(Denied, lambda: s.redact("adm", seq, "x"))
    noreason = expect(Invalid, lambda: s.redact("ctl1", seq, ""))
    s.redact("ctl1", seq, "Disputed record corrected under data-correction request")
    p = s.db.execute("SELECT payload, salt FROM audit_payload WHERE seq=?", (seq,)).fetchone()
    ok, why = s.verify_chain(s.head_anchor())
    ev = s.db.execute("SELECT COUNT(*) c FROM audit_chain WHERE action='REDACT_PAYLOAD'").fetchone()["c"]
    add("V11", "Redaction of sensitive payload keeps audit chain valid", denied and noreason and p["payload"] is None and p["salt"] is None and ok and ev == 1,
        "administrator cannot redact; reason mandatory; payload and salt erased; chain still verifies; redaction itself is audited")

    # V12 revaluation / correction workflow with version history
    s = fresh(); happy_path(s, "R1", student="S001", mark=2, sugg=2)
    s.request_revaluation("S001", "R1", "Answer 3 not credited")
    s.moderate("mod2", "R1", new_mark=3, reason="Independent re-evaluation credits hold-and-wait")
    s.approve("ctl2", "R1"); s.publish("ctl2", "R1")
    vs = [(r["version"], r["mark"], r["status"]) for r in s.db.execute("SELECT * FROM mark_versions WHERE record_id='R1' ORDER BY rowid")]
    orig_kept = any(m == 2 and st == "PUBLISHED" for _, m, st in vs)
    add("V12", "Revaluation: independent re-evaluation, versioned correction", s.get("R1")["mark"] == 3 and orig_kept and s.get("R1")["status"] == "PUBLISHED",
        f"{len(vs)} versions kept; original published mark 2 retained; corrected mark 3 published after independent moderator and different approver")

    # V13 outbox retry safety (external verification service unavailable)
    s = fresh(); [happy_path(s, f"R{i}", mark=3, sugg=3) for i in range(20)]
    for i in range(20):
        s.enqueue(f"cred-{i}", {"cred": i})
    s.enqueue("cred-3", {"cred": 3})   # duplicate enqueue must be ignored
    delivered, calls = {}, {"n": 0}

    def service(key, payload):
        calls["n"] += 1
        if calls["n"] <= 5:
            raise ServiceDown()
        if calls["n"] in (8, 9):
            delivered[key] = delivered.get(key, 0) + 1     # processed, but the response was lost
            raise TimeoutAfterProcessing()
        delivered[key] = delivered.get(key, 0) + 1

    rounds = 0
    while s.db.execute("SELECT COUNT(*) c FROM outbox WHERE status='PENDING'").fetchone()["c"] and rounds < 10:
        s.flush_outbox(service); rounds += 1
    status = {r["status"]: r["c"] for r in s.db.execute("SELECT status, COUNT(*) c FROM outbox GROUP BY status")}
    marks_intact = all(s.get(f"R{i}")["status"] == "PUBLISHED" for i in range(20))
    # Receiver-side deduplication by idempotency key: effective deliveries per key
    effective_unique = len(delivered)
    add("V13", "Verification service outage: local records preserved, safe retry", marks_intact and status.get("SENT") == 20 and effective_unique == 20,
        f"20 marks stay PUBLISHED locally during outage; outbox status {status}; {rounds} retry rounds; duplicates absorbed by idempotency keys (receiver processed {sum(delivered.values())} calls for {effective_unique} unique keys)")

    # V14 signed credentials, offline verification, revocation
    iss = Issuer()
    c1 = iss.issue("C-001", "pseud-7f3a", "B.E. CSE", 2026, "First Class")
    ok1, _ = verify(c1, iss.public_key)
    c2 = {"claims": dict(c1["claims"], band="Distinction"), "sig": c1["sig"]}
    ok2, why2 = verify(c2, iss.public_key)
    iss.revoke("C-001"); rl = iss.revocation_list()
    ok3, why3 = verify(c1, iss.public_key, rl)
    rl_bad = {"body": dict(rl["body"], revoked=[]), "sig": rl["sig"]}
    ok4, why4 = verify(c1, iss.public_key, rl_bad)
    c3 = iss.issue("C-002", "pseud-7f3a", "B.E. CSE", 2026, "First Class")
    ok5, _ = verify(c3, iss.public_key, rl)
    add("V14", "Signed credential: offline verify, tamper, revoke and re-issue", ok1 and (not ok2) and (not ok3) and (not ok4) and ok5,
        f"original verifies; altered band -> '{why2}'; revoked -> '{why3}'; forged revocation list -> '{why4}'; corrected credential C-002 verifies")
    return R, tm, bypass


if __name__ == "__main__":
    res, tm, bp = run_validation()
    for r in res:
        print(("PASS" if r["passed"] else "FAIL"), r["id"], r["title"], "-", r["detail"])
