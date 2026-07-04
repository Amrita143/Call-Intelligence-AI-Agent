// Call Intelligence Agent — frontend (vanilla JS, no build step)
const $ = (s) => document.querySelector(s);
const el = (t, cls, html) => { const e = document.createElement(t); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; };
const esc = (s) => (s ?? "").toString().replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

let CONFIG = {}, LIMITS = {};
let stagedAudio = null;      // File selected but not yet transcribed
let busy = false;            // this tab is running a job
let LAST_SEGMENTS = [];

// section icons (inline SVG so no icon dependency)
const IC = {
  decisions: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m9 12 2 2 4-4"/><circle cx="12" cy="12" r="9"/></svg>',
  actions:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>',
  blockers:  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M5.6 5.6l12.8 12.8"/></svg>',
  compliance:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>',
  review:    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 9v4m0 4h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/></svg>',
  next:      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12h14M13 6l6 6-6 6"/></svg>',
};

// ── init ──────────────────────────────────────────────
async function init() {
  CONFIG = await (await fetch("/api/config")).json();
  LIMITS = CONFIG.limits || {};
  renderChips();
  const samples = await (await fetch("/api/samples")).json();
  const box = $("#sampleChips");
  samples.forEach((s) => {
    const c = el("div", "sample-chip", esc(s.label));
    c.onclick = () => {
      clearAudio();
      $("#transcript").value = s.transcript;
      $("#meetingDate").value = s.meeting_date;
      updateCharCount();
      setHint(`Loaded sample: ${s.label}`, "ok");
    };
    box.appendChild(c);
  });
  $("#transcript").addEventListener("input", updateCharCount);
  loadHistory();
  loadDomains();
  pollStatus();
}

function renderChips() {
  const box = $("#statusChips"); box.innerHTML = "";
  const mk = (label, on, warn) => {
    const c = el("div", "chip" + (on ? " on" : "") + (warn ? " warn" : ""));
    c.appendChild(el("span", "dot")); c.appendChild(el("span", null, label)); return c;
  };
  box.appendChild(CONFIG.mock_mode ? mk("Mock mode (no key)", false, true) : mk(`LLM · ${CONFIG.model}`, true));
  box.appendChild(mk(CONFIG.supabase_enabled ? "Supabase connected" : "Supabase off", CONFIG.supabase_enabled));
  box.appendChild(mk(CONFIG.assemblyai_enabled ? "Audio on" : "Audio off", CONFIG.assemblyai_enabled));
}

function updateCharCount() {
  const n = $("#transcript").value.length, max = LIMITS.max_transcript_chars || 100000;
  const c = $("#charCount");
  c.textContent = n ? `${n.toLocaleString()} / ${max.toLocaleString()} characters` : "";
  c.style.color = n > max ? "var(--red)" : "var(--faint)";
}
function setHint(msg, kind) { const h = $("#inputHint"); h.textContent = msg; h.className = "hint" + (kind ? " " + kind : ""); }

// ── tabs ──────────────────────────────────────────────
document.querySelectorAll(".tab").forEach((t) => (t.onclick = () => switchTab(t.dataset.tab)));
function switchTab(name) {
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  document.querySelectorAll(".tab-body").forEach((b) => (b.hidden = b.id !== `tab-${name}`));
}

// ── audio staging (no auto-transcribe; audio XOR transcript) ──────────
$("#audioInput").onchange = (e) => {
  const file = e.target.files[0]; e.target.value = "";
  if (!file) return;
  if (!CONFIG.assemblyai_enabled) return setHint("Audio transcription is off (no AssemblyAI key). Paste a transcript instead.", "err");
  const ext = "." + (file.name.split(".").pop() || "").toLowerCase();
  const allowed = LIMITS.allowed_audio_ext || [];
  if (allowed.length && !allowed.includes(ext)) return setHint(`Unsupported audio type "${ext}". Allowed: ${allowed.join(", ")}`, "err");
  const maxMb = LIMITS.max_audio_mb || 200;
  if (file.size > maxMb * 1024 * 1024) return setHint(`File is ${(file.size / 1048576).toFixed(0)} MB — over the ${maxMb} MB limit.`, "err");
  if ($("#transcript").value.trim()) return setHint("You already have transcript text. Clear it first — provide either audio or a transcript, not both.", "err");
  stagedAudio = file;
  $("#stagedName").textContent = `${file.name} · ${(file.size / 1048576).toFixed(1)} MB`;
  $("#stagedAudio").hidden = false;
  $("#audioDropText").textContent = "Choose a different file";
  setHint("Audio staged. It will be transcribed when you click Analyze.", "ok");
};
$("#removeAudio").onclick = () => { clearAudio(); setHint(""); };
function clearAudio() {
  stagedAudio = null; $("#stagedAudio").hidden = true; $("#audioDropText").textContent = "Choose an audio file";
}

