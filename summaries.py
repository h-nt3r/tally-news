"""Machine-written "what happened" summaries, made locally by a small open model (llama.cpp + Qwen).

The model only restates what the outlets' own excerpts say. How outlets differ is never model-written: the page shows each
outlet's own headline, grouped by side. Every summary passes a mechanical check before it is shown, and the whole thing
is optional: with no model installed the page simply has no summaries. Summaries are cached by the story's headlines,
the prompt and the model, so a rebuild only works on stories that are new or changed.
"""
import hashlib, json, os, re, subprocess, sys, time
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


FALLBACK_H = 48       # a story's previous summary stays on the page this long while its replacement is written
RETRY_BAD_H = 2       # a summary that failed the check is tried again after this long
RETRY_BASE_MIN = 10   # after a timeout or crash on a story: wait 10, 20, 40... minutes before trying it again (never more than 6 h)
TIMEOUT_S = 420       # one generation on an old dual-core CPU takes about a minute when the machine is idle, several when it is busy


def _sides(members):
    return sorted({m["lean"] for m in members})


def _story_key(members, prompt, model, sid=None):
    """Cache key. With a story id it names the story and the sides that cover it, so a reworded headline or one more outlet on a
    side that is already there does not throw the summary away; a new side joining does. Without an id (a story the archive has not
    numbered yet) it falls back to the exact excerpts, which is how keys were made before."""
    if sid:
        basis = json.dumps(["sid", sid, _sides(members), prompt, model.name])
    else:
        basis = json.dumps([sorted((m["source"], m["title"]) for m in pick_excerpts(members)), prompt, model.name])
    return hashlib.sha1(basis.encode()).hexdigest()[:16]


def _generate(members, prompt, binary, model, threads, timeout=TIMEOUT_S):
    lines = [f"- {m['title']}. {m.get('text', '')[:200]}" for m in pick_excerpts(members)]
    user = "Excerpts:\n" + "\n".join(lines) + "\n\nTwo-sentence summary:"
    full = (f"<|im_start|>system\n{prompt}<|im_end|>\n<|im_start|>user\n{user}<|im_end|>\n"
            f"<|im_start|>assistant\n<think>\n\n</think>\n\n")  # Qwen3 chat format, thinking off
    p = subprocess.run([str(binary), "-m", str(model), "-p", full, "-n", "90", "-c", "3072", "-t", str(threads),
                        "--temp", "0.2", "-no-cnv", "--no-display-prompt"], capture_output=True, text=True, timeout=timeout)
    text = p.stdout.replace("[end of text]", "").strip()
    if text and text[-1] not in ".!?\"”":  # cut off mid-sentence: keep only whole sentences
        text = " ".join(sentences(text)[:-1]).replace("․", ".")
    return text.replace("․", ".")


def _load(path):
    try:
        data = json.loads(Path(path).read_text())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write(path, data):
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(data))
    os.replace(tmp, path)


def _save_cache(path, mine, now):
    """Fold our changes into whatever is on disk right now (a build and the summary job can run at the same time), and drop old entries."""
    try:
        disk = _load(path)
        disk.update(mine)
        _write(path, {k: v for k, v in disk.items() if now - v.get("at", now) < KEEP_DAYS * 86400})
    except Exception:
        pass


def latest_by_sid(hist_dir):
    """{story id: {"text", "model"}} for the newest summary of each story that passed the check, for pages (a story's own page) that
    are not built from the live story list. Never raises."""
    best = {}
    for v in _load(Path(hist_dir) / "summaries.json").values():
        if v.get("ok") and v.get("sid") and v.get("text") and v.get("at", 0) >= best.get(v["sid"], {"at": -1})["at"]:
            best[v["sid"]] = v
    return {sid: {"text": v["text"], "model": v.get("model", "")} for sid, v in best.items()}


def _backed_off(fail, now):
    """True while a story that just timed out or crashed is resting, so one hard story cannot use every build's slot."""
    return bool(fail) and now - fail["at"] < min(RETRY_BASE_MIN * 60 * 2 ** (fail["n"] - 1), 6 * 3600)


