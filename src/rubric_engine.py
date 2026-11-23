"""Deterministic rubric-rule engine (NOT trained machine learning).

Three versions are kept so that the design revision in Task 4 can be demonstrated:

  v0  simple baseline   - literal keyword substring match, no stemming, no synonyms
  v1  initial design    - stemming + synonym lists; every match earns the mark
  v2  revised design    - v1 + negation guard + unmatched-content flag + moderation priority

The output is always a SUGGESTION with an evidence trace. The "confidence" idea is
deliberately replaced by explicit flags: a coverage/flag value is not a calibrated
probability and is never presented as one.
"""
import re
from .dataset import MAX_MARK, PASS_MARK

NEGATION_CUES = {"not", "no", "never", "cannot", "without", "neither", "nor",
                 "isnt", "doesnt", "dont", "arent", "wont", "cant", "wasnt"}
WINDOW_BEFORE = 5
WINDOW_AFTER = 4
SUBSTANTIVE_MIN_TOKENS = 6


def stem(tok):
    if tok.endswith("sses"):
        return tok[:-2]
    if tok.endswith("ies") and len(tok) > 4:
        return tok[:-3] + "y"
    for suf in ("ing", "ed", "ly"):
        if tok.endswith(suf) and len(tok) > len(suf) + 2:
            return tok[:-len(suf)]
    if tok.endswith("s") and not tok.endswith("ss") and len(tok) > 3:
        return tok[:-1]
    return tok


def tokens(text):
    text = text.lower().replace("'", "")
    return re.findall(r"[a-z0-9]+", text)


def stems(text):
    return [stem(t) for t in tokens(text)]


def split_sentences(text):
    return [s.strip() for s in re.split(r"[.!?;]+", text) if s.strip()]


def find_spans(sent_stems, phrase_stems):
    n = len(phrase_stems)
    return [(i, i + n) for i in range(len(sent_stems) - n + 1) if sent_stems[i:i + n] == phrase_stems]


def is_negated(raw_tokens, span):
    start, end = span
    window = raw_tokens[max(0, start - WINDOW_BEFORE):start] + raw_tokens[end:end + WINDOW_AFTER]
    return any(t in NEGATION_CUES for t in window)


# ------------------------------------------------------------------ v0
def score_v0(answer, question):
    low = answer.lower()
    credited, evidence = [], {}
    for pt in question["points"]:
        for kw in pt["keywords"]:
            if kw.lower() in low:
                credited.append(pt["id"]); evidence[pt["id"]] = kw
                break
    return {"engine": "v0", "mark": len(credited), "credited": credited, "evidence": evidence,
            "flags": [], "priority": "NORMAL"}


# ------------------------------------------------------------------ v1 / v2
def _match_points(answer, question, negation_guard):
    sentences = split_sentences(answer)
    s_raw = [tokens(s) for s in sentences]
    s_stem = [[stem(t) for t in r] for r in s_raw]
    credited, evidence, negated_pts = [], {}, []
    matched_sentence = [False] * len(sentences)
    for pt in question["points"]:
        phrases = pt["keywords"] + pt["synonyms"]
        ok_phrase, neg_phrase = None, None
        for ph in phrases:
            pst = stems(ph)
            for si, ss in enumerate(s_stem):
                for span in find_spans(ss, pst):
                    matched_sentence[si] = True
                    if negation_guard and is_negated(s_raw[si], span):
                        neg_phrase = neg_phrase or ph
                    else:
                        ok_phrase = ok_phrase or ph
        if ok_phrase:
            credited.append(pt["id"]); evidence[pt["id"]] = ok_phrase
        elif neg_phrase:
            negated_pts.append(pt["id"]); evidence[pt["id"]] = f"NEGATED: {neg_phrase}"
    unmatched = sum(1 for i, r in enumerate(s_raw)
                    if len(r) >= SUBSTANTIVE_MIN_TOKENS and not matched_sentence[i])
    return credited, evidence, negated_pts, unmatched


def score_v1(answer, question):
    credited, evidence, _, _ = _match_points(answer, question, negation_guard=False)
    return {"engine": "v1", "mark": len(credited), "credited": credited, "evidence": evidence,
            "flags": [], "priority": "NORMAL"}


def grade_band(mark, max_mark=MAX_MARK):
    pct = 100.0 * mark / max_mark
    if pct >= 90: return "O"
    if pct >= 75: return "A"
    if pct >= 60: return "B"
    if pct >= 40: return "C"
    return "F"


if __name__ == "__main__":
    from .dataset import QUESTIONS
    q = QUESTIONS["Q1"]
    txt = ("Mutual exclusion is not needed for deadlock to occur. Hold and wait means a process holds "
           "at least one resource while requesting additional resources.")
    for f in (score_v0, score_v1):
        print(f.__name__, f(txt, q))
