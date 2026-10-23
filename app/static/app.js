const $ = (selector) => document.querySelector(selector);

const form = $("#shorten-form");
const formError = $("#form-error");
const linksBody = $("#links-body");
const statsSection = $("#stats");

let currentStatsCode = null;

// ------------------------------------------------------------------ API helpers

async function api(path, options = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(errorMessage(data, res.status));
  return data;
}

function errorMessage(data, status) {
  if (typeof data.detail === "string") return data.detail;
  if (Array.isArray(data.detail) && data.detail.length) {
    const first = data.detail[0];
    if (first.loc?.at(-1) === "url") return "Please enter a valid http(s) URL.";
    return first.msg;
  }
  return `Request failed (${status}).`;
}

const enc = encodeURIComponent;

// ------------------------------------------------------------------ small UI utils

function el(tag, props = {}, ...children) {
  const node = Object.assign(document.createElement(tag), props);
  node.append(...children);
  return node;
}

let toastTimer;
function toast(message) {
  const node = $("#toast");
  node.textContent = message;
  node.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (node.hidden = true), 2200);
}

function timeAgo(iso) {
  const seconds = Math.round((Date.now() - new Date(iso)) / 1000);
  const units = [["day", 86400], ["hour", 3600], ["minute", 60]];
  for (const [unit, size] of units) {
    if (seconds >= size) {
      const n = Math.floor(seconds / size);
      return `${n} ${unit}${n > 1 ? "s" : ""} ago`;
    }
  }
  return "just now";
}

function expiryBadge(expiresAt) {
  if (!expiresAt) return null;
  const msLeft = new Date(expiresAt) - Date.now();
  if (msLeft <= 0) return el("span", { className: "badge expired", textContent: "expired" });
  const days = Math.ceil(msLeft / 86400000);
  return el("span", { className: "badge", textContent: `${days}d left` });
}

async function copy(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast("Copied to clipboard");
  } catch {
    toast("Copy failed. Select the link and copy it manually");
  }
}

// ------------------------------------------------------------------ shorten form

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  formError.hidden = true;
  const button = form.querySelector("button[type=submit]");
  button.disabled = true;

  const alias = $("#alias").value.trim();
  const expires = $("#expires").value;
  try {
    const link = await api("/api/links", {
      method: "POST",
      body: JSON.stringify({
        url: $("#url").value.trim(),
        alias: alias || null,
        expires_in_days: expires ? Number(expires) : null,
      }),
    });
    showResult(link);
    form.reset();
    loadLinks();
  } catch (err) {
    formError.textContent = err.message;
    formError.hidden = false;
  } finally {
    button.disabled = false;
  }
});

function showResult(link) {
  const anchor = $("#result-link");
  anchor.href = link.short_url;
  anchor.textContent = link.short_url.replace(/^https?:\/\//, "");
  $("#result-target").textContent = `→ ${link.target_url}`;
  $("#result-qr").src = `/api/links/${enc(link.code)}/qr`;
  $("#copy-btn").onclick = () => copy(link.short_url);
  $("#result-stats-btn").onclick = () => openStats(link.code);
  $("#result").hidden = false;
}

// ------------------------------------------------------------------ recent links table

async function loadLinks() {
  try {
    const links = await api("/api/links?limit=25");
    linksBody.replaceChildren(...links.map(renderRow));
    $("#empty-state").hidden = links.length > 0;
  } catch (err) {
    toast(err.message);
  }
}

function renderRow(link) {
  const shortCell = el("td", { className: "code-cell" },
    el("a", { href: link.short_url, target: "_blank", rel: "noopener", textContent: `/${link.code}` }));
  const badge = expiryBadge(link.expires_at);
  if (badge) shortCell.append(badge);

  const statsBtn = el("button", { className: "button ghost small", type: "button", textContent: "Stats" });
  statsBtn.onclick = () => openStats(link.code);
  const copyBtn = el("button", { className: "button ghost small", type: "button", textContent: "Copy" });
  copyBtn.onclick = () => copy(link.short_url);
  const deleteBtn = el("button", { className: "button ghost small danger", type: "button", textContent: "Delete" });
  deleteBtn.onclick = () => deleteLink(link.code);

  return el("tr", {},
    shortCell,
    el("td", { className: "dest" }, el("span", { className: "truncate", title: link.target_url, textContent: link.target_url })),
    el("td", { className: "num", textContent: link.clicks.toLocaleString() }),
    el("td", { className: "muted", title: link.created_at, textContent: timeAgo(link.created_at) }),
    el("td", { className: "row-actions" }, statsBtn, copyBtn, deleteBtn),
  );
}

async function deleteLink(code) {
  if (!confirm(`Delete /${code} and all of its click data?`)) return;
  try {
    await api(`/api/links/${enc(code)}`, { method: "DELETE" });
    toast(`Deleted /${code}`);
    if (currentStatsCode === code) closeStats();
    loadLinks();
  } catch (err) {
    toast(err.message);
  }
}

// ------------------------------------------------------------------ analytics panel

async function openStats(code) {
  try {
    const stats = await api(`/api/links/${enc(code)}/stats`);
    currentStatsCode = code;
    renderStats(stats);
    statsSection.hidden = false;
    statsSection.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    toast(err.message);
  }
}

function closeStats() {
  currentStatsCode = null;
  statsSection.hidden = true;
}

function renderStats(stats) {
  $("#stats-code").textContent = `/${stats.code}`;
  $("#stats-target").textContent = stats.target_url;
  $("#stats-total").textContent = stats.total_clicks.toLocaleString();

  const max = Math.max(1, ...stats.last_7_days.map((d) => d.clicks));
  $("#stats-chart").replaceChildren(...stats.last_7_days.map(({ date, clicks }) => {
    const day = new Date(`${date}T00:00:00Z`).toLocaleDateString(undefined, { weekday: "short", timeZone: "UTC" });
    const fill = el("div", { className: "bar-fill", title: `${clicks} clicks on ${date}` });
    fill.style.height = `${(clicks / max) * 100}%`;
    return el("div", { className: "bar" },
      el("span", { className: "bar-value", textContent: clicks }),
      fill,
      el("span", { className: "bar-label", textContent: day }));
  }));

  renderBreakdown($("#stats-referrers"), stats.referrers, stats.total_clicks);
  renderBreakdown($("#stats-browsers"), stats.browsers, stats.total_clicks);
  renderBreakdown($("#stats-devices"), stats.devices, stats.total_clicks);
}

function renderBreakdown(list, items, total) {
  if (!items.length) {
    list.replaceChildren(el("li", { className: "muted", textContent: "No clicks yet" }));
    return;
  }
  list.replaceChildren(...items.map(({ label, clicks }) => {
    const meter = el("span");
    meter.style.width = `${(clicks / total) * 100}%`;
    return el("li", {},
      el("div", { className: "line" }, el("span", { textContent: label }), el("strong", { textContent: clicks })),
      el("div", { className: "meter" }, meter));
  }));
}

$("#stats-close").onclick = closeStats;
$("#refresh-btn").onclick = () => {
  loadLinks();
  if (currentStatsCode) openStats(currentStatsCode);
};

loadLinks();
