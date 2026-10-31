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
  // Leaflet tooltips render HTML, and act and venue names come from listings: escape them.
  const esc = (v) => String(v).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const fmt = (d) => new Date(d + "T12:00:00").toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
  const where = () => ({ city: $("d-city").value, month: $("d-month").value });
  const busy = (out, text) => { out.innerHTML = ""; out.append(el("p", "c-wait", text)); };
  const fail = (out, msg) => { out.innerHTML = ""; out.append(el("p", "form-error", msg)); };

  // ---------- the map: the agent flies venue to venue as it reads the month ----------
  const CENTRE = {
    "new-york": [40.7306, -73.9866], chicago: [41.8881, -87.6398], "los-angeles": [34.0622, -118.3037],
    boston: [42.3501, -71.0789], philadelphia: [39.9526, -75.1652], washington: [38.9072, -77.0369],
    atlanta: [33.769, -84.388], nashville: [36.1627, -86.7816], austin: [30.2672, -97.7431],
    denver: [39.7392, -104.9903], seattle: [47.6162, -122.3321], "san-francisco": [37.7749, -122.4194],
  };
  const REDUCE = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const token = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  let map = null, layer = null, sweep = 0, skip = false;

  function ensureMap() {
    if (map || !window.L) return map;
    map = L.map("d-map", { scrollWheelZoom: false }).setView(CENTRE["new-york"], 13);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(map);
    layer = L.layerGroup().addTo(map);
    return map;
  }
  const pause = (ms) => (skip || REDUCE ? Promise.resolve() : new Promise((r) => setTimeout(r, ms)));
  function fly(ll, zoom, secs) {
    if (skip || REDUCE) { map.setView(ll, zoom, { animate: false }); return Promise.resolve(); }
    return new Promise((done) => { map.once("moveend", done); map.flyTo(ll, zoom, { duration: secs }); setTimeout(done, secs * 1000 + 500); });
  }
  function fit(points, maxZoom = 14) {
    const pts = points.filter((p) => p[0] != null);
    // extra room at the bottom, where the caption card sits over the map
    if (pts.length) map.flyToBounds(pts, { paddingTopLeft: [30, 30], paddingBottomRight: [30, 120], maxZoom: Math.max(maxZoom, 14), duration: skip || REDUCE ? 0.01 : 1.2 });
  }
  // The city's core: drop the farthest tenth of venues on each side, so one outlying venue does not zoom the map out.
  function core(points) {
    const pts = points.filter((p) => p[0] != null);
    if (pts.length < 10) return pts;
    const q = (arr, f) => arr[Math.floor(f * (arr.length - 1))];
    const la = pts.map((p) => p[0]).sort((a, b) => a - b), lo = pts.map((p) => p[1]).sort((a, b) => a - b);
    const box = [q(la, 0.1), q(la, 0.9), q(lo, 0.1), q(lo, 0.9)];
    return pts.filter((p) => p[0] >= box[0] && p[0] <= box[1] && p[1] >= box[2] && p[1] <= box[3]);
  }
  function caption(k, t, s) {
    $("d-cap").hidden = false;
    $("d-cap-k").textContent = k;
    $("d-cap-t").textContent = t;
    $("d-cap-s").textContent = s || "";
    $("d-cap").classList.remove("in");
    void $("d-cap").offsetWidth; // restart the entrance
    $("d-cap").classList.add("in");
  }
  const uncaption = () => { $("d-cap").hidden = true; };
  function pulse(lat, lon, cls) {
    return L.marker([lat, lon], { icon: L.divIcon({ className: "", html: `<div class="c-pulse ${cls || ""}"></div>`, iconSize: [44, 44], iconAnchor: [22, 22] }),
      interactive: false, zIndexOffset: 2000 }).addTo(layer);
  }
  function dots(points, artist) {
    const q = token("--qloo"), l = token("--lfm"), g = token("--faint");
    points.forEach((p) => {
      const on = p.weight >= 0.2, col = !on ? g : p.source === "lastfm" ? l : q;
      const tip = esc(`${p.act}, ${fmt(p.date)} at ${p.venue}` + (on && artist ? ` (pulls on ${artist}'s fans)` : ""));
      if (p.weight >= 0.5) { // the shows that pull hardest stand up as pins, bigger for a stronger pull
        const s = Math.round(18 + p.weight * 14);
        L.marker([p.lat, p.lon], { icon: L.divIcon({ className: "", iconSize: [s, s], iconAnchor: [s / 2, s],
          html: `<div class="m-pin${p.source === "lastfm" ? " lfm" : ""}" style="--s:${s}px"><i></i></div>` }), zIndexOffset: Math.round(p.weight * 1000) })
          .bindTooltip(tip, { direction: "top", offset: [0, -s] }).addTo(layer);
        return;
      }
      L.circleMarker([p.lat, p.lon], { radius: on ? 4 + p.weight * 9 : 3, color: col, fillColor: col,
        fillOpacity: on ? 0.35 + p.weight * 0.5 : 0.35, weight: on ? 1.5 : 0.5 })
        .bindTooltip(tip).addTo(layer);
    });
  }
  // A new sweep cancels the one before it; Skip jumps to the end of the current one.
  const begin = () => { sweep += 1; skip = false; return sweep; };
  const live = (id) => id === sweep;
  $("d-skip").addEventListener("click", () => { skip = true; });

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
    r.nights.forEach((n, i) => {
      const d = el("button", "c-dd");
      d.type = "button";
      d.style.setProperty("--i", i);
      const k = Math.round((n.pull / max) * 100);
      d.style.setProperty("--k", k + "%");
      if (n.few_announced) d.classList.add("few");
      if (r.best.includes(n.date)) d.classList.add("best");
      if (r.worst.includes(n.date)) d.classList.add("worst");
      d.append(el("span", "dn", String(Number(n.date.slice(8)))));
      d.append(el("span", "ds", n.few_announced ? "few listed" : `${n.shows} shows`));
      d.title = `${fmt(n.date)}: pull ${n.pull.toFixed(2)} from ${n.shows} shows` + (n.rivals[0] ? `; closest: ${n.rivals[0].act}` : "");
      d.addEventListener("click", () => { night(r, n); nightOnMap(r, n); });
      wrap.append(d);
    });
    return wrap;
  }

  // One night on the map: that night's shows stand out, the rest of the month fades.
  function nightOnMap(r, n) {
    if (!ensureMap()) return;
    begin();
    layer.clearLayers();
    const that = r.map.filter((p) => p.date === n.date), rest = r.map.filter((p) => p.date !== n.date);
    dots(rest.map((p) => ({ ...p, weight: 0 })), null);
    dots(that, r.artist);
    that.filter((p) => p.weight >= 0.2).forEach((p) => pulse(p.lat, p.lon, p.source === "lastfm" ? "l" : ""));
    caption(fmt(n.date), that.length ? `${that.length} shows that night` : "No shows listed that night",
      n.rivals[0] ? `Closest for ${r.artist}'s fans: ${n.rivals[0].act} at ${n.rivals[0].venue} (#${n.rivals[0].rank})` : `Nothing pulls on ${r.artist}'s fans`);
    fit(that.map((p) => [p.lat, p.lon]), 14);
  }

  // The agent's sweep: every show appears as a dot, then the camera visits the shows that pull hardest on the
  // artist's fans, in date order, before pulling back to the whole city.
  async function sweepMonth(r, cal) {
    if (!ensureMap()) { cal.classList.add("shown"); return; }
    const id = begin();
    layer.clearLayers();
    dots(r.map, r.artist);
    const ranked = [...new Set(r.map.filter((p) => p.weight > 0).sort((a, b) => b.weight - a.weight).map((p) => p.act))];
    const seen = new Set(), stops = [];
    r.map.filter((p) => p.weight >= 0.3).sort((a, b) => b.weight - a.weight).forEach((p) => {
      if (!seen.has(p.act) && stops.length < 6) { seen.add(p.act); stops.push(p); }
    });
    stops.sort((a, b) => (a.date < b.date ? -1 : 1));
    caption("Agent", `Reading ${r.shows} shows in ${r.city}`, `Scoring each act for ${r.artist}'s fans with Qloo`);
    fit(core(r.map.map((p) => [p.lat, p.lon])), 13);
    await pause(1300);
    for (const p of stops) {
      if (!live(id)) return;
      const ring = pulse(p.lat, p.lon, p.source === "lastfm" ? "l" : "");
      caption(`Reading ${fmt(p.date)}`, `${p.act} at ${p.venue}`,
        `#${ranked.indexOf(p.act) + 1} for ${r.artist}'s fans (${SRC[p.source] || "Qloo"})`);
      await fly([p.lat, p.lon], 15, 1.1);
      await pause(1000);
      if (live(id)) layer.removeLayer(ring);
    }
    if (!live(id)) return;
    const best = r.nights.filter((n) => r.best.includes(n.date)).map((n) => fmt(n.date));
    caption("Done", `Book ${best[0] || "a quiet night"}`, `${stops.length} venues visited; the calendar shows every night`);
    fit(core(r.map.map((p) => [p.lat, p.lon])), 13);
    cal.classList.add("shown");
    setTimeout(() => { if (live(id)) uncaption(); }, 4000);
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
      const cal = calendar(r);
      left.append(cal);
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
      $("d-map").scrollIntoView({ behavior: REDUCE ? "auto" : "smooth", block: "center" });
      sweepMonth(r, cal);
    } catch (err) { fail(out, "Something went wrong: " + err.message); }
  });

  // ---------- the other tools on the map ----------
  const LINE = { compete: "--err", sequence: "--qloo", copromote: "--ok" };
  async function portfolioOnMap(r) {
    if (!ensureMap()) return;
    const id = begin();
    layer.clearLayers();
    const all = [];
    r.pairs.forEach((p) => {
      const [a, b] = p.shows;
      if (a.lat == null || b.lat == null) return;
      L.polyline([[a.lat, a.lon], [b.lat, b.lon]], { color: token(LINE[p.kind]), weight: p.kind === "compete" ? 4 : 2,
        opacity: 0.75, dashArray: p.kind === "copromote" ? "2 6" : p.kind === "sequence" ? "8 6" : null })
        .bindTooltip(esc(`${a.act} and ${b.act}: ${KIND[p.kind][0].split(":")[0].toLowerCase()}`)).addTo(layer);
      all.push([a.lat, a.lon], [b.lat, b.lon]);
    });
    r.pairs.forEach((p) => p.shows.forEach((x) => {
      if (x.lat != null) L.circleMarker([x.lat, x.lon], { radius: 5, color: token("--ink"), fillColor: token("--surface"), fillOpacity: 1, weight: 2 })
        .bindTooltip(esc(`${x.act}, ${fmt(x.date)} at ${x.venue}`)).addTo(layer);
    }));
    caption("Agent", `${r.promoter}: ${r.shows} shows`, "Linking every pair of shows that share fans");
    fit(all, 13);
    await pause(1300);
    const tour = [...r.pairs.filter((p) => p.kind === "compete"), ...r.pairs.filter((p) => p.kind === "sequence").slice(0, 2),
      ...r.pairs.filter((p) => p.kind === "copromote").slice(0, 1)];
    for (const p of tour) {
      if (!live(id)) return;
      const [a, b] = p.shows;
      if (a.lat == null || b.lat == null) continue;
      caption(KIND[p.kind][0], `${a.act} and ${b.act}`, `${fmt(a.date)} at ${a.venue}; ${fmt(b.date)} at ${b.venue}. ${KIND[p.kind][1]}`);
      map.flyToBounds([[a.lat, a.lon], [b.lat, b.lon]], { paddingTopLeft: [80, 60], paddingBottomRight: [80, 170], maxZoom: 15, duration: skip || REDUCE ? 0.01 : 1.1 });
      await pause(2600);
    }
    if (!live(id)) return;
    caption("Done", `${r.counts.compete} same night, ${r.counts.sequence} within a week, ${r.counts.copromote} to co-promote`, "Red: compete. Pink: sequence. Green: co-promote.");
    fit(all, 13);
  }

  function friendsOnMap(r) {
    if (!ensureMap()) return;
    begin();
    layer.clearLayers();
    const pts = [], at = new Map(); // picks at the same venue share one pin, so none hides another
    r.picks.forEach((p, i) => {
      if (p.lat == null) return;
      const k = `${p.lat},${p.lon}`;
      if (!at.has(k)) at.set(k, []);
      at.get(k).push([i + 1, p]);
    });
    at.forEach((list) => {
      const [, first] = list[0], label = list.map(([n]) => n).join("·");
      L.marker([first.lat, first.lon], { icon: L.divIcon({ className: "", html: `<div class="c-pin${list.length > 1 ? " wide" : ""}">${label}</div>`,
        iconSize: [list.length > 1 ? 44 : 28, 28], iconAnchor: [list.length > 1 ? 22 : 14, 14] }) })
        .bindTooltip(list.map(([n, p]) => esc(`${n}. ${p.act}, ${fmt(p.date)}`)).join("<br>") + `<br>at ${esc(first.venue)}`).addTo(layer);
      pts.push([first.lat, first.lon]);
    });
    if (r.picks[0]) caption("Your month", `${r.picks.length} nights out, numbered by date`, `first: ${r.picks[0].act}, ${fmt(r.picks[0].date)}`);
    fit(pts, 14);
  }

  async function tourOnMap(r) {
    if (!ensureMap()) return;
    const id = begin();
    layer.clearLayers();
    const legs = r.legs.filter((x) => CENTRE[x.slug]), route = legs.map((x) => CENTRE[x.slug]);
    L.polyline(route, { color: token("--qloo"), weight: 3, opacity: 0.8, dashArray: "10 8" }).addTo(layer);
    legs.forEach((x, i) => L.marker(CENTRE[x.slug], { icon: L.divIcon({ className: "", html: `<div class="c-pin">${i + 1}</div>`, iconSize: [28, 28], iconAnchor: [14, 14] }) })
      .bindTooltip(esc(`${i + 1}. ${x.city}${x.date ? ", " + fmt(x.date) : ""}`)).addTo(layer));
    caption("Route", legs.map((x) => x.city).join(" to "), r.route_why);
    fit(route, 6);
    await pause(1600);
    for (const [i, x] of legs.entries()) {
      if (!live(id)) return;
      caption(`Stop ${i + 1}`, `${x.city}${x.date ? ", " + fmt(x.date) : ""}`,
        x.error || (x.rivals[0] ? `Closest rival that night: ${x.rivals[0].act}` : "No rival for these fans that night"));
      await fly(CENTRE[x.slug], 11, 1.4);
      await pause(900);
    }
    if (live(id)) fit(route, 6);
  }

  // ---------- promoter portfolio ----------
  let promotersFor = "", promotersLoading = null;
  function loadPromoters() {
    // Every caller waits on the same load, so a submit right after a tab switch sees the filled list.
    const w = where(), key = w.city + w.month;
    if (promotersFor === key && promotersLoading) return promotersLoading;
    promotersFor = key;
    const sel = $("p-promoter");
    sel.innerHTML = "";
    promotersLoading = (async () => {
      const r = await (await fetch(`/api/city/promoters?city=${w.city}&month=${w.month}`)).json();
      r.promoters.forEach((p) => { const o = el("option", "", `${p.name} (${p.shows} shows)`); o.value = p.name; sel.append(o); });
      if (!r.promoters.length) sel.append(el("option", "", "No promoter named on this month's listings"));
    })();
    return promotersLoading;
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
      portfolioOnMap(r);
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
      ourMonth(out, r);
    } catch (err) { fail(out, "Something went wrong: " + err.message); }
  });

  // The group's month as a timetable: the calendar with each night out, then the nights in order with who goes.
  const initial = (n) => n.trim().slice(0, 1).toUpperCase();
  function ourMonth(out, r) {
    const plan = r.plan || [];
    if (!plan.length) { out.append(el("p", "", "No show this month suits any of you. Try more or different artists.")); return; }
    const all = plan.filter((p) => p.everyone).length, many = r.people.length > 1;
    out.append(el("p", "c-lead", `Your month: ${plan.length} nights out` + (many && all ? `, ${all} with all of you` : "") +
      `, picked from ${r.shows} shows on sale. Each person goes to shows they would love (about their top tenth of the month).`));
    if (many) {
      const who = el("div", "s-whoall");
      r.people.forEach((n) => who.append(el("span", "", `${n}: ${plan.filter((p) => p.going.includes(n)).length} nights`)));
      out.append(who);
    }
    // the calendar
    const cal = el("div", "s-mcal");
    ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].forEach((d) => cal.append(el("div", "c-dow", d)));
    const d0 = new Date(r.start + "T12:00:00"), d1 = new Date(r.end + "T12:00:00");
    for (let i = 0; i < (d0.getDay() + 6) % 7; i++) cal.append(el("div", "s-day blank"));
    const byDate = new Map(plan.map((p, i) => [p.date, [p, i]]));
    for (let d = new Date(d0); d <= d1; d.setDate(d.getDate() + 1)) {
      const iso = d.toISOString().slice(0, 10), hit = byDate.get(iso);
      const c = el(hit ? "button" : "div", "s-day" + (hit ? " on" + (hit[0].everyone ? " all" : "") : ""));
      c.append(el("span", "dn", String(d.getDate())));
      if (hit) {
        const [p, i] = hit;
        c.type = "button";
        c.append(el("span", "da", p.act));
        const w = el("span", "dw");
        p.going.forEach((n) => w.append(el("i", "", initial(n))));
        c.append(w);
        c.title = `${p.act} at ${p.venue}: ${p.going.join(", ")}`;
        c.addEventListener("click", () => { document.getElementById("night-" + i).scrollIntoView({ behavior: "smooth", block: "center" }); nightOut(p); });
      }
      cal.append(c);
    }
    out.append(cal);
    // the agenda
    const list = el("ol", "s-agenda");
    plan.forEach((p, i) => {
      const li = el("li", p.everyone ? "all" : "");
      li.id = "night-" + i;
      const when = el("div", "s-when");
      when.append(el("strong", "", fmt(p.date)), el("span", "", p.time ? p.time.slice(0, 5) : ""));
      const what = el("div", "s-agw");
      const head = el("div", "s-agh");
      head.append(el("strong", "", p.act), el("span", "", ` at ${p.venue}`));
      what.append(head);
      const who = el("div", "s-going");
      if (p.everyone) who.append(el("b", "", "All of you"));
      else who.append(el("span", "", p.going.join(" and ") + (p.going.length === 1 && many ? " (just you)" : "")));
      what.append(who);
      if (p.alt) what.append(el("span", "s-alt", `Or that night: ${p.alt.act} at ${p.alt.venue} (${p.alt.going.join(", ")})`));
      const go = el("div", "s-act");
      const map = el("button", "quiet small", "On the map");
      map.type = "button";
      map.addEventListener("click", () => nightOut(p));
      go.append(map);
      if (p.url) { const t = el("a", "s-tix", "Tickets"); t.href = p.url; t.target = "_blank"; t.rel = "noopener"; go.append(t); }
      li.append(when, what, go);
      list.append(li);
    });
    out.append(list);
    if (r.pairs.length) {
      const top = r.pairs[0];
      out.append(el("p", "hint", `Closest tastes: ${top.people[0]} and ${top.people[1]} (of the shows either would love, ` +
        `${Math.round(top.shared * 100)}% suit both).`));
    }
    friendsOnMap({ picks: plan });
  }
  function nightOut(p) {
    if (!ensureMap() || p.lat == null) return;
    caption(fmt(p.date), p.act, `at ${p.venue}, ${p.everyone ? "all of you" : p.going.join(" and ")}`);
    fly([p.lat, p.lon], 15, 1.2);
    document.getElementById("d-map").scrollIntoView({ behavior: "smooth", block: "center" });
  }

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
      tourOnMap(r);
    } catch (err) { fail(out, "Something went wrong: " + err.message); }
  });

  // ---------- options ----------
  (async () => {
    const o = await (await fetch("/api/city/options")).json();
    o.cities.forEach((c) => { const x = el("option", "", c.name); x.value = c.slug; $("d-city").append(x); });
    o.months.forEach((m) => { const x = el("option", "", m.name); x.value = m.key; $("d-month").append(x); });
    o.cities.forEach((c, i) => {
      const b = el("button", "", c.name);
      b.type = "button"; b.dataset.slug = c.slug; b.setAttribute("aria-pressed", "true");
      b.addEventListener("click", () => b.setAttribute("aria-pressed", String(b.getAttribute("aria-pressed") !== "true")));
      $("t-cities").append(b);
    });
    ["d-city", "d-month"].forEach((id) => $(id).addEventListener("change", () => { promotersFor = ""; if (!$("f-port").hidden) loadPromoters(); }));
    if (ensureMap()) {
      $("d-city").addEventListener("change", () => { begin(); layer.clearLayers(); uncaption(); fly(CENTRE[$("d-city").value], 13, 1.4); });
    }
    const q = new URLSearchParams(location.search);
    if (q.get("book")) { $("b-artist").value = q.get("book"); $("f-book").requestSubmit(); }
    const tab = (name) => document.querySelector(`#tabs button[data-tab="${name}"]`).click();
    if (q.get("portfolio")) { tab("portfolio"); await loadPromoters(); $("f-port").requestSubmit(); }
    if (q.get("friends")) { tab("friends"); $("f-friends").requestSubmit(); }
    if (q.get("tour")) { tab("tour"); $("t-artist").value = q.get("tour"); $("t-route").click(); }
  })();

  // Hooks for the guided tour: each resolves when the map has finished its sweep.
  const whenDone = (test, ms) => new Promise((done) => {
    const t0 = Date.now(), id = setInterval(() => { if (test() || Date.now() - t0 > ms) { clearInterval(id); done(); } }, 250);
  });
  const pick = (name) => document.querySelector(`#tabs button[data-tab="${name}"]`).click();
  window.cityDesk = {
    async book(artist) {
      pick("book");
      $("b-artist").value = artist;
      $("f-book").requestSubmit();
      await whenDone(() => document.querySelector("#o-book .c-cal.shown"), 60000);
    },
    async portfolio() {
      pick("portfolio");
      await loadPromoters();
      $("f-port").requestSubmit();
      await whenDone(() => $("d-cap-k").textContent === "Done" && document.querySelector("#o-port .c-cols"), 60000);
    },
  };
})();
