const $ = (sel, root = document) => root.querySelector(sel);
const state = { history: [], model: null, busy: false, saving: false };
const STAGES = [
  ["understand", "Understand"],
  ["route", "Pick agent"],
  ["plan", "Plan blocks"],
  ["research", "Search agents"],
  ["write", "Build answer"],
];

const thread = $("#thread");
const input = $("#input");
const sendBtn = $("#send");
const saveBtn = $("#save-project");

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function escapeHtml(text) {
  const d = document.createElement("div");
  d.textContent = text;
  return d.innerHTML;
}

function renderMarkdown(text) {
  if (window.marked && window.DOMPurify) return DOMPurify.sanitize(marked.parse(text));
  return escapeHtml(text).replace(/\n/g, "<br>");
}

function toast(message) {
  const t = $("#toast");
  t.textContent = message;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { t.hidden = true; }, 3500);
}

function nearBottom() {
  return thread.scrollHeight - thread.scrollTop - thread.clientHeight < 120;
}

function scrollDown(force) {
  if (force || nearBottom()) thread.scrollTop = thread.scrollHeight;
}

async function loadModels() {
  const select = $("#model");
  try {
    const data = await (await fetch("/api/models")).json();
    select.innerHTML = "";
    if (!data.models.length) {
      select.append(new Option("No models configured", ""));
      return;
    }
    data.models.forEach((m) => select.append(new Option(m, m, false, m === data.default)));
    state.model = data.default;
  } catch {
    select.append(new Option("Couldn't load models", ""));
  }
  select.addEventListener("change", () => { state.model = select.value; });
}

async function loadProjects() {
  const list = $("#projects");
  try {
    const data = await (await fetch("/api/projects")).json();
    list.innerHTML = "";
    if (!data.projects.length) {
      list.append(el("li", "empty", "No projects yet"));
      return;
    }
    data.projects.forEach((p) => {
      const li = el("li");
      li.append(el("span", "", p.name), el("em", "", p.status));
      list.append(li);
    });
  } catch {
    list.innerHTML = "";
    list.append(el("li", "empty", "Couldn't load projects"));
  }
}

function highlightAgent(key) {
  document.querySelectorAll("#agents li").forEach((li) => li.classList.toggle("active", li.dataset.agent === key));
}

function addUserBubble(text) {
  const row = el("div", "user");
  row.append(el("div", "bubble", text));
  thread.append(row);
}

function createTurn() {
  const turn = el("div", "turn");
  const build = el("div", "build");
  const stages = el("div", "stages");
  STAGES.forEach(([key, label]) => {
    const s = el("div", "stage");
    s.dataset.stage = key;
    s.append(el("span", "dot"), document.createTextNode(label));
    stages.append(s);
  });
  const route = el("div", "route");
  route.hidden = true;
  const agents = el("div", "agents-grid");
  agents.hidden = true;
  const blocks = el("div", "blocks");
  build.append(stages, route, agents, blocks);

  const answer = el("div", "answer");
  const md = el("div", "md");
  md.append(el("span", "waiting", "Thinking about how to handle this..."));
  answer.append(md, el("span", "cursor"));

  const sources = el("div", "sources");
  sources.hidden = true;
  turn.append(build, answer, sources);
  thread.append(turn);
  return { turn, stages, route, agents, blocks, answer, md, sources, buffer: "", blockEls: [], agentEls: {}, sourceList: null, seenSources: new Set(), rendering: false };
}

function setStage(ctx, key, value) {
  const s = ctx.stages.querySelector(`[data-stage="${key}"]`);
  if (s) s.className = `stage ${value}`;
}

function normalizeTitle(text) {
  return text.toLowerCase().replace(/[^a-z0-9 ]+/g, " ").replace(/\s+/g, " ").trim();
}