// ── busy state / status polling ───────────────────────
let statusTimer = null;
async function pollStatus() {
  try {
    const s = await (await fetch("/api/status")).json();
    // only reflect *foreign* busy (another tab/process); our own run manages the button directly
    if (s.busy && !busy) showForeignBusy(true);
    else if (!s.busy) showForeignBusy(false);
  } catch {}
  clearTimeout(statusTimer);
  statusTimer = setTimeout(pollStatus, 4000);
}
function showForeignBusy(on) {
  const b = $("#busyBanner");
  b.hidden = !on;
  if (on) b.innerHTML = `<span class="spinner dark"></span> A call is currently being processed. One analysis runs at a time — please wait.`;
  $("#analyzeBtn").disabled = on || busy;
}
function setBusy(on) {
  busy = on;
  $("#analyzeBtn").disabled = on;
  $("#analyzeBtnText").innerHTML = on ? `<span class="spinner"></span> Analyzing…` : "Analyze call";
  $("#transcript").disabled = on; $("#audioInput").disabled = on;
}

// ── analyze ───────────────────────────────────────────
$("#analyzeBtn").onclick = analyze;
async function analyze() {
  if (busy) return;
  const transcript = $("#transcript").value.trim();

  if (stagedAudio && transcript) return setHint("Provide either an audio file or a transcript — not both. Remove one.", "err");
  if (!stagedAudio && !transcript) return setHint("Paste a transcript, load a sample, or upload audio first.", "err");
  if (transcript && transcript.length > (LIMITS.max_transcript_chars || 100000)) return setHint("Transcript exceeds the character limit.", "err");

  setBusy(true); setHint("");
  $("#traceList").innerHTML = ""; $("#traceEmpty").hidden = true;
  $("#resultsEmpty").hidden = true; $("#resultsContent").hidden = true; $("#resultsContent").innerHTML = "";
  switchTab("trace");

  let finalTranscript = transcript, sourceType = "transcript", sourceName = null;

  try {
    // 1) transcribe staged audio first (shown as an explicit trace step)
    if (stagedAudio) {
      appendTrace({ node: "transcribe", title: `Transcribing ${stagedAudio.name}`, status: "running",
        detail: "Uploading to AssemblyAI (Universal) with speaker diarization. This can take a bit for long calls." });
      const fd = new FormData(); fd.append("file", stagedAudio);
      const res = await fetch("/api/transcribe", { method: "POST", body: fd });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "transcription failed");
      finalTranscript = data.transcript; sourceType = "audio"; sourceName = stagedAudio.name;
      updateTrace({ node: "transcribe", title: "Transcription complete", status: "done",
        detail: `${data.utterances} diarized utterances.`,
        output: { transcript_preview: data.transcript.slice(0, 800) + (data.transcript.length > 800 ? " …" : "") } });
      $("#transcript").value = finalTranscript; updateCharCount();
    }

    // 2) stream the workflow
    const res = await fetch("/api/analyze", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ transcript: finalTranscript, meeting_date: $("#meetingDate").value || null,
        source_name: sourceName, source_type: sourceType }),
    });
    if (res.status === 429) { const d = await res.json(); throw new Error(d.detail); }
    if (!res.ok) { const d = await res.json().catch(() => ({})); throw new Error(d.detail || `HTTP ${res.status}`); }

    const reader = res.body.getReader(); const dec = new TextDecoder(); let buf = "";
    while (true) {
      const { done, value } = await reader.read(); if (done) break;
      buf += dec.decode(value, { stream: true });
      const parts = buf.split("\n\n"); buf = parts.pop();
      for (const p of parts) { const line = p.trim(); if (line.startsWith("data:")) handleEvent(JSON.parse(line.slice(5).trim())); }
    }
    if (stagedAudio) clearAudio();
  } catch (err) {
    setHint(err.message || "Analysis failed.", "err");
    appendTrace({ node: "error", title: "Stopped", status: "info", detail: err.message });
  } finally {
    setBusy(false);
    loadHistory();
  }
}

