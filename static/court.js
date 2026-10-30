// Clash Court page. The server holds the timetable; every reply carries the full state. When the court sits, the
// worst clashes are argued one case at a time on the timetable as published, then the whole timetable moves to the
// court's plan (each set slides from where it was to where it ends up).
const $ = (id) => document.getElementById(id);
const PX = 1.05; // pixels per minute
let state = null, published = null, busy = false, fast = false, pace = 1; // pace < 1 speeds the court up (the tour)
let weights = {}; // act -> act -> shared-fan weight, sent once on load, so a drop can be previewed before it happens
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
const heat = (x) => { const w = x.clashes.length ? x.clashes[0].weight : 0; return w >= 0.45 ? "hot" : w >= 0.3 ? "warm" : ""; }; // 0.45: the same clash line as the arcs and the drop preview

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
      d.dataset.cell = x.cell;
      d.style.top = (x.start - d0) * PX + 1 + "px";
      d.style.height = Math.max(16, (x.end - x.start) * PX - 3) + "px";
      if (x.act) {
        d.dataset.act = x.act;
        d.draggable = !trial.length;
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

// ---------- the booker moves sets by hand ----------

let dragAct = null;
const CLASH = 0.45; // shared-fan weight at which an overlap counts as a clash (as the arcs draw them)

// What happens to the dragged act's fans if it plays in this slot: which sets on other stages overlap it, and how many
// fans they share (the set already in the slot swaps into the dragged act's old slot, so it is left out).
function preview(cell) {
  const target = state.sets[cell], from = state.sets.find((x) => x.act === dragAct);
  if (!target || !from) return null;
  const hits = [];
  state.sets.forEach((x) => {
    if (!x.act || x.act === dragAct || x.cell === cell || x.stage === target.stage) return;
    const mins = Math.min(target.end, x.end) - Math.max(target.start, x.start);
    const w = (weights[dragAct] || {})[x.act] || 0;
    if (mins > 0 && w >= 0.35) hits.push({ act: x.act, w, mins });
  });
  hits.sort((a, b) => b.w - a.w);
  return { hits, clash: hits.some((h) => h.w >= CLASH), swap: target.act };
}

function showPreview(node, p) {
  let tip = $("drop-tip");
  if (!tip) { tip = el("div", "c-droptip"); tip.id = "drop-tip"; $("grid").append(tip); }
  const g = $("grid").getBoundingClientRect(), r = node.getBoundingClientRect();
  tip.style.left = Math.min(r.left - g.left, $("grid").scrollWidth - 230) + "px";
  tip.style.top = r.bottom - g.top + 6 + "px";
  tip.className = "c-droptip " + (p.clash ? "bad" : "good");
  tip.innerHTML = "";
  tip.append(el("strong", "", p.clash ? `Clash for ${dragAct}'s fans` : `Clear for ${dragAct}'s fans`));
  if (p.hits.length) p.hits.slice(0, 3).forEach((h) => tip.append(el("span", "", `${h.act}: ${h.mins} min, ${h.w >= CLASH ? "many" : "some"} shared fans`)));
  else tip.append(el("span", "", "No set on another stage shares many of its fans at that time."));
  if (p.swap) tip.append(el("span", "swap", `Swaps with ${p.swap}`));
}
const hidePreview = () => { const t = $("drop-tip"); if (t) t.remove(); };

function wireDrag() {
  const g = $("grid");
  g.addEventListener("dragstart", (e) => {
    const c = e.target.closest(".c-cell[data-act]");
    if (!c || busy) { e.preventDefault(); return; }
    dragAct = c.dataset.act;
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", dragAct);
    c.classList.add("dragging");
    g.classList.add("dragmode");
  });
  g.addEventListener("dragend", () => {
    dragAct = null;
    g.classList.remove("dragmode");
    g.querySelectorAll(".dragging, .drop-good, .drop-bad").forEach((x) => x.classList.remove("dragging", "drop-good", "drop-bad"));
    hidePreview();
  });
  g.addEventListener("dragover", (e) => {
    const c = e.target.closest(".c-cell[data-cell]");
    if (!dragAct || !c || c.dataset.act === dragAct) return;
    e.preventDefault();
    if (c.classList.contains("drop-good") || c.classList.contains("drop-bad")) return;
    g.querySelectorAll(".drop-good, .drop-bad").forEach((x) => x.classList.remove("drop-good", "drop-bad"));
    const p = preview(+c.dataset.cell);
    if (!p) return;
    c.classList.add(p.clash ? "drop-bad" : "drop-good");
    showPreview(c, p);
  });
  g.addEventListener("drop", async (e) => {
    const c = e.target.closest(".c-cell[data-cell]");
    if (!dragAct || !c) return;
    e.preventDefault();
    const act = dragAct, cell = +c.dataset.cell;
    hidePreview();
    try {
      const s = await post("/api/clash/move", { session: state.session, act, cell });
      manual(s);
    } catch (err) { error("Could not move that set: " + err.message); }
  });
}

// After a move or an undo: redraw, re-score, and tell the booker what changed and what (if anything) it breaks.
function manual(s) {
  if (s.error) { error(s.error); return; }
  const before = state.score;
  state = s;
  drawGrid(s, { flip: true, landed: s.moved ? [s.moved.act, s.moved.swapped].filter(Boolean) : [] });
  drawScore(s, true);
  $("docket").innerHTML = "";
  $("transcript").innerHTML = "";
  $("case-no").textContent = s.undone ? "Undone" : "Your move";
  $("case-title").textContent = s.undone ? "Back one step." : `${s.moved.act} to ${s.moved.to}`;
  const diff = s.score - before;
  const lines = [];
  if (s.moved) lines.push(`${s.moved.act} now plays ${s.moved.to}` + (s.moved.swapped ? `; ${s.moved.swapped} moves to ${s.moved.swapped_to}.` : "."));
  lines.push(`Clash score ${before.toFixed(2)} to ${s.score.toFixed(2)}: ${Math.abs(diff) < 0.005 ? "no change" : diff < 0 ? "fewer fans must choose" : "more fans must choose"}.`);
  say("e", "Booker (you)", lines.join(" "));
  if (s.broken && s.broken.length) {
    say("o", "House rules: this breaks", s.broken.slice(0, 4).join("; ") + ". It is your call; Undo puts it back.");
  } else if (s.moved) {
    say("j", "The court", `Every house rule still holds. Your placement is pinned: when the court sits, it plans around it.`);
  }
  const row = el("div", "c-manual");
  const u = el("button", "quiet small", "Undo"); u.type = "button";
  u.addEventListener("click", async () => manual(await post("/api/clash/undo", { session: state.session })));
  const c = el("button", "quiet small", "Let the court plan around it"); c.type = "button";
  c.addEventListener("click", () => quickRuling());
  row.append(u, c);
  $("transcript").append(row);
  error("");
}

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
  $("transcript").scrollTop = $("transcript").scrollHeight;
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
    $("case-no").textContent = `Quick ruling (optimiser, no agents): case ${i + 1} of ${cases.length}, ${c.when}`;
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

// "Convene the court": the working agents. A recorded sitting replays when the timetable is as published; otherwise,
// or when asked, the agents sit live and every event streams in.
function convene(live = false) {
  if (state) return council(live);
}

// The quick ruling (optimiser, no agents): used after an emergency or a manual move.
function quickRuling() {
  if (state) return act(post("/api/clash/run", { session: state.session }));
}

// A view of the timetable for any placement, with clashes worked out here from the weights sent at load.
function viewOf(pos) {
  const at = {};
  Object.entries(pos).forEach(([a, i]) => { at[i] = a; });
  const sets = published.sets.map((x) => ({ ...x, act: at[x.cell] || null, clashes: [] }));
  sets.forEach((x) => {
    if (!x.act) return;
    sets.forEach((y) => {
      if (!y.act || y === x || y.stage === x.stage) return;
      const mins = Math.min(x.end, y.end) - Math.max(x.start, y.start), w = (weights[x.act] || {})[y.act] || 0;
      if (mins > 0 && w >= 0.2) x.clashes.push({ act: y.act, weight: w, minutes: mins });
    });
    x.clashes.sort((a, b) => b.weight - a.weight);
  });
  return { ...published, from_lastfm: state.from_lastfm, sets };
}

const TOOLNAME = { fans_of: "Qloo: who shares fans", moves_for: "moves that free fans", check_move: "rules check",
  legal_moves: "legal moves", score_move: "score check" };

function toolLine(e) {
  const who = e.agent.startsWith("fan:") ? e.agent.slice(4) + "'s fan agent" : e.agent === "booker" ? "Booker agent" : "Judge";
  const d = el("div", "c-toolline");
  d.append(el("span", "k", who), el("span", "n", TOOLNAME[e.name] || e.name), el("span", "s", e.summary || ""));
  $("transcript").append(d);
  $("transcript").scrollTop = $("transcript").scrollHeight;
}

function proposalChip(p, label) {
  const d = el("div", "c-prop" + (p.breaks && p.breaks.length ? " bad" : " ok"));
  d.append(el("strong", "", `${label}: ${p.act} to ${p.to}` + (p.swaps_with ? ` (swaps with ${p.swaps_with})` : "")));
  d.append(el("span", "", p.breaks && p.breaks.length ? `Breaks a rule: ${p.breaks[0]}` : `Keeps every rule; day's clash score ${p.clash_score_after.toFixed(2)}`));
  return d;
}

// The booker has the floor: approve a proposal that keeps every rule, let the clash stand, or let the judge decide.
// After 30 seconds without a choice the judge decides, so a viewer who only watches is never stuck.
function gate(table) {
  return new Promise((done) => {
    const box = el("div", "c-gate");
    box.append(el("div", "who", "You have the floor, booker"));
    box.append(el("p", "", "Approve a move, let the clash stand, or leave it to the judge."));
    const row = el("div", "c-gatebtns");
    let left = 30, finished = false;
    const finish = (pick) => { if (finished) return; finished = true; clearInterval(tick); box.remove(); done(pick); };
    table.forEach((p) => {
      const b = el("button", "quiet small" + (p.breaks && p.breaks.length ? " off" : ""), `Approve: ${p.act} to ${p.to}`);
      b.type = "button";
      if (p.breaks && p.breaks.length) { b.disabled = true; b.title = `Breaks a rule: ${p.breaks[0]}`; }
      else b.addEventListener("click", () => finish({ kind: "approve", p }));
      row.append(b);
    });
    const st = el("button", "quiet small", "The clash stands"); st.type = "button";
    st.addEventListener("click", () => finish({ kind: "stands" }));
    const jd = el("button", "primary c-auto", "Let the judge decide"); jd.type = "button";
    jd.addEventListener("click", () => finish({ kind: "judge" }));
    row.append(st, jd);
    const count = el("span", "c-gatecount", `The judge decides in ${left} s`);
    box.append(row, count);
    $("transcript").append(box);
    $("transcript").scrollTop = $("transcript").scrollHeight;
    const tick = setInterval(() => { left -= 1; count.textContent = `The judge decides in ${left} s`; if (left <= 0) finish({ kind: "judge" }); }, 1000);
  });
}

async function council(live) {
  if (busy || !state) return;
  busy = true;
  document.body.style.cursor = "progress";
  $("convene").disabled = true;
  error("");
  fast = false;
  let pos = {};
  published.sets.forEach((x) => { if (x.act) pos[x.act] = x.cell; });
  const gone = new Set((state.rules || []).filter((r) => r.type === "cancel").map((r) => r.act));
  gone.forEach((a) => delete pos[a]);
  let cases = 0, finalState = null, handedOff = false, savedPace = null, gated = false, yourPick = null;
  $("skip").hidden = false;
  $("transcript").innerHTML = "";
  $("docket").innerHTML = "";
  $("case-no").textContent = live ? "The agents sit now" : "The court sits";
  $("case-title").textContent = live ? "Live: the agents are reading the bill." : "Fan agents, the booker and the judge argue the worst clashes.";
  drawGrid(viewOf(pos), { flip: true });

  let onTable = [];
  const play = async (e, replay) => {
    if (e.type === "case") {
      onTable = [];
      cases = e.of;
      const li = el("li", "now");
      li.append(el("span", "n", String(e.n).padStart(2, "0")), el("span", "", `${e.acts[0]} v. ${e.acts[1]}`), el("span", "tag", ""));
      [...$("docket").children].forEach((x) => x.classList.remove("now"));
      $("docket").append(li);
      $("case-no").textContent = (e.of ? `Case ${e.n} of the ${e.of} worst` : `Case ${e.n}, every red clash`) + `, ${e.when}, ${e.minutes} min overlap`;
      if (replay && e.n === 6) { savedPace = pace; pace = Math.min(pace, 0.35); } // a long docket replays faster after case 5
      $("case-title").innerHTML = "";
      $("case-title").append(faceoff(e.acts[0], e.acts[1]));
      $("transcript").innerHTML = "";
      drawGrid(viewOf(pos), { trial: e.acts });
      if (replay) await wait(700);
    } else if (e.type === "tool") {
      toolLine(e);
      if (replay) await wait(380);
    } else if (e.type === "say" && e.agent === "fan") {
      if (e.proposal) onTable.push({ ...e.proposal, by: `${e.act}'s fan agent` });
      const m = await say("p", `Fan agent for ${e.act}`, e.text, e.proposal ? proposalChip(e.proposal, "Proposes") : null, e.act);
      if (replay) await wait(500);
    } else if (e.type === "say" && e.agent === "booker") {
      if (e.counter) onTable.push({ ...e.counter, by: "the booker agent" });
      const extra = el("div", "");
      (e.objections || []).forEach((o) => extra.append(el("div", "c-obj", `Objects: ${o}`)));
      if (e.counter) extra.append(proposalChip(e.counter, "Counter-proposes"));
      await say("o", "Booker agent", e.text, extra.childNodes.length ? extra : null);
      if (replay) await wait(500);
    } else if (e.type === "ruling") {
      const stamp = el("span", "c-stamp " + e.outcome, VERDICT[e.outcome]);
      let tagged = stamp;
      if (e.move && e.move.by) { // whose proposal won: the agents choose, the code only refuses rule-breaking moves
        tagged = el("div", "c-rulingfoot");
        const by = e.move.by.startsWith("fans of ") ? `${e.move.by.slice(8)}'s fan agent` : "the booker agent";
        tagged.append(stamp, el("span", "c-by", `Accepted: ${e.move.act} to ${e.move.to}, proposed by ${by}; keeps every rule`));
      }
      await say("j", "Judge agent", e.text, tagged);
      if (e.clerk) await say("o", "Clerk (code check)", e.clerk);
      const tag = $("docket").lastChild && $("docket").lastChild.querySelector(".tag");
      if (tag) { tag.className = "tag " + e.outcome; tag.textContent = VERDICT[e.outcome]; }
      if (e.move) {
        pos = { ...e.pos };
        drawGrid(viewOf(pos), { flip: true, landed: [e.move.act, e.move.swaps_with].filter(Boolean) });
      }
      $("now").textContent = e.clash_score.toFixed(2);
      if (replay) await wait(1300);
    } else if (e.type === "tidy") {
      const m = e.summary;
      [...$("docket").children].forEach((x) => x.classList.remove("now"));
      $("case-no").textContent = "Judgment";
      $("case-title").textContent = "The agents ruled; the optimiser tidies the rest.";
      $("transcript").innerHTML = "";
      if (savedPace !== null) { pace = savedPace; savedPace = null; }
      await say("j", "The court", (m.every ? `The agents argued every red clash (${m.cases} cases) and decided ${m.decided} moves` :
        `The agents argued the ${m.cases || 5} worst clashes and decided ${m.decided} moves`) +
        `: clash score ${m.start.toFixed(2)} to ${m.after_cases.toFixed(2)}. ` +
        `The optimiser then tidied the rest of the day with those moves pinned: ${m.final.toFixed(2)}. ` +
        `For comparison, the optimiser alone reaches ${m.optimiser_alone.toFixed(2)}.`);
      if (m.by_fans !== undefined) {
        await say("e", "Who decided", `Of the ${m.decided} moves made, ${m.by_fans} were proposed by fan agents and ${m.by_booker} by the booker. ` +
          `The code refused ${m.refused} proposals that broke a rule. ${m.not_the_optimisers} of the moves are not ones the optimiser on its own would have made.`);
      }
    } else if (e.type === "final") {
      finalState = e.state;
    } else if (e.type === "error") {
      error(e.message);
    }
  };

  try {
    const r = await fetch("/api/clash/council", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session: state.session, live }) });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.statusText);
    if ((r.headers.get("content-type") || "").includes("application/json")) {
      const d = await r.json();
      $("case-no").textContent = `Recorded sitting of the agents, ${d.recorded}`;
      const evs = d.events;
      let diverged = null;
      for (let i = 0; i < evs.length; i++) {
        await play(evs[i], true);
        const e = evs[i];
        if (e.type === "say" && e.agent === "booker" && !window.__touring && !instant && !gated) {
          gated = true;
          const ruling = evs.slice(i + 1).find((x) => x.type === "ruling");
          const caseEv = evs.slice(0, i).reverse().find((x) => x.type === "case");
          const pick = await gate(onTable);
          const same = pick.kind === "judge" || (pick.kind === "stands" && !ruling.move) ||
            (pick.kind === "approve" && ruling.move && ruling.move.act === pick.p.act && ruling.move.to === pick.p.to);
          if (pick.kind !== "judge") {
            await say("e", "Booker (you)", pick.kind === "approve" ? `I approve ${pick.p.act} to ${pick.p.to}, proposed by ${pick.p.by}.`
              : "The clash stands: I approve none of these moves.");
          }
          if (!same) { diverged = { pair: caseEv.acts, pick }; yourPick = pick; break; }
        }
      }
      if (diverged) {
        await say("e", "The court", "Your ruling differs from the judge's, so the rest of the day changes: the agents argue the remaining cases live, from your timetable.");
        const r2 = await fetch("/api/clash/council/continue", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session: state.session, pair: diverged.pair,
            act: diverged.pick.kind === "approve" ? diverged.pick.p.act : null, to: diverged.pick.kind === "approve" ? diverged.pick.p.to : null }) });
        if (!r2.ok) throw new Error((await r2.json().catch(() => ({}))).error || (await r2.text()) || r2.statusText);
        const reader = r2.body.getReader(), dec = new TextDecoder();
        let buf = "";
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          buf += dec.decode(value, { stream: true });
          let k;
          while ((k = buf.indexOf("\n\n")) >= 0) {
            const line = buf.slice(0, k).trim();
            buf = buf.slice(k + 2);
            if (line.startsWith("data:")) await play(JSON.parse(line.slice(5)), false);
          }
        }
      } else {
        finalState = d.state;
      }
    } else {
      const reader = r.body.getReader(), dec = new TextDecoder();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let i;
        while ((i = buf.indexOf("\n\n")) >= 0) {
          const line = buf.slice(0, i).trim();
          buf = buf.slice(i + 2);
          if (line.startsWith("data:")) await play(JSON.parse(line.slice(5)), false);
        }
      }
    }
    if (!finalState && live !== "fallback") {
      // the agents could not sit (for example the model provider refused): say so, then give the quick ruling
      $("transcript").innerHTML = "";
      $("case-no").textContent = "The agents are unavailable";
      $("case-title").textContent = "The quick ruling (optimiser, no agents) sits instead.";
      if (yourPick && yourPick.kind === "approve") {
        // keep the booker's ruling: place the approved move first (it is then pinned), so the quick ruling plans around it
        const f = state.festival, slot = published.sets.find((x) => `${f.stages[x.stage]} at ${clock(x.start)}` === yourPick.p.to);
        if (slot) {
          try { state = await post("/api/clash/move", { session: state.session, act: yourPick.p.act, cell: slot.cell }); } catch (_) { /* the quick ruling still runs */ }
        }
      }
      busy = false;
      handedOff = true; // the quick ruling now owns the busy flag and the buttons
      await wait(1500);
      return quickRuling();
    }
    if (finalState) {
      state = finalState;
      fast = false;
      fadeArcs();
      await wait(300);
      drawGrid(state, { flip: true });
      drawScore(state, true);
    }
  } catch (err) {
    error("The court could not sit: " + err.message);
  } finally {
    if (!handedOff) {
      $("skip").hidden = true;
      busy = false;
      document.body.style.cursor = "";
      $("convene").disabled = false;
    }
  }
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
  weights = s.weights || {};
  drawMeta(s);
  drawGrid(s);
  drawScore(s);
  $("transcript").innerHTML = "";
  $("docket").innerHTML = "";
  $("case-no").textContent = "Court is not yet in session";
  $("case-title").textContent = 'Press "Convene the court" to put the worst clashes on trial.';
  document.dispatchEvent(new CustomEvent("court:loaded", { detail: slug })); // the graph and the Qloo panel redraw for the new day
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

$("convene").addEventListener("click", () => convene(false));
$("convene-live").addEventListener("click", () => convene(true));
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
  current: () => state,
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

wireDrag();
