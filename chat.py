"""Ask: questions answered from the stories on this site, written by a small open model on your own computer.

How an answer is made, in order, with no hidden steps:
  0. COUNT: a question that is really a lookup ("which stories did the right miss?", "stories only the left covered", "what are
     the main stories?") is answered by plain code filtering the data. No model, so it is instant and exact.
  1. RETRIEVE: the question is matched to the stories in data/latest.json by shared words (TF-IDF, the same kind of
     matching the site uses to group stories). The best few stories are picked. If nothing matches well, the model
     is not called at all and the answer is "That is not in today's coverage."
  2. COVERAGE: who covered each picked story, by side, with their own headlines and links, is copied from the data
     by plain code. A language model never writes that part, because a small model gets sides wrong.
  2b. SUMMARY: when a picked story already has its stored "what happened" (written earlier by the same model, see summaries.py), that
     is the answer, shown at once. The model runs only if the reader asks it to compare how the sides worded the story.
  3. WRITE: the model is shown only the picked stories' headlines (grouped by side, without outlet names) and the
     instructions in config/chat_prompt.txt, and writes a few sentences. Nothing else goes in, and nothing is sent anywhere.
This file has no network or model code; chat_server.py runs the model.
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SIDES = ("left", "center", "right")
MIN_SCORE = 0.12     # how closely a story must match the question (0 to 1) before the model is asked to write about it
MIN_SHARE = 0.5      # and at least this share of the question's meaningful words must appear in the story ("world series" must not match a World Cup story)
MAX_STORIES = 2      # stories shown to the model. Each one adds reading time on a slow computer
PER_SIDE = 3         # headlines per side given to the model
MAX_QUESTION = 300

NOT_COVERED = "That is not in today's coverage."
COMPARE = "\n(Compare how the left, center and right headlines word this story. Say which words each group uses.)"

# Words that describe the question rather than the story: "how did the left cover it" says nothing about which story.
FILLER = set("""a about all an and any are as at be been being but by can could did do does for from give had has have how i if in
into is it its just me more most my news of on one or other our out over say said says show so some tell than that the their
them then there these they this those to up us was we were what when where which who why will with would you your
left right center centre cover covers covered covering coverage outlet outlets story stories report reports reported reporting
happen happened happening latest new now right today todays tonight yesterday top big main headline headlines""".split())

_SUFFIXES = ("ing", "ed", "es", "s")


def stem(word):
    """A very light stemmer so reinstate, reinstated and reinstates match. Words under 5 letters are left alone."""
    for suf in _SUFFIXES:
        if word.endswith(suf) and len(word) - len(suf) >= 4:
            return word[:-len(suf)]
    return word


def tokens(text):
    words = re.findall(r"[a-z0-9]+", text.lower().replace("’", "'").replace("'s ", " "))
    return [stem(w) for w in words if w not in FILLER and len(w) > 1]


def load_stories(path):
    """The stories in the last build's data file, most-covered first (the order the site shows them)."""
    try:
        return json.loads(Path(path).read_text()).get("stories", [])
    except (OSError, ValueError):
        return []


# ---- questions that are lookups, not language tasks ----
LIST_MAX = 8
MISS_NOTE_CENTER = " The News page flags only left and right gaps; for center, the same 3-outlet rule is applied here."
FIRST_NOTE = "First means first among the outlets this site reads, by their feed publish times, not first in the world."
NEWEST_NOTE = "Newest means most recently first reported among the outlets this site reads. A story that gained reports later is not moved."
MISS_NOTE = "A side counts as missing only when 3 or more outlets covered the story, the same rule as the News page."
_ONLY = re.compile(r"\b(only|exclusively|solely|just)\b")
_MISS = re.compile(r"\b(not covered|not cover|did ?n[o']?t cover|do ?n[o']?t cover|never cover\w*|have ?n[o']?t cover\w*|miss(?:ed|es|ing)?|ignor\w+|silent|silence|"
                   r"skipp\w+|no coverage|without coverage|blind ?spots?|neglect\w+|left out|overlook\w+|lack\w*|absent)\b")
