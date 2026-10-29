// Clash Court page. The server holds the timetable; every reply carries the full state and a version, and the page
// redraws from it. Referee moves in a feed are replayed on the grid one by one, then the final state is drawn.
const $ = (id) => document.getElementById(id);
let state = null, busy = false, latest = -1;

async function post(path, body) {
  const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}

function heat(cell) {
  const w = cell && cell.clashes.length ? cell.clashes[0].weight : 0;
  return w >= 0.45 ? "hot" : w >= 0.2 ? "warm" : "";
}

function drawGrid(s, moved = new Set()) {
  const g = $("grid"), f = s.festival;
  g.style.gridTemplateColumns = `56px repeat(${f.stages.length}, minmax(120px, 1fr))`;
  g.innerHTML = "";
  g.append(el("div", "h", ""));
  f.stages.forEach((st) => g.append(el("div", "h", st)));
  f.slots.forEach((slot, k) => {
    g.append(el("div", "t", slot));
    f.stages.forEach((_, si) => {
      const c = s.grid[si][k];
      const d = el("div", "cell " + (c ? heat(c) : "empty") + (c && !c.matched ? " nodata" : "") + (c && moved.has(c.act) ? " moved" : ""));
      if (c) {
        d.append(el("div", "a", c.act));
        if (c.clashes.length) d.append(el("div", "c", "vs " + c.clashes.map((x) => `${x.act} ${x.weight.toFixed(2)}`).join(", ")));
        d.title = c.clashes.length ? `${c.act} shares fans with ${c.clashes.map((x) => x.act).join(", ")} at ${slot}` : `${c.act}: no real clash at ${slot}`;
      }
      g.append(d);
    });
  });
}

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

function drawScore(s, now = s.score) {
  $("pub").textContent = s.published_score.toFixed(2);
  $("now").textContent = now.toFixed(2);
  const cut = s.published_score ? (100 * (s.published_score - now)) / s.published_score : 0;
  $("cut").textContent = cut > 0.5 ? `${cut.toFixed(0)}% fewer clashes` : "";
}

function drawSide(s) {
  $("worst").innerHTML = "";
  if (s.worst.length) {
    $("worst").append(el("h3", "", "Worst clashes now"));
    s.worst.forEach((w) => $("worst").append(el("div", "", `${w.slot}  ${w.acts[0]} vs ${w.acts[1]}  (${w.weight.toFixed(2)})`)));
  }
  $("rules").innerHTML = "";
  s.rules.forEach((r) => $("rules").append(el("span", "", r.reads_as)));
  if (s.unmatched.length) $("rules").append(el("div", "", "No Qloo data (treated as no clash): " + s.unmatched.join(", ")));
  $("festnote").textContent = s.festival.note;
  $("demand").innerHTML = "";
  if (s.fan_demand && s.fan_demand.length) {
    $("demand").append(el("div", "", "From fans' routes, still forced to choose:"));
    s.fan_demand.forEach((d) => $("demand").append(el("span", "", `${d.acts[0]} or ${d.acts[1]}: ${d.fans} fan${d.fans > 1 ? "s" : ""}`)));
  }
}