// ── trace rendering (with expandable per-node output) ─────────────────
const traceEls = {};
function handleEvent(ev) {
  if (ev.node === "result") return renderResult(ev.result, ev.segments);
  if (ev.status === "done") updateTrace(deriveOutput(ev));
  else if (ev.status === "running") appendTrace(ev);
  else appendTrace(ev); // info/start/saved
}
// pull a compact, human-readable "output" object from a done event
function deriveOutput(ev) {
  const o = {};
  if (ev.segments) o.segments = ev.segments;
  if (ev.meta) o.meta = ev.meta;
  if (ev.extraction) o.extraction = ev.extraction;
  if (ev.review) o.review = ev.review;
  if (ev.output) Object.assign(o, ev.output);
  if (ev.rationale) o.routing_rationale = ev.rationale;
  if (ev.domain) o.domain = ev.domain;
  return Object.keys(o).length ? { ...ev, output: o } : ev;
}
function traceRow(ev) {
  const row = el("li", "trace-item");
  const rail = el("div", "trace-rail");
  rail.appendChild(el("div", "trace-dot " + ev.status));
  rail.appendChild(el("div", "trace-line"));
  const content = el("div", "trace-content");
  content.innerHTML =
    `<div class="trace-title">${esc(ev.title)}` +
    (ev.node && !["start", "result", "saved", "error", "transcribe"].includes(ev.node) ? ` <span class="trace-node">${esc(ev.node)}</span>` : "") +
    (ev.elapsed_ms != null ? ` <span class="trace-ms">${ev.elapsed_ms} ms</span>` : "") + `</div>` +
    (ev.detail ? `<div class="trace-detail">${esc(ev.detail)}</div>` : "");
  if (ev.output && Object.keys(ev.output).length) {
    const d = el("details", "trace-output");
    d.innerHTML = `<summary>inspect output</summary><pre>${esc(JSON.stringify(ev.output, null, 2))}</pre>`;
    content.appendChild(d);
  }
  row.appendChild(rail); row.appendChild(content);
  return row;
}
function appendTrace(ev) {
  const row = traceRow(ev); $("#traceList").appendChild(row);
  if (ev.node) traceEls[ev.node] = row;
  row.scrollIntoView({ behavior: "smooth", block: "nearest" });
}
function updateTrace(ev) {
  const row = traceEls[ev.node];
  if (!row) return appendTrace(ev);
  const fresh = traceRow(ev); row.replaceWith(fresh); traceEls[ev.node] = fresh;
}
// render a stored trace array (from history)
function renderStoredTrace(trace) {
  $("#traceList").innerHTML = ""; $("#traceEmpty").hidden = true;
  (trace || []).filter((e) => e.status === "done" || e.node === "start" || e.node === "saved")
    .forEach((e) => $("#traceList").appendChild(traceRow(deriveOutput(e))));
  if (!trace || !trace.length) $("#traceList").innerHTML = `<p style="color:var(--faint)">No stored trace for this run.</p>`;
}

