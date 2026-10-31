// The organised site: the festival court is the front page; fans, promoters and why Qloo are pages of their own,
// switched by the address (#/fans and so on). Every page's parts stay in the document, so the court, the map and the chat keep one session;
// a page that is not shown is only hidden. Anything that scrolls to a part on a hidden page opens that page first,
// so the guided tour and the court's own jumps work unchanged.
(() => {
  const VIEWS = ["festivals", "fans", "promoters", "why"];
  const DAY_ON = new Set(["fans", "festivals", "why"]); // pages that work on the chosen festival day
  const SUGGEST = {
    fans: [
      "Plan my day: I love Hozier, Jungle and Clairo",
      "Who on this bill shares the most fans with Chappell Roan?",
      "Where does Hozier play, and who clashes with him?",
    ],
    festivals: [
      "What are the worst clashes on this day?",
      "Tyla just cancelled. What does the court change?",
      "Keep Hozier and Lizzy McAlpine apart",
    ],
    promoters: [
      "Which night in Chicago in November should Clairo play?",
      "Does Live Nation have shows fighting each other in New York this November?",
      "Which promoters have the most shows in New York this November?",
    ],
    why: [
      "Is Qloo better than a model alone at this?",
      "Do Hozier and Lizzy McAlpine share fans?",
    ],
  };
  const $ = (id) => document.getElementById(id);
  let current = null, graphStale = true;

  const viewOf = (hash) => {
    const v = (hash || "").replace(/^#\/?/, "");
    return VIEWS.includes(v) ? v : v === "" ? "festivals" : null;
  };

  // The city desk is one panel (one map, one set of tabs): fans see only Friends' month, promoters the other three.
  function placeDesk(view) {
    const panel = $("desk-panel");
    if (!panel) return;
    const slot = view === "fans" ? $("slot-fans") : $("slot-promoters");
    if (panel.parentElement !== slot) slot.append(panel);
    const tabs = [...document.querySelectorAll("#tabs button")];
    tabs.forEach((b) => { b.hidden = view === "fans" ? b.dataset.tab !== "friends" : b.dataset.tab === "friends"; });
    const on = tabs.find((b) => b.getAttribute("aria-checked") === "true");
    if (view === "fans" && (!on || on.dataset.tab !== "friends")) tabs.find((b) => b.dataset.tab === "friends").click();
    if (view === "promoters" && (!on || on.dataset.tab === "friends")) tabs.find((b) => b.dataset.tab === "book").click();
  }

  function show(view, { keepScroll = false } = {}) {
    if (!VIEWS.includes(view)) view = "festivals";
    const changed = view !== current;
    current = view;
    document.querySelectorAll(".s-view").forEach((v) => { v.hidden = v.dataset.view !== view; });
    $("daybar").hidden = !DAY_ON.has(view);
    document.querySelectorAll(".s-links a").forEach((a) => a.setAttribute("aria-current", String(a.dataset.view === view)));
    document.body.dataset.view = view;
    if (view === "fans" || view === "promoters") placeDesk(view);
    if (window.askCourt && window.askCourt.suggest) window.askCourt.suggest(SUGGEST[view]);
    if (view === "festivals" && graphStale && window.billGraph) { graphStale = false; window.billGraph.load(); }
    // Leaflet and the graph measure their boxes; a page that was hidden has none until it is shown.
    requestAnimationFrame(() => window.dispatchEvent(new Event("resize")));
    if (changed && !keepScroll) window.scrollTo({ top: 0 });
    const titles = { festivals: "Verdict", fans: "Verdict for fans",
      promoters: "Verdict for promoters", why: "Why Qloo, Verdict" };
    document.title = titles[view];
  }

  // Scrolling to a part of a hidden page opens that page first (the tour, the court, the city desk all scroll).
  const scroll = Element.prototype.scrollIntoView;
  Element.prototype.scrollIntoView = function (...args) {
    const page = this.closest && this.closest(".s-view");
    if (page && page.hidden) {
      history.replaceState(null, "", "#/" + (page.dataset.view === "festivals" ? "" : page.dataset.view));
      show(page.dataset.view, { keepScroll: true });
    }
    return scroll.apply(this, args);
  };

  // The graph is drawn to its box; drawn while hidden, it is redrawn the next time its page opens.
  document.addEventListener("court:loaded", () => { if (current !== "festivals") graphStale = true; });

  // "Try" chips fill an input and submit its form.
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-fill]");
    if (!b) return;
    $(b.dataset.fill).value = b.dataset.text;
    $(b.dataset.submit).requestSubmit();
  });

  // Section headings (and the panels under them) rise into place as they scroll into view.
  function reveal() {
    if (matchMedia("(prefers-reduced-motion: reduce)").matches || !("IntersectionObserver" in window)) return;
    const io = new IntersectionObserver((seen) => seen.forEach((e) => {
      if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); }
    }), { threshold: 0.15, rootMargin: "0px 0px -8% 0px" });
    document.querySelectorAll(".band-head, .s-test, .s-mstat, .s-case, .w-panel, .s-alsocard, .sources article, .flow li")
      .forEach((el, i) => { el.classList.add("rv"); el.style.setProperty("--rv", (i % 4) * 70 + "ms"); io.observe(el); });
  }

  // The header steps aside while reading down the page and returns as soon as the reader scrolls up.
  function autoHide() {
    let last = scrollY;
    addEventListener("scroll", () => {
      const y = scrollY;
      if (y > last + 6 && y > 160) document.body.classList.add("nav-up");
      else if (y < last - 6 || y < 160) document.body.classList.remove("nav-up");
      last = y;
    }, { passive: true });
  }

  // Less text on screen: each section's explanation folds behind "How it works", and a page's numbered steps fold
  // behind "How to use". Why Qloo keeps everything open: there the detail is the point.
  function fold() {
    document.querySelectorAll('.s-view:not([data-view="why"]) .band-head > p.hint').forEach((hint) => {
      const b = document.createElement("button");
      b.type = "button"; b.className = "s-info"; b.setAttribute("aria-expanded", "false");
      b.innerHTML = '<span aria-hidden="true">i</span>How it works';
      hint.classList.add("s-fold");
      hint.before(b);
      b.addEventListener("click", () => { const open = b.getAttribute("aria-expanded") !== "true"; b.setAttribute("aria-expanded", String(open)); hint.classList.toggle("open", open); });
    });
    const note = document.getElementById("festnote"); // the timetable's source note: one line until clicked
    if (note) { note.title = "Click to read the whole note"; note.addEventListener("click", () => note.classList.toggle("open")); }
    document.querySelectorAll(".s-how").forEach((ol) => {
      const d = document.createElement("details"), sum = document.createElement("summary");
      d.className = "s-howto"; sum.textContent = `How to use, in ${ol.children.length} steps`;
      ol.before(d); d.append(sum, ol);
    });
  }

  function start() {
    document.querySelectorAll(".s-jump [data-go]").forEach((b) => b.addEventListener("click", () => {
      const t = document.getElementById(b.dataset.go);
      if (t) t.scrollIntoView({ behavior: "smooth", block: "start" });
    }));
    reveal();
    autoHide();
    fold();
    window.addEventListener("hashchange", () => { const v = viewOf(location.hash); if (v) show(v); });
    show(viewOf(location.hash) || "festivals");
  }
  window.site = { start, show, current: () => current };
})();
