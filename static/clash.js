// Clash Court page. The server holds the timetable; every reply carries the full state and a version, and the page
// redraws from it. Sets are drawn on a time axis (one column per stage). Referee moves in a feed are replayed on the
// timetable one by one, then the final state is drawn.
const $ = (id) => document.getElementById(id);
const PX = 1.15; // pixels per minute
let state = null, busy = false, latest = -1;

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

function heat(set) {
  const w = set.clashes.length ? set.clashes[0].weight : 0;
  return w >= 0.45 ? "hot" : w >= 0.2 ? "warm" : "";
}

function drawGrid(s, moved = new Set()) {
  const g = $("grid"), f = s.festival, [d0, d1] = f.day;
  const height = (d1 - d0) * PX;
  g.innerHTML = "";
  g.style.gridTemplateColumns = `48px repeat(${f.stages.length}, minmax(120px, 1fr))`;
  g.append(el("div", "h", ""));
  f.stages.forEach((st) => g.append(el("div", "h", st)));
  const axis = el("div", "axis");
  axis.style.height = height + "px";
  for (let m = Math.ceil(d0 / 60) * 60; m <= d1; m += 60) {
    const t = el("div", "tick", clock(m));
    t.style.top = (m - d0) * PX + "px";
    axis.append(t);
  }
  g.append(axis);
  f.stages.forEach((_, si) => {
    const col = el("div", "col");
    col.style.height = height + "px";
    for (let m = Math.ceil(d0 / 60) * 60; m <= d1; m += 60) {
      const line = el("div", "line");
      line.style.top = (m - d0) * PX + "px";
      col.append(line);
    }
    s.sets.filter((x) => x.stage === si).forEach((x) => {
      const d = el("div", "cell " + (x.act ? heat(x) : "empty") + (x.act && !x.matched ? " nodata" : "") + (x.act && moved.has(x.act) ? " moved" : ""));
      d.style.top = (x.start - d0) * PX + 1 + "px";
      d.style.height = Math.max(18, (x.end - x.start) * PX - 3) + "px";
      if (x.act) {
        d.append(el("div", "a", x.act));
        d.append(el("div", "c", `${clock(x.start)} to ${clock(x.end)}` + (x.clashes.length ? "  vs " + x.clashes.map((c) => `${c.act} ${c.weight.toFixed(2)}`).join(", ") : "")));
        d.title = x.clashes.length
          ? `${x.act} shares fans with ${x.clashes.map((c) => `${c.act} (${c.minutes} min overlap)`).join(", ")}`
          : `${x.act}: no real clash`;
      } else {
        d.append(el("div", "c", `${clock(x.start)} empty`));
      }
      col.append(d);
    });
    g.append(col);
  });
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
    s.worst.forEach((w) => $("worst").append(el("div", "", `${w.from}  ${w.acts[0]} vs ${w.acts[1]}: weight ${w.weight.toFixed(2)}, ${w.minutes} minutes`)));
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

// Replay the feed: messages appear in turn and each referee move is applied to a copy of the old timetable.
async function play(old, s) {
  const sets = old.sets.map((x) => ({ ...x, clashes: [] }));
  const cancelled = new Set(s.rules.filter((r) => r.type === "cancel").map((r) => r.act));
  sets.forEach((x) => { if (cancelled.has(x.act)) x.act = null; });
  const view = { ...old, sets };
  drawGrid(view);
  for (const f of s.feed) {
    say(f.who, f.text);
    if (f.to) {
      Object.keys(f.to).forEach((act) => sets.forEach((x) => { if (x.act === act) x.act = null; }));
      Object.entries(f.to).forEach(([act, cell]) => { sets[cell].act = act; sets[cell].matched = true; });
      drawGrid(view, new Set(Object.keys(f.to)));
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
  say("referee", "This is the timetable as published. Red sets share many fans with a set on another stage at the same time. Press 'Run the war-room' or give the booker an order.");
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
    r.sets.forEach((h) => {
      const row = el("div", "r" + (h.top ? " top" : ""));
      row.append(el("span", "t", h.start));
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
  const cmd = new URLSearchParams(location.search).get("cmd"); // e.g. /?cmd=Run, for demo links
  if (cmd) send(cmd);
})();