// ── results rendering ─────────────────────────────────
function renderResult(r, segments) {
  if (segments) { LAST_SEGMENTS = segments; renderTranscript(segments); }
  const c = $("#resultsContent"); c.innerHTML = "";

  const hero = el("div", "result-hero");
  hero.innerHTML =
    `<div class="hero-top"><span class="domain-badge">${esc(r.domain)}</span>` +
    `<span class="agent-badge">handled by <b>${esc(r.domain_agent)}</b></span>` +
    (r.mock_mode ? `<span class="chip warn"><span class="dot"></span>mock output</span>` : "") + `</div>` +
    `<div class="hero-tag">${esc(r.tag)}</div>` +
    `<div class="hero-meta"><span>anchor date <b>${esc(r.anchor_date)}</b></span>` +
    `<span><b>${r.segment_count}</b> lines</span>` +
    (r.domain_rationale ? `<span>routing: ${esc(r.domain_rationale)}</span>` : "") + `</div>` +
    `<div class="hero-summary">${esc(r.summary)}</div>`;
  c.appendChild(hero);

  section(c, "sec-decisions", IC.decisions, "Decisions", r.decisions, (d) => card(d.decision, [], d.source_ids, d.evidence));
  section(c, "sec-actions", IC.actions, "Action items", r.action_items, (a) => {
    const meta = [a.owner ? pill(`owner <b>${esc(a.owner)}</b>`) : pill(`owner <b>unassigned</b>`, "owner-null")];
    if (a.due) meta.push(pill(`due <b>${esc(a.due)}</b>`, "due"));
    if (a.start) meta.push(pill(`start <b>${esc(a.start)}</b>`, "due"));
    return card(a.task, meta, a.source_ids, a.evidence);
  });
  section(c, "sec-blockers", IC.blockers, "Blockers", r.blockers, (b) => card(b.blocker, [], b.source_ids, b.evidence));
  section(c, "sec-compliance", IC.compliance, "Compliance observations", r.compliance_observations, (o) => {
    const cd = card(`<span class="status-tag ${o.status}">${o.status}</span>${esc(o.note)}`, [], o.source_ids, o.evidence, true);
    cd.classList.add("status-" + o.status); return cd;
  });
  section(c, "sec-review", IC.review, "Needs human review", r.items_needing_human_review, (x) => {
    const cd = el("div", "card review");
    cd.innerHTML = `<div class="card-main"><span class="review-cat">${esc(x.category)}</span> ${esc(x.item)}</div>` +
      `<div class="review-reason">${esc(x.reason)}</div>`;
    cd.appendChild(evidenceBlock(x.source_ids, x.evidence)); return cd;
  });
  if (r.recommended_next_steps && r.recommended_next_steps.length) {
    const s = el("div", "section sec-next");
    s.appendChild(sectionHead(IC.next, "Recommended next steps", r.recommended_next_steps.length));
    const ul = el("ul", "next-steps");
    r.recommended_next_steps.forEach((x) => ul.appendChild(el("li", null, esc(x))));
    s.appendChild(ul); c.appendChild(s);
  }
  c.hidden = false; $("#resultsEmpty").hidden = true;
  switchTab("results");
}
function sectionHead(icon, title, n) {
  const h = el("div", "section-head");
  h.appendChild(el("div", "section-icon", icon));
  h.appendChild(el("h3", null, title));
  h.appendChild(el("span", "count-pill", n));
  return h;
}
function section(parent, cls, icon, title, items, render) {
  if (!items || !items.length) return;
  const s = el("div", "section " + cls);
  s.appendChild(sectionHead(icon, title, items.length));
  items.forEach((it) => s.appendChild(render(it)));
  parent.appendChild(s);
}
function pill(html, cls) { return `<span class="pill ${cls || ""}">${html}</span>`; }
function card(mainHtml, metaPills, sourceIds, evidence, mainIsHtml) {
  const cd = el("div", "card");
  cd.appendChild(el("div", "card-main", mainIsHtml ? mainHtml : esc(mainHtml)));
  if (metaPills && metaPills.length) cd.appendChild(el("div", "card-meta", metaPills.join("")));
  cd.appendChild(evidenceBlock(sourceIds, evidence));
  return cd;
}
function evidenceBlock(sourceIds, evidence) {
  const e = el("div", "evidence");
  if (evidence && evidence.trim()) {
    e.innerHTML = `<span class="ev-label">⟵ grounded evidence · lines ${(sourceIds || []).join(", ")}</span>\n${esc(evidence)}`;
    e.title = "Click to highlight these lines in the transcript";
    e.onclick = () => highlightLines(sourceIds);
  } else {
    e.innerHTML = `<span class="no-ev">⚠ no verifiable source lines — escalated to human review</span>`;
  }
  return e;
}

// ── transcript + citation highlight ───────────────────
function renderTranscript(segments) {
  const v = $("#transcriptView"); v.innerHTML = "";
  segments.forEach((s) => {
    const row = el("div", "t-line"); row.id = "tline-" + s.id;
    row.innerHTML = `<span class="t-id">${s.id}</span><span class="t-txt">${esc(s.text)}</span>`;
    v.appendChild(row);
  });
  $("#transcriptEmpty").hidden = true;
}
function highlightLines(ids) {
  if (!ids || !ids.length) return;
  switchTab("transcript");
  document.querySelectorAll(".t-line.hl").forEach((e) => e.classList.remove("hl"));
  ids.forEach((id, i) => { const row = $("#tline-" + id); if (row) { row.classList.add("hl"); if (i === 0) row.scrollIntoView({ behavior: "smooth", block: "center" }); } });
}

