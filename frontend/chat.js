const userPill = document.querySelector("#userPill");
const logoutButton = document.querySelector("#logoutButton");
const memoryLink = document.querySelector("#memoryLink");
const chatForm = document.querySelector("#chatForm");
const chatInput = document.querySelector("#chatInput");
const messagesEl = document.querySelector("#messages");
const recommendationsEl = document.querySelector("#recommendations");
const recommendationList = document.querySelector("#recommendationList");
const quickReplies = document.querySelector("#quickReplies");

const state = {
  user: JSON.parse(localStorage.getItem("shl_user") || "null"),
  messages: [],
  lastRecommendations: [],
  lastDetails: null,
};

function updateUserChrome() {
  userPill.textContent = state.user ? state.user.username : "Guest";
  logoutButton.hidden = !state.user;
  if (state.user) {
    memoryLink.textContent = "View memory";
    memoryLink.href = `/memory/${state.user.user_id}`;
    memoryLink.target = "_blank";
  }
}

function addMessage(role, content) {
  const article = document.createElement("article");
  article.className = `message ${role}`;
  const paragraph = document.createElement("p");
  paragraph.textContent = role === "assistant" ? cleanAssistantText(content) : content;
  article.appendChild(paragraph);
  messagesEl.appendChild(article);
  scrollConversationToLatest();
}

function addRecommendationSnapshot(items, details) {
  if (!items.length) return;
  const section = document.createElement("section");
  section.className = "inline-shortlist";

  const title = document.createElement("h3");
  title.textContent = "Shortlist for this response";
  section.appendChild(title);

  if (details) {
    const summary = document.createElement("div");
    summary.className = "inline-summary";
    summary.innerHTML = `
      <span>${escapeHtml(details.strategy || "Role-fit shortlist")}</span>
      <span>${escapeHtml((details.coverage || []).join(", ") || "Catalog match")}</span>
      <span>${escapeHtml(details.total_duration || "Varies")}</span>
    `;
    section.appendChild(summary);
  }

  const grid = document.createElement("div");
  grid.className = "inline-rec-grid";
  const richItems = details?.items?.length ? details.items : items;
  richItems.forEach((item, index) => {
    const card = document.createElement("article");
    card.className = "inline-rec-card";
    card.innerHTML = `
      <strong>${index + 1}. ${escapeHtml(item.name)}</strong>
      <span>${escapeHtml(item.stage || "Recommended")} ${item.test_type ? " | Type " + escapeHtml(item.test_type) : ""}</span>
      <a href="${escapeHtml(item.url)}" target="_blank" rel="noreferrer">Open catalog</a>
    `;
    grid.appendChild(card);
  });
  section.appendChild(grid);
  messagesEl.appendChild(section);
}

function cleanAssistantText(content) {
  const tableStart = content.indexOf("| # | Name |");
  const withoutTable = tableStart >= 0 ? content.slice(0, tableStart) : content;
  return withoutTable
    .replace(/<think>[\s\S]*?<\/think>/gi, "")
    .replace(/<analysis>[\s\S]*?<\/analysis>/gi, "")
    .replace(/^.*?<\/think>/gis, "")
    .replace(/\*\*(.*?)\*\*/g, "$1")
    .replace(/https?:\/\/\S+/g, "")
    .replace(/^\s*[-*]\s+/gm, "")
    .replace(/_`end_of_conversation`:[\s\S]*/g, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function isComparisonQuery(content) {
  const text = content.toLowerCase();
  return (
    text.includes("compare ") ||
    text.includes(" difference ") ||
    text.includes("different between") ||
    text.includes(" vs ") ||
    text.includes(" versus ")
  );
}

function scrollConversationToLatest() {
  requestAnimationFrame(() => {
    messagesEl.scrollTo({ top: messagesEl.scrollHeight, behavior: "smooth" });
    window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
  });
}

async function renderRecommendations(items) {
  if (!items.length) {
    if (state.lastRecommendations.length) {
      recommendationsEl.hidden = false;
      return state.lastDetails;
    }
    recommendationsEl.hidden = true;
    return null;
  }

  const details = await fetchRecommendationDetails(items);
  state.lastRecommendations = items;
  state.lastDetails = details;

  messagesEl.appendChild(recommendationsEl);
  recommendationList.innerHTML = "";
  recommendationsEl.hidden = false;
  renderBatterySummary(details);
  const richItems = details?.items?.length ? details.items : items;

  richItems.forEach((item, index) => {
    const card = document.createElement("div");
    card.className = "rec-card";

    const badge = document.createElement("span");
    badge.className = "rec-index";
    badge.textContent = String(index + 1);

    const body = document.createElement("div");
    body.className = "rec-body";
    const link = document.createElement("a");
    link.href = item.url;
    link.target = "_blank";
    link.rel = "noreferrer";
    link.textContent = item.name;

    const meta = document.createElement("div");
    meta.className = "rec-meta";
    [item.stage, item.test_type ? `Type ${item.test_type}` : "", item.duration && item.duration !== "-" ? item.duration : ""]
      .filter(Boolean)
      .forEach((value) => {
        const chip = document.createElement("span");
        chip.textContent = value;
        meta.appendChild(chip);
      });

    const score = document.createElement("strong");
    score.className = "fit-score";
    score.textContent = item.fit_score ? `${item.fit_score}% fit` : "Catalog fit";

    const why = document.createElement("p");
    why.className = "why-fit";
    why.textContent = item.why_fit || "Recommended from the SHL catalog for this role context.";

    const caution = document.createElement("small");
    caution.className = "caution";
    caution.textContent = item.caution || "";
    const hasUsefulCaution = item.caution && !item.caution.toLowerCase().includes("no major catalog constraint");

    const actions = document.createElement("div");
    actions.className = "rec-actions";
    const openButton = document.createElement("a");
    openButton.className = "catalog-button";
    openButton.href = item.url;
    openButton.target = "_blank";
    openButton.rel = "noreferrer";
    openButton.textContent = "Open catalog";
    actions.appendChild(openButton);

    body.append(link, meta, score, why);
    if (hasUsefulCaution) body.appendChild(caution);
    body.appendChild(actions);
    card.append(badge, body);
    recommendationList.appendChild(card);
  });
  return details;
}

async function fetchRecommendationDetails(items) {
  try {
    const response = await fetch("/recommendation-details", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        urls: items.map((item) => item.url),
        messages: state.messages,
      }),
    });
    if (!response.ok) return null;
    return await response.json();
  } catch {
    return null;
  }
}

