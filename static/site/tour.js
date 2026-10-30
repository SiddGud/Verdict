// The guided tour: plays the page's main features in order with a narration bar, no input needed. Starts from the
// "Watch the tour" button or /?watch=1. Each step waits for the feature to finish before the next begins.
(() => {
  const $ = (id) => document.getElementById(id);
  let running = false, stopped = false;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const go = (id) => document.getElementById(id).scrollIntoView({ behavior: "smooth", block: "start" });
  const STEPS = 6;

  function bar(n, title, sub) {
    $("tour-bar").hidden = false;
    $("tour-n").textContent = n ? `${n} of ${STEPS}` : "Tour";
    $("tour-t").textContent = title;
    $("tour-s").textContent = sub;
    $("tour-bar").classList.remove("in");
    void $("tour-bar").offsetWidth;
    $("tour-bar").classList.add("in");
  }
  const until = (test, ms) => new Promise((done) => {
    const t0 = Date.now(), id = setInterval(() => { if (stopped || test() || Date.now() - t0 > ms) { clearInterval(id); done(); } }, 250);
  });

  async function tour() {
    if (running || !window.court || !window.cityDesk) return;
    running = true; stopped = false;
    window.__touring = true; // the court's booker gate is skipped during the tour
    try {
      window.scrollTo({ top: 0, behavior: "smooth" });
      bar(1, "The problem", "Two acts that share fans, on two stages, at the same time: someone misses one. Every festival has dozens.");
      await sleep(4500); if (stopped) return;

      go("graph");
      window.billGraph.setMode("published");
      bar(2, "The bill as Qloo sees it", "Every act pulled toward the acts its fans share. Pink lines: pairs on at the same time, whose fans must choose.");
      await sleep(5500); if (stopped) return;

      go("court");
      bar(3, "The court sits", "Qloo scores how much every pair of acts shares fans. Fan agents argue each clash, the booker objects, the court rules, and the timetable moves.");
      window.court.pace(0.55);
      await window.court.convene();
      window.court.pace(1);
      await sleep(1500); if (stopped) return;
      go("graph");
      await window.billGraph.setMode("now");
      bar(3, "The court sits", "After the ruling: the pink lines are gone. Fans of those pairs no longer have to choose.");
      await sleep(4500); if (stopped) return;

      go("desk");
      bar(4, "A city's month, for one audience", "Every show on sale in New York this November, scored for Clairo's fans. The agent visits the shows that pull hardest on them.");
      await window.cityDesk.book("Clairo");
      await sleep(2500); if (stopped) return;

      bar(5, "A promoter's shows", "Live Nation's New York month: which of its own shows compete for the same fans, and which should market each other.");
      go("desk");
      await window.cityDesk.portfolio();
      await sleep(3000); if (stopped) return;

      bar(6, "Ask the court", "A conversational agent that picks its own tools: Qloo overlap, the timetable, Ticketmaster listings. Every number is checked.");
      window.askCourt.open();
      const before = document.querySelectorAll("#ask-log .q-answer").length;
      window.askCourt.send("Who on this bill shares the most fans with Chappell Roan, and do they clash with her now?");
      await until(() => document.querySelectorAll("#ask-log .q-answer").length > before, 90000);
      await sleep(5000); if (stopped) return;

      document.getElementById("ask-close").click();
      go("evidence");
      bar(0, "With and without Qloo", "Tested before we built on it: Qloo far beyond popularity, level with a frontier model, and best of all when the two work together.");
      await sleep(7000);
      bar(0, "That's Clash Court", "Try it yourself: convene the court, type an emergency, ask the clerk anything.");
      await sleep(6000);
      $("tour-bar").hidden = true;
    } finally {
      window.court.pace(1);
      running = false;
      window.__touring = false;
    }
  }

  $("tour-start").addEventListener("click", tour);
  $("tour-stop").addEventListener("click", () => { stopped = true; window.court.pace(1); $("tour-bar").hidden = true; });
  if (new URLSearchParams(location.search).has("watch")) setTimeout(tour, 1200);
  window.courtTour = tour;

  // The comparison bars grow when they first come into view.
  const vs = $("vs");
  if (vs && "IntersectionObserver" in window) {
    new IntersectionObserver((seen, o) => seen.forEach((e) => { if (e.isIntersecting) { vs.classList.add("seen"); o.disconnect(); } }),
      { threshold: 0.3 }).observe(vs);
  } else if (vs) vs.classList.add("seen");
})();
