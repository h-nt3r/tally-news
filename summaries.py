"""Machine-written "what happened" summaries, made locally by a small open model (llama.cpp + Qwen).

The model only restates what the outlets' own excerpts say. How outlets differ is never model-written: the page shows each
outlet's own headline, grouped by side. Every summary passes a mechanical check before it is shown, and the whole thing
is optional: with no model installed the page simply has no summaries. Summaries are cached by the story's headlines,
the prompt and the model, so a rebuild only works on stories that are new or changed.
"""
import hashlib, json, re, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROMPT_FILE = ROOT / "config" / "summary_prompt.txt"
KEEP_DAYS = 14
STOP = set("the a an in on of to and for with after as at by from is are was were has have will it its that this he she they his her "
           "their but not who more than into over about been said says".split())
ABBR = re.compile(r"\b(Sen|Rep|Gov|Lt|Dr|Mr|Mrs|Ms|St|Jr|Sr|Gen|Col|Sgt|Capt|Rev|vs|etc|U\.S|U\.K|No)\.")


def _words(t):
    return re.findall(r"[A-Za-z0-9][A-Za-z0-9'’\.\-]*", t)


def sentences(text):
    return [s for s in re.split(r"(?<=[.!?])\s+", ABBR.sub(lambda m: m.group(0)[:-1] + "․", text)) if s.strip()]


def check(summary, corpus, outlets):
    """Mechanical check, not proof of truth: no outlets or sides, no numbers or names the excerpts don't contain."""
    low, problems = corpus.lower(), []
    for o in outlets:
        if o.lower() in summary.lower():
            problems.append(f"names outlet {o}")
    if re.search(r"\b((the )?(left|right)[- ](leaning|wing|of center)|center[- ](left|right)|centrist|(the )?(political )?(left|right) (outlets|media|press)|conservative outlets|liberal outlets|outlets (differ|disagree|emphasi[sz]e))", summary, re.I):
        problems.append("talks about sides or coverage")
    for n in re.findall(r"\d[\d,\.]*", summary):
        if n.strip(".,") not in corpus:
            problems.append(f"number {n} not in sources")
    sents = sentences(summary)
    for s in sents:
        for i, w in enumerate(_words(s)):
            if i > 0 and w[0].isupper() and w.lower().strip(".'’") not in STOP and not w.isdigit() and not _supported(w, low):
                problems.append(f"name '{w}' not in sources")
    if not 1 <= len(sents) <= 3:
        problems.append("not 1-3 sentences")
    return problems


# words a summary may use when the excerpts only carry the short form ("U.S.", "UK", "Democrat")
ALIASES = {
    "united": r"\bu\.?s\.?a?\b|\bu\.?k\.?\b|\bunited\b", "states": r"\bu\.?s\.?a?\b|\bstates\b", "kingdom": r"\bu\.?k\.?\b|\bbritain\b|\bbritish\b|\bkingdom\b",
    "american": r"\bamerica|\bu\.?s\.?a?\b", "americans": r"\bamerica|\bu\.?s\.?a?\b",
    "democratic": r"\bdemocrat", "republican": r"\bgop\b|\brepublican",
}


def _supported(word, low):
    w = re.sub(r"['’]s?$", "", word.lower().strip(".,"))
    return w in low or (w in ALIASES and re.search(ALIASES[w], low) is not None)


MAX_EXCERPTS = 8      # the prompt is read by a small model on an old CPU, so its length is what costs time
REFRESH_H = 6         # a summary this old is rewritten when there is spare time, since stories develop


def pick_excerpts(members):
    """At most MAX_EXCERPTS members: the earliest report from each side first, then the next earliest. Stable as a story
    grows: later outlets joining do not change the picks once there are enough early ones."""
    ordered = sorted(members, key=lambda m: (m["when"], m["source"]))
    picked, seen = [], set()
    for m in ordered:  # one from each side, earliest first
        if m["lean"] not in seen:
            seen.add(m["lean"]); picked.append(m)
    for m in ordered:
        if len(picked) >= MAX_EXCERPTS:
            break
        if m not in picked:
            picked.append(m)
    return sorted(picked[:MAX_EXCERPTS], key=lambda m: (m["when"], m["source"]))


def _story_key(members, prompt, model):
    basis = json.dumps([sorted((m["source"], m["title"]) for m in pick_excerpts(members)), prompt, model.name])
    return hashlib.sha1(basis.encode()).hexdigest()[:16]