// ── domain registry management ────────────────────────
async function loadDomains() {
  const list = $("#domainList");
  const domains = await (await fetch("/api/domains")).json();
  list.innerHTML = "";
  Object.entries(domains).forEach(([key, d]) => {
    const card = el("div", "domain-card");
    card.innerHTML =
      `<div class="domain-card-head"><span class="domain-key">${esc(key)}</span>` +
      `<span class="domain-agent">${esc(d.agent)}</span>` +
      `<span class="domain-flag">${d.custom ? "custom" : "built-in"}</span>` +
      (d.custom ? `<button class="domain-del" data-key="${esc(key)}">Delete</button>` : "") + `</div>` +
      `<div class="domain-desc">${esc(d.description)}</div>` +
      (d.context ? `<div class="domain-ctx">${esc(d.context)}</div>` : "");
    list.appendChild(card);
  });
  list.querySelectorAll(".domain-del").forEach((b) => (b.onclick = () => deleteDomain(b.dataset.key)));
}
async function deleteDomain(key) {
  if (!confirm(`Delete custom domain "${key}"?`)) return;
  const res = await fetch("/api/domains/" + encodeURIComponent(key), { method: "DELETE" });
  if (res.ok) loadDomains(); else alert("Could not delete this domain.");
}
$("#dfSave").onclick = async () => {
  const agent = $("#dfAgent").value.trim(), description = $("#dfDesc").value.trim(), context = $("#dfContext").value.trim();
  const hint = $("#dfHint");
  if (!agent || !description) { hint.textContent = "Name and description are required."; hint.className = "hint err"; return; }
  const key = agent.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
  const res = await fetch("/api/domains", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ key, agent, description, context }) });
  const data = await res.json().catch(() => ({}));
  if (res.ok) {
    hint.textContent = `Saved as "${data.key}".`; hint.className = "hint ok";
    $("#dfAgent").value = ""; $("#dfDesc").value = ""; $("#dfContext").value = "";
    $("#domainAdd").open = false; loadDomains();
  } else { hint.textContent = data.detail || "Could not save."; hint.className = "hint err"; }
};
$("#dfCancel").onclick = () => { $("#domainAdd").open = false; };

// ── history ───────────────────────────────────────────
$("#refreshHistory").onclick = loadHistory;
async function loadHistory() {
  const list = $("#historyList");
  if (!CONFIG.supabase_enabled) { list.innerHTML = `<p style="color:var(--faint);padding:20px;text-align:center">Supabase not configured.</p>`; return; }
  const runs = await (await fetch("/api/runs")).json();
  list.innerHTML = "";
  if (!runs.length) { list.innerHTML = `<p style="color:var(--faint);padding:24px;text-align:center">No runs yet.</p>`; return; }
  runs.forEach((r) => {
    const row = el("div", "history-row");
    const when = new Date(r.created_at).toLocaleString();
    row.innerHTML =
      `<span class="h-domain">${esc(r.domain || "—")}</span>` +
      `<span class="h-tag">${esc(r.tag || "(untitled)")}</span>` +
      `<span class="h-src">${r.source_type === "audio" ? "🎙 audio" : "transcript"}</span>` +
      `<span class="h-meta">${r.human_review_count || 0} review · ${when}</span>`;
    row.onclick = () => openRun(r.id);
    list.appendChild(row);
  });
}
async function openRun(id) {
  const row = await (await fetch("/api/runs/" + id)).json();
  const segs = row.transcript ? segmentClient(row.transcript) : [];
  renderResult(row.result, segs);
  renderStoredTrace(row.trace);
}
// mirror of backend ingest() for re-segmenting a stored transcript
function segmentClient(raw) {
  const out = []; let idx = 0;
  raw.split("\n").forEach((line) => { const s = line.trim(); if (s && !s.startsWith("#")) out.push({ id: ++idx, text: s }); });
  return out;
}

init();
