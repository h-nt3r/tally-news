/* The Ask page. It sends your question to the helper running on this computer (chat_server.py) and shows what comes back:
   first the stories it picked with who covered each one (copied from the data), then the model's answer as it is written.
   Nothing here talks to any other server. Text from the helper is always inserted as text, never as HTML. */
(function () {
  var root = document.getElementById("ask");
  if (!root) return;
  var $ = function (id) { return document.getElementById(id); };
  var form = $("askForm"), input = $("askQ"), go = $("askGo"), stop = $("askStop"), status = $("askStatus"),
      off = $("askOff"), out = $("askOut"), text = $("askText"), note = $("askNote"), srcHead = $("askSrcHead"),
      srcBox = $("askSources"), ex = $("askEx");
  var base = document.body.getAttribute("data-base") || "";
  /* "Your own computer": this Mac by name, its address on your Wi-Fi (how a phone reaches it), or its .local name. A hosted copy is none of these. */
  var h = location.hostname;
  var local = h === "localhost" || /^127\./.test(h) || /^10\./.test(h) || /^192\.168\./.test(h) || /^172\.(1[6-9]|2\d|3[01])\./.test(h) ||
              /^169\.254\./.test(h) || /^[\w-]+(\.[\w-]+)*\.local$/.test(h);
  var touch = window.matchMedia && matchMedia("(pointer: coarse)").matches;  /* a phone or tablet: do not pop the keyboard up on its own */
  var api = location.protocol + "//" + location.hostname + ":" + root.getAttribute("data-port");
  var SIDE = {left: "Left", center: "Center", right: "Right"};
  var ctl = null, timer = null, t0 = 0, label = "", answer = "", n = 0;

  function el(tag, cls, txt) {
    var x = document.createElement(tag);
    if (cls) x.className = cls;
    if (txt != null) x.textContent = txt;
    return x;
  }
  function safe(u) { return /^https?:\/\//i.test(u || "") ? u : null; }
  function say(t) { status.textContent = t || ""; status.classList.remove("bad"); }
  function bad(t) { status.textContent = t; status.classList.add("bad"); }
  function offline(title, body, cmd) {
    off.hidden = false;
    off.textContent = "";
    off.appendChild(el("h2", null, title));
    off.appendChild(el("p", "muted-note", body));
    if (cmd) off.appendChild(el("pre", "ask-cmd", cmd));
  }
  function busy(on) {
    go.hidden = on; stop.hidden = !on; input.disabled = on;
    if (on) { t0 = Date.now(); timer = setInterval(tick, 1000); } else { clearInterval(timer); }
  }
  function tick() {
    var s = Math.round((Date.now() - t0) / 1000);
    status.textContent = label + (label ? " " : "") + "(" + s + " s)";
  }

  /* The answer, with [1] turned into a link to the story card it points at. Only numbers of stories shown are linked. */
  function paint() {
    text.textContent = "";
    answer.split(/(\[\d\])/).forEach(function (part) {
      var m = /^\[(\d)\]$/.exec(part);
      if (m && +m[1] >= 1 && +m[1] <= n) {
        var a = el("a", "cite", part);
        a.href = "#askS" + m[1];
        text.appendChild(a);
      } else if (part) text.appendChild(document.createTextNode(part));
    });
  }

  function card(s) {
    var c = el("article", "ask-story"); c.id = "askS" + s.n;
    var h = el("h3"); h.appendChild(el("span", "ask-n", "[" + s.n + "]"));
    var page = /^story\/[\w.-]+\.html$/.test(s.page || "") ? base + s.page : null;
    if (page) { var a = el("a", null, s.label); a.href = page; h.appendChild(a); } else h.appendChild(el("span", null, s.label));
    c.appendChild(h);
    var row = el("p", "ask-cov");
    ["left", "center", "right"].forEach(function (side) {
      var p = el("span", "pill lean-" + side); p.appendChild(document.createElement("i"));
      p.appendChild(document.createTextNode(SIDE[side] + " " + (s.counts[side] || 0)));
      row.appendChild(p); row.appendChild(document.createTextNode(" "));
    });
    if (s.not_covered_by && s.not_covered_by.length) row.appendChild(el("span", "badge gap", "Not covered by " + s.not_covered_by.join(" or ")));
    c.appendChild(row);
    var d = el("details", "ask-heads"); d.appendChild(el("summary", null, "The " + s.outlets + " outlets' own headlines"));
    ["left", "center", "right"].forEach(function (side) {
      var list = s.by_side[side] || [];
      if (!list.length) return;
      var g = el("div", "ask-side lean-" + side); g.appendChild(el("h4", null, SIDE[side]));
      var ul = el("ul");
      list.forEach(function (r) {
        var li = el("li"), u = safe(r.url);
        li.appendChild(el("b", null, r.outlet + ": "));
        if (u) { var a = el("a", null, r.headline); a.href = u; a.target = "_blank"; a.rel = "noopener"; li.appendChild(a); } else li.appendChild(document.createTextNode(r.headline));
        ul.appendChild(li);
      });
      g.appendChild(ul); d.appendChild(g);
    });
    c.appendChild(d);
    return c;
  }

  function handle(ev, model) {
    if (ev.type === "sources") {
      n = ev.stories.length; srcBox.textContent = "";
      ev.stories.forEach(function (s) { srcBox.appendChild(card(s)); });
      srcHead.hidden = !n; out.hidden = false;
      label = n ? "Reading " + n + (n === 1 ? " story" : " stories") : "";
    } else if (ev.type === "status") { label = ev.text; tick(); }
    else if (ev.type === "text") { label = "Writing"; answer += ev.text; paint(); note.hidden = false; }
    else if (ev.type === "error") { bad(ev.text); }
  }

  function ask(q) {
    q = q.trim();
    if (!q || ctl) return;
    answer = ""; n = 0; text.textContent = ""; srcBox.textContent = ""; srcHead.hidden = true; note.hidden = true; out.hidden = true;
    label = "Finding the stories"; ctl = new AbortController(); busy(true); tick();
    if (touch) { input.blur(); status.scrollIntoView({block: "center", behavior: "smooth"}); }  /* close the keyboard so the answer is in view */
    var failed = false;
    fetch(api + "/api/chat", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({question: q}), signal: ctl.signal})
      .then(function (r) {
        if (!r.ok) return r.json().then(function (j) { failed = true; bad(j.error || "The helper could not answer."); });
        var reader = r.body.getReader(), dec = new TextDecoder(), buf = "";
        function pump() {
          return reader.read().then(function (x) {
            if (x.done) return;
            buf += dec.decode(x.value, {stream: true});
            var lines = buf.split("\n"); buf = lines.pop();
            lines.forEach(function (l) { if (l.trim()) { try { var ev = JSON.parse(l); if (ev.type === "error") failed = true; handle(ev); } catch (e) {} } });
            return pump();
          });
        }
        return pump();
      })
      .then(function () { if (!failed) say("Done in " + Math.round((Date.now() - t0) / 1000) + " s. Not what you meant? Ask it another way."); })
      .catch(function (e) {
        if (e && e.name === "AbortError") say("Stopped.");
        else if (touch) { bad("Lost the connection. A phone pauses a page when you switch apps or the screen locks, so stay on this page while it answers. Then ask again."); }
        else { bad("Lost contact with the helper. Is ./chat.sh still running?"); }
      })
      .then(function () { busy(false); ctl = null; if (!touch) input.focus(); });
  }

  form.addEventListener("submit", function (ev) { ev.preventDefault(); ask(input.value); });
  stop.addEventListener("click", function () { if (ctl) ctl.abort(); });

  function examples() {
    var qs = ["What are the main stories right now?"];
    fetch(base + "data/latest.json").then(function (r) { return r.json(); }).then(function (d) {
      (d.stories || []).slice(0, 2).forEach(function (s) {
        var parts = (s.label || "").split(/\s*·\s*/).filter(Boolean).slice(0, 2);
        if (parts.length) qs.push("What is the news on " + parts.join(" and ") + "?");
      });
    }).catch(function () {}).then(function () {
      qs.forEach(function (q) {
        var b = el("button", null, q); b.type = "button";
        b.addEventListener("click", function () { input.value = q; ask(q); });
        ex.appendChild(b);
      });
    });
  }

  function start() {
    if (!local) {
      offline("Ask runs on your own computer",
        "The model runs on the computer that builds this site, so this copy cannot answer questions. Run your own copy (see \"Run your own\" in the footer), install the model, and open this page there.");
      return;
    }
    say("Checking the helper…");
    fetch(api + "/api/status").then(function (r) { return r.json(); }).then(function (s) {
      if (!s.installed) {
        offline("The model is not installed yet",
          "Ask needs llama.cpp and the model file in the tools folder, the same two files the summaries use. The README's section on summaries written on your own computer shows how.");
        say("");
        return;
      }
      say(s.stories ? "Ready. " + s.stories + " stories to ask about." : "Ready, but the last build has no stories yet.");
      input.disabled = false; go.disabled = false; if (!touch) input.focus(); examples();
    }).catch(function () {
      offline("The helper is not running",
        "On the computer that runs this site, start it in Terminal in the project folder, then reload this page. To use it from a phone, start it with --lan. It loads the model on your first question and unloads it after a quiet spell.", "./chat.sh --lan");
      say("");
    });
  }
  start();
})();
