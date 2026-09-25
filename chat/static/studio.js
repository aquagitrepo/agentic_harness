const $ = (sel, root = document) => root.querySelector(sel);
const FIELDS = [
  ["goal", "Goal"], ["users", "For whom"], ["first_version", "First version"],
  ["inputs", "Input"], ["constraints", "Constraints"],
];
const TOOL_LABELS = {
  update_brief: "Updating the brief", ask_user: "Writing a question", propose_plan: "Drafting the plan",
  write_file: "Writing code", read_file: "Reading a file", list_files: "Checking the project files",
  run_python: "Running your code",
};
const HEX = '<svg width="20" height="20" viewBox="0 0 28 28" fill="none" aria-hidden="true"><path d="M14 2 25 8.5v11L14 26 3 19.5v-11Z" stroke="currentColor" stroke-width="2"/></svg>';
const KEYWORDS = new Set(("False None True and as assert async await break class continue def del elif else except "
  + "finally for from global if import in is lambda nonlocal not or pass raise return try while with yield").split(" "));
const TOKENS = /(#[^\n]*)|("""[\s\S]*?(?:"""|$)|'''[\s\S]*?(?:'''|$)|"(?:\\.|[^"\\\n])*"?|'(?:\\.|[^'\\\n])*'?)|\b([A-Za-z_]\w*)\b/g;

const state = {
  session: null, model: null, busy: false,
  files: new Map(), writing: null, openFile: null,
  questionCard: null, planCard: null, activeStep: 0, ranCode: false, briefSeen: {},
};
const thread = $("#thread");
const input = $("#input");
const sendBtn = $("#send");
const welcomeTemplate = $("#welcome").cloneNode(true);

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function esc(text) {
  return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function md(text) {
  if (window.marked && window.DOMPurify) return DOMPurify.sanitize(marked.parse(text));
  return esc(text).replace(/\n/g, "<br>");
}

function highlight(code) {
  let out = "";
  let last = 0;
  TOKENS.lastIndex = 0;
  for (let m = TOKENS.exec(code); m; m = TOKENS.exec(code)) {
    out += esc(code.slice(last, m.index));
    if (m[1]) out += `<span class="tk-c">${esc(m[1])}</span>`;
    else if (m[2]) out += `<span class="tk-s">${esc(m[2])}</span>`;
    else out += KEYWORDS.has(m[3]) ? `<span class="tk-k">${m[3]}</span>` : m[3];
    last = TOKENS.lastIndex;
  }
  return out + esc(code.slice(last));
}

function toast(message) {
  const t = $("#toast");
  t.textContent = message;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { t.hidden = true; }, 4500);
}

function remember(id) { try { localStorage.setItem("studio:last", id); } catch { /* private mode */ } }
function recall() { try { return localStorage.getItem("studio:last"); } catch { return null; } }
function forget() { try { localStorage.removeItem("studio:last"); } catch { /* private mode */ } }

function normPath(path) { return String(path || "").replace(/\\/g, "/").replace(/^(\.\/)+/, ""); }
function nearBottom() { return thread.scrollHeight - thread.scrollTop - thread.clientHeight < 140; }
function scrollDown(force) { if (force || nearBottom()) thread.scrollTop = thread.scrollHeight; }

async function getJSON(url, options) {
  const res = await fetch(url, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.error) throw new Error(data.error || `The Studio server answered with an error (${res.status}).`);
  return data;
}

function postJSON(url, body) {
  return getJSON(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

// ---- engine and projects -------------------------------------------------------------

async function loadModels() {
  const select = $("#model");
  try {
    const data = await getJSON("/api/models");
    select.innerHTML = "";
    data.models.forEach((m) => select.append(new Option(m, m, false, m === data.default)));
    state.model = data.default;
  } catch {
    select.append(new Option("Couldn't load models", ""));
  }
  select.addEventListener("change", () => { state.model = select.value; });
}

async function loadSessions() {
  const list = $("#sessions");
  try {
    const { sessions } = await getJSON("/api/studio/sessions");
    list.innerHTML = "";
    if (!sessions.length) list.append(el("li", "hint", "Your projects will appear here."));
    for (const s of sessions) {
      const button = el("button");
      button.type = "button";
      const building = s.phase === "build";
      button.append(el("span", "", s.name), el("span", building ? "badge live" : "badge", building ? "BUILD" : "DISCOVER"));
      if (state.session && state.session.id === s.id) button.setAttribute("aria-current", "true");
      button.addEventListener("click", () => { if (!state.busy) openSession(s.id); });
      const li = el("li");
      li.append(button);
      list.append(li);
    }
  } catch {
    list.innerHTML = "";
    list.append(el("li", "hint", "Couldn't load projects."));
  }
}

async function openSession(id) {
  try {
    state.session = await getJSON(`/api/studio/session?id=${encodeURIComponent(id)}`);
  } catch (err) {
    forget();
    toast(err.message);
    return;
  }
  remember(id);
  if (state.session.model && [...$("#model").options].some((o) => o.value === state.session.model)) {
    $("#model").value = state.session.model;
    state.model = state.session.model;
  }
  renderSession();
  loadSessions();
}

function makeWelcome() {
  const welcome = welcomeTemplate.cloneNode(true);
  welcome.querySelectorAll(".chip").forEach((chip) => chip.addEventListener("click", () => send(chip.textContent)));
  return welcome;
}

function resetView() {
  thread.innerHTML = "";
  Object.assign(state, { files: new Map(), writing: null, openFile: null, questionCard: null, planCard: null,
    activeStep: 0, ranCode: false, briefSeen: {} });
  const out = $("#console");
  out.innerHTML = "";
  out.append(el("span", "empty", "Program output appears here when the Studio runs your code."));
  showCode(null, "", false);
  renderTree();
}

function startFresh() {
  state.session = null;
  forget();
  resetView();
  thread.append(makeWelcome());
  renderBrief({}, false);
  renderPhases();
  setCost(0);
  updateComposer();
  $("#app").classList.remove("building");
  $("#where").textContent = "";
  selectTab("brief");
}

function renderSession() {
  const s = state.session;
  resetView();
  if (!s.log.length) thread.append(makeWelcome());
  s.log.forEach((entry, i) => replay(entry, i === s.log.length - 1));
  for (const f of s.files || []) if (!state.files.has(f.path)) state.files.set(f.path, null);
  if (state.activeStep) markStep(state.activeStep, true);
  renderTree();
  renderBrief(s.brief, false);
  renderPhases();
  setCost(s.cost_usd);
  updateComposer();
  $("#app").classList.toggle("building", s.phase === "build");
  $("#where").textContent = s.slug ? `projects/${s.slug}` : "";
  selectTab(s.phase === "build" ? "files" : "brief");
  scrollDown(true);
}

function replay(entry, last) {
  const waiting = state.session.waiting;
  switch (entry.kind) {
    case "user": addUser(entry.text); break;
    case "assistant": addAssistant(entry.text); break;
    case "question": addQuestion(entry, last && waiting === "question"); break;
    case "plan": addPlan(entry, last && waiting === "plan"); break;
    case "approved": markPlanApproved(); addNote(`Plan approved. Building in projects/${entry.slug}/`); break;
    case "file": addFileLine(entry.path, entry.lines); markStep(entry.step); break;
    case "run": {
      state.ranCode = true;
      const run = addRun(entry.command);
      run.append(entry.output || "");
      run.done(entry);
      consoleStart(entry.command);
      consoleAppend(entry.output || "");
      consoleDone(entry);
      markStep(entry.step);
      break;
    }
    default: break;
  }
}

// ---- thread ------------------------------------------------------------------------

function addUser(text) { thread.append(el("div", "user", text)); }

function addAssistant(text) {
  const row = el("div", "msg");
  row.innerHTML = HEX;
  const body = el("div", "md");
  row.append(body);
  thread.append(row);
  const ctx = { body, buffer: text || "", queued: false };
  if (text) body.innerHTML = md(text);
  return ctx;
}

function renderAssistant(ctx) {
  if (ctx.queued) return;
  ctx.queued = true;
  requestAnimationFrame(() => {
    ctx.queued = false;
    ctx.body.innerHTML = md(ctx.buffer);
    scrollDown();
  });
}

function addNote(text, warn) { thread.append(el("div", warn ? "note warn" : "note", text)); }
function addError(text) { thread.append(el("div", "error-box", text)); }

function addFileLine(path, lines) {
  const row = el("div", "file-line");
  const open = el("button", "", path);
  open.type = "button";
  open.addEventListener("click", () => { selectTab("files"); openFile(path); });
  row.append(document.createTextNode("Wrote"), open, document.createTextNode(`${lines} line${lines === 1 ? "" : "s"}`));
  thread.append(row);
}

function deactivateCards() {
  thread.querySelectorAll(".card.active").forEach((card) => {
    card.classList.remove("active");
    card.querySelectorAll(".options button").forEach((b) => { b.disabled = true; });
    const tag = card.querySelector(".card-head .label");
    if (tag && card.classList.contains("question")) tag.textContent = "ANSWERED";
  });
  state.questionCard = null;
}

function addQuestion(q, active) {
  deactivateCards();
  const number = thread.querySelectorAll(".card.question").length + 1;
  const card = el("section", active ? "card question active" : "card question");
  card.setAttribute("aria-label", `Question ${number}`);
  const head = el("div", "card-head");
  head.append(el("span", "ask", `QUESTION ${number}`), el("span", "label", active ? "YOUR TURN" : "ANSWERED"));
  card.append(head, el("h2", "", q.question));
  if (q.why) card.append(el("p", "why", `Why I'm asking: ${q.why}`));
  const options = el("div", "options");
  q.options.forEach((option, i) => {
    const button = el("button", "option");
    button.type = "button";
    button.disabled = !active;
    const text = el("span", "text");
    text.append(el("b", "", option.label));
    if (option.detail) text.append(el("small", "", option.detail));
    button.append(el("span", "key", String(i + 1)), text);
    button.addEventListener("click", () => { button.classList.add("picked"); send(option.label); });
    options.append(button);
  });
  card.append(options);
  thread.append(card);
  if (active) state.questionCard = card;
  scrollDown(true);
}

function addPlan(plan, active) {
  deactivateCards();
  const card = el("section", active ? "card plan active" : "card plan");
  card.setAttribute("aria-label", "Proposed plan");
  const head = el("div", "card-head");
  head.append(el("span", "ask", "PROPOSED FIRST VERSION"), el("span", "label", active ? "NEEDS YOUR OK" : ""));
  card.append(head, el("h2", "", plan.summary));
  const steps = el("ol", "steps");
  plan.steps.forEach((step) => steps.append(el("li", "", step)));
  card.append(steps);
  if (plan.files && plan.files.length) {
    const chips = el("div", "file-chips");
    plan.files.forEach((f) => chips.append(el("code", "", f)));
    card.append(chips);
  }
  if (plan.run) card.append(el("div", "run-hint", `Run it with: ${plan.run}`));
  if (active) {
    const actions = el("div", "actions");
    const build = el("button", "primary", "Build it");
    build.type = "button";
    build.addEventListener("click", () => send("Build it.", { approve: true }));
    const change = el("button", "ghost", "Change something");
    change.type = "button";
    change.addEventListener("click", () => input.focus());
    actions.append(build, change);
    card.append(actions);
  }
  thread.append(card);
  state.planCard = card;
  state.activeStep = 0;
  scrollDown(true);
}

function markPlanApproved() {
  const card = state.planCard;
  if (!card) return;
  card.querySelectorAll(".actions").forEach((a) => a.remove());
  const tag = card.querySelector(".card-head .label");
  if (tag) tag.textContent = "APPROVED";
}

function markStep(step, finished) {
  if (!state.planCard || !Number.isInteger(step) || step < 1) return;
  state.planCard.querySelectorAll(".steps li").forEach((li, i) => {
    const n = i + 1;
    if (n < step || (n === step && finished)) li.className = "done";
    else if (n === step) li.className = "active";
  });
  state.activeStep = step;
}

function addRun(command) {
  const box = el("div", "run");
  const head = el("div", "run-head");
  const status = el("span", "run-status", "RUNNING");
  head.append(el("span", "", `$ ${command}`), status);
  const out = el("pre");
  box.append(head, out);
  thread.append(box);
  scrollDown(true);
  return {
    append(text) {
      out.textContent += text;
      out.scrollTop = out.scrollHeight;
      scrollDown();
    },
    done(ev) {
      if (ev.timed_out) {
        status.textContent = "STOPPED AT THE TIME LIMIT";
        status.className = "run-status stop";
      } else if (ev.exit_code === 0) {
        status.textContent = `EXIT 0 · ${ev.seconds} S`;
      } else {
        status.textContent = `FAILED · EXIT ${ev.exit_code}`;
        status.className = "run-status fail";
      }
      if (!out.textContent) out.textContent = "(no output)";
    },
  };
}

function activity(text) {
  const bar = $("#activity");
  bar.hidden = !text;
  if (text) bar.querySelector("span").textContent = text;
}

// ---- console -----------------------------------------------------------------------

function consoleStart(command) {
  const out = $("#console");
  out.querySelector(".empty")?.remove();
  out.append(el("span", "cmd", `$ ${command}\n`));
  out.scrollTop = out.scrollHeight;
}

function consoleAppend(text) {
  const out = $("#console");
  out.append(document.createTextNode(text));
  out.scrollTop = out.scrollHeight;
}

function consoleDone(ev) {
  const ok = ev.exit_code === 0 && !ev.timed_out;
  const summary = ev.timed_out ? "stopped at the time limit" : `exit ${ev.exit_code} · ${ev.seconds} s`;
  $("#console").append(el("span", ok ? "ok" : "bad", `${summary}\n\n`));
}

// ---- files -------------------------------------------------------------------------

function renderTree() {
  const tree = $("#tree");
  tree.innerHTML = "";
  const paths = [...state.files.keys()].sort();
  if (!paths.length) {
    tree.append(el("p", "empty", "No files yet. They appear here as they're written."));
    return;
  }
  let lastDir = "";
  for (const path of paths) {
    const parts = path.split("/");
    const dir = parts.slice(0, -1).join("/");
    if (dir && dir !== lastDir) tree.append(el("div", "dir", `${dir}/`));
    lastDir = dir;
    const button = el("button");
    button.type = "button";
    button.style.paddingLeft = dir ? "22px" : "8px";
    button.append(el("span", "", parts[parts.length - 1]));
    if (state.writing === path) button.append(el("i"));
    if (state.openFile === path) button.setAttribute("aria-current", "true");
    button.addEventListener("click", () => openFile(path));
    tree.append(button);
  }
}

async function openFile(path) {
  state.openFile = path;
  let content = state.files.get(path);
  if (content == null && state.session) {
    try {
      const data = await getJSON(`/api/studio/file?id=${encodeURIComponent(state.session.id)}&path=${encodeURIComponent(path)}`);
      content = data.content;
      state.files.set(path, content);
    } catch (err) {
      toast(err.message);
      return;
    }
  }
  showCode(path, content || "", state.writing === path);
  renderTree();
}

function showCode(path, content, writing) {
  // While writing, count the line the caret is on; once saved, a trailing newline doesn't start a line (as on the server).
  const parts = content ? content.split("\n").length : 1;
  const lines = !writing && content && content.endsWith("\n") ? parts - 1 : parts;
  $("#editor-name").textContent = path || "No file open";
  $("#editor-state").textContent = !path ? "" : writing ? `WRITING · LINE ${lines}` : `${lines} LINE${lines === 1 ? "" : "S"}`;
  $("#gutter").textContent = path ? Array.from({ length: lines }, (_, i) => i + 1).join("\n") : "";
  $("#code").innerHTML = (content ? highlight(content) : "") + (writing ? '<span class="caret"></span>' : "");
}

let codeFrame = 0;
function liveWrite(path, content) {
  path = normPath(path);
  const fresh = state.writing !== path;
  state.files.set(path, content);
  state.writing = path;
  state.openFile = path;
  if (fresh) {
    renderTree();
    selectTab("files");
  }
  if (codeFrame) return;
  codeFrame = requestAnimationFrame(() => {
    codeFrame = 0;
    if (!state.writing) return;
    showCode(state.writing, state.files.get(state.writing), true);
    const wrap = $("#code-wrap");
    wrap.scrollTop = wrap.scrollHeight;
  });
}

function finishWrite(path) {
  path = normPath(path);
  if (state.writing && state.writing !== path) {
    // The server's cleaned-up path wins over the one Claude typed.
    state.files.set(path, state.files.get(state.writing));
    state.files.delete(state.writing);
  }
  state.writing = null;
  state.openFile = path;
  renderTree();
  showCode(path, state.files.get(path) || "", false);
}

// ---- brief, phases, composer ---------------------------------------------------------

function renderBrief(brief, live) {
  brief = brief || {};
  $("#brief-name").textContent = brief.name || "Untitled project";
  const box = $("#brief-fields");
  box.innerHTML = "";
  const scores = brief.confidence || {};
  let total = 0;
  for (const [key, label] of FIELDS) {
    const value = brief[key];
    const score = Number.isInteger(scores[key]) ? scores[key] : value ? 3 : 0;
    total += score;
    const card = el("div", "field");
    const signature = `${value || ""}|${score}`;
    if (live && state.briefSeen[key] !== signature) card.classList.add("changed");
    state.briefSeen[key] = signature;
    const top = el("div", "field-top");
    const meter = el("span", "meter");
    meter.setAttribute("role", "img");
    meter.setAttribute("aria-label", `Confidence ${score} of 5`);
    for (let i = 0; i < 5; i += 1) meter.append(el("i", i < score ? "on" : ""));
    top.append(el("span", "label", label), meter);
    card.append(top, el("div", value ? "field-value" : "field-value unknown", value || "Not known yet"));
    box.append(card);
  }
  const questions = $("#brief-questions");
  questions.innerHTML = "";
  const open = brief.open_questions || [];
  questions.hidden = !open.length;
  if (open.length) {
    questions.append(el("span", "label", "OPEN QUESTIONS"));
    open.forEach((q) => questions.append(el("div", "", q)));
  }
  const pct = Math.round((total / (FIELDS.length * 5)) * 100);
  $("#ready-pct").textContent = `${pct}%`;
  $("#ready-bar").style.width = `${pct}%`;
  $("#ready-bar-wrap").setAttribute("aria-label", `${pct} percent ready`);
  if (live) {
    const tag = $("#brief-live");
    tag.hidden = false;
    clearTimeout(renderBrief.timer);
    renderBrief.timer = setTimeout(() => {
      tag.hidden = true;
      box.querySelectorAll(".changed").forEach((c) => c.classList.remove("changed"));
    }, 3500);
  }
}

function renderPhases() {
  const s = state.session;
  let current = "discover";
  if (s && s.phase === "build") current = state.ranCode ? "run" : "build";
  else if (s && s.waiting === "plan") current = "plan";
  const order = ["discover", "plan", "build", "run"];
  const at = order.indexOf(current);
  document.querySelectorAll("#phases li[data-phase]").forEach((li) => {
    const i = order.indexOf(li.dataset.phase);
    li.className = i < at ? "done" : i === at ? "active" : "";
    if (i === at) li.setAttribute("aria-current", "step");
    else li.removeAttribute("aria-current");
  });
}

function updateComposer() {
  const s = state.session;
  let label = "YOUR MESSAGE";
  if (!s || !s.log.length) label = "DESCRIBE YOUR PROJECT";
  else if (s.waiting === "question") label = "OR ANSWER IN YOUR OWN WORDS";
  else if (s.waiting === "plan") label = "WHAT SHOULD CHANGE? OR PRESS BUILD IT";
  else if (s.phase === "build") label = "ASK FOR CHANGES OR STEER THE BUILD";
  $("#composer-label").textContent = label;
}

function setCost(usd) {
  $("#cost").textContent = !usd ? "$0.00" : `$${usd < 1 ? usd.toFixed(4) : usd.toFixed(2)}`;
}

function selectTab(name) {
  for (const tab of ["brief", "files", "console"]) {
    $(`#tab-${tab}`).setAttribute("aria-selected", String(tab === name));
    $(`#view-${tab}`).hidden = tab !== name;
  }
}

// ---- a turn --------------------------------------------------------------------------

function handle(turn, ev) {
  switch (ev.type) {
    case "status": activity("Thinking"); break;
    case "retry": turn.assistant = null; activity("Retrying"); break;
    case "text":
      if (!turn.assistant) turn.assistant = addAssistant("");
      turn.assistant.buffer += ev.text;
      renderAssistant(turn.assistant);
      activity(null);
      break;
    case "tool_start": turn.assistant = null; activity(TOOL_LABELS[ev.tool] || "Working"); break;
    case "brief":
      state.session.brief = ev.brief;
      renderBrief(ev.brief, true);
      if (state.session.phase !== "build") selectTab("brief");
      break;
    case "file_delta": liveWrite(ev.path, ev.content); break;
    case "file_done": finishWrite(ev.path); addFileLine(ev.path, ev.lines); markStep(ev.step); break;
    case "run_start":
      turn.run = addRun(ev.command);
      consoleStart(ev.command);
      markStep(ev.step);
      state.ranCode = true;
      renderPhases();
      activity("Running your code");
      break;
    case "run_output": turn.run?.append(ev.text); consoleAppend(ev.text); break;
    case "run_done": turn.run?.done(ev); consoleDone(ev); turn.run = null; break;
    case "tool_error": addNote(`${TOOL_LABELS[ev.tool] || ev.tool}: ${ev.message}`, true); break;
    case "question":
      state.session.waiting = "question";
      addQuestion(ev, true);
      renderPhases();
      updateComposer();
      break;
    case "plan":
      state.session.waiting = "plan";
      addPlan(ev, true);
      renderPhases();
      updateComposer();
      break;
    case "phase":
      Object.assign(state.session, { phase: ev.phase, slug: ev.slug });
      addNote(`Plan approved. Building in projects/${ev.slug}/`);
      $("#app").classList.add("building");
      $("#where").textContent = `projects/${ev.slug}`;
      selectTab("files");
      renderPhases();
      break;
    case "cost": setCost(ev.session_usd); break;
    case "turn_end":
      turn.ended = true;
      activity(null);
      if (ev.reason === "done") {
        state.session.waiting = null;
        if (state.activeStep) markStep(state.activeStep, true);
      }
      if (ev.reason === "limit") addNote("Paused after 30 steps to keep the cost in check. Say \"keep going\" to continue.", true);
      updateComposer();
      break;
    case "error": turn.failed = true; activity(null); addError(ev.message); break;
    default: break;
  }
  scrollDown();
}

async function refreshSession() {
  if (!state.session) return;
  try {
    const fresh = await getJSON(`/api/studio/session?id=${encodeURIComponent(state.session.id)}`);
    state.session = fresh;
    for (const f of fresh.files) if (!state.files.has(f.path)) state.files.set(f.path, null);
    renderTree();
    renderPhases();
    updateComposer();
    setCost(fresh.cost_usd);
  } catch {
    // keep what's on screen
  }
}

async function send(text, { approve = false } = {}) {
  text = (text || "").trim();
  if (!text || state.busy) return;
  state.busy = true;
  sendBtn.disabled = true;
  if (!state.session) {
    try {
      state.session = await postJSON("/api/studio/new", { model: state.model });
      remember(state.session.id);
    } catch (err) {
      toast(err.message);
      state.busy = false;
      sendBtn.disabled = false;
      return;
    }
  }
  $("#welcome")?.remove();
  deactivateCards();
  if (approve) markPlanApproved();
  else addUser(text);
  input.value = "";
  autoresize();
  scrollDown(true);
  activity("Thinking");

  const turn = { assistant: null, run: null, ended: false, failed: false };
  try {
    const res = await fetch("/api/studio/message", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: state.session.id, message: text, model: state.model, approve }),
    });
    if (!res.ok || !(res.headers.get("Content-Type") || "").startsWith("text/event-stream")) {
      const data = await res.json().catch(() => ({}));
      handle(turn, { type: "error", message: data.error || `The Studio server answered with an error (${res.status}).` });
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
          if (line.startsWith("data:")) handle(turn, JSON.parse(line.slice(5)));
        }
      }
    }
  } catch {
    handle(turn, { type: "error", message: "Lost the connection to the Studio server. Is it still running?" });
  }
  if (!turn.ended && !turn.failed) {
    handle(turn, { type: "error", message: "The reply stopped before it finished. Send a message to continue." });
  }
  activity(null);
  state.busy = false;
  sendBtn.disabled = false;
  await refreshSession();
  loadSessions();
  input.focus();
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
document.addEventListener("keydown", (e) => {
  if (state.busy || !state.questionCard || e.target === input || e.altKey || e.ctrlKey || e.metaKey) return;
  const options = state.questionCard.querySelectorAll(".option");
  const n = Number(e.key);
  if (n >= 1 && n <= options.length) { e.preventDefault(); options[n - 1].click(); }
});
for (const tab of ["brief", "files", "console"]) $(`#tab-${tab}`).addEventListener("click", () => selectTab(tab));
$("#new-session").addEventListener("click", () => { if (!state.busy) { startFresh(); loadSessions(); input.focus(); } });

$("#welcome").replaceWith(makeWelcome());
renderBrief({}, false);
renderPhases();
(async () => {
  await loadModels();
  await loadSessions();
  const last = recall();
  if (last) await openSession(last);
  input.focus();
})();
