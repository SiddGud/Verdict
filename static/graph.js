// The bill as Qloo sees it: a force layout where each act is pulled toward the acts its fans share. Pink lines are
// pairs that overlap in time (fans who must choose); "After the court" recolours them for the court's timetable.
(() => {
  const $ = (id) => document.getElementById(id);
  if (!window.d3) return;
  const svg = d3.select("#g-svg"), card = $("g-card");
  let data = null, sim = null, mode = "published", sid = null;

  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const clashOf = (l) => (mode === "published" ? l.clash_published : l.clash_now);
  const initials = (n) => n.replace(/\(.*\)/, "").split(/\s+/).filter(Boolean).map((x) => x[0]).join("").slice(0, 2).toUpperCase();
  const width = (l) => (clashOf(l) ? 1.5 + l.weight * 4 : 0.6 + l.weight * 2.2);

  async function load() {
    const s = window.court && window.court.session();
    if (!s) return;
    sid = s;
    const r = await fetch(`/api/clash/graph?session=${encodeURIComponent(s)}`);
    if (!r.ok) return;
    data = await r.json();
    mode = "published";
    document.querySelectorAll("#g-mode button").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.mode === mode)));
    draw();
  }

  function draw() {
    const box = $("g-svg").getBoundingClientRect(), W = box.width || 900, H = box.height || 560;
    if (sim) sim.stop();
    svg.attr("viewBox", `0 0 ${W} ${H}`).selectAll("*").remove();
    const defs = svg.append("defs");
    const nodes = data.nodes.map((n) => ({ ...n })), byId = new Map(nodes.map((n) => [n.id, n]));
    const links = data.links.filter((l) => byId.has(l.source) && byId.has(l.target)).map((l) => ({ ...l }));
    const degree = {};
    links.forEach((l) => { degree[l.source] = (degree[l.source] || 0) + 1; degree[l.target] = (degree[l.target] || 0) + 1; });
    const R = (n) => 11 + Math.min(9, (degree[n.id] || 0) * 1.6);

    nodes.forEach((n, i) => {
      if (!n.photo) return;
      defs.append("pattern").attr("id", `gp${i}`).attr("patternContentUnits", "objectBoundingBox").attr("width", 1).attr("height", 1)
        .append("image").attr("href", n.photo).attr("width", 1).attr("height", 1).attr("preserveAspectRatio", "xMidYMid slice");
      n.fill = `url(#gp${i})`;
    });

    const link = svg.append("g").selectAll("line").data(links).join("line")
      .attr("class", (l) => "g-link" + (clashOf(l) ? " clash" : "")).attr("stroke-width", width);
    const node = svg.append("g").selectAll("g").data(nodes).join("g")
      .attr("class", (n) => "g-node" + (n.cancelled ? " gone" : "")).attr("tabindex", 0)
      .call(d3.drag().on("start", (e, n) => { if (!e.active) sim.alphaTarget(0.25).restart(); n.fx = n.x; n.fy = n.y; })
        .on("drag", (e, n) => { n.fx = e.x; n.fy = e.y; })
        .on("end", (e, n) => { if (!e.active) sim.alphaTarget(0); n.fx = null; n.fy = null; }));
    node.append("circle").attr("r", (n) => R(n) + 2.5).attr("class", (n) => "ring" + (n.source === "lastfm" ? " lfm" : ""));
    node.append("circle").attr("r", R).attr("class", "face").attr("fill", (n) => n.fill || "var(--qloo-tint)");
    node.filter((n) => !n.photo).append("text").attr("class", "mono").attr("dy", "0.35em").text((n) => initials(n.id));
    node.append("text").attr("class", "lbl").attr("dy", (n) => R(n) + 13).text((n) => n.id.replace(/\s*\(.*\)$/, ""));

    const near = new Map(nodes.map((n) => [n.id, new Set([n.id])]));
    links.forEach((l) => { near.get(l.source).add(l.target); near.get(l.target).add(l.source); });
    node.on("mouseenter focus", (e, n) => focus(n)).on("mouseleave blur", () => focus(null));

    function focus(n) {
      svg.classed("focus", !!n);
      node.classed("on", (m) => !!n && near.get(n.id).has(m.id));
      link.classed("on", (l) => !!n && (l.source.id === n.id || l.target.id === n.id));
      if (!n) { card.hidden = true; return; }
      const mine = links.filter((l) => l.source.id === n.id || l.target.id === n.id).sort((a, b) => b.weight - a.weight);
      const other = (l) => (l.source.id === n.id ? l.target.id : l.source.id);
      const clashes = mine.filter(clashOf);
      card.hidden = false;
      card.innerHTML = `<div class="hd">${n.photo ? `<img src="${esc(n.photo)}" alt="" referrerpolicy="no-referrer">` : `<span class="mono">${esc(initials(n.id))}</span>`}
        <div><strong>${esc(n.id)}</strong><span>${esc(data.stages[n.stage])}${n.source === "lastfm" ? ", fan data from Last.fm" : ""}</span></div></div>
        ${n.about ? `<p class="ab">${esc(n.about)}</p>` : ""}
        <p><b>Fans shared most with:</b> ${mine.slice(0, 4).map((l) => esc(other(l))).join(", ") || "none on this bill"}</p>
        ${clashes.length ? `<p class="cl"><b>Must choose:</b> ${clashes.map((l) => `${esc(other(l))} (${clashOf(l)} min)`).join(", ")}</p>`
          : `<p class="ok">No clash with its closest acts${mode === "now" ? " after the court" : ""}.</p>`}`;
    }

    sim = d3.forceSimulation(nodes)
      .force("link", d3.forceLink(links).id((n) => n.id).distance((l) => 75 + (1 - l.weight) * 170).strength((l) => 0.2 + l.weight * 0.5))
      .force("charge", d3.forceManyBody().strength(-420))
      .force("center", d3.forceCenter(W / 2, H / 2))
      .force("x", d3.forceX(W / 2).strength(0.04)).force("y", d3.forceY(H / 2).strength(0.07))
      .force("collide", d3.forceCollide().radius((n) => R(n) + 16))
      .on("tick", () => {
        nodes.forEach((n) => { n.x = Math.max(70, Math.min(W - 70, n.x)); n.y = Math.max(30, Math.min(H - 34, n.y)); });
        link.attr("x1", (l) => l.source.x).attr("y1", (l) => l.source.y).attr("x2", (l) => l.target.x).attr("y2", (l) => l.target.y);
        node.attr("transform", (n) => `translate(${n.x},${n.y})`);
      });
    count();
  }

  function count() {
    const c = data.links.filter(clashOf).length;
    $("g-count").textContent = `${data.nodes.length} acts, ${data.links.length} close pairs; ${c} pair${c === 1 ? "" : "s"} must choose ${mode === "published" ? "as published" : "after the court"}.`;
  }

  // Switching mode recolours the lines in place, so the layout does not jump.
  async function setMode(m) {
    if (!data) return;
    mode = m;
    document.querySelectorAll("#g-mode button").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.mode === m)));
    if (m === "now") {
      const r = await fetch(`/api/clash/graph?session=${encodeURIComponent(sid)}`);
      if (r.ok) {
        const fresh = await r.json(), now = new Map(fresh.links.map((l) => [l.source + "|" + l.target, l.clash_now]));
        data.links.forEach((l) => { const v = now.get(l.source + "|" + l.target); if (v !== undefined) l.clash_now = v; });
        data.court_has_sat = fresh.court_has_sat;
      }
    }
    const fresh = new Map(data.links.map((l) => [l.source + "|" + l.target, l]));
    svg.selectAll(".g-link").each((l) => {
      const src = fresh.get((l.source.id || l.source) + "|" + (l.target.id || l.target));
      if (src) { l.clash_published = src.clash_published; l.clash_now = src.clash_now; }
    }).attr("class", (l) => "g-link" + (clashOf(l) ? " clash" : "")).transition().duration(600).attr("stroke-width", width);
    count();
    if (m === "now" && !data.court_has_sat) $("g-count").textContent += " Convene the court to see what it changes.";
  }
  document.querySelectorAll("#g-mode button").forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode)));

  // Draw once the court has its session; redraw when the festival day changes.
  const ready = setInterval(() => { if (window.court && window.court.session()) { clearInterval(ready); load(); } }, 300);
  document.addEventListener("court:loaded", load);
  window.billGraph = { load, setMode };
})();
