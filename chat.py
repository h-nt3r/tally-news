"""Ask: questions answered from the stories on this site, written by a small open model on your own computer.

How an answer is made, in order, with no hidden steps:
  1. RETRIEVE: the question is matched to the stories in data/latest.json by shared words (TF-IDF, the same kind of
     matching the site uses to group stories). The best few stories are picked. If nothing matches well, the model
     is not called at all and the answer is "That is not in today's coverage."
  2. COVERAGE: who covered each picked story, by side, with their own headlines and links, is copied from the data
     by plain code. A language model never writes that part, because a small model gets sides wrong.
  3. WRITE: the model is shown only the picked stories' headlines (grouped by side, without outlet names) and the
     instructions in config/chat_prompt.txt, and writes a few sentences. Nothing else goes in, and nothing is sent anywhere.
This file has no network or model code; chat_server.py runs the model.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SIDES = ("left", "center", "right")
MIN_SCORE = 0.12     # how closely a story must match the question (0 to 1) before the model is asked to write about it
MIN_SHARE = 0.5      # and at least this share of the question's meaningful words must appear in the story ("world series" must not match a World Cup story)
MAX_STORIES = 2      # stories shown to the model. Each one adds reading time on a slow computer
PER_SIDE = 3         # headlines per side given to the model
MAX_QUESTION = 300

NOT_COVERED = "That is not in today's coverage."

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
            "counts": {s: len(v) for s, v in by_side.items()}, "by_side": by_side,
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
    q = question.strip()[:MAX_QUESTION].replace("<|", "< |")  # the question cannot smuggle in chat-format markers
    return (f"<|im_start|>system\n{system}\n\nSTORIES:\n" + "\n\n".join(blocks) + f"<|im_end|>\n<|im_start|>user\n{q}<|im_end|>\n"
            "<|im_start|>assistant\n<think>\n\n</think>\n\n")


def prepare(question, stories, system):
    """Everything before the model: what was picked, what the page shows, and the prompt (None when the model is not needed)."""
    picked, mode = retrieve(question, stories)
    return {"mode": mode, "sources": [coverage(st, n) for n, st in enumerate(picked, 1)],
            "prompt": build_prompt(question, picked, system) if picked else None}