def attach(stories, settings, hist_dir, per_build=None, budget_s=None):
    """Set story["summary"] = {"text", "model"} on every story that has a passing summary. Never raises. Returns how many it wrote.
    A story whose summary is being rewritten keeps showing its previous one (FALLBACK_H) rather than going blank."""
    if not settings.get("summaries", False):
        return 0
    binary, model = ROOT / settings.get("summary_bin", "tools/llama/llama-completion"), ROOT / settings.get("summary_model", "tools/Qwen3-4B-Q4_K_M.gguf")
    cache_path, fails_path = Path(hist_dir) / "summaries.json", Path(hist_dir) / "summary_fails.json"
    cache, fails = _load(cache_path), _load(fails_path)
    have_model = binary.exists() and model.exists()
    if not have_model:
        print(f"  summaries: model or llama.cpp not found ({model.name}); showing cached summaries only", file=sys.stderr)
    prompt = PROMPT_FILE.read_text().strip()
    per_build = settings.get("summary_per_build", 6) if per_build is None else per_build
    budget_s = settings.get("summary_budget_s", 420) if budget_s is None else budget_s
    timeout = settings.get("summary_timeout_s", TIMEOUT_S)
    threads = settings.get("summary_threads", 2)
    start, made, now = time.time(), 0, int(time.time())
    changed, fails_changed, resting, earlier = {}, False, 0, 0
    newest = {}  # the newest passing summary of each story id: what a story shows while its current one is missing
    for v in cache.values():
        if v.get("ok") and v.get("sid") and now - v.get("at", 0) < FALLBACK_H * 3600 and v["at"] >= newest.get(v["sid"], {"at": 0})["at"]:
            newest[v["sid"]] = v

    def generate(st, k, sid):
        """One summary for this story, cached under k. A timeout or crash is remembered as a failed try, not as an answer."""
        nonlocal made, fails_changed
        made += 1
        corpus = " ".join(m["title"] + " " + m.get("text", "") for m in st["members"])  # everything the story's outlets said
        try:
            text = _generate(st["members"], prompt, binary, model, threads, timeout)
            problems = check(text, corpus, [m["source"] for m in st["members"]]) if text else ["empty"]
        except Exception as ex:
            fails[k] = {"n": fails.get(k, {"n": 0})["n"] + 1, "at": int(time.time())}
            fails_changed = True
            print(f"  summaries: one story skipped ({str(ex)[:60]}), will wait before trying it again", file=sys.stderr)
            return None
        if k in fails:
            del fails[k]
            fails_changed = True
        ent = cache[k] = {"text": text, "ok": not problems, "problems": problems, "model": model.name, "at": int(time.time())}
        if sid:
            ent["sid"] = sid
        changed[k] = ent
        _save_cache(cache_path, {k: ent}, now)  # save as we go, so an interrupted build keeps its progress
        return ent

    # stories that are breaking go first, so a new one is not left waiting behind older stories (stable sort keeps page order otherwise)
    for st in sorted(stories, key=lambda st: 0 if st.get("breaking") else 1):
        sid = st.get("sid")
        k = _story_key(st["members"], prompt, model, sid)
        ent = cache.get(k)
        if ent is None and sid:  # a summary made when keys were per excerpt: adopt it under the story's key
            old = cache.get(_story_key(st["members"], prompt, model))
            if old is not None:
                ent = cache[k] = dict(old, sid=sid)
                changed[k] = ent
        if ent is not None and sid and ent.get("sid") != sid:
            ent["sid"] = sid
            changed[k] = ent
        if ent is not None and not ent.get("ok") and now - ent.get("at", now) > RETRY_BAD_H * 3600:
            ent = None  # it failed the check a while ago; the story may read differently now
        if ent is None and have_model and made < per_build and time.time() - start < budget_s:
            if _backed_off(fails.get(k), now):
                resting += 1
            else:
                ent = generate(st, k, sid)
        if ent and ent.get("ok"):
            st["summary"] = {"text": ent["text"], "model": ent["model"]}
            st["_summary_key"] = k
        elif sid and sid in newest:
            st["summary"] = {"text": newest[sid]["text"], "model": newest[sid]["model"]}
            earlier += 1
    if have_model and made < per_build and time.time() - start < budget_s:
        # nothing was missing, so use the spare time to rewrite the oldest summary that has gone stale
        stale = sorted((st for st in stories if st.get("_summary_key") and now - cache[st["_summary_key"]]["at"] > REFRESH_H * 3600),
                       key=lambda st: cache[st["_summary_key"]]["at"])
        for st in stale[:1]:
            k = st["_summary_key"]
            if _backed_off(fails.get(k), now):
                continue
            before = cache[k]
            ent = generate(st, k, st.get("sid"))
            if ent and ent["ok"]:
                st["summary"] = {"text": ent["text"], "model": ent["model"]}
            elif ent:  # the rewrite failed the check: keep the summary that passed
                cache[k] = before
                changed[k] = before
                _save_cache(cache_path, {k: before}, now)
    if changed or any(now - v.get("at", now) >= KEEP_DAYS * 86400 for v in cache.values()):
        _save_cache(cache_path, changed, now)
    if fails_changed or any(now - f["at"] > 7 * 86400 for f in fails.values()):
        try:
            _write(fails_path, {k: f for k, f in fails.items() if now - f["at"] < 7 * 86400})
        except Exception:
            pass
    shown = sum(1 for st in stories if "summary" in st)
    notes = ([f"{earlier} showing an earlier version while the new one is written"] if earlier else []) + ([f"{resting} resting after a timeout"] if resting else [])
    print(f"  summaries: {made} new in {time.time() - start:.0f}s, {shown} of {len(stories)} stories have one"
          f"{'' if made < per_build else ' (per-build limit reached; the rest follow on later builds)'}"
          f"{' (' + '; '.join(notes) + ')' if notes else ''}")
    return made