_ALL = re.compile(r"\b(all (three )?sides|every side|all three|across the (political )?spectrum|everyone covered|bipartisan|left,? (center|centre),? and right)\b")
_FIRST = re.compile(r"\b(first|earliest|broke|scoop)\b|\bbreak the\b")
_FIRST_CTX = re.compile(r"\b(who|which|outlets?|sources?|report\w*|cover\w*|publish\w*|ran|run|story|stories|sides?)\b")
_WHICH_SIDE = re.compile(r"\b(which|what) sides?\b|\b(usually|often|typically|generally|mostly)\b")
_NEWEST = re.compile(r"\b(newest|latest|most recent\w*|recent\w*|just in|just (?:reported|happened|broke)|fresh|breaking|last (?:hour|few hours)|new stories|newly)\b|\bwhat(?:'s| is) new\b")
_TOP = re.compile(r"\b(main|top|biggest|major|leading|most[- ]covered|biggest|headline)\b.*\b(news|stories|story|headlines)\b|\bwhat(?:'s| is) (?:happening|going on|in the news)\b|"
                  r"\bmost[- ]covered\b|\bwhat happened today\b")
_NOT_A_SIDE = re.compile(r"\bright (now|away|after|before|here|there|to|of|about)\b")
_STRUCT = {stem(w) for w in ("only exclusively solely just not never miss missed missing ignore ignored ignoring skipped silent silence blindspot blindspots blind "
                             "spot spots without lack lacking lacks absent overlooked neglected didn didnt don dont haven havent doesn wasn weren "
                             "sides side three every everyone spectrum political bipartisan which what stories story show list "
                             "first earliest newest latest recent recently fresh breaking broke break scoop who whom outlet outlets source sources "
                             "publish published ran run usually often typically generally mostly").split()}


def sides_in(question):
    """The sides a question names, in order. 'right now' is not a side."""
    q = _NOT_A_SIDE.sub(" ", question.lower())
    out = []
    for w in re.findall(r"[a-z]+", q):
        side = "center" if w in ("center", "centre") else w if w in SIDES else None
        if side and side not in out:
            out.append(side)
    return out


def _age(iso, now=None):
    """'3 h ago' for a feed time like 2026-11-23T14:14:40Z."""
    try:
        t = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return "at an unknown time"
    sec = max(0, int(((now or datetime.now(timezone.utc)) - t).total_seconds()))
    return "just now" if sec < 90 else f"{sec // 60} min ago" if sec < 3600 else f"{sec // 3600} h ago" if sec < 172800 else f"{sec // 86400} d ago"


def _noun(n, one, many):
    return f"{n} {one if n == 1 else many}"


