/* Reader settings and page behavior. No accounts, nothing is sent anywhere: settings live in this browser only. */
(function () {
  var KEY = "newsdigest.settings", OLD = "newsdigest.filters", LAST = "newsdigest.lastVisit";
  var SIDES = ["left", "center", "right"];

  function defaults() {
    return {lean: {left: true, center: true, right: true}, off: [], signals: true, newMarks: true};
  }
  function merge(base, o) {  // accepts only known keys of the right type, so a bad file can't break the page
    if (!o || typeof o !== "object") return base;
    SIDES.forEach(function (k) { if (o.lean && typeof o.lean[k] === "boolean") base.lean[k] = o.lean[k]; });
    if (Array.isArray(o.off)) base.off = o.off.filter(function (x) { return typeof x === "string"; }).slice(0, 500);
    if (typeof o.signals === "boolean") base.signals = o.signals;
    if (typeof o.newMarks === "boolean") base.newMarks = o.newMarks;
    return base;
  }
  var S = defaults();
  try {  // if storage is unavailable the page still works, it just won't remember
    var raw = localStorage.getItem(KEY);
    if (raw) S = merge(S, JSON.parse(raw));
    else {
      var old = JSON.parse(localStorage.getItem(OLD) || "null");  // earlier versions saved only the four toggles
      if (old) S = merge(S, {lean: old});
    }
  } catch (err) {}
  var prevVisit = 0;
  try { prevVisit = parseInt(localStorage.getItem(LAST) || "0", 10) || 0; } catch (err) {}

  function save() { try { localStorage.setItem(KEY, JSON.stringify(S)); } catch (err) {} }
  window.tallyClock = function (d) { return clock(d); };
  window.tallyAllowed = function (lean, source) { return lean === "none" || (S.lean[lean] && S.off.indexOf(source) < 0); };  // for pages that draw their own lists
  function all(root, sel) { return Array.prototype.slice.call(root.querySelectorAll(sel)); }
  function get(path) { var p = path.split("."); return p.length === 2 ? S[p[0]][p[1]] : S[p[0]]; }
  function set(path, v) { var p = path.split("."); if (p.length === 2) S[p[0]][p[1]] = v; else S[p[0]] = v; }
  function shown(el) {
    var sideOk = el.dataset.lean === "none" || S.lean[el.dataset.lean];  // clips and posts have no side
    return sideOk && S.off.indexOf(el.dataset.source) < 0;
  }

  /* every page: the on/off switches and the reading preferences */
  function applyCommon() {
    var root = document.documentElement;
    root.dataset.signals = S.signals ? "on" : "off";
    all(document, "[data-set]").forEach(function (b) { b.setAttribute("aria-checked", String(get(b.dataset.set))); });
    var note = document.getElementById("switchNote");
    if (note) note.hidden = !filtersActive();
    var sum = document.getElementById("sideSum");
    if (sum) {
      var on = ["left", "center", "right"].filter(function (l) { return S.lean[l]; }).map(function (l) { return l[0].toUpperCase() + l.slice(1); });
      var text = !filtersActive() ? "Showing all sides"
        : "Showing " + (on.length === 3 ? "all sides" : on.length ? on.join(", ") : "no sides") +
          (S.off.length ? ", " + S.off.length + (S.off.length === 1 ? " outlet" : " outlets") + " off" : "");
      sum.textContent = text;
    }
  }

  /* times are built in the server's time zone; show them in the reader's own */
  function clock(d) {
    var t = d.toLocaleTimeString([], {hour: "numeric", minute: "2-digit"});
    return d.toDateString() === new Date().toDateString() ? t : d.toLocaleDateString([], {weekday: "short"}) + " " + t;
  }
  function localTimes(root) {
    all(root || document, "time[data-clock]").forEach(function (t) { t.textContent = clock(new Date(t.getAttribute("datetime"))); });
  }
  function pad2(n) { return (n < 10 ? "0" : "") + n; }
  function filtersActive() {
    return S.off.length > 0 || !S.lean.left || !S.lean.center || !S.lean.right;
  }
  function ticks(span) {
    var steps = [3600, 7200, 21600, 43200, 86400, 172800], step = 604800, out = [];
    for (var i = 0; i < steps.length; i++) { if (span / steps[i] <= 6) { step = steps[i]; break; } }
    for (var k = 1; k * step < span; k++) {
      var p = k * step / span;
      if (p > 0.08 && p < 0.92) out.push([p, step < 86400 ? "+" + (k * step / 3600) + " h" : "+" + (k * step / 86400) + " d"]);
    }
    return out;
  }
  /* the timing facts and timeline follow what the reader has switched on: a hidden outlet is never "first" */
  function refreshFacts(st) {
    var box = st.querySelector(".facts");
    if (!box) return;
    var marks = all(st, ".mk"), rows = all(st, ".tbl tbody tr, .rep"), vis = [];
    marks.forEach(function (m) { var ok = shown(m); m.hidden = !ok; if (ok) vis.push(m); });
    rows.forEach(function (r) { r.hidden = !shown(r); });
    box.hidden = vis.length === 0;
    if (!vis.length) return;
    vis.sort(function (a, b) { return a.dataset.t - b.dataset.t; });
    var t0 = +vis[0].dataset.t, t1 = +vis[vis.length - 1].dataset.t, span = Math.max(t1 - t0, 1);
    vis.forEach(function (m) {
      m.style.setProperty("--p", ((m.dataset.t - t0) / span).toFixed(4));
      m.setAttribute("data-tip", m.dataset.name + " · " + clock(new Date(m.dataset.t * 1000)));
    });
    var first = st.querySelector(".f-first");
    first.querySelector("b").textContent = vis[0].dataset.name;
    var ft = first.querySelector("time");
    ft.setAttribute("datetime", new Date(t0 * 1000).toISOString());
    ft.textContent = clock(new Date(t0 * 1000));
    var utc = first.querySelector(".utc");
    if (utc) { var d0 = new Date(t0 * 1000); utc.textContent = "(" + pad2(d0.getUTCHours()) + ":" + pad2(d0.getUTCMinutes()) + " UTC)"; }
    var tk = st.querySelector(".ticks");
    if (tk) {  // multi-day timelines get relative ticks (+6 h, +1 d) that follow the visible range
      tk.innerHTML = "";
      ticks(span).forEach(function (t) {
        var el = document.createElement("span");
        el.className = "tick"; el.style.setProperty("--p", t[0].toFixed(4)); el.textContent = t[1];
        tk.appendChild(el);
      });
    }
    var ends = st.querySelectorAll(".ends time");
    [[ends[0], t0], [ends[1], t1]].forEach(function (p) {
      p[0].setAttribute("datetime", new Date(p[1] * 1000).toISOString());
      p[0].textContent = clock(new Date(p[1] * 1000));
    });
    var allSides = st.querySelector(".f-all");
    if (allSides) allSides.hidden = filtersActive();  // that sentence is about every outlet, so it only shows when nothing is switched off
  }

  /* news page */
  function applyNews() {
    /* two lists of the same videos: the strip below the articles (phones, tablets) and the rail rows (wide screens) */
    all(document, ".videos, .rv-list").forEach(function (box) {
      var rail = box.classList.contains("rv-list"), limit = rail ? 4 : 6, vis = 0;
      all(box, ".video").forEach(function (v) {
        var ok = shown(v);
        v.hidden = !ok;
        v.classList.toggle("extra", ok && ++vis > limit);
      });
      var btn = document.getElementById(rail ? "railMore" : "allVideos"), open = box.classList.contains("all");
      if (btn) {
        btn.hidden = vis <= limit;
        btn.textContent = open ? (rail ? "Show fewer" : "Show fewer videos") : (rail ? "Show all " + vis + " videos" : "Show all " + vis + " videos");
        btn.setAttribute("aria-expanded", String(open));
      }
      var panel = box.closest(".rail-videos");
      if (panel) panel.querySelector(".none-left").hidden = vis > 0;
    });
    all(document, ".briefs li").forEach(function (li) { li.hidden = !shown(li); });
    all(document, ".clip").forEach(function (p) { p.hidden = !shown(p); });
    all(document, ".story").forEach(function (st) {
      var total = 0, cols = 0, counts = {left: 0, center: 0, right: 0};
      all(st, ".group").forEach(function (g) {
        var lean = g.dataset.lean, n = 0, extra = 0;
        all(g, "li[data-lean]").forEach(function (li) {
          var ok = shown(li);
          li.hidden = !ok;
          if (ok) { n++; if (li.closest("details")) extra++; }
        });
        var det = g.querySelector("details");
        if (det) { det.hidden = extra === 0; det.querySelector("summary").textContent = "Show " + extra + " more"; }
        g.querySelector(".n").textContent = n;
        g.querySelector(".none").hidden = n > 0;
        g.hidden = !S.lean[lean];
        if (!g.hidden) cols++;
        counts[lean] = n;
        total += n;
      });
      st.hidden = total === 0;
      st.querySelector(".n-total").textContent = total;
      st.querySelector(".w").textContent = total === 1 ? "outlet" : "outlets";
      ["left", "center", "right"].forEach(function (l) {
        st.querySelector('.k[data-lean="' + l + '"] b').textContent = counts[l];
        var seg = st.querySelector('.seg[data-lean="' + l + '"]');
        if (seg) { seg.style.flexGrow = counts[l]; seg.hidden = counts[l] === 0; }
      });
      st.querySelector(".bar").setAttribute("aria-label",
        "Outlets covering this story: left " + counts.left + ", center " + counts.center + ", right " + counts.right);
      st.querySelector(".groups").style.setProperty("--cols", Math.max(cols, 1));
      var t = parseInt(st.dataset.t, 10);
      st.querySelector(".new").hidden = !(S.newMarks && prevVisit && t > prevVisit);
      refreshFacts(st);
    });
    all(document, "[data-section]").forEach(function (sec) {
      var any = all(sec, ".video, .story, .briefs li, .clip").some(function (el) { return !el.hidden; }) || !sec.querySelector(".video, .story, .briefs li, .clip");
      sec.querySelector(".none-left").hidden = any;
    });
    fitClips();
  }

  /* clips: wide screens show one row until asked; the button only appears when there is more than one row */
  function fitClips() {
    var strip = document.querySelector(".clips"), btn = document.getElementById("allClips");
    if (!strip || !btn) return;
    var open = strip.classList.contains("all");
    var n = all(strip, ".clip").filter(function (c) { return !c.hidden; }).length;
    btn.hidden = !(open || strip.scrollHeight > strip.clientHeight + 4);
    btn.textContent = open ? "Show fewer clips" : "Show all " + n + " clips";
    btn.setAttribute("aria-expanded", String(open));
  }

  /* story page: the chart, list and counts follow the reader's switches */
  function applyStory() {
    var root = document.querySelector(".story-page");
    if (!root) return;
    all(root, ".clip").forEach(function (p) { p.hidden = !shown(p); });
    refreshFacts(root);
    var seen = {left: {}, center: {}, right: {}}, total = {};
    all(root, ".rep").forEach(function (r) { if (!r.hidden) { seen[r.dataset.lean][r.dataset.source] = 1; total[r.dataset.source] = 1; } });
    var n = Object.keys(total).length;
    root.querySelector(".n-total").textContent = n;
    root.querySelector(".w").textContent = n === 1 ? "outlet" : "outlets";
    ["left", "center", "right"].forEach(function (l) {
      var c = Object.keys(seen[l]).length;
      root.querySelector('.k[data-lean="' + l + '"] b').textContent = c;
      var seg = root.querySelector('.seg[data-lean="' + l + '"]');
      if (seg) { seg.style.flexGrow = c; seg.hidden = c === 0; }
    });
  }

  /* archive page: filter the list as you type */
  function applyArchive() {
    var box = document.getElementById("find");
    if (!box) return;
    var q = box.value.trim().toLowerCase(), shownN = 0, items = all(document, ".stories-list li[data-q]");
    items.forEach(function (li) { var ok = !q || li.dataset.q.indexOf(q) >= 0; li.hidden = !ok; if (ok) shownN++; });
    all(document, ".day").forEach(function (d) { d.hidden = !all(d, "li[data-q]").some(function (li) { return !li.hidden; }); });
    document.getElementById("found").textContent = (q ? shownN + " of " + items.length : items.length) + " stories";
  }

  /* sources page */
  function applySources() {
    var on = 0, rows = all(document, ".src-row");
    rows.forEach(function (row) {
      var key = row.dataset.source, isOn = S.off.indexOf(key) < 0, hiddenBySide = !shown({dataset: {lean: row.dataset.lean, source: ""}});
      row.classList.toggle("off", !isOn);
      row.querySelector(".trow").setAttribute("aria-checked", String(isOn));
      row.querySelector(".s-note").hidden = !(isOn && hiddenBySide);
      if (isOn) on++;
    });
    var c = document.getElementById("srcCount");
    if (c) c.textContent = on + " of " + rows.length + " sources are on";
  }

  /* settings page */
  function applySettings() {
    var n = document.getElementById("offCount");
    if (n) n.textContent = S.off.length === 0 ? "All sources are on." : S.off.length + " source" + (S.off.length === 1 ? " is" : "s are") + " turned off.";
  }

  function applyAll() {
    applyCommon();
    var page = document.body.dataset.page;
    if (page === "news") applyNews();
    if (page === "sources") applySources();
    if (page === "settings") applySettings();
    if (page === "story") applyStory();
  }

  document.addEventListener("click", function (ev) {
    var sw = ev.target.closest("[data-set]");
    if (sw) { set(sw.dataset.set, !get(sw.dataset.set)); save(); applyAll(); return; }
    var src = ev.target.closest(".src-row .trow");
    if (src) {
      var key = src.closest(".src-row").dataset.source, i = S.off.indexOf(key);
      if (i < 0) S.off.push(key); else S.off.splice(i, 1);
      save(); applyAll();
    }
  });

  function say(msg) { var el = document.getElementById("status"); if (el) el.textContent = msg; }

  /* settings page: export, import, reset */
  var exp = document.getElementById("export"), imp = document.getElementById("import"), file = document.getElementById("file"), reset = document.getElementById("reset");
  if (exp) exp.addEventListener("click", function () {
    var blob = new Blob([JSON.stringify(merge(defaults(), S), null, 2)], {type: "application/json"});
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = "news-settings.json";
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 1000);
    say("Settings file downloaded.");
  });
  if (imp && file) {
    imp.addEventListener("click", function () { file.click(); });
    file.addEventListener("change", function () {
      var f = file.files && file.files[0];
      if (!f) return;
      if (f.size > 100000) { say("That file is too large to be a settings file."); return; }
      var r = new FileReader();
      r.onload = function () {
        try { S = merge(defaults(), JSON.parse(String(r.result))); save(); applyAll(); say("Settings imported."); }
        catch (err) { say("That file isn't a settings file."); }
      };
      r.readAsText(f);
      file.value = "";
    });
  }
  if (reset) {
    var armed = null;
    reset.addEventListener("click", function () {
      if (!armed) {
        reset.textContent = "Tap again to confirm";
        armed = setTimeout(function () { reset.textContent = "Reset to defaults"; armed = null; }, 4000);
        return;
      }
      clearTimeout(armed); armed = null;
      reset.textContent = "Reset to defaults";
      S = defaults(); save(); applyAll(); say("Settings reset to defaults.");
    });
  }

  var statBtns = all(document, ".stat");
  var showStat = function (key) {
    statBtns.forEach(function (b) {
      var on = b.getAttribute("data-stat") === key;
      b.setAttribute("aria-expanded", on ? "true" : "false");
      var p = document.getElementById("stat-" + b.getAttribute("data-stat"));
      if (p) p.hidden = !on;
    });
  };
  statBtns.forEach(function (b) {
    b.addEventListener("click", function () { showStat(b.getAttribute("aria-expanded") === "true" ? null : b.getAttribute("data-stat")); });
  });
  all(document, "[data-close]").forEach(function (c) {
    c.addEventListener("click", function () {
      var panel = c.closest(".stat-panel"), key = panel.id.replace("stat-", "");
      showStat(null);
      var btn = document.querySelector('.stat[data-stat="' + key + '"]'); if (btn) btn.focus();
    });
  });

  all(document, ".c-filter").forEach(function (g) {
    var panel = g.closest(".stat-panel");
    g.addEventListener("click", function (ev) {
      var btn = ev.target.closest("button"); if (!btn) return;
      var topic = btn.getAttribute("data-topic");
      all(g, "button").forEach(function (o) { o.setAttribute("aria-pressed", o === btn ? "true" : "false"); });
      all(panel, ".c-rows li").forEach(function (li) { li.hidden = !!topic && li.getAttribute("data-topic") !== topic; });
    });
  });

  /* story rows: one open at a time; the open row shows who covered it, and each headline inside opens the article */
  function openStory(st, on, scroll) {
    var head = st.querySelector(".s-head"), panel = st.querySelector(".s-panel");
    if (!head || !panel) return;
    head.setAttribute("aria-expanded", String(on));
    panel.hidden = !on;
    st.classList.toggle("open", on);
    if (on && scroll && st.getBoundingClientRect().top < (document.getElementById("tabs") ? document.getElementById("tabs").offsetHeight : 0) + 4) st.scrollIntoView({block: "start"});
  }
  document.addEventListener("click", function (ev) {
    var head = ev.target.closest(".s-head");
    if (!head) return;
    var st = head.closest(".story"), willOpen = head.getAttribute("aria-expanded") !== "true";
    all(document, ".story.open").forEach(function (o) { if (o !== st) openStory(o, false); });
    openStory(st, willOpen, true);
  });
  if (/^#s-/.test(location.hash)) {
    var linked = document.getElementById(location.hash.slice(1));
    if (linked && linked.classList.contains("story")) { openStory(linked, true); linked.scrollIntoView(); }
  }

  var railBtn = document.getElementById("railMore");
  if (railBtn) railBtn.addEventListener("click", function () { document.querySelector(".rv-list").classList.toggle("all"); applyAll(); });
  var avBtn = document.getElementById("allVideos");
  if (avBtn) avBtn.addEventListener("click", function () { document.querySelector(".videos").classList.toggle("all"); applyAll(); });
  var zones = document.querySelectorAll(".tz");
  for (var zi = 0; zi < zones.length; zi++) { try { zones[zi].textContent = Intl.DateTimeFormat().resolvedOptions().timeZone; } catch (err) {} }
  var cite = document.getElementById("cite");
  if (cite) {
    var template = cite.textContent;
    var local = /^file:$/.test(location.protocol) || /^(localhost$|127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|.*\.local$)/.test(location.hostname);
    var fill = function () {
      var now = new Date(), pad2 = function (n) { return (n < 10 ? "0" : "") + n; };
      var stamp = now.getUTCFullYear() + "-" + pad2(now.getUTCMonth() + 1) + "-" + pad2(now.getUTCDate()) + " " + pad2(now.getUTCHours()) + ":" + pad2(now.getUTCMinutes());
      var where = local ? "local copy only, no public address yet (use the story ID above)"
        : location.href.split("#")[0] + " (outlets and side labels: " + location.href.replace(/story\/[^\/]*$/, "").split("#")[0] + "sources.html)";
      cite.textContent = template.replace("[retrieval time]", stamp).replace("[where]", where);
    };
    fill();
    var copy = document.getElementById("copyCite");
    copy.addEventListener("click", function () {
      fill();
      var done = function () { say("Citation copied."); };
      var fallback = function () {
        var r = document.createRange(); r.selectNodeContents(cite);
        var sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(r);
        try { document.execCommand("copy") ? done() : say("The text is selected above. Copy it from there."); } catch (err) { say("The text is selected above. Copy it from there."); }
      };
      if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(cite.textContent).then(done, fallback); else fallback();
    });
  }
  var find = document.getElementById("find");
  if (find) find.addEventListener("input", applyArchive);
  var sideD = document.getElementById("sideD");
  if (sideD) {
    var touched = false;
    sideD.querySelector("summary").addEventListener("click", function () { touched = true; });
    var syncSide = function () {
      if (window.matchMedia("(min-width: 1000px)").matches) sideD.open = true;
      else if (!touched) sideD.open = false;
    };
    syncSide();
    window.addEventListener("resize", syncSide);
  }
  var ac = document.getElementById("allClips");
  if (ac) {
    ac.addEventListener("click", function () { document.querySelector(".clips").classList.toggle("all"); fitClips(); });
    window.addEventListener("resize", fitClips);
  }
  var allOn = document.getElementById("allOn");
  if (allOn) allOn.addEventListener("click", function () { S.off = []; save(); applyAll(); });

  /* "first reported 12 min ago": kept current while the page is open */
  function agoTimes() {
    all(document, "time[data-ago]").forEach(function (t) {
      var m = Math.max(0, Math.round((Date.now() - new Date(t.getAttribute("datetime")).getTime()) / 60000));
      t.textContent = m < 1 ? "first reported just now" : m < 60 ? "first reported " + m + " min ago" : "first reported " + Math.floor(m / 60) + " h " + (m % 60) + " min ago";
    });
  }
  function sinceTimes() {  // "3 h ago" on videos
    all(document, "time[data-since]").forEach(function (t) {
      var m = Math.max(0, Math.round((Date.now() - new Date(t.getAttribute("datetime")).getTime()) / 60000));
      t.textContent = m < 1 ? "just now" : m < 60 ? m + " min ago" : m < 1440 ? Math.floor(m / 60) + " h ago" : Math.floor(m / 1440) + " d ago";
    });
  }
  agoTimes(); sinceTimes(); setInterval(function () { agoTimes(); sinceTimes(); }, 60000);
  localTimes();
  applyAll();

  /* news page: new since your last visit, and the section tabs */
  if (document.body.dataset.page === "news") {
    if (prevVisit && S.newMarks) {
      var fresh = all(document, ".story").filter(function (st) { return !st.querySelector(".new").hidden; }).length;
      var since = document.getElementById("since"), d = new Date(prevVisit * 1000);
      since.textContent = (fresh ? fresh + " new" : "Nothing new") + " since " + d.toLocaleTimeString([], {hour: "numeric", minute: "2-digit"});
      since.hidden = false;
    }
    try { localStorage.setItem(LAST, String(Math.floor(Date.now() / 1000))); } catch (err) {}

    var bar = document.getElementById("tabs"), links = all(document, "#tabs a");
    var secs = links.map(function (a) { return document.querySelector(a.getAttribute("href")); });
    var pad = function () { document.documentElement.style.scrollPaddingTop = (bar.offsetHeight + 8) + "px"; };
    var spy = function () {
      var y = bar.offsetHeight + 24, cur = 0;
      var last = 0;  // a section hidden at this width (Videos on wide screens, where they sit in the rail) is skipped
      secs.forEach(function (sec, i) { if (!sec.offsetParent) return; last = i; if (sec.getBoundingClientRect().top <= y) cur = i; });
      if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2) cur = last;
      links.forEach(function (a, i) { a.setAttribute("aria-current", String(i === cur)); });
    };
    pad(); spy();
    window.addEventListener("resize", function () { pad(); spy(); });
    window.addEventListener("scroll", spy, {passive: true});

    /* staying current: say so when the page is old, and offer a refresh when a newer build exists */
    var meta = document.querySelector('meta[name="built"]'), built = meta ? parseInt(meta.content, 10) : 0;
    var feed = document.querySelector(".feed");
    if (built && feed) {
      var age = Date.now() / 1000 - built;
      if (age > 5400) {
        var hrs = Math.floor(age / 3600), note = document.createElement("p");
        note.className = "notice";
        note.textContent = "This page was built " + (hrs >= 48 ? Math.floor(hrs / 24) + " days" : hrs + (hrs === 1 ? " hour" : " hours")) + " ago, so newer stories may exist.";
        feed.insertBefore(note, feed.firstChild);
      }
      var toast = null, dismissed = 0;
      var showToast = function (when) {
        if (toast || dismissed === when) return;
        toast = document.createElement("div");
        toast.className = "toast"; toast.setAttribute("role", "status");
        toast.innerHTML = '<span>A newer update is ready.</span><span class="btns"><button class="btn primary" type="button">Refresh</button><button class="btn" type="button">Later</button></span>';
        var btns = toast.querySelectorAll("button");
        btns[0].addEventListener("click", function () { location.reload(); });
        btns[1].addEventListener("click", function () { dismissed = when; toast.remove(); toast = null; });
        document.body.appendChild(toast);
      };
      var check = function () {
        if (document.hidden) return;
        fetch("build.json", {cache: "no-store"}).then(function (r) { return r.ok ? r.json() : null; })
          .then(function (j) { if (j && j.built > built) showToast(j.built); })
          .catch(function () {});  // offline or opened from a file: nothing to do
      };
      setInterval(check, 5 * 60 * 1000);
      document.addEventListener("visibilitychange", check);
      check();
    }
  }
})();
