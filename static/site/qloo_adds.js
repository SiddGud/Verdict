// What Qloo adds on the festival day in view: coverage and identity (IDs, photos), consistency against a model asked
// twice with no Qloo, what each side does not know, and cost. Accuracy is stated as Test 28 found it: a tie.
(() => {
  const $ = (id) => document.getElementById(id);
  if (!$("qa-grid")) return;
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; };
  const MODEL_COST = 0.5; // measured: $0.47 and $0.56 for one model-alone scoring of a 40 to 44 act bill (CometAPI)
  let shown = null;

  function tile(cls, k, big, text, extra) {
    const t = el("div", "c-add " + cls);
    t.append(el("span", "k", k));
    const b = el("div", "big"); b.innerHTML = big; t.append(b);
    if (extra) t.append(extra);
    t.append(el("p", "", text));
    return t;
  }

  async function draw() {
    const st = window.court && window.court.current && window.court.current();
    if (!st) return;
    const f = st.festival;
    if (shown === f.slug) return;
    shown = f.slug;
    const acts = st.sets.filter((x) => x.act).length, lfm = (st.from_lastfm || []).length, none = (st.unmatched || []).length;
    const inQloo = acts - lfm - none, photos = Object.keys(f.photos || {}).length;
    $("qa-day").textContent = f.name.replace(/\s*\(.*\)$/, "");
    const g = $("qa-grid");
    g.innerHTML = "";
    const faces = el("div", "faces");
    Object.values(f.photos || {}).slice(0, 7).forEach((u) => { const i = new Image(); i.src = u; i.alt = ""; i.referrerPolicy = "no-referrer"; faces.append(i); });
    g.append(tile("q", "Who is who", `${inQloo}<small> of ${acts} acts</small>`,
      `matched in Qloo by exact name, each with an ID${photos ? ", a photo and a description" : ""}. ${lfm} filled from Last.fm, ${none} with no data.`, faces));
    let b = null;
    try { b = (await (await fetch(`/api/clash/baseline?festival=${encodeURIComponent(f.slug)}`)).json()).summary; } catch (_) { b = null; }
    if (b) {
      g.append(tile("m", "Same question, twice", `${b.pairs_changed_by_10_or_more}<small> of ${b.pairs} pairs</small>`,
        `changed by 10 points or more when a frontier model, with no Qloo, scored this bill twice. Qloo gave the same scores both times.`));
      g.append(tile("m", "Acts each side does not know", `${b.qloo_no_data.length}<small> Qloo</small> · ${b.model_unknown.length}<small> model</small>`,
        `Qloo has no data for ${b.qloo_no_data.length} (filled from Last.fm). The model said it does not know ` +
        (b.model_unknown.length ? `${b.model_unknown.length}: ${b.model_unknown.slice(0, 3).join(", ")}${b.model_unknown.length > 3 ? "..." : ""}.` : "any of them, but it cannot show an ID, photo or source for its guesses.")));
    } else {
      g.append(tile("m", "Same question, twice", "<small>not measured</small>", "The model-alone comparison has not been run for this day."));
      g.append(tile("m", "What each side does not know", "<small>not measured</small>", "Not run for this day."));
    }
    g.append(tile("t", "Cost of a day's overlap", `~${inQloo * 2}<small> Qloo calls</small>`,
      `once, then cached; no model needed. The model alone: about $${MODEL_COST.toFixed(2)} (measured $0.47 and $0.56) and several minutes for each scoring of a bill like this.`));
    $("qa-note").textContent = "On accuracy, Qloo and a frontier model tie (Test 28, below). Qloo's edge is in identity, " +
      "consistency and cost, and in making a model's own scores closer to real fans when the two work together.";
  }

  const id = setInterval(() => { if (window.court && window.court.current && window.court.current()) { clearInterval(id); draw(); } }, 400);
  document.addEventListener("court:loaded", () => { shown = null; draw(); });
})();
