// Clash Court page. The server holds the timetable; every reply carries the full state. When the court sits, the
// worst clashes are argued one case at a time on the timetable as published, then the whole timetable moves to the
// court's plan (each set slides from where it was to where it ends up).
const $ = (id) => document.getElementById(id);
const PX = 1.05; // pixels per minute
let state = null, published = null, busy = false, fast = false, pace = 1; // pace < 1 speeds the court up (the tour)
const instant = new URLSearchParams(location.search).has("fast"); // for screenshots and demo links

async function post(path, body) {
  const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

const clock = (m) => `${String(Math.floor(m / 60) % 24).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
const wait = (ms) => (fast || instant ? Promise.resolve() : new Promise((r) => setTimeout(r, ms * pace)));
const heat = (x) => { const w = x.clashes.length ? x.clashes[0].weight : 0; return w >= 0.6 ? "hot" : w >= 0.35 ? "warm" : ""; };

// ---------- photos ----------

// Qloo's photo for an act (allowed in hackathon demos, credited on the page), or a monogram for acts Qloo lacks.
function avatar(name, size) {
  const f = (state || published || {}).festival || {}, url = (f.photos || {})[name];
  const w = el("span", "c-av" + (size ? " " + size : ""));
  if (url) {
    const img = new Image();
    img.src = url; img.alt = ""; img.loading = "lazy"; img.decoding = "async"; img.referrerPolicy = "no-referrer";
    img.onerror = () => { img.remove(); w.textContent = initials(name); };
    w.append(img);
  } else w.textContent = initials(name);
  return w;
}
const initials = (n) => n.replace(/\(.*\)/, "").split(/\s+/).filter(Boolean).map((x) => x[0]).join("").slice(0, 2).toUpperCase();

// ---------- timetable ----------

function drawGrid(view, { trial = [], landed = [], flip = false } = {}) {
  const g = $("grid"), f = view.festival, [d0, d1] = f.day, height = (d1 - d0) * PX;
  const before = {};
  if (flip) g.querySelectorAll(".c-cell[data-act]").forEach((c) => { before[c.dataset.act] = c.getBoundingClientRect(); });
  g.innerHTML = "";
  g.classList.toggle("trial", trial.length > 0);
  g.style.gridTemplateColumns = `44px repeat(${f.stages.length}, minmax(96px, 1fr))`;
  g.append(el("div", "c-h", ""));
  f.stages.forEach((s) => g.append(el("div", "c-h", s)));
  const axis = el("div", "c-axis");
  axis.style.height = height + "px";
  for (let m = Math.ceil(d0 / 60) * 60; m <= d1; m += 60) {
    const t = el("div", "c-tick", clock(m));
    t.style.top = (m - d0) * PX + "px";
    axis.append(t);
  }
  g.append(axis);
  const lfm = new Set(view.from_lastfm || []);
  f.stages.forEach((_, si) => {
    const col = el("div", "c-col");
    col.style.height = height + "px";
    for (let m = Math.ceil(d0 / 60) * 60; m <= d1; m += 60) {
      const line = el("div", "c-line");
      line.style.top = (m - d0) * PX + "px";
      col.append(line);
    }
    view.sets.filter((x) => x.stage === si).forEach((x) => {
      const cls = ["c-cell"];
      if (!x.act) cls.push("empty");
      else {
        if (heat(x)) cls.push(heat(x));
        if (lfm.has(x.act)) cls.push("lfm");
        if (!x.matched) cls.push("nodata");
        if (trial.includes(x.act)) cls.push("on-trial");
        if (landed.includes(x.act)) cls.push("landed");
      }
      const d = el("div", cls.join(" "));
      d.style.top = (x.start - d0) * PX + 1 + "px";
      d.style.height = Math.max(16, (x.end - x.start) * PX - 3) + "px";
      if (x.act) {
        d.dataset.act = x.act;
        const name = el("div", "a");
        name.append(avatar(x.act, "xs"), document.createTextNode(x.act));
        d.append(name);
        d.append(el("div", "t", `${clock(x.start)} to ${clock(x.end)}`));
        d.title = x.clashes.length
          ? `${x.act} shares fans with ${x.clashes.map((c) => `${c.act} (${c.minutes} min overlap)`).join(", ")}`
          : `${x.act}: no real clash`;
      } else d.append(el("div", "t", "open"));
      col.append(d);
    });
    g.append(col);
  });
  const moving = flip && !matchMedia("(prefers-reduced-motion: reduce)").matches;
  setTimeout(() => drawArcs(view, trial), moving ? (fast ? 380 : 1150) : 30);
  if (moving) {
    g.querySelectorAll(".c-cell[data-act]").forEach((c) => {
      const a = before[c.dataset.act];
      if (!a) return;
      const b = c.getBoundingClientRect(), dx = a.left - b.left, dy = a.top - b.top;
      if (Math.abs(dx) + Math.abs(dy) < 1) return;
      c.style.zIndex = 3;
      c.animate([{ transform: `translate(${dx}px, ${dy}px)` }, { transform: "none" }],
        { duration: fast ? 350 : 1100, easing: "cubic-bezier(.2,.8,.2,1)" }).onfinish = () => { c.style.zIndex = ""; };
    });
  }
}

// Clash arcs: a curve between every two sets that overlap in time and share many fans, thicker for more shared fans.
// They are drawn from where the sets sit, so when the court moves sets, the arcs it resolved are simply gone.
let arcToken = 0;
function drawArcs(view, trial = []) {
  const g = $("grid"), token = ++arcToken;
  g.querySelectorAll(".c-arcs").forEach((x) => x.remove());
  const box = g.getBoundingClientRect(), at = {};
  g.querySelectorAll(".c-cell[data-act]").forEach((c) => { at[c.dataset.act] = c.getBoundingClientRect(); });
  const NS = "http://www.w3.org/2000/svg", svg = document.createElementNS(NS, "svg");
  svg.setAttribute("class", "c-arcs");
  svg.setAttribute("width", g.scrollWidth); svg.setAttribute("height", g.scrollHeight);
  const seen = new Set();
  view.sets.forEach((x) => x.act && x.clashes.forEach((c) => {
    const key = [x.act, c.act].sort().join("|");
    if (c.weight < 0.45 || seen.has(key) || !at[x.act] || !at[c.act]) return;
    seen.add(key);
    const a = at[x.act], b = at[c.act];
    const [l, r] = a.left < b.left ? [a, b] : [b, a];
    const x1 = l.right - box.left - 6, y1 = l.top - box.top + l.height / 2;
    const x2 = r.left - box.left + 6, y2 = r.top - box.top + r.height / 2;
    const lift = 26 + Math.abs(x2 - x1) * 0.18;
    const path = document.createElementNS(NS, "path");
    path.setAttribute("d", `M${x1},${y1} C${x1 + 18},${y1 - lift} ${x2 - 18},${y2 - lift} ${x2},${y2}`);
    path.setAttribute("pathLength", "1");
    path.setAttribute("class", "arc" + (trial.length && trial.includes(x.act) && trial.includes(c.act) ? " trial" : trial.length ? " dim" : ""));
    path.style.setProperty("--w", c.weight);
    svg.append(path);
  }));
  if (token === arcToken) g.append(svg);
}
const fadeArcs = () => $("grid").querySelectorAll(".c-arcs").forEach((x) => x.classList.add("gone"));

// The timetable the court argues over: as published, without any act the booker cancelled.
function baseView(s) {
  const gone = new Set(s.rules.filter((r) => r.type === "cancel").map((r) => r.act));
  return { ...published, from_lastfm: s.from_lastfm,
    sets: published.sets.map((x) => (gone.has(x.act) ? { ...x, act: null, clashes: [] } : x)) };
}

// ---------- score and side panels ----------

function animateNumber(node, to) {
  const from = parseFloat(node.textContent) || 0, t0 = performance.now(), dur = fast ? 200 : 900;
  const step = (t) => {
    const k = Math.min(1, (t - t0) / dur);
    node.textContent = (from + (to - from) * (1 - Math.pow(1 - k, 3))).toFixed(2);
    if (k < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

function drawScore(s, animate = false) {
  $("pub").textContent = s.published_score.toFixed(2);
  if (animate) animateNumber($("now"), s.score); else $("now").textContent = s.score.toFixed(2);
  const cut = s.published_score ? (100 * (s.published_score - s.score)) / s.published_score : 0;
  $("cut").textContent = cut > 0.5 ? `${cut.toFixed(0)}% fewer clashes, every rule kept` : "";
  $("st-cut").textContent = `${Math.max(0, cut).toFixed(0)}%`;
}

function drawMeta(s) {
  const f = s.festival, acts = s.sets.filter((x) => x.act).length, known = acts - s.unmatched.length;
  $("fest-short").textContent = f.name.replace(/\s*\(.*\)$/, "");
  $("festnote").textContent = f.note;
  $("st-acts").textContent = acts;
  $("st-stages").textContent = f.stages.length;
  $("st-pairs").textContent = (known * (known - 1) / 2).toLocaleString();
  const ex = $("examples");
  ex.innerHTML = "";
  (f.examples || []).forEach((t) => {
    const b = el("button", "", t);
    b.type = "button";
    b.addEventListener("click", () => emergency(t));
    ex.append(b);
  });
  $("text").placeholder = f.examples && f.examples[0] ? `For example: ${f.examples[0]}` : "An act just cancelled";
}

function error(msg) {
  $("err").hidden = !msg;
  $("err").textContent = msg || "";
}

// ---------- the court ----------

// One line in the court. The text types out (instantly when skipping); resolves when it has finished.
function say(kind, who, text, extra, face) {
  const m = el("div", "c-say " + kind), head = el("div", "who"), body = el("div", "txt");
  if (face) head.append(avatar(face, "sm"));
  head.append(document.createTextNode(who));
  m.append(head, body);
  $("transcript").append(m);
  const finish = () => { body.textContent = text; if (extra) m.append(extra); };
  if (fast || instant || matchMedia("(prefers-reduced-motion: reduce)").matches) { finish(); return Promise.resolve(m); }
  return new Promise((done) => {
    let i = 0;
    const step = () => {
      if (fast) { finish(); return done(m); }
      i = Math.min(text.length, i + 3);
      body.textContent = text.slice(0, i);
      if (i < text.length) setTimeout(step, 22 * pace); else { finish(); done(m); }
    };
    step();
  });
}

function faceoff(a, b) {
  const side = (n) => { const d = el("div", "side"); d.append(avatar(n, "lg"), el("span", "nm", n), el("span", "fans", "fans")); return d; };
  const f = el("div", "c-faceoff");
  f.append(side(a), el("span", "v", "v."), side(b));
  return f;
}

function docket(cases) {
  const d = $("docket");
  d.innerHTML = "";
  cases.forEach((c, i) => {
    const li = el("li");
    li.append(el("span", "n", String(i + 1).padStart(2, "0")));
    li.append(el("span", "", `${c.acts[0]} v. ${c.acts[1]}`));
    li.append(el("span", "tag", ""));
    d.append(li);
  });
}

const VERDICT = { resolved: "Clash resolved", eased: "Clash eased", stands: "Clash stands" };

async function sit(s, opening) {
  const cases = s.cases || [], lfm = new Set(s.from_lastfm || []);
  fast = false;
  $("skip").hidden = false;
  $("transcript").innerHTML = "";
  docket(cases);
  drawGrid(baseView(s), { flip: true });
  if (opening) {
    $("case-no").textContent = "Emergency";
    $("case-title").textContent = "The booker has news.";
    await say("e", "Booker agent", opening);
    await wait(900);
  }
  for (let i = 0; i < cases.length; i++) {
    const c = cases[i], [a, b] = c.acts, src = lfm.has(a) || lfm.has(b) ? " lfm" : "";
    const items = $("docket").children;
    [...items].forEach((li, j) => li.classList.toggle("now", j === i));
    $("case-no").textContent = `Case ${i + 1} of ${cases.length}, ${c.when}`;
    const t = $("case-title");
    t.innerHTML = "";
    t.append(faceoff(a, b));
    $("transcript").innerHTML = "";
    drawGrid(baseView(s), { trial: [a, b] });
    await wait(500);
    await say("p" + src, `Fan agent for ${a}`, c.plaintiff, null, a);
    await wait(500);
    await say("d" + src, `Fan agent for ${b}`, c.defendant, null, b);
    await wait(500);
    if (c.objection) {
      await say("o", "Booker agent: objection", c.objection);
      await wait(600);
    }
    await say("j", "The court", c.ruling, el("span", "c-stamp " + c.outcome, VERDICT[c.outcome]));
    const tag = items[i].querySelector(".tag");
    tag.className = "tag " + c.outcome;
    tag.textContent = VERDICT[c.outcome];
    await wait(1900);
  }
  [...$("docket").children].forEach((li) => li.classList.remove("now"));
  $("case-no").textContent = "Judgment";
  $("case-title").textContent = "The court rules on the whole timetable.";
  $("transcript").innerHTML = "";
  const done = (s.feed || []).filter((f) => f.who === "referee").pop();
  say("j", "The court", done ? done.text : "No move would lower the clash score without breaking a rule.");
  fadeArcs();
  await wait(450);
  (s.feed || []).filter((f) => f.who === "referee" && /^(The current|I cannot)/.test(f.text)).forEach((f) => say("o", "Booker agent", f.text));
  fast = false;
  drawGrid(s, { flip: true, landed: cases.flatMap((c) => (c.outcome !== "stands" ? c.acts : [])) });
  drawScore(s, true);
  $("skip").hidden = true;
}

async function act(promise, opening) {
  if (busy) return;
  busy = true;
  document.body.style.cursor = "progress";
  $("convene").disabled = true;
  error("");
  try {
    const s = await promise;
    if (s.error) { error(s.error); return; }
    state = s;
    drawMeta(s);
    await sit(s, opening ? opening(s) : null);
  } catch (e) {
    error("Something went wrong: " + e.message);
  } finally {
    busy = false;
    document.body.style.cursor = "";
    $("convene").disabled = false;
  }
}

function convene() {
  if (state) return act(post("/api/clash/run", { session: state.session }));
}

function emergency(text) {
  if (!state || !text.trim()) return;
  $("court").scrollIntoView({ behavior: "smooth" });
  act(post("/api/clash/command", { session: state.session, text }),
    (s) => (s.rule ? `${s.rule.reads_as.charAt(0).toUpperCase() + s.rule.reads_as.slice(1)}. ${s.rule.read_by_model ? "(Read by the language model.) " : ""}The court sits again.` : null));
}

async function reset() {
  if (!state || busy) return;
  const s = await post("/api/clash/reset", { session: state.session });
  state = s;
  $("transcript").innerHTML = "";
  $("docket").innerHTML = "";
  $("case-no").textContent = "Court is not yet in session";
  $("case-title").textContent = 'Press "Convene the court" to put the worst clashes on trial.';
  drawGrid(s, { flip: true });
  drawScore(s);
  error("");
}

async function load(slug) {
  error("");
  const s = await post("/api/clash/load", { festival: slug });
  state = s;
  published = s;
  drawMeta(s);
  drawGrid(s);
  drawScore(s);
  $("transcript").innerHTML = "";
  $("docket").innerHTML = "";
  $("case-no").textContent = "Court is not yet in session";
  $("case-title").textContent = 'Press "Convene the court" to put the worst clashes on trial.';
}

// ---------- your day ----------

async function planDay(e) {
  e.preventDefault();
  const favs = $("favs").value.split(",").map((x) => x.trim()).filter(Boolean).slice(0, 5);
  if (!favs.length || !state) return;
  const out = $("route");
  out.innerHTML = "";
  out.append(el("p", "note", "Scoring every act on the bill for you..."));
  try {
    const r = await post("/api/clash/route", { session: state.session, favourites: favs });
    out.innerHTML = "";
    if (r.error) { out.append(el("p", "note", r.error)); return; }
    if (r.not_found.length) out.append(el("p", "note", "Not found: " + r.not_found.join(", ")));
    r.sets.forEach((h) => {
      const row = el("div", "r" + (h.top ? " top" : "") + (h.source === "lastfm" ? " lfm" : ""));
      row.append(el("span", "tm", `${h.start} to ${h.end}`));
      const txt = el("div", "", "");
      txt.append(el("strong", "", h.act), ` on ${h.stage}, fit ${h.fit.toFixed(2)}${h.source === "lastfm" ? " (Last.fm)" : ""}`);
      if (h.clash_with) txt.append(el("span", "must", `Clash: ${h.clash_with.act} (fit ${h.clash_with.fit.toFixed(2)}) at the same time. Filed with the court.`));
      row.append(txt);
      out.append(row);
    });
    out.append(el("p", "note", r.summary + (r.sets.some((h) => h.clash_with) ? " Convene the court again to weigh your case." : "")));
    state = r.state;
  } catch (err) {
    out.innerHTML = "";
    out.append(el("p", "note", "Something went wrong: " + err.message));
  }
}

// ---------- wiring ----------

$("convene").addEventListener("click", convene);
$("reset").addEventListener("click", reset);
$("skip").addEventListener("click", () => { fast = true; });
$("cmd").addEventListener("submit", (e) => { e.preventDefault(); const t = $("text").value; $("text").value = ""; emergency(t); });
$("routeform").addEventListener("submit", planDay);
$("festival").addEventListener("change", (e) => load(e.target.value));
$("theme-toggle").addEventListener("click", () => {
  const dark = document.documentElement.dataset.theme
    ? document.documentElement.dataset.theme === "dark"
    : matchMedia("(prefers-color-scheme: dark)").matches;
  document.documentElement.dataset.theme = dark ? "light" : "dark";
  try { localStorage.setItem("ws-theme", dark ? "light" : "dark"); } catch (_) {}
});

(async () => {
  const list = await (await fetch("/api/clash/festivals")).json();
  list.forEach((f) => { const o = el("option", "", f.name); o.value = f.slug; $("festival").append(o); });
  await load(list[0].slug);
  const q = new URLSearchParams(location.search);
  if (q.get("convene")) convene();
  else if (q.get("cmd")) emergency(q.get("cmd"));
})();

// Hooks for the other scripts on the page (Ask the court, the guided tour).
window.court = {
  session: () => state && state.session,
  pace: (p) => { pace = p; },
  festival: () => state && state.festival,
  convene,
  // A state the agent produced (for example after a booker order): replay the court with it.
  async replay(s) {
    if (busy) return;
    busy = true;
    try {
      state = s;
      drawMeta(s);
      document.getElementById("court").scrollIntoView({ behavior: "smooth" });
      await sit(s, s.rule ? `${s.rule.reads_as.charAt(0).toUpperCase() + s.rule.reads_as.slice(1)}. The court sits again.` : null);
    } finally {
      busy = false;
    }
  },
};
