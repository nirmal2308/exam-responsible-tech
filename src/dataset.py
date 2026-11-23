"""Synthetic dataset for the examination demonstrator (NO real student data).

Three synthetic descriptive questions, five rubric points each (1 mark per point).
Every answer is assembled from sentence variants so that the expert mark is known
by construction:

  exact       - uses the rubric keyword                       -> expert credits the point
  paraphrase  - uses a synonym that the rules know about      -> expert credits the point
  unfamiliar  - correct meaning, words the rules do NOT know  -> expert credits the point
  negated     - contains the keyword but denies the concept   -> expert gives NO credit
  absent      - point missing (sometimes a generic filler)    -> expert gives NO credit

LIMITATION: this is a controlled construction. It exercises specific mechanisms
(paraphrase, unfamiliar terms, negation, run-on answers). It does not estimate how
the engine would perform on real handwritten or typed scripts.
"""
import random

MAX_MARK = 5
PASS_MARK = 2          # 40 % of 5
SEED = 20261123
N_PER_QUESTION = 80
P_VARIANT = {"exact": 0.30, "paraphrase": 0.20, "unfamiliar": 0.15, "negated": 0.10, "absent": 0.25}
P_FILLER_WHEN_ABSENT = 0.40
P_RUN_ON = 0.30        # share of answers written as one long run-on sentence

CREDITED = {"exact", "paraphrase", "unfamiliar"}


def P(pid, keywords, synonyms, exact, paraphrase, unfamiliar, negated):
    return {"id": pid, "keywords": keywords, "synonyms": synonyms,
            "variants": {"exact": exact, "paraphrase": paraphrase,
                         "unfamiliar": unfamiliar, "negated": negated}}


QUESTIONS = {
    "Q1": {"category": "Operating Systems",
           "text": "Explain deadlock and state the conditions necessary for it to occur.",
           "fillers": ["Deadlock is an important topic in operating systems.",
                       "Many systems handle this problem in different ways."],
           "points": [
               P("P1", ["blocked indefinitely"], ["stuck forever", "wait forever", "never proceed", "permanently blocked"],
                 "Deadlock is a state in which a set of processes is blocked indefinitely because each one waits for a resource held by another.",
                 "In a deadlock the processes are permanently blocked since none of them can ever proceed.",
                 "Deadlock leaves the tasks frozen in a standoff where nobody gets to continue execution.",
                 "Deadlock does not leave processes blocked indefinitely."),
               P("P2", ["mutual exclusion"], ["exclusive access", "one process at a time", "non-shareable", "only one process"],
                 "Mutual exclusion requires that a resource can be used by only one process at a time.",
                 "The resource is non-shareable, so exclusive access is given to a single process.",
                 "A printer, for example, cannot be driven by two jobs simultaneously.",
                 "Mutual exclusion is not needed for deadlock to occur."),
               P("P3", ["hold and wait"], ["holding resources while waiting", "hold one resource and wait", "keeps what it has while requesting"],
                 "Hold and wait means a process holds at least one resource while requesting additional resources.",
                 "A process that is holding resources while waiting for others contributes to deadlock.",
                 "A task grabs some resources early and then asks for more without giving the first ones back.",
                 "Hold and wait is never a requirement for deadlock."),
               P("P4", ["no preemption"], ["cannot be forcibly taken", "non-preemptive", "only released voluntarily", "not preempted"],
                 "The no preemption condition states that a granted resource is released only by the process holding it.",
                 "Resources are non-preemptive and can only be released voluntarily by their holder.",
                 "The system has no right to snatch a resource back from a process that is using it.",
                 "Preemption is allowed in deadlock, so the no preemption condition does not hold."),
               P("P5", ["circular wait"], ["form a cycle", "cycle of processes", "closed chain", "circular chain", "waiting in a cycle"],
                 "Circular wait means a closed chain of processes exists where each waits for a resource held by the next.",
                 "The processes form a cycle in which each one is waiting for the next one's resource.",
                 "P1 waits for P2, P2 waits for P3, and P3 waits back for P1.",
                 "There is no circular wait among the processes in a deadlock."),
           ]},
    "Q2": {"category": "Database Systems",
           "text": "Explain the ACID properties of a database transaction.",
           "fillers": ["Transactions are widely used in banking applications.",
                       "These properties are usually remembered together as one acronym."],
           "points": [
               P("P1", ["atomicity"], ["all or nothing", "entirely or not at all", "completely or not at all"],
                 "Atomicity ensures that a transaction is executed completely or not at all.",
                 "Every transaction follows an all or nothing rule, so partial updates never remain.",
                 "Either every step of the transaction takes effect or none of them are kept.",
                 "Atomicity does not require a transaction to complete fully."),
               P("P2", ["consistency"], ["valid state", "preserves integrity", "integrity constraints"],
                 "Consistency guarantees the database moves from one valid state to another.",
                 "A transaction preserves integrity, so all integrity constraints still hold afterwards.",
                 "After the transaction finishes the data still follows every rule defined for the schema.",
                 "Consistency is not maintained by transactions in a DBMS."),
               P("P3", ["isolation"], ["run independently", "do not interfere", "without interference", "concurrent transactions"],
                 "Isolation ensures concurrent transactions execute as if they were serial.",
                 "Transactions run independently, without interference from each other's intermediate results.",
                 "One user's half-finished work stays hidden from the other users working at the same moment.",
                 "Isolation is never provided when many users access the database."),
               P("P4", ["durability"], ["permanently stored", "survives a crash", "persist after commit", "survive failures"],
                 "Durability means committed changes remain even after a system failure.",
                 "Once committed, the changes are permanently stored and survive failures.",
                 "A power cut after the commit cannot undo the work that was already confirmed.",
                 "Durability does not apply to committed transactions."),
               P("P5", ["transaction log"], ["write-ahead log", "redo log", "undo log", "rollback"],
                 "The transaction log records every change so the DBMS can recover or roll back after a failure.",
                 "A write-ahead log lets the system redo or undo operations during recovery.",
                 "A diary of all operations is kept so the engine can restore the earlier situation.",
                 "The transaction log is not used for recovery in a DBMS."),
           ]},
    "Q3": {"category": "Software Engineering",
           "text": "Explain regression testing and state when it is performed.",
           "fillers": ["This is an important activity in software projects.",
                       "Quality assurance teams rely on it frequently."],
           "points": [
               P("P1", ["re-execution of test cases"], ["rerun existing tests", "re-run existing tests", "repeat earlier tests"],
                 "Regression testing is the re-execution of test cases that were run earlier to confirm the software still works.",
                 "It means we rerun existing tests after every modification to the code.",
                 "The team goes through the earlier checks once more whenever the code is touched.",
                 "Regression testing is not the re-execution of test cases; only new tests are written."),
               P("P2", ["unintended side effects"], ["break existing functionality", "new defects", "previously working features"],
                 "Its goal is to detect unintended side effects introduced by a change.",
                 "It ensures previously working features keep working after the change.",
                 "The aim is to catch damage that a modification causes in other parts of the application.",
                 "Regression testing does not look for unintended side effects of changes."),
               P("P3", ["bug fix"], ["code change", "new feature", "configuration change", "patch"],
                 "It is performed after a bug fix, enhancement, or environment update.",
                 "It is carried out whenever a new feature is added or a patch is applied.",
                 "It happens each time developers deliver another release of the product.",
                 "Regression testing is not needed after a bug fix."),
               P("P4", ["automated test suite"], ["test scripts", "ci pipeline", "continuous integration"],
                 "An automated test suite is normally used so the checks can be repeated cheaply.",
                 "Test scripts run in a CI pipeline make the repetition fast.",
                 "Machines execute the checks overnight so people are not required.",
                 "An automated test suite is not useful for regression testing."),
               P("P5", ["test prioritization"], ["test prioritisation", "select relevant tests", "risk-based selection", "impacted tests"],
                 "Test prioritization orders the suite so the most important tests run first.",
                 "Teams select relevant tests using risk-based selection when the full suite is too large.",
                 "Only the checks close to the modified area are chosen to save time.",
                 "Test prioritization is not required in regression testing."),
           ]},
}

