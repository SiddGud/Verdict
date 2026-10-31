// Why Qloo: the evidence as interactive charts. Every number is a test result from PROJECT_LOG.md; nothing is computed
// here except layout. Colors come from CSS classes (k-right, k-wrong, k-none), so light and dark themes both work.
(() => {
  const $ = (id) => document.getElementById(id);
  if (!$("w-t20") || !window.d3) return;
  const REDUCE = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const tip = $("w-tip");
  const show = (ev, html) => {
    tip.innerHTML = html; tip.hidden = false;
    const r = tip.getBoundingClientRect(), x = Math.min(ev.clientX + 14, innerWidth - r.width - 8), y = ev.clientY - r.height - 12;
    tip.style.left = x + "px"; tip.style.top = (y < 8 ? ev.clientY + 16 : y) + "px";
  };
  const hide = () => { tip.hidden = true; };
  const once = (el, fn) => {
    if (!("IntersectionObserver" in window)) return fn();
    new IntersectionObserver((seen, o) => seen.forEach((e) => { if (e.isIntersecting) { o.disconnect(); fn(); } }), { threshold: 0.25 }).observe(el);
  };

  // ---------- donuts ----------
  function donut(host, { title, sub, parts, total, center, centerSub, qloo }) {
    const S = 150, R = 66, r = 48;
    const card = document.createElement("div");
    card.className = "w-donut" + (qloo ? " q" : "");
    host.append(card);
    const svg = d3.select(card).append("svg").attr("viewBox", `0 0 ${S} ${S}`).attr("role", "img")
      .attr("aria-label", `${title}: ${parts.map((p) => `${p.n} ${p.label}`).join(", ")}`);
    const g = svg.append("g").attr("transform", `translate(${S / 2},${S / 2})`);
    const pie = d3.pie().sort(null).value((p) => p.n).padAngle(parts.filter((p) => p.n).length > 1 ? 0.03 : 0);
    const arc = d3.arc().innerRadius(r).outerRadius(R).cornerRadius(3);
    const big = d3.arc().innerRadius(r).outerRadius(R + 5).cornerRadius(3);
    g.append("circle").attr("r", (R + r) / 2).attr("class", "w-track").attr("stroke-width", R - r);
    const tipOf = (p) => `<b>${title}</b><br>${p.data.n} of ${total} ${p.data.label.toLowerCase()} (${Math.round(p.data.n / total * 100)}%)`;
    const paths = g.selectAll("path").data(pie(parts)).join("path").attr("class", (p) => p.data.cls)
      .on("mousemove", (ev, p) => { d3.select(ev.currentTarget).attr("d", big); show(ev, tipOf(p)); })
      .on("mouseleave", (ev) => { d3.select(ev.currentTarget).attr("d", arc); hide(); });
    const num = g.append("text").attr("class", "w-cnum").attr("text-anchor", "middle").attr("dy", "0.1em").text(REDUCE ? center : 0);
    g.append("text").attr("class", "w-csub").attr("text-anchor", "middle").attr("dy", "1.6em").text(centerSub);
    const lab = document.createElement("div");
    lab.className = "w-dl";
    lab.innerHTML = `<b>${title}</b><span>${sub}</span>`;
    card.append(lab);
    const grow = () => {
      paths.transition().duration(REDUCE ? 0 : 1100).ease(d3.easeCubicOut)
        .attrTween("d", (p) => { const i = d3.interpolate({ startAngle: 0, endAngle: 0 }, p); return (t) => arc(i(t)); });
      const target = parseInt(center, 10);
      if (!REDUCE && !isNaN(target)) num.transition().duration(1100).tween("text", function () {
        const i = d3.interpolateNumber(0, target); return (t) => { this.textContent = Math.round(i(t)) + center.replace(/^\d+/, ""); };
      });
      else num.text(center);
    };
    paths.attr("d", REDUCE ? arc : null);
    once(card, grow);
  }

  const T20 = [
    { title: "GPT-6 Astra alone", sub: "declined all 30", right: 0, wrong: 0, none: 30 },
    { title: "GPT-6 Astra with Qloo", sub: "+96.7 points, significant", right: 29, wrong: 1, none: 0, qloo: true },
    { title: "Gemini 3.8 Flash alone", sub: "guessed 9 times, wrong on 6", right: 3, wrong: 6, none: 21 },
    { title: "Gemini 3.8 Flash with Qloo", sub: "+86.7 points, significant", right: 29, wrong: 1, none: 0, qloo: true },
  ];
  T20.forEach((m) => donut($("w-t20"), {
    title: m.title, sub: m.sub, total: 30, qloo: m.qloo, center: `${m.right}/30`, centerSub: "right",
    parts: [{ n: m.right, label: "Right within 30 minutes", cls: "k-right" }, { n: m.wrong, label: "Wrong time", cls: "k-wrong" },
      { n: m.none, label: "Said it did not know", cls: "k-none" }],
  }));
  donut($("w-id"), { title: "Places found", sub: "named in model-written NYC plans (Test 22)", total: 120, qloo: true,
    center: "119/120", centerSub: "found",
    parts: [{ n: 119, label: "Found by Qloo", cls: "k-right" }, { n: 1, label: "Not found", cls: "k-none" }] });
  donut($("w-id"), { title: "Festival acts matched", sub: "Lollapalooza Thursday 2024; Last.fm fills the rest", total: 44, qloo: true,
    center: "38/44", centerSub: "in Qloo",
    parts: [{ n: 38, label: "Matched in Qloo (ID, photo, description)", cls: "k-right" }, { n: 6, label: "Filled from Last.fm", cls: "k-alt" }] });

  // ---------- dumbbell: model alone to model with Qloo ----------
  const DUMB = [
    { task: "Shared fans", model: "GPT-6 Astra", test: "Test 28", metric: "Spearman", a: 0.697, ai: [0.671, 0.721], q: 0.728, qi: [0.707, 0.750], d: "+0.031 [0.005, 0.056]", v: "Significant" },
    { task: "Shared fans", model: "Gemini 3.8 Flash", test: "Test 28", metric: "Spearman", a: 0.695, ai: [0.670, 0.718], q: 0.723, qi: [0.697, 0.750], d: "+0.028 [0.003, 0.056]", v: "Significant" },
    { task: "Timetable quality", model: "GPT-6 Astra", test: "Test 28", metric: "gain, 0 random to 1 best", a: 0.669, ai: [0.634, 0.704], q: 0.702, qi: [0.652, 0.746], d: "+0.033 [0.000, 0.063]", v: "Borderline" },
    { task: "Small artists", model: "GPT-6 Astra", test: "Test 27", metric: "AUC", a: 0.865, ai: [0.827, 0.901], q: 0.874, qi: [0.84, 0.906], d: "+0.010 [-0.001, 0.022]", v: "Higher" },
  ];
  // drawn at the panel's real width once it is on screen, so text stays at its true size
  once($("w-dumb"), function dumbbell() {
    const host = $("w-dumb");
    const W = Math.max(300, host.clientWidth), narrow = W < 700, rowH = 58, L = narrow ? 128 : 230, Rm = narrow ? 104 : 170, T = 26, H = T + DUMB.length * rowH + 8;
    const svg = d3.select(host).append("svg").attr("viewBox", `0 0 ${W} ${H}`).attr("role", "img")
      .attr("aria-label", "Each model alone and with Qloo, four comparisons");
    const x = d3.scaleLinear().domain([0.6, 0.95]).range([L, W - Rm]);
    svg.append("g").attr("class", "w-axis").attr("transform", `translate(0,${T - 6})`)
      .call(d3.axisTop(x).ticks(narrow ? 4 : 7).tickSize(-(H - T)).tickFormat(d3.format(".2f")))
      .call((g) => g.select(".domain").remove());
    DUMB.forEach((r, i) => {
      const y = T + i * rowH + rowH / 2, g = svg.append("g").attr("class", "w-row");
      g.append("rect").attr("class", "w-hit").attr("x", 0).attr("y", y - rowH / 2).attr("width", W).attr("height", rowH);
      g.append("text").attr("class", "w-rl").attr("x", 0).attr("y", y - 4).text(r.task);
      g.append("text").attr("class", "w-rs").attr("x", 0).attr("y", y + 13).text(`${r.model}, ${r.test}`);
      [["ai", "k-none", -7], ["qi", "k-right", 7]].forEach(([k, c, dy]) => g.append("line").attr("class", `w-ci ${c}`)
        .attr("x1", x(r[k][0])).attr("x2", x(r[k][1])).attr("y1", y + dy).attr("y2", y + dy));
      const bar = g.append("line").attr("class", "w-link").attr("x1", x(r.a)).attr("x2", x(r.a)).attr("y1", y).attr("y2", y);
      g.append("circle").attr("class", "k-none w-dot").attr("cx", x(r.a)).attr("cy", y).attr("r", 7);
      const qd = g.append("circle").attr("class", "k-right w-dot").attr("cx", x(r.a)).attr("cy", y).attr("r", 8);
      g.append("text").attr("class", "w-val").attr("x", W - Rm + 12).attr("y", y - 2).text(narrow ? `to ${r.q.toFixed(3)}` : `${r.a.toFixed(3)} to ${r.q.toFixed(3)}`);
      g.append("text").attr("class", "w-ver" + (r.v === "Significant" ? " sig" : "")).attr("x", W - Rm + 12).attr("y", y + 15).text(r.v);
      g.on("mousemove", (ev) => show(ev, `<b>${r.task}, ${r.model}</b> (${r.test}, ${r.metric})<br>Alone ${r.a} [${r.ai.join(", ")}]<br>With Qloo <b>${r.q}</b> [${r.qi.join(", ")}]<br>Difference ${r.d}: <b>${r.v}</b>`))
        .on("mouseleave", hide);
      once(host, () => {
        bar.transition().delay(200 + i * 150).duration(REDUCE ? 0 : 900).attr("x2", x(r.q));
        qd.transition().delay(200 + i * 150).duration(REDUCE ? 0 : 900).attr("cx", x(r.q));
      });
    });
  });

  // ---------- Qloo against popularity ----------
  const POP = [
    { task: "Timetable quality", test: "Test 28", q: 0.663, p: 0.043 },
    { task: "Shared fans (Spearman)", test: "Test 28", q: 0.723, p: 0.394 },
    { task: "Small artists (AUC)", test: "Test 27", q: 0.841, p: 0.516 },
    { task: "Real tour bills (AUC)", test: "Test 15", q: 0.875, p: 0.473 },
    { task: "Films a person loves (AUC)", test: "Test 18", q: 0.758, p: 0.687 },
    { task: "Venue bookings (AUC)", test: "Test 14", q: 0.589, p: 0.485 },
  ];
  once($("w-pop"), function bars() {
    const host = $("w-pop"), W = Math.max(280, host.clientWidth), L = W < 420 ? 130 : 186, R = 46, rowH = 46, T = 6, H = T + POP.length * rowH;
    const svg = d3.select(host).append("svg").attr("viewBox", `0 0 ${W} ${H}`).attr("role", "img")
      .attr("aria-label", "Qloo against popularity in six tests");
    const x = d3.scaleLinear().domain([0, 1]).range([L, W - R]);
    POP.forEach((r, i) => {
      const y = T + i * rowH, g = svg.append("g").attr("class", "w-row");
      g.append("rect").attr("class", "w-hit").attr("x", 0).attr("y", y).attr("width", W).attr("height", rowH);
      g.append("text").attr("class", "w-rl sm").attr("x", 0).attr("y", y + 17).text(r.task);
      g.append("text").attr("class", "w-rs").attr("x", 0).attr("y", y + 33).text(r.test);
      const bq = g.append("rect").attr("class", "k-right").attr("x", L).attr("y", y + 6).attr("height", 14).attr("rx", 3).attr("width", 0);
      const bp = g.append("rect").attr("class", "k-none").attr("x", L).attr("y", y + 23).attr("height", 14).attr("rx", 3).attr("width", 0);
      const tq = g.append("text").attr("class", "w-bv").attr("x", L + 4).attr("y", y + 17).text(r.q.toFixed(2)).attr("opacity", 0);
      const tp = g.append("text").attr("class", "w-bv mute").attr("x", L + 4).attr("y", y + 34).text(r.p.toFixed(2)).attr("opacity", 0);
      g.on("mousemove", (ev) => show(ev, `<b>${r.task}</b> (${r.test})<br>Qloo <b>${r.q}</b>, popularity ${r.p}<br>Qloo ahead by ${(r.q - r.p).toFixed(3)}`)).on("mouseleave", hide);
      once(host, () => {
        const d = REDUCE ? 0 : 900;
        bq.transition().delay(i * 90).duration(d).attr("width", Math.max(2, x(r.q) - L));
        bp.transition().delay(i * 90).duration(d).attr("width", Math.max(2, x(r.p) - L));
        tq.transition().delay(i * 90 + d).attr("x", x(r.q) + 6).attr("opacity", 1);
        tp.transition().delay(i * 90 + d).attr("x", Math.max(L, x(r.p)) + 6).attr("opacity", 1);
      });
    });
  });

  // ---------- consistency waffle ----------
  const DAYS = [
    { key: "fri", label: "2026 Fri", pairs: 903, moved: 46 }, { key: "sun", label: "2026 Sun", pairs: 903, moved: 13 },
    { key: "thu", label: "2026 Thu", pairs: 903, moved: 9 }, { key: "sat", label: "2026 Sat", pairs: 903, moved: 9 },
    { key: "t24", label: "2024 Thu", pairs: 946, moved: 4 },
  ];
  let day = DAYS[0], src = "model";
  DAYS.forEach((d, i) => {
    const b = document.createElement("button");
    b.type = "button"; b.setAttribute("role", "radio"); b.setAttribute("aria-checked", String(i === 0)); b.textContent = d.label;
    b.addEventListener("click", () => { day = d; [...$("w-days").children].forEach((x) => x.setAttribute("aria-checked", String(x === b))); waffle(); });
    $("w-days").append(b);
  });
  [...$("w-src").children].forEach((b) => b.addEventListener("click", () => {
    src = b.dataset.src; [...$("w-src").children].forEach((x) => x.setAttribute("aria-checked", String(x === b))); waffle();
  }));
  // which pairs moved is spread evenly but fixed per day, so switching back and forth shows the same squares
  const spread = (n, k, seed) => { const s = new Set(); let v = seed; while (s.size < k) { v = (v * 9301 + 49297) % 233280; s.add(Math.floor(v / 233280 * n)); } return s; };
  function waffle() {
    const host = $("w-waffle"), lit = src === "model" ? spread(day.pairs, day.moved, day.pairs + day.moved) : new Set();
    host.innerHTML = "";
    host.setAttribute("aria-label", `${src === "model" ? day.moved : 0} of ${day.pairs} pairs changed`);
    const frag = document.createDocumentFragment();
    for (let i = 0; i < day.pairs; i++) {
      const c = document.createElement("i");
      if (lit.has(i)) { c.className = "on"; c.style.animationDelay = (REDUCE ? 0 : Math.random() * 600) + "ms"; }
      frag.append(c);
    }
    host.append(frag);
    const n = src === "model" ? day.moved : 0;
    $("w-moved").textContent = n;
    $("w-movedlbl").textContent = `of ${day.pairs} pairs changed${src === "model" ? ", GPT-6 Astra alone" : ", Qloo: the same scores every time"}`;
    $("w-moved").classList.toggle("zero", n === 0);
  }
  once($("w-waffle"), waffle);
  $("w-waffle").addEventListener("mousemove", (ev) => {
    if (ev.target.tagName !== "I") return hide();
    show(ev, ev.target.classList.contains("on") ? `<b>Changed</b>: this pair's score moved 10+ points between two identical requests (${day.label})`
      : `Steady pair (${day.label})`);
  });
  $("w-waffle").addEventListener("mouseleave", hide);
})();
