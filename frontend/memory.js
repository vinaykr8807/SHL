const userId = window.location.pathname.split("/").filter(Boolean).pop();
const rawJsonLink = document.querySelector("#rawJsonLink");
const memoryMeta = document.querySelector("#memoryMeta");
const conversationCount = document.querySelector("#conversationCount");
const assessmentCount = document.querySelector("#assessmentCount");
const lastUpdated = document.querySelector("#lastUpdated");
const memorySummary = document.querySelector("#memorySummary");
const assessmentFrequency = document.querySelector("#assessmentFrequency");
const roleContexts = document.querySelector("#roleContexts");
const timeline = document.querySelector("#timeline");

rawJsonLink.href = `/users/${userId}/memory`;

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function formatDate(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

async function loadMemory() {
  const response = await fetch(`/users/${userId}/memory`);
  if (!response.ok) {
    memoryMeta.textContent = "Memory not found for this user.";
    return;
  }
  const memory = await response.json();
  renderMemory(memory);
}

function renderMemory(memory) {
  const conversations = memory.conversations || [];
  const allRecommendations = conversations.flatMap((item) => item.response?.recommendations || []);
  const freq = countBy(allRecommendations, (item) => item.name);
  const contexts = conversations
    .map((item) => (item.messages || []).filter((message) => message.role === "user").at(-1)?.content)
    .filter(Boolean)
    .slice(-8)
    .reverse();

  memoryMeta.textContent = `${memory.username || "User"} | Created ${formatDate(memory.created_at)}`;
  conversationCount.textContent = conversations.length;
  assessmentCount.textContent = Object.keys(freq).length;
  lastUpdated.textContent = formatDate(memory.updated_at);
  renderSummary(memory.summary || "");

  renderFrequency(freq);
  renderContexts(contexts);
  renderTimeline(conversations.slice().reverse());
}

function renderSummary(summary) {
  if (!summary.trim()) {
    memorySummary.innerHTML = `<span class="empty-state">No summary has been generated yet.</span>`;
    return;
  }

  const cleaned = summary
    .replace(/^here'?s a summary of the shl assessment-selection conversation memory:\s*/i, "")
    .replace(/^summary:\s*/i, "")
    .trim();
  const sections = parseMarkdownSections(cleaned);

  if (!sections.length) {
    memorySummary.innerHTML = `<p>${escapeHtml(cleaned)}</p>`;
    return;
  }

  memorySummary.innerHTML = sections
    .map((section) => `
      <article class="summary-section">
        <h3>${escapeHtml(section.title)}</h3>
        <div class="summary-chip-list">
          ${section.items.map((item) => `<span>${escapeHtml(item)}</span>`).join("")}
        </div>
      </article>
    `)
    .join("");
}

function parseMarkdownSections(text) {
  const lines = text.split(/\r?\n/);
  const sections = [];
  let current = null;

  lines.forEach((line) => {
    const trimmed = line.trim();
    if (!trimmed) return;

    const heading = trimmed.match(/^\*\*(.+?)\*\*:?\s*$/);
    if (heading) {
      current = { title: heading[1], items: [] };
      sections.push(current);
      return;
    }

    const item = trimmed.replace(/^[-*]\s*/, "").replace(/\*\*/g, "").trim();
    if (!current) {
      current = { title: "Memory notes", items: [] };
      sections.push(current);
    }
    if (item) current.items.push(item);
  });

  return sections.filter((section) => section.items.length);
}

function countBy(items, getKey) {
  return items.reduce((acc, item) => {
    const key = getKey(item);
    if (!key) return acc;
    acc[key] = (acc[key] || 0) + 1;
    return acc;
  }, {});
}

function renderFrequency(freq) {
  const entries = Object.entries(freq).sort((a, b) => b[1] - a[1]).slice(0, 10);
  if (!entries.length) {
    assessmentFrequency.innerHTML = `<p class="subtle">No recommendations saved yet.</p>`;
    return;
  }
  assessmentFrequency.innerHTML = entries
    .map(([name, count]) => `
      <div class="frequency-row">
        <span>${escapeHtml(name)}</span>
        <strong>${count}</strong>
      </div>
    `)
    .join("");
}

function renderContexts(contexts) {
  if (!contexts.length) {
    roleContexts.innerHTML = `<p class="subtle">No role contexts saved yet.</p>`;
    return;
  }
  roleContexts.innerHTML = contexts
    .map((context) => `<div class="context-pill">${escapeHtml(context)}</div>`)
    .join("");
}

function renderTimeline(conversations) {
  if (!conversations.length) {
    timeline.innerHTML = `<p class="subtle">No conversation evidence yet.</p>`;
    return;
  }
  timeline.innerHTML = conversations
    .map((conversation) => {
      const userMessage = (conversation.messages || []).filter((message) => message.role === "user").at(-1)?.content || "Conversation";
      const recommendations = conversation.response?.recommendations || [];
      return `
        <article class="timeline-item">
          <div>
            <span>${escapeHtml(formatDate(conversation.created_at))}</span>
            <h3>${escapeHtml(userMessage)}</h3>
            <p>${recommendations.length} recommendation(s)</p>
          </div>
          <div class="timeline-recs">
            ${recommendations.slice(0, 6).map((rec) => `<a href="${escapeHtml(rec.url)}" target="_blank" rel="noreferrer">${escapeHtml(rec.name)}</a>`).join("")}
          </div>
        </article>
      `;
    })
    .join("");
}

loadMemory();
