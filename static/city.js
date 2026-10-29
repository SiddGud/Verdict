// City desk: four tools over one city's month of shows. Each answer comes from /api/city/*; nothing is computed here
// except layout.
(() => {
  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; };
  const post = async (path, body) => {
    const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
    return r.json();
  };
  const SRC = { qloo: "Qloo", lastfm: "Last.fm", named: "named" };
  const fmt = (d) => new Date(d + "T12:00:00").toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
  const where = () => ({ city: $("d-city").value, month: $("d-month").value });
  const busy = (out, text) => { out.innerHTML = ""; out.append(el("p", "c-wait", text)); };
  const fail = (out, msg) => { out.innerHTML = ""; out.append(el("p", "form-error", msg)); };

  // ---------- tabs ----------
  document.querySelectorAll("#tabs button").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll("#tabs button").forEach((x) => x.setAttribute("aria-checked", String(x === b)));
    document.querySelectorAll(".c-tab").forEach((t) => { t.hidden = t.dataset.tab !== b.dataset.tab; });
    if (b.dataset.tab === "portfolio") loadPromoters();
  }));

  // ---------- book a date ----------
  function calendar(r) {
    const wrap = el("div", "c-cal");
    ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].forEach((d) => wrap.append(el("div", "c-dow", d)));
    const first = new Date(r.nights[0].date + "T12:00:00");
    for (let i = 0; i < (first.getDay() + 6) % 7; i++) wrap.append(el("div", "c-dd blank"));
    const max = Math.max(...r.nights.map((n) => n.pull), 0.01);
    r.nights.forEach((n) => {
      const d = el("button", "c-dd");
      d.type = "button";
      const k = Math.round((n.pull / max) * 100);
      d.style.setProperty("--k", k + "%");
      if (n.few_announced) d.classList.add("few");
      if (r.best.includes(n.date)) d.classList.add("best");
      if (r.worst.includes(n.date)) d.classList.add("worst");
      d.append(el("span", "dn", String(Number(n.date.slice(8)))));
      d.append(el("span", "ds", n.few_announced ? "few listed" : `${n.shows} shows`));
      d.title = `${fmt(n.date)}: pull ${n.pull.toFixed(2)} from ${n.shows} shows` + (n.rivals[0] ? `; closest: ${n.rivals[0].act}` : "");
      d.addEventListener("click", () => night(r, n));
      wrap.append(d);
    });
    return wrap;
  }

  function night(r, n) {
    const box = $("o-night");
    box.innerHTML = "";
    box.append(el("h4", "", `${fmt(n.date)}: ${n.shows} shows listed (a ${n.weekday} usually has ${n.usual})`));
    if (n.few_announced) box.append(el("p", "hint", "Fewer shows announced than a usual " + n.weekday + ": it may only look quiet."));
    if (!n.rivals.length) box.append(el("p", "", `No show that night pulls on ${r.artist}'s fans.`));
    n.rivals.forEach((x) => {
      const row = el("div", "c-li");
      row.append(el("span", "c-rank", `#${x.rank}`));
      row.append(el("span", "", `${x.act} at ${x.venue}${x.time ? ", " + x.time : ""}`));
      row.append(el("span", "c-src " + x.source, SRC[x.source] || ""));
      box.append(row);
    });
  }

  $("f-book").addEventListener("submit", async (e) => {
    e.preventDefault();
    const artist = $("b-artist").value.trim(), out = $("o-book");
    if (!artist) return;
    busy(out, "Reading every show on sale this month...");
    try {
      const r = await post("/api/city/plan", { ...where(), artist, weekends: $("b-weekends").checked });
      if (r.error) return fail(out, r.error);
      out.innerHTML = "";
      out.append(el("p", "c-lead", `${r.shows} shows on sale in ${r.city}; ${r.scored} of their acts scored for ${r.artist}'s fans. Darker nights pull harder on those fans.`));
      const grid = el("div", "c-split");
      const left = el("div", "");
      left.append(calendar(r));
      const legend = el("div", "c-legend");
      legend.innerHTML = '<span><i class="sw best"></i>Best three nights</span><span><i class="sw worst"></i>Worst three</span><span><i class="sw few"></i>Few shows announced yet</span>';
      left.append(legend);
      const right = el("div", "");
      right.append(el("h4", "", "Avoid, partner, book"));
      const best = r.nights.filter((n) => r.best.includes(n.date));
      const worst = r.nights.filter((n) => r.worst.includes(n.date));
      right.append(el("p", "", "Book: " + best.map((n) => fmt(n.date)).join(", ") + "."));
      right.append(el("p", "", "Avoid: " + worst.map((n) => `${fmt(n.date)}${n.rivals[0] ? " (" + n.rivals[0].act + ")" : ""}`).join(", ") + "."));
      if (r.partners.length) {
        right.append(el("h4", "", "Partners: their fans are your fans"));
        r.partners.slice(0, 6).forEach((x) => {
          const row = el("div", "c-li");
          row.append(el("span", "c-rank", `#${x.rank}`));
          row.append(el("span", "", `${x.act}, ${fmt(x.date)} at ${x.venue}`));
          row.append(el("span", "c-src " + x.source, SRC[x.source] || ""));
          right.append(row);
        });
        right.append(el("p", "hint", "Market to their crowds, swap promos, or bundle. On your own night they are rivals."));
      }
      const nb = el("div", "c-night");
      nb.id = "o-night";
      right.append(nb);
      grid.append(left, right);
      out.append(grid);
      night(r, worst[0] || r.nights[0]);
    } catch (err) { fail(out, "Something went wrong: " + err.message); }
  });

  // ---------- promoter portfolio ----------
  let promotersFor = "";
  async function loadPromoters() {
    const w = where(), key = w.city + w.month;
    if (promotersFor === key) return;
    promotersFor = key;
    const sel = $("p-promoter");
    sel.innerHTML = "";
    const r = await (await fetch(`/api/city/promoters?city=${w.city}&month=${w.month}`)).json();
    r.promoters.forEach((p) => { const o = el("option", "", `${p.name} (${p.shows} shows)`); o.value = p.name; sel.append(o); });
    if (!r.promoters.length) sel.append(el("option", "", "No promoter named on this month's listings"));
  }
  const KIND = {
    compete: ["Same night: competing for the same fans", "Move one, or market them as a pair."],
    sequence: ["Within a week: the first crowd is the second show's audience", "Advertise the later show at the earlier one."],
    copromote: ["Further apart: co-promote", "Shared mailing list, a bundle, or retargeting."],
  };
  $("f-port").addEventListener("submit", async (e) => {
    e.preventDefault();
    const out = $("o-port"), promoter = $("p-promoter").value;
    if (!promoter) return;
    busy(out, "Scoring every pair of this promoter's shows (the first time for a city takes a few minutes)...");
    try {
      const r = await post("/api/city/portfolio", { ...where(), promoter });
      if (r.error) return fail(out, r.error);
      out.innerHTML = "";
      out.append(el("p", "c-lead", `${r.promoter}: ${r.shows} shows in ${r.city}, ${r.matched} of ${r.acts} acts with fan data. Pairs that share the most fans:`));
      const cols = el("div", "c-cols");
      ["compete", "sequence", "copromote"].forEach((k) => {
        const c = el("div", "c-colbox " + k);
        c.append(el("h4", "", `${KIND[k][0]} (${r.counts[k]})`));
        c.append(el("p", "hint", KIND[k][1]));
        r.pairs.filter((p) => p.kind === k).slice(0, 6).forEach((p) => {
          const [a, b] = p.shows;
          const row = el("div", "c-pair");
          row.append(el("div", "", `${a.act}, ${fmt(a.date)}, ${a.venue}`));
          row.append(el("div", "", `${b.act}, ${fmt(b.date)}, ${b.venue}`));
          c.append(row);
        });
        if (!r.counts[k]) c.append(el("p", "", "None this month."));
        cols.append(c);
      });
      out.append(cols);
    } catch (err) { fail(out, "Something went wrong: " + err.message); }
  });

  // ---------- friends ----------
  function person(name = "", artists = "") {
    const row = el("div", "c-person");
    const n = el("input"); n.placeholder = "Name"; n.maxLength = 30; n.value = name; n.className = "pn";
    const a = el("input"); a.placeholder = "Artists they love, comma separated"; a.maxLength = 300; a.value = artists; a.className = "pa";
    row.append(n, a);
    $("people").append(row);
  }
  person("Asha", "Clairo, Phoebe Bridgers");
  person("Ben", "Mitski, boygenius");
  $("add-person").addEventListener("click", () => { if ($("people").children.length < 6) person(); });
  $("f-friends").addEventListener("submit", async (e) => {
    e.preventDefault();
    const out = $("o-friends"), people = {};
    $("people").querySelectorAll(".c-person").forEach((r) => {
      const n = r.querySelector(".pn").value.trim(), a = r.querySelector(".pa").value.split(",").map((x) => x.trim()).filter(Boolean);
      if (n && a.length) people[n] = a.slice(0, 5);
    });
    if (!Object.keys(people).length) return;
    busy(out, "Scoring the month for each of you...");
    try {
      const r = await post("/api/city/friends", { ...where(), people });
      if (r.error) return fail(out, r.error);
      out.innerHTML = "";
      if (!r.picks.length) out.append(el("p", "", "No show this month suits everyone. Try fewer people or more artists."));
      else out.append(el("p", "c-lead", `The shows that suit all of you, out of ${r.shows} on sale:`));
      r.picks.forEach((p) => {
        const row = el("div", "c-pick");
        row.append(el("div", "c-pt", `${p.act}, ${fmt(p.date)} at ${p.venue}`));
        const bars = el("div", "c-bars");
        Object.entries(p.fits).forEach(([n, v]) => {
          const b = el("div", "c-bar");
          b.append(el("span", "", n));
          const t = el("i", ""); t.style.width = Math.round(v * 100) + "%";
          const track = el("span", "c-track"); track.append(t);
          b.append(track);
          bars.append(b);
        });
        row.append(bars);
        out.append(row);
      });
      if (r.pairs.length) {
        out.append(el("h4", "", "Who should go together"));
        r.pairs.forEach((p) => out.append(el("p", "", `${p.people[0]} and ${p.people[1]}: ${Math.round(p.shared * 100)}% of the shows either would love, both would.`)));
      }
    } catch (err) { fail(out, "Something went wrong: " + err.message); }
  });

  // ---------- openers and tour ----------
  $("f-tour").addEventListener("submit", async (e) => {
    e.preventDefault();
    const out = $("o-tour"), headliner = $("t-artist").value.trim();
    if (!headliner) return;
    busy(out, "The model suggests openers; Qloo and Ticketmaster check each one...");
    try {
      const r = await post("/api/city/support", { headliner });
      if (r.error) return fail(out, r.error);
      out.innerHTML = "";
      out.append(el("p", "c-lead", `Openers for ${r.headliner}, ranked by how much ${r.headliner}'s fans share them (Qloo).`));
      r.openers.forEach((x) => {
        const row = el("div", "c-li c-op");
        row.append(el("span", "c-rank", x.overlap_rank ? `#${x.overlap_rank}` : "n/a"));
        const t = el("div", "");
        t.append(el("strong", "", x.name), ` ${x.smaller_draw === false ? "(bigger draw than the headliner)" : ""}`);
        t.append(el("span", "c-why", x.why));
        if (x.playing.length) t.append(el("span", "c-play", "On sale: " + x.playing.join(", ")));
        row.append(t);
        row.append(el("span", "c-src model", "model idea"));
        out.append(row);
      });
      out.append(el("p", "hint", r.note));
    } catch (err) { fail(out, "Something went wrong: " + err.message); }
  });

  $("t-route").addEventListener("click", async () => {
    const out = $("o-tour"), artist = $("t-artist").value.trim();
    const cities = [...$("t-cities").querySelectorAll("button[aria-pressed='true']")].map((b) => b.dataset.slug);
    if (!artist || cities.length < 2) { fail(out, "Name the artist above and pick at least two cities."); return; }
    busy(out, "The model orders the cities; each date is picked from that city's listings...");
    try {
      const r = await post("/api/city/tour", { artist, cities, month: $("d-month").value });
      if (r.error) return fail(out, r.error);
      out.innerHTML = "";
      out.append(el("p", "c-lead", `Route: ${r.route_why}`));
      r.legs.forEach((x, i) => {
        const row = el("div", "c-li");
        row.append(el("span", "c-rank", String(i + 1)));
        row.append(el("span", "", x.error ? `${x.city}: ${x.error}` :
          `${x.city}, ${fmt(x.date)}: pull ${x.pull.toFixed(2)}${x.rivals[0] ? `, closest rival ${x.rivals[0].act}` : ", no rival for these fans"}${x.few_announced ? " (few shows announced yet)" : ""}`));
        out.append(row);
      });
      out.append(el("p", "hint", r.note));
    } catch (err) { fail(out, "Something went wrong: " + err.message); }
  });

  // ---------- options ----------
  (async () => {
    const o = await (await fetch("/api/city/options")).json();
    o.cities.forEach((c) => { const x = el("option", "", c.name); x.value = c.slug; $("d-city").append(x); });
    o.months.forEach((m) => { const x = el("option", "", m.name); x.value = m.key; $("d-month").append(x); });
    o.cities.forEach((c, i) => {
      const b = el("button", "", c.name);
      b.type = "button"; b.dataset.slug = c.slug; b.setAttribute("aria-pressed", String(["new-york", "boston", "philadelphia", "washington"].includes(c.slug)));
      b.addEventListener("click", () => b.setAttribute("aria-pressed", String(b.getAttribute("aria-pressed") !== "true")));
      $("t-cities").append(b);
    });
    ["d-city", "d-month"].forEach((id) => $(id).addEventListener("change", () => { promotersFor = ""; if (!$("f-port").hidden) loadPromoters(); }));
    const q = new URLSearchParams(location.search);
    if (q.get("book")) { $("b-artist").value = q.get("book"); $("f-book").requestSubmit(); }
  })();
})();