def _generate(members, prompt, binary, model, threads):
    lines = [f"- {m['title']}. {m.get('text', '')[:200]}" for m in pick_excerpts(members)]
    user = "Excerpts:\n" + "\n".join(lines) + "\n\nTwo-sentence summary:"
    full = (f"<|im_start|>system\n{prompt}<|im_end|>\n<|im_start|>user\n{user}<|im_end|>\n"
            f"<|im_start|>assistant\n<think>\n\n</think>\n\n")  # Qwen3 chat format, thinking off
    p = subprocess.run([str(binary), "-m", str(model), "-p", full, "-n", "90", "-c", "3072", "-t", str(threads),
                        "--temp", "0.2", "-no-cnv", "--no-display-prompt"], capture_output=True, text=True, timeout=240)
    text = p.stdout.replace("[end of text]", "").strip()
    if text and text[-1] not in ".!?\"”":  # cut off mid-sentence: keep only whole sentences
        text = " ".join(sentences(text)[:-1]).replace("․", ".")
    return text.replace("․", ".")


def attach(stories, settings, hist_dir, per_build=None, budget_s=None):
    """Set story["summary"] = {"text", "model"} on every story that has a passing summary. Never raises. Returns how many it wrote."""
    if not settings.get("summaries", False):
        return 0
    binary, model = ROOT / settings.get("summary_bin", "tools/llama/llama-completion"), ROOT / settings.get("summary_model", "tools/Qwen3-4B-Q4_K_M.gguf")
    cache_path = Path(hist_dir) / "summaries.json"
    try:
        cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    except Exception:
        cache = {}
    have_model = binary.exists() and model.exists()
    if not have_model:
        print(f"  summaries: model or llama.cpp not found ({model.name}); showing cached summaries only", file=sys.stderr)
    prompt = PROMPT_FILE.read_text().strip()
    per_build = settings.get("summary_per_build", 6) if per_build is None else per_build
    budget_s = settings.get("summary_budget_s", 420) if budget_s is None else budget_s
    start, made, now = time.time(), 0, int(time.time())
    # stories that are breaking go first, so a new one is not left waiting behind older stories (stable sort keeps page order otherwise)
    for st in sorted(stories, key=lambda st: 0 if st.get("breaking") else 1):
        k = _story_key(st["members"], prompt, model)
        ent = cache.get(k)
        if ent is None and have_model and made < per_build and time.time() - start < budget_s:
            corpus = " ".join(m["title"] + " " + m.get("text", "") for m in st["members"])  # everything the story's outlets said
            try:
                text = _generate(st["members"], prompt, binary, model, settings.get("summary_threads", 2))
                problems = check(text, corpus, [m["source"] for m in st["members"]]) if text else ["empty"]
            except Exception as ex:  # a timeout or crash says nothing about the story: don't remember it, try again next build
                print(f"  summaries: one story skipped ({str(ex)[:60]})", file=sys.stderr)
                made += 1
                continue
            ent = cache[k] = {"text": text, "ok": not problems, "problems": problems, "model": model.name, "at": now}
            made += 1
            try:  # save as we go, so an interrupted build keeps its progress
                cache_path.write_text(json.dumps(cache))
            except Exception:
                pass
        if ent and ent.get("ok"):
            st["summary"] = {"text": ent["text"], "model": ent["model"]}
            st["_summary_key"] = k
    if have_model and made < per_build and time.time() - start < budget_s:
        # nothing was missing, so use the spare time to rewrite the oldest summary that has gone stale
        stale = sorted((st for st in stories if st.get("_summary_key") and now - cache[st["_summary_key"]]["at"] > REFRESH_H * 3600),
                       key=lambda st: cache[st["_summary_key"]]["at"])
        for st in stale[:1]:
            k = st["_summary_key"]
            corpus = " ".join(m["title"] + " " + m.get("text", "") for m in st["members"])
            try:
                text = _generate(st["members"], prompt, binary, model, settings.get("summary_threads", 2))
                problems = check(text, corpus, [m["source"] for m in st["members"]]) if text else ["empty"]
            except Exception as ex:
                print(f"  summaries: refresh skipped ({str(ex)[:60]})", file=sys.stderr)
                problems = ["failed"]
            if not problems:
                cache[k] = {"text": text, "ok": True, "problems": [], "model": model.name, "at": now}
                st["summary"] = {"text": text, "model": model.name}
                made += 1
    cache = {k: v for k, v in cache.items() if now - v.get("at", now) < KEEP_DAYS * 86400}
    try:
        cache_path.write_text(json.dumps(cache))
    except Exception:
        pass
    shown = sum(1 for st in stories if "summary" in st)
    print(f"  summaries: {made} new in {time.time() - start:.0f}s, {shown} of {len(stories)} stories have one"
          f"{'' if made < per_build else ' (per-build limit reached; the rest follow on later builds)'}")
    return made