# Assumed examiner inconsistency (simulation parameter, NOT measured data).
HIST_NOISE_SD = {"Operating Systems": 0.35, "Database Systems": 0.35, "Software Engineering": 1.25}


def generate(seed=SEED, n_per_q=N_PER_QUESTION):
    rng = random.Random(seed)
    kinds, probs = zip(*P_VARIANT.items())
    rows = []
    for qid, q in QUESTIONS.items():
        for i in range(n_per_q):
            sentences, variants = [], {}
            for pt in q["points"]:
                v = rng.choices(kinds, probs)[0]
                variants[pt["id"]] = v
                if v == "absent":
                    if rng.random() < P_FILLER_WHEN_ABSENT:
                        sentences.append(rng.choice(q["fillers"]))
                else:
                    sentences.append(pt["variants"][v])
            if not sentences:
                sentences.append(rng.choice(q["fillers"]))
            run_on = rng.random() < P_RUN_ON
            if run_on:
                parts = [s.rstrip(".") for s in sentences]
                parts = [parts[0]] + [p[0].lower() + p[1:] for p in parts[1:]]
                text = " and ".join(parts) + "."
            else:
                text = " ".join(sentences)
            expert = sum(1 for v in variants.values() if v in CREDITED)
            # simulated historical examiner mark (used only for the Task 6 label-inconsistency checks)
            sd = HIST_NOISE_SD[q["category"]]
            hist = min(MAX_MARK, max(0, int(round(expert + rng.gauss(0, sd)))))
            rows.append({"id": f"{qid}-{i + 1:03d}", "qid": qid, "category": q["category"],
                         "text": text, "variants": variants, "expert_mark": expert,
                         "hist_mark": hist, "run_on": run_on})
    return rows


if __name__ == "__main__":
    d = generate()
    print(len(d), "synthetic answers; sample:\n", d[0]["text"], "| expert =", d[0]["expert_mark"])