function writtenHeadings(text) {
  const prose = text.replace(/```[\s\S]*?(```|$)/g, "");
  return [...prose.matchAll(/^##\s+(.+)$/gm)].map((m) => normalizeTitle(m[1]));
}

// A block is done only if its own heading was actually written; unmatched blocks end as "skipped", not "done".
function updateBlocks(ctx, finished) {
  const seen = writtenHeadings(ctx.buffer);
  const titles = ctx.blockEls.map((b) => b.dataset.title);
  const latest = Math.max(-1, ...seen.map((t) => titles.indexOf(t)));
  ctx.blockEls.forEach((b, i) => {
    const appeared = seen.includes(titles[i]);
    let next = "";
    if (finished) next = appeared ? "done" : "skipped";
    else if (i === latest) next = "building";
    else if (appeared) next = "done";
    else if (i < latest) next = "skipped";
    const cls = `block ${next}`.trim();
    if (b.className !== cls) b.className = cls;
  });
}

function scheduleRender(ctx) {
  if (ctx.rendering) return;
  ctx.rendering = true;
  requestAnimationFrame(() => {
    ctx.rendering = false;
    if (ctx.failed) return;
    ctx.md.innerHTML = renderMarkdown(ctx.buffer);
    updateBlocks(ctx, Boolean(ctx.completed));
    scrollDown();
  });
}

function handleEvent(ctx, ev) {
  switch (ev.type) {
    case "stage":
      setStage(ctx, ev.stage, ev.state);
      break;
    case "route":
      ctx.route.hidden = false;
      ctx.route.innerHTML = `Handing this to <b>${escapeHtml(ev.label)}</b>, the ${escapeHtml(ev.role)}.`;
      highlightAgent(ev.agent);
      break;
    case "plan":
      ev.steps.forEach((step, i) => {
        const b = el("div", "block");
        b.dataset.title = normalizeTitle(step);
        b.style.animationDelay = `${i * 110}ms`;
        b.append(el("span", "num", String(i + 1)), document.createTextNode(step));
        ctx.blocks.append(b);
        ctx.blockEls.push(b);
      });
      if (ev.mode === "clarify") ctx.route.append(el("span", "tag", "asking you a few questions first"));
      break;
    case "agent_deployed": {
      ctx.agents.hidden = false;
      const card = el("div", "search-agent");
      card.style.animationDelay = `${ev.id * 120}ms`;
      card.append(el("span", "radar"), el("div", "name", `Search agent ${ev.id + 1}`), el("div", "query", ev.query),
        el("div", "result", "searching the web..."));
      ctx.agents.append(card);
      ctx.agentEls[ev.id] = card;
      break;
    }
    case "agent_done": {
      const card = ctx.agentEls[ev.id];
      if (!card) break;
      card.classList.add(ev.error ? "failed" : ev.results.length ? "done" : "empty");
      $(".result", card).textContent = ev.error ? "search failed, continuing without it"
        : ev.results.length ? `found ${ev.results.length} sources` : "found nothing usable";
      if (ev.results.length) {
        if (!ctx.sourceList) {
          ctx.sources.hidden = false;
          ctx.sources.append(el("div", "", "Sources the search agents found:"));
          ctx.sourceList = el("ol");
          ctx.sources.append(ctx.sourceList);
        }
        ev.results.forEach((r) => {
          if (ctx.seenSources.has(r.n)) return;
          ctx.seenSources.add(r.n);
          const li = el("li");
          li.value = r.n;
          if (/^https?:\/\//i.test(r.href)) {
            const a = el("a", "", r.title || r.href);
            a.href = r.href;
            a.target = "_blank";
            a.rel = "noopener noreferrer";
            li.append(a);
          } else {
            li.append(document.createTextNode(r.title || r.href));
          }
          ctx.sourceList.append(li);
        });
      }
      break;
    }
    case "token":
      if (ctx.failed) break;
      ctx.buffer += ev.text;
      scheduleRender(ctx);
      break;
    case "done":
      ctx.md.innerHTML = renderMarkdown(ctx.buffer);
      updateBlocks(ctx, true);
      $(".cursor", ctx.answer)?.remove();
      highlightAgent(null);
      ctx.completed = true;
      break;
    case "error":
      if (ctx.failed || ctx.completed) break;
      ctx.failed = true;
      ctx.answer.classList.add("error");
      ctx.md.textContent = ev.message;
      $(".cursor", ctx.answer)?.remove();
      ctx.stages.querySelectorAll(".stage.active").forEach((s) => { s.className = "stage error"; });
      ctx.blockEls.forEach((b) => { if (b.classList.contains("building")) b.className = "block"; });
      highlightAgent(null);
      break;
  }
}

async function send(text) {
  text = text.trim();
  if (!text || state.busy) return;
  state.busy = true;
  sendBtn.disabled = true;
  $("#welcome")?.remove();
  input.value = "";
  autoresize();

  addUserBubble(text);
  const ctx = createTurn();
  scrollDown(true);

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model: state.model, history: state.history, message: text }),
    });
    if (!res.ok || !(res.headers.get("Content-Type") || "").startsWith("text/event-stream")) {
      const data = await res.json().catch(() => ({}));
      handleEvent(ctx, { type: "error", message: data.error || `The harness server answered with an error (${res.status}).` });
    } else {
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let carry = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        carry += decoder.decode(value, { stream: true });
        const parts = carry.split("\n\n");
        carry = parts.pop();
        for (const part of parts) {
          const line = part.trim();
          if (line.startsWith("data:")) handleEvent(ctx, JSON.parse(line.slice(5)));
        }
      }
    }
  } catch {
    handleEvent(ctx, { type: "error", message: "Lost the connection to the harness server. Is it still running?" });
  }
  if (!ctx.completed) {
    handleEvent(ctx, { type: "error", message: "The answer stopped before it finished. Try sending it again." });
  }

  if (ctx.completed) {
    state.history.push({ role: "user", content: text }, { role: "assistant", content: ctx.buffer });
    if (!state.saving) saveBtn.disabled = false;
  }
  state.busy = false;
  sendBtn.disabled = false;
  input.focus();
}

async function saveProject() {
  state.saving = true;
  saveBtn.disabled = true;
  saveBtn.textContent = "Summarizing your project...";
  try {
    const res = await fetch("/api/save-project", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model: state.model, history: state.history }),
    });
    const data = await res.json();
    if (data.error) toast(data.error);
    else {
      toast(`Saved "${data.name}" to ${data.file}`);
      loadProjects();
    }
  } catch {
    toast("Couldn't reach the harness server.");
  }
  state.saving = false;
  saveBtn.textContent = "Save this chat as a project";
  saveBtn.disabled = state.history.length === 0;
}

function autoresize() {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 180)}px`;
}

$("#composer").addEventListener("submit", (e) => { e.preventDefault(); send(input.value); });
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input.value); }
});
input.addEventListener("input", autoresize);
document.querySelectorAll(".chip").forEach((chip) => chip.addEventListener("click", () => send(chip.textContent)));
saveBtn.addEventListener("click", saveProject);

loadModels();
loadProjects();
input.focus();