function renderBatterySummary(details) {
  const existing = document.querySelector(".battery-summary");
  if (existing) existing.remove();
  if (!details) return;

  const summary = document.createElement("div");
  summary.className = "battery-summary";
  summary.innerHTML = `
    <div><span>Strategy</span><strong>${escapeHtml(details.strategy || "Role-fit shortlist")}</strong></div>
    <div><span>Coverage</span><strong>${escapeHtml((details.coverage || []).join(", ") || "Catalog match")}</strong></div>
    <div><span>Estimated time</span><strong>${escapeHtml(details.total_duration || "Varies")}</strong></div>
  `;
  recommendationList.before(summary);
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function renderQuickReplies(items) {
  quickReplies.innerHTML = "";
  quickReplies.hidden = !items.length;
  const suggestions = buildSuggestions(items);
  suggestions.forEach((text) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = text;
    button.addEventListener("click", () => {
      chatInput.value = text;
      chatInput.focus();
    });
    quickReplies.appendChild(button);
  });
}

function buildSuggestions(items) {
  if (!items.length) return [];
  const names = items.map((item) => item.name.toLowerCase()).join(" ");
  const hasPersonality = items.some((item) => (item.test_type || "").includes("P") || item.name.toLowerCase().includes("opq"));
  const suggestions = ["Make this shortlist shorter"];
  if (!hasPersonality) {
    suggestions.push("Add a personality measure");
  }
  if (items.length >= 2) {
    suggestions.push(`Compare ${items[0].name} and ${items[1].name}`);
  }
  if (names.includes("contact") || names.includes("customer")) {
    suggestions.unshift("Which should be used first for volume screening?");
  }
  if (names.includes("java") || names.includes("spring")) {
    suggestions.unshift("Drop anything redundant for a senior IC");
  }
  return suggestions.slice(0, 4);
}

document.querySelectorAll("[data-prompt]").forEach((button) => {
  button.addEventListener("click", () => {
    chatInput.value = button.dataset.prompt;
    chatInput.focus();
  });
});

logoutButton.addEventListener("click", () => {
  localStorage.removeItem("shl_user");
  window.location.href = "/login";
});

chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const content = chatInput.value.trim();
  if (!content) return;

  chatInput.value = "";
  state.messages.push({ role: "user", content });
  addMessage("user", content);
  if (state.lastRecommendations.length) {
    recommendationsEl.hidden = false;
  }
  addMessage("assistant", "Searching the SHL catalog and shaping a grounded response...");

  const response = await fetch("/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      user_id: state.user?.user_id || null,
      messages: state.messages,
    }),
  });
  const data = await response.json();
  messagesEl.lastElementChild.remove();

  if (!response.ok) {
    addMessage("assistant", data.detail || "Something went wrong.");
    return;
  }

  state.messages.push({ role: "assistant", content: data.reply });
  addMessage("assistant", data.reply);
  const incomingRecommendations = data.recommendations || [];
  const keepCurrentShortlist = isComparisonQuery(content) && state.lastRecommendations.length;
  if (keepCurrentShortlist) {
    await renderRecommendations([]);
    renderQuickReplies(state.lastRecommendations);
  } else {
    await renderRecommendations(incomingRecommendations);
    renderQuickReplies(incomingRecommendations.length ? incomingRecommendations : state.lastRecommendations);
  }
  scrollConversationToLatest();
});

updateUserChrome();
