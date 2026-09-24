/* Clinical LLM Safety Harness — demo UI logic */
const $ = (id) => document.getElementById(id);

function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.style.display = "block";
  setTimeout(() => (t.style.display = "none"), 3500);
}

async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json" };
  // Optional API key: required by the backend only when HARNESS_API_KEY is set.
  const key = ($("api-key") && $("api-key").value.trim()) || sessionStorage.getItem("harness_key") || "";
  if (key) headers["X-API-Key"] = key;
  const res = await fetch(path, { headers, ...opts });
  if (!res.ok) {
    const body = await res.text();
    if (res.status === 401) toast("API key required — enter it in the header field.");
    if (res.status === 429) toast("Rate limit exceeded — please wait a moment.");
    throw new Error(`${res.status}: ${body}`);
  }
  return res.json();
}

// Persist the API key for the session (never in a cookie, never logged).
document.addEventListener("input", (e) => {
  if (e.target && e.target.id === "api-key") {
    sessionStorage.setItem("harness_key", e.target.value.trim());
  }
});

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/* ---------------- tabs ---------------- */
document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".panel").forEach((p) => p.classList.add("hidden"));
    btn.classList.add("active");
    $("tab-" + btn.dataset.tab).classList.remove("hidden");
    if (btn.dataset.tab === "queue") refreshQueue();
    if (btn.dataset.tab === "redteam") loadTraps();
    if (btn.dataset.tab === "audit") loadAuditTab();
  });
});

/* ---------------- evaluate ---------------- */
$("btn-evaluate").addEventListener("click", async () => {
  let sources;
  try {
    sources = JSON.parse($("sources-json").value || "[]");
  } catch (e) {
    toast("Sources JSON is invalid: " + e.message);
    return;
  }
  const messages = [];
  const u = $("user-text").value.trim();
  const a = $("assistant-text").value.trim();
  if (u) messages.push({ role: "user", content: u });
  if (a) messages.push({ role: "assistant", content: a });
  if (!a) { toast("Paste an assistant response to evaluate."); return; }
  try {
    const data = await api("/api/evaluate", {
      method: "POST",
      body: JSON.stringify({
        conversation_id: $("conv-id").value || "conv-1",
        messages,
        assistant_text: a,
        sources,
      }),
    });
    renderEval(data);
    refreshQueueCount();
    toast("Evaluation complete: " + data.summary.eval_id);
  } catch (e) { toast("Evaluate failed: " + e.message); }
});

$("btn-clear").addEventListener("click", () => {
  $("user-text").value = ""; $("assistant-text").value = "";
  $("eval-result").innerHTML = "";
});

function renderEval(data) {
  const s = data.summary;
  let html = `<h3>Result — ${esc(s.eval_id)}</h3>
  <div>
    <span class="badge s-medium">${s.total_claims} claims</span>
    <span class="badge v-supported">${s.supported} supported</span>
    <span class="badge v-contradicted">${s.contradicted} contradicted</span>
    <span class="badge v-unverifiable">${s.unverifiable} unverifiable</span>
    <span class="badge a-escalate_immediate">${s.escalated} escalated</span>
    <span class="badge a-flag_review">${s.flagged} flagged</span>
    ${s.phi_findings ? `<span class="badge v-unverifiable">🔒 ${s.phi_findings} PHI span(s)${s.phi_redacted ? " redacted" : " detected"}</span>` : ""}
  </div>`;

  if (data.safeguarding && data.safeguarding.length) {
    html += `<div class="safeguard-banner"><h3>🚨 Safeguarding escalation — ${data.safeguarding.length} finding(s), P0</h3>`;
    for (const f of data.safeguarding) {
      html += `<div class="card"><span class="badge k-safeguarding">${esc(f.category)}</span>
        <span class="badge p-P0">P0</span>
        <p class="muted">turn ${f.message_index} (${esc(f.message_role)}): “${esc(f.matched_text)}”</p>
        <div class="guidance"><strong>Reviewer guidance:</strong> ${esc(f.guidance)}</div></div>`;
    }
    html += `</div>`;
  }

  html += `<div class="cards">`;
  for (const c of data.claims) {
    html += `<div class="card">
      <span class="badge v-${c.verdict}">${esc(c.verdict)}</span>
      <span class="badge s-${c.severity}">${esc(c.severity)}</span>
      <span class="badge a-${c.action}">${esc(c.action.replace("_", " "))}</span>
      <span class="muted">confidence ${c.confidence}</span>
      <p class="claim-text">${esc(c.claim.text)}</p>
      ${c.claim.citations.length ? `<p class="muted">citations: [${c.claim.citations.join("], [")}]</p>` : ""}
      ${c.evidence ? `<div class="evidence"><strong>Best source match:</strong> ${esc(c.evidence)}</div>` : ""}
      ${c.reasons.length ? `<div class="reasons">${c.reasons.map(esc).join("<br>")}</div>` : ""}
      ${c.citation_issues.length ? `<div class="reasons">${c.citation_issues.map(esc).join("<br>")}</div>` : ""}
    </div>`;
  }
  html += `</div>`;
  $("eval-result").innerHTML = html;
}

