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


def score_v2(answer, question, unmatched_threshold=2):
    credited, evidence, negated_pts, unmatched = _match_points(answer, question, negation_guard=True)
    mark = len(credited)
    flags = []
    if negated_pts:
        flags.append("NEGATION")
    if unmatched >= unmatched_threshold:
        flags.append("UNMATCHED_CONTENT")
    if mark in (PASS_MARK - 1, PASS_MARK):
        flags.append("BOUNDARY")
    high = ("NEGATION" in flags) or ("UNMATCHED_CONTENT" in flags)
    priority = "HIGH" if high else ("MEDIUM" if "BOUNDARY" in flags else "LOW")
    return {"engine": "v2", "mark": mark, "credited": credited, "evidence": evidence,
            "flags": flags, "priority": priority, "negated_points": negated_pts,
            "unmatched_sentences": unmatched}


# ------------------------------------------------------------------ v3 (clause-aware revision of v2)
BOUNDARY_WORDS = {"and", "but", "so", "because", "while", "which", ","}


def _tok_comma(sentence):
    return re.findall(r"[a-z0-9]+|,", sentence.lower().replace("'", ""))


def _neg_clause(raw, span):
    """Negation cue within 5 words before / 4 words after the phrase, never crossing a clause boundary."""
    start, end = span
    n = 0
    for t in reversed(raw[:start]):
        if t in BOUNDARY_WORDS:
            break
        n += 1
        if t in NEGATION_CUES:
            return True
        if n >= WINDOW_BEFORE:
            break
    n = 0
    for t in raw[end:]:
        if t in BOUNDARY_WORDS:
            break
        n += 1
        if t in NEGATION_CUES:
            return True
        if n >= WINDOW_AFTER:
            break
    return False


def score_v3(answer, question, unmatched_threshold=2):
    sentences = split_sentences(answer)
    raws = [_tok_comma(s) for s in sentences]
    sts = [[t if t == "," else stem(t) for t in r] for r in raws]
    covered = [[False] * len(r) for r in raws]
    credited, evidence, negated_pts = [], {}, []
    for pt in question["points"]:
        ok_phrase = neg_phrase = None
        for ph in pt["keywords"] + pt["synonyms"]:
            pst = stems(ph)
            for si, ss in enumerate(sts):
                for span in find_spans(ss, pst):
                    for k in range(*span):
                        covered[si][k] = True
                    if _neg_clause(raws[si], span):
                        neg_phrase = neg_phrase or ph
                    else:
                        ok_phrase = ok_phrase or ph
        if ok_phrase:
            credited.append(pt["id"]); evidence[pt["id"]] = ok_phrase
        elif neg_phrase:
            negated_pts.append(pt["id"]); evidence[pt["id"]] = f"NEGATED: {neg_phrase}"
    # clause segmentation: a clause ends at a sentence end or at an uncovered 'and'; a clause that
    # contains any rubric match is "covered"; an uncovered clause with >= 6 words is unmatched content
    runs = 0
    for raw, cov in zip(raws, covered):
        words, hit = 0, False
        for t, c in zip(raw, cov):
            if t == ",":
                continue
            if t == "and" and not c:
                runs += (words >= SUBSTANTIVE_MIN_TOKENS and not hit)
                words, hit = 0, False
            else:
                words += 1
                hit = hit or c
        runs += (words >= SUBSTANTIVE_MIN_TOKENS and not hit)
    mark = len(credited)
    flags = []
    if negated_pts:
        flags.append("NEGATION")
    if runs >= unmatched_threshold:
        flags.append("UNMATCHED_CONTENT")
    if mark in (PASS_MARK - 1, PASS_MARK):
        flags.append("BOUNDARY")
    high = ("NEGATION" in flags) or ("UNMATCHED_CONTENT" in flags)
    priority = "HIGH" if high else ("MEDIUM" if "BOUNDARY" in flags else "LOW")
    return {"engine": "v3", "mark": mark, "credited": credited, "evidence": evidence, "flags": flags,
            "priority": priority, "negated_points": negated_pts, "unmatched_sentences": runs}


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
    for f in (score_v0, score_v1, score_v2):
        print(f.__name__, f(txt, q))