def structured(question, stories, now=None):
    """A lookup answered by counting: returns (text, picked stories, note, show_first) or None when the question is about a topic or needs words.
    Wording is fixed here, so the reader can see exactly what was counted."""
    q = question.lower().replace("\u2019", "'")
    sides = sides_in(q)
    topic = [t for t in tokens(q) if t not in _STRUCT]
    if _ALL.search(q) and not sides_in(_ALL.sub(" ", q)):
        kind, hits, what = "all", [s for s in stories if all(s["by_side"].get(x, 0) for x in SIDES)], "were covered by left, center and right outlets"
    elif _MISS.search(q) and sides:
        miss = sides[0]
        if miss == "center":  # the News page never flags a center gap, so apply the same 3-outlet rule here
            hits = [s for s in stories if s.get("outlets", 0) >= 3 and not s["by_side"].get("center", 0) and all(s["by_side"].get(x, 0) for x in sides[1:])]
        else:
            hits = [s for s in stories if miss in s.get("not_covered_by", []) and all(s["by_side"].get(x, 0) for x in sides[1:])]
        kind, what = "miss", f"had no coverage from {miss} outlets"
    elif _MISS.search(q):
        kind, hits, what = "miss", [s for s in stories if s.get("not_covered_by")], "had no coverage from at least one side"
    elif _ONLY.search(q) and sides:
        only = sides[0]
        hits = [s for s in stories if s["by_side"].get(only, 0) and not any(s["by_side"].get(x, 0) for x in SIDES if x != only)]
        kind, what = "only", f"were reported only by {only} outlets"
    elif _FIRST.search(q) and _FIRST_CTX.search(q):
        if _WHICH_SIDE.search(q) and not sides:  # "which side usually reports first?": a tally over every story
            tally = {x: sum(1 for s in stories if (s.get("first_reported") or {}).get("side") == x) for x in SIDES}
            parts = [f"a {x} outlet in {c}" for x, c in sorted(tally.items(), key=lambda kv: (-kv[1], SIDES.index(kv[0]))) if c]
            if not parts:
                return NOT_COVERED, [], None, False
            return (f"Across today's {len(stories)} stories, the first report came from " + ", ".join(parts[:-1]) + (" and " if len(parts) > 1 else "") + parts[-1] + ".",
                    [], FIRST_NOTE, False)
        if sides:  # "which stories did the right report first?"
            hits = [s for s in stories if (s.get("first_reported") or {}).get("side") == sides[0]]
            kind, what = "firstside", f"were first reported by a {sides[0]} outlet"
        else:
            kind, hits, what = "first", list(stories), None
    elif _NEWEST.search(q) and not topic and not sides:
        kind, hits, what = "newest", sorted(stories, key=lambda s: (s.get("first_reported") or {}).get("at") or "", reverse=True), None
    elif not topic and (_TOP.search(q) or not sides):
        kind, hits, what = "top", list(stories), None
    else:
        return None
    about = ""
    miss_note = MISS_NOTE + (MISS_NOTE_CENTER if kind == "miss" and sides and sides[0] == "center" else "")
    if topic and kind not in ("top", "newest"):  # "stories only the right covered about Iran": keep the ones that match the rest of the words
        terms = set(topic)
        hits = [s for s in hits if len(terms & set(tokens(story_text(s)))) / len(terms) >= MIN_SHARE]
        about = " matching your words"
    if kind == "top":
        n = min(LIST_MAX, len(hits))
        return (f"The {_noun(n, 'story', 'stories')} covered by the most outlets right now, most first." if n else NOT_COVERED), hits[:LIST_MAX], None, False
    if kind == "newest":
        n = min(LIST_MAX, len(hits))
        return (f"The {_noun(n, 'story', 'stories')} first reported most recently, newest first." if n else NOT_COVERED), hits[:LIST_MAX], NEWEST_NOTE, True
    if kind == "first":
        shown = hits[:LIST_MAX]
        if not shown:
            return f"No story{about} today to look at.", [], None, False
        def who(st):
            f = st.get("first_reported") or {}
            return f"{f.get('outlet', 'unknown')} ({f.get('side', '?')}), {_age(f.get('at'), now)}"
        if len(hits) == 1:
            f = hits[0].get("first_reported") or {}
            return f"{f.get('outlet', 'An unknown outlet')}, a {f.get('side', 'unknown')} outlet, reported it first, {_age(f.get('at'), now)}.", hits, FIRST_NOTE, True
        head = (f"Who reported each of the {len(shown)} most-covered stories first:" if len(hits) > LIST_MAX
                else f"Who reported each of these {len(shown)} stories first:")
        return (head + "\n" + "\n".join(f"[{i}] {who(st)}" for i, st in enumerate(shown, 1))), shown, FIRST_NOTE, True
    n, shown = len(hits), hits[:LIST_MAX]
    if not n:
        if kind == "miss":
            return f"No story{about} with 3 or more outlets {what.replace('had no coverage from', 'lacked coverage from')}.", [], miss_note, False
        return f"No story{about} today {what.replace('were', 'was', 1)}.", [], (FIRST_NOTE if kind == "firstside" else None), False
    more = f" Showing the first {LIST_MAX}, most-covered first." if n > LIST_MAX else ""
    verb = what if n != 1 else what.replace("were", "was", 1)
    return (f"{_noun(n, 'story', 'stories')}{about} {verb}.{more}", shown,
            miss_note if kind == "miss" else FIRST_NOTE if kind == "firstside" else None, kind == "firstside")


def story_text(st):
    return (st.get("label") or "") + " " + " ".join(r.get("headline", "") for r in st.get("reports", []))