function say(who, text) {
  const kind = who.startsWith("fan:") ? "fan" : who;
  const m = el("div", "msg " + kind);
  m.append(el("div", "who", who.startsWith("fan:") ? `fan agent for ${who.slice(4)}` : who === "booker" ? "booker agent" : who));
  m.append(el("div", "", text));
  $("feed").append(m);
  $("feed").scrollTop = $("feed").scrollHeight;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Replay the feed: messages appear in turn and each referee move is applied to a copy of the old grid.
async function play(old, s) {
  if (!s.feed.length) return;
  const g = old.grid.map((col) => col.map((c) => (c ? { ...c, clashes: [] } : null)));
  const view = { ...old, grid: g };
  for (const f of s.feed) {
    say(f.who, f.text);
    if (f.to) {
      const cells = Object.entries(f.to).map(([act, [st, k]]) => [act, st, k]);
      const from = {};
      g.forEach((col, si) => col.forEach((c, k) => { if (c && f.to[c.act]) from[c.act] = [si, k]; }));
      cells.forEach(([act]) => { if (from[act]) g[from[act][0]][from[act][1]] = null; });
      cells.forEach(([act, st, k]) => { g[st][k] = { act, matched: true, clashes: [] }; });
      drawGrid(view, new Set(cells.map((c) => c[0])));
      drawScore(s, f.score);
      await sleep(320);
    } else {
      await sleep(f.who === "booker" ? 400 : 550);
    }
  }
}

async function show(promise) {
  if (busy) return;
  busy = true;
  document.body.style.cursor = "progress";
  try {
    const old = state, s = await promise;
    if (s.version < latest) return; // a stale reply
    latest = s.version;
    if (s.error) say("error", s.error);
    if (s.rule && s.rule.read_by_model) say("booker", `Read your words as: ${s.rule.reads_as}.`);
    if (old && s.feed.length) await play(old, s);
    state = s;
    drawGrid(s);
    drawScore(s);
    drawSide(s);
  } catch (e) {
    say("error", "Something went wrong: " + e.message);
  } finally {
    busy = false;
    document.body.style.cursor = "";
  }
}

function send(text) {
  if (!state || !text.trim()) return;
  if (text === "Run") return show(post("/api/clash/run", { session: state.session }));
  if (text === "Reset") { $("feed").innerHTML = ""; return show(post("/api/clash/reset", { session: state.session })); }
  return show(post("/api/clash/command", { session: state.session, text }));
}

async function load(slug) {
  $("feed").innerHTML = "";
  latest = -1;
  state = null;
  await show(post("/api/clash/load", { festival: slug }));
  say("referee", "This is the timetable as published. Red cells share many fans with an act on another stage at the same hour. Press 'Run the war-room' or give the booker an order.");
}

async function planDay(e) {
  e.preventDefault();
  const favs = $("favs").value.split(",").map((x) => x.trim()).filter(Boolean).slice(0, 5);
  if (!favs.length || !state) return;
  $("route").textContent = "Asking Qloo...";
  try {
    const r = await post("/api/clash/route", { session: state.session, favourites: favs });
    $("route").innerHTML = "";
    if (r.error) { $("route").textContent = r.error; return; }
    if (r.not_found.length) $("route").append(el("div", "note", "Not found in Qloo: " + r.not_found.join(", ")));
    r.hours.forEach((h) => {
      const row = el("div", "r" + (h.top ? " top" : ""));
      row.append(el("span", "t", h.slot));
      const txt = el("span", "", `${h.act} on ${h.stage} (fit ${h.fit.toFixed(2)})`);
      if (h.clash_with) txt.append(el("span", "must", `  must choose: ${h.clash_with.act} (${h.clash_with.fit.toFixed(2)})`));
      row.append(txt);
      $("route").append(row);
    });
    $("route").append(el("div", "note", r.summary));
    state = r.state; latest = r.state.version; drawSide(state);
  } catch (err) { $("route").textContent = "Something went wrong: " + err.message; }
}

async function proof(slug) {
  const r = await (await fetch("/api/clash/baseline?festival=" + encodeURIComponent(slug))).json();
  const b = $("baseline"), s = r.summary;
  b.innerHTML = "";
  if (!s) { b.textContent = "The model-alone comparison has not been computed for this festival."; return; }
  b.append(el("p", "", "We asked a frontier language model, with no Qloo, to score how much every pair of acts shares fans. Twice, the same question."));
  b.append(el("div", "big", `${s.set_times_that_differ} of ${s.acts}`));
  b.append(el("p", "", "set times differ between the timetables built from its two answers."));
  b.append(el("p", "", `${s.pairs_changed_by_10_or_more} of ${s.pairs} pair scores moved by 10 points or more between the two runs. Qloo gives the same score every time.`));
  b.append(el("p", "", s.unknown.length ? `Acts it said it does not know: ${s.unknown.join(", ")}.` : "It said it knew every act on this bill."));
}

$("routeform").addEventListener("submit", planDay);
$("cmd").addEventListener("submit", (e) => { e.preventDefault(); const t = $("text").value; $("text").value = ""; send(t); });
document.querySelectorAll(".chips button").forEach((b) => b.addEventListener("click", () => send(b.dataset.cmd)));
$("festival").addEventListener("change", (e) => { load(e.target.value); proof(e.target.value); });

(async () => {
  const list = await (await fetch("/api/clash/festivals")).json();
  list.forEach((f) => { const o = el("option", "", f.name); o.value = f.slug; $("festival").append(o); });
  await load(list[0].slug);
  proof(list[0].slug);
  const cmd = new URLSearchParams(location.search).get("cmd"); // e.g. /clash?cmd=Run, for demo links
  if (cmd) send(cmd);
})();
