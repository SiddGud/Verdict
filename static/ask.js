// Ask the court: a side panel where the agent answers in plain words. Each tool it calls appears as it runs; a
// booker order it issues replays the court on the timetable. Answers stream from /api/clash/ask.
(() => {
  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; };
  const TOOL = {
    timetable: "Reading the timetable", where_is: "Finding the act", shares_fans_with: "Asking Qloo who shares fans",
    clash_between: "Checking the clash", booker_order: "Booker order: the court sits again", fan_route: "Planning a fan's route",
    city_plan: "Reading the city's month (Ticketmaster and Qloo)", promoter_portfolio: "Reading the promoter's shows",
    promoters: "Listing promoters", evidence: "Opening Test 28",
  };
  const SUGGEST = [
    "Who on this bill shares the most fans with Chappell Roan?",
    "Tyla just cancelled. What does the court change?",
    "Which night in Chicago in November should Clairo play?",
    "Does Live Nation have shows fighting each other in New York this November?",
  ];
  const history = [];
  let busy = false;

  function open(state) {
    $("ask-panel").classList.toggle("open", state);
    $("ask-panel").setAttribute("aria-hidden", String(!state));
    $("ask-open").setAttribute("aria-expanded", String(state));
    if (state) setTimeout(() => $("ask-text").focus(), 250);
  }
  $("ask-open").addEventListener("click", () => open(!$("ask-panel").classList.contains("open")));
  $("ask-close").addEventListener("click", () => open(false));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") open(false); });

  SUGGEST.forEach((q) => {
    const b = el("button", "", q);
    b.type = "button";
    b.addEventListener("click", () => send(q));
    $("ask-suggest").append(b);
  });

  const log = () => $("ask-log");
  const scroll = () => { log().scrollTop = log().scrollHeight; };

  async function send(q) {
    q = (q || "").trim();
    if (!q || busy) return;
    const sid = window.court && window.court.session();
    if (!sid) return;
    busy = true;
    $("ask-send").disabled = true;
    $("ask-suggest").hidden = true;
    log().append(el("div", "q-me", q));
    const turn = el("div", "q-turn");
    const trace = el("ol", "q-trace");
    const think = el("div", "q-think", "Thinking");
    turn.append(trace, think);
    log().append(turn);
    scroll();
    const steps = new Map();
    let answer = "";
    try {
      const r = await fetch("/api/clash/ask", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session: sid, question: q, history: history.slice(-4) }) });
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.statusText);
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
          if (!line.startsWith("data:")) continue;
          const e = JSON.parse(line.slice(5));
          if (e.type === "tool") {
            let li = steps.get(e.n);
            if (!li) {
              li = el("li", "running");
              li.append(el("span", "t", TOOL[e.name] || e.name), el("span", "s", ""));
              steps.set(e.n, li);
              trace.append(li);
            }
            li.className = e.status;
            if (e.status !== "running") li.querySelector(".s").textContent = (e.summary || "") + (e.seconds != null ? `  ${e.seconds}s` : "");
            think.textContent = e.status === "running" ? "Working" : "Thinking";
          } else if (e.type === "state") {
            window.court.replay(e.state);
          } else if (e.type === "answer") {
            answer = e.text;
            think.remove();
            const a = el("div", "q-answer");
            e.text.split(/\n+/).forEach((p) => a.append(el("p", "", p)));
            if (e.unchecked_numbers.length) a.append(el("p", "q-flag", `Numbers not found in any tool result: ${e.unchecked_numbers.join(", ")}. Treat them with care.`));
            else if (e.tool_calls) a.append(el("p", "q-ok", `Every number checked against ${e.tool_calls} tool result${e.tool_calls > 1 ? "s" : ""}.`));
            turn.append(a);
          } else if (e.type === "error") {
            think.remove();
            turn.append(el("div", "q-answer q-err", e.message));
          }
          scroll();
        }
      }
      if (answer) history.push({ q, a: answer });
    } catch (err) {
      think.remove();
      turn.append(el("div", "q-answer q-err", "Something went wrong: " + err.message));
    } finally {
      busy = false;
      $("ask-send").disabled = false;
      scroll();
    }
  }

  $("ask-form").addEventListener("submit", (e) => { e.preventDefault(); const t = $("ask-text").value; $("ask-text").value = ""; send(t); });
  window.askCourt = { open: () => open(true), send };
  const preset = new URLSearchParams(location.search).get("ask"); // demo link: /?ask=your question
  if (preset) {
    const id = setInterval(() => { if (window.court && window.court.session()) { clearInterval(id); open(true); send(preset); } }, 300);
  }
})();