def retrieve(question, stories, k=MAX_STORIES, min_score=MIN_SCORE):
    """Pick the stories that best match the question. Returns (stories, mode): mode is 'match', 'overview' (the question
    names nothing in particular, like "what's happening?", so the top-ranked stories are used) or 'none'."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    if not stories:
        return [], "none"
    q = tokens(question)
    if not q:
        return list(stories[:k]), "overview"
    docs = [story_text(s) for s in stories]
    vec = TfidfVectorizer(analyzer=tokens, sublinear_tf=True).fit(docs)
    scores = cosine_similarity(vec.transform([question]), vec.transform(docs))[0]
    order = sorted(range(len(stories)), key=lambda i: (-scores[i], i))
    terms = set(q)

    def shares(i):  # how much of the question this story's words account for
        return len(terms & set(tokens(docs[i]))) / len(terms)
    picked = [stories[i] for i in order[:k] if scores[i] >= min_score and shares(i) >= MIN_SHARE]
    return picked, ("match" if picked else "none")


def coverage(st, number):
    """Who covered one story, by side, copied from the data. This is what the page shows; the model never writes it."""
    by_side = {s: [] for s in SIDES}
    for r in st.get("reports", []):
        if r.get("side") in by_side:
            by_side[r["side"]].append({"outlet": r.get("outlet", ""), "headline": r.get("headline", ""),
                                       "url": r.get("url", ""), "published": r.get("published", "")})
    return {"n": number, "id": st.get("id"), "page": st.get("page"), "label": st.get("label", ""), "outlets": st.get("outlets", 0),
            "counts": {s: len(v) for s, v in by_side.items()}, "by_side": by_side, "first": st.get("first_reported"),
            "not_covered_by": list(st.get("not_covered_by", []))}


def system_text(path=None):
    return (Path(path) if path else ROOT / "config" / "chat_prompt.txt").read_text().strip()


def build_prompt(question, picked, system, per_side=PER_SIDE):
    """The exact text the model reads (Qwen's chat format, with thinking switched off so it answers directly).
    Headlines are grouped under LEFT, CENTER and RIGHT and outlet names are left out, so it cannot misname an outlet."""
    blocks = []
    for n, st in enumerate(picked, 1):
        lines = [f"[{n}] {st.get('label', '')}"]
        for side in SIDES:
            heads = []
            for r in st.get("reports", []):
                h = r.get("headline", "").strip()
                if r.get("side") == side and h and h not in heads:
                    heads.append(h)
            if heads:
                lines.append(f"{side.upper()} outlets' headlines:")
                lines += [f"- {h}" for h in heads[:per_side]]
            else:
                lines.append(f"{side.upper()} outlets: no coverage")
        blocks.append("\n".join(lines))
    q = question.strip()[:MAX_QUESTION + len(COMPARE)].replace("<|", "< |")  # the question cannot smuggle in chat-format markers
    return (f"<|im_start|>system\n{system}\n\nSTORIES:\n" + "\n\n".join(blocks) + f"<|im_end|>\n<|im_start|>user\n{q}<|im_end|>\n"
            "<|im_start|>assistant\n<think>\n\n</think>\n\n")


def write_prompt(question, stories, system):
    """For the "compare how each side worded it" button: only the best-matching story, so the model reads less and answers sooner."""
    picked, mode = retrieve(question, stories)
    return build_prompt(question.strip()[:MAX_QUESTION] + COMPARE, picked[:1], system) if mode == "match" and picked else None


def prepare(question, stories, system, now=None):
    """Everything before the model: what was picked, what the page shows, and the prompt (None when the model is not needed)."""
    found = structured(question, stories, now)
    if found:  # a lookup: counted by code, no model
        text, picked, note, show_first = found
        return {"mode": "list", "sources": [coverage(st, n) for n, st in enumerate(picked, 1)], "prompt": None, "text": text, "note": note,
                "show_first": show_first}
    picked, mode = retrieve(question, stories)
    stored = [(n, st["summary"]) for n, st in enumerate(picked, 1) if (st.get("summary") or {}).get("text")]
    if mode == "match" and stored:  # the answer already exists, written earlier: show it at once; the model only compares wording on request
        text = "\n\n".join(f"{sm['text'].strip()} [{n}]" for n, sm in stored)
        return {"mode": "summary", "sources": [coverage(st, n) for n, st in enumerate(picked, 1)], "prompt": None, "text": text, "note": None,
                "can_write": True, "model": stored[0][1].get("model", "")}
    if mode == "overview":  # nothing in the question to match: show the top stories rather than ask the model to guess
        picked = picked[:MAX_STORIES]
    return {"mode": mode, "sources": [coverage(st, n) for n, st in enumerate(picked, 1)],
            "prompt": build_prompt(question, picked, system) if picked else None, "text": None if picked else NOT_COVERED, "note": None}
