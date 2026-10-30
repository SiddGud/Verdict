// Bring your own lineup: paste sets (stage, act, start, end), the server matches every act in Qloo and scores the fan
// overlap, and the new day opens like any built-in one.
(() => {
  const $ = (id) => document.getElementById(id);
  const dlg = $("lineup-dlg");
  if (!dlg) return;
  const SAMPLE = [
    "Stage, Act, Start, End",
    "Main, Olivia Rodrigo, 20:30, 22:00",
    "Main, Clairo, 18:30, 19:30",
    "Main, Mitski, 16:30, 17:30",
    "Second, Phoebe Bridgers, 19:00, 20:15",
    "Second, beabadoobee, 17:00, 18:00",
    "Second, Faye Webster, 15:00, 16:00",
    "Third, Lizzy McAlpine, 18:45, 19:45",
    "Third, Japanese Breakfast, 16:45, 17:45",
    "Third, Snail Mail, 14:45, 15:45",
  ].join("\n");

  $("lineup-open").addEventListener("click", () => { $("lu-err").hidden = true; $("lu-prog").textContent = ""; dlg.showModal(); });
  $("lu-close").addEventListener("click", () => dlg.close());
  $("lu-sample").addEventListener("click", () => { $("lu-text").value = SAMPLE; $("lu-name").value = "Indie night (sample)"; });

  $("lu-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const err = $("lu-err"), prog = $("lu-prog"), go = $("lu-go");
    err.hidden = true;
    go.disabled = true;
    prog.textContent = "Checking your sets...";
    try {
      const r = await fetch("/api/clash/lineup", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: $("lu-name").value, text: $("lu-text").value }) });
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.statusText);
      const reader = r.body.getReader(), dec = new TextDecoder();
      let buf = "", done = null;
      for (;;) {
        const { value, done: end } = await reader.read();
        if (end) break;
        buf += dec.decode(value, { stream: true });
        let i;
        while ((i = buf.indexOf("\n\n")) >= 0) {
          const line = buf.slice(0, i).trim();
          buf = buf.slice(i + 2);
          if (!line.startsWith("data:")) continue;
          const ev = JSON.parse(line.slice(5));
          if (ev.type === "progress") prog.textContent = ev.of > 1 ? `${ev.step}: ${ev.done} of ${ev.of}` : `${ev.step}...`;
          else if (ev.type === "error") throw new Error(ev.message);
          else if (ev.type === "done") done = ev;
        }
      }
      if (!done) throw new Error("the server stopped before the day was ready");
      prog.textContent = `${done.acts} acts: ${done.in_qloo} in Qloo, ${done.from_lastfm} from Last.fm. Opening...`;
      const sel = $("festival");
      let opt = [...sel.options].find((o) => o.value === done.slug);
      if (!opt) { opt = document.createElement("option"); opt.value = done.slug; opt.textContent = `${done.name} (yours)`; sel.prepend(opt); }
      dlg.close();
      sel.value = done.slug;
      sel.dispatchEvent(new Event("change"));
    } catch (x) {
      err.hidden = false;
      err.textContent = x.message;
      prog.textContent = "";
    } finally {
      go.disabled = false;
    }
  });
})();