/* ---------------- demo cases ---------------- */
async function loadDemoCases() {
  const data = await api("/api/demo/cases");
  $("demo-cases").innerHTML = data.cases.map((c, i) => `
    <div class="card"><h4>${esc(c.title)}</h4>
      <p class="muted">${esc(c.narrative)}</p>
      <button data-case="${i}">Load &amp; run</button>
    </div>`).join("");
  document.querySelectorAll("[data-case]").forEach((b) =>
    b.addEventListener("click", () => runDemoCase(data.cases[+b.dataset.case]))
  );
}

async function runDemoCase(c) {
  $("conv-id").value = c.conversation_id;
  $("user-text").value = (c.messages.find((m) => m.role === "user") || {}).content || "";
  $("assistant-text").value = c.assistant_text;
  $("sources-json").value = JSON.stringify(c.sources, null, 2);
  const data = await api("/api/evaluate", {
    method: "POST",
    body: JSON.stringify({
      conversation_id: c.conversation_id,
      messages: c.messages,
      assistant_text: c.assistant_text,
      sources: c.sources,
    }),
  });
  renderEval(data);
  refreshQueueCount();
  document.querySelector('[data-tab="evaluate"]').scrollIntoView();
}

/* ---------------- review queue ---------------- */
async function refreshQueueCount() {
  try {
    const d = await api("/api/queue?status=open");
    $("queue-count").textContent = d.count;
  } catch {}
}

async function refreshQueue() {
  const kind = $("queue-kind").value;
  const status = $("queue-status").value;
  const d = await api(`/api/queue?status=${status}${kind ? "&kind=" + kind : ""}`);
  $("queue-count").textContent = (await api("/api/queue?status=open")).count;
  if (!d.items.length) { $("queue-list").innerHTML = `<p class="muted">Queue is empty.</p>`; return; }
  $("queue-list").innerHTML = d.items.map((it) => `
    <div class="card">
      <span class="badge k-${it.kind}">${esc(it.kind)}</span>
      <span class="badge p-${it.priority}">${esc(it.priority)}</span>
      <span class="badge s-${it.severity}">${esc(it.severity)}</span>
      <span class="badge v-${it.verdict === "safeguarding_risk" ? "contradicted" : it.verdict}">${esc(it.verdict)}</span>
      <span class="muted">#${it.id} · ${esc(it.eval_id)} · ${new Date(it.created_at * 1000).toLocaleString()}</span>
      <p class="claim-text">${esc(it.claim_text)}</p>
      <div class="reasons">${JSON.parse(it.reasons_json).map(esc).join("<br>")}</div>
      ${it.status === "open" ? `
      <div class="decide-form">
        <select id="dec-${it.id}">
          <option value="approved">approved</option>
          <option value="rejected">rejected</option>
          <option value="escalated">escalated</option>
        </select>
        <input id="rev-${it.id}" placeholder="reviewer name">
        <input id="note-${it.id}" placeholder="note (optional)">
        <button data-decide="${it.id}" class="primary">Record decision</button>
      </div>` : `
      <p class="muted">Decided: <strong>${esc(it.decision)}</strong> by ${esc(it.decided_by || "?")}
      ${it.note ? ` — “${esc(it.note)}”` : ""}</p>`}
    </div>`).join("");
  document.querySelectorAll("[data-decide]").forEach((b) =>
    b.addEventListener("click", async () => {
      const id = b.dataset.decide;
      try {
        await api(`/api/queue/${id}/decide`, {
          method: "POST",
          body: JSON.stringify({
            decision: $("dec-" + id).value,
            reviewer: $("rev-" + id).value || "anonymous",
            note: $("note-" + id).value,
          }),
        });
        toast("Decision recorded for #" + id);
        refreshQueue();
      } catch (e) { toast("Decide failed: " + e.message); }
    })
  );
}
$("btn-refresh-queue").addEventListener("click", refreshQueue);
$("queue-kind").addEventListener("change", refreshQueue);
$("queue-status").addEventListener("change", refreshQueue);

/* ---------------- red team ---------------- */
async function loadTraps() {
  const d = await api("/api/redteam/traps");
  $("trap-list").innerHTML = d.traps.map((t) => `
    <div class="card"><h4>${esc(t.title)}</h4>
      <span class="badge s-medium">${esc(t.category)}</span>
      <p><strong>Prompt:</strong> ${esc(t.prompt)}</p>
      <p class="muted"><strong>Expected harness behavior:</strong> ${esc(t.expected_harness_behavior)}</p>
    </div>`).join("");
}

/* ---------------- audit ---------------- */
$("btn-verify").addEventListener("click", async () => {
  const d = await api("/api/audit/verify");
  $("audit-result").innerHTML = d.intact
    ? `<p><span class="badge v-supported">intact</span> Hash chain verified — no tampering detected.</p>`
    : `<p><span class="badge v-contradicted">broken</span> Chain broken at seq ${d.bad_seq}.</p>`;
});

async function loadAuditTab() {
  const evals = await api("/api/evals?limit=10");
  $("eval-list").innerHTML = evals.length ? evals.map((e) => `
    <div class="card"><h4>${esc(e.eval_id)}</h4>
      <p class="muted">${esc(e.conversation_id)} · ${new Date(e.created_at * 1000).toLocaleString()}</p>
      <pre class="json">${esc(JSON.stringify(e.summary, null, 2))}</pre>
    </div>`).join("") : `<p class="muted">No evaluations yet.</p>`;
}

/* ---------------- init ---------------- */
loadDemoCases();
refreshQueueCount();
