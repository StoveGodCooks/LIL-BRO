"use strict";

const esc = (s) => String(s ?? "")
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

const fetchJson = async (url) => {
  try {
    const r = await fetch(url, { cache: "no-store" });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return await r.json();
  } catch (err) {
    return { error: String(err) };
  }
};

function renderRoadmap(data) {
  const ms = (data && data.milestones) || [];
  if (!ms.length) return "<em>Roadmap is empty.</em>";
  return ms.map((m) => {
    const tasks = (m.tasks || []).map((t) =>
      `<li class="state-${esc(t.state)}">
        <span class="state-${esc(t.state)}">${esc(t.title)}</span>
        <span class="meta"> · ${esc(t.state)}</span>
      </li>`,
    ).join("");
    return `<div class="card">
      <div class="title state-${esc(m.state)}">${esc(m.title)}</div>
      <div class="meta">${esc(m.id)} · ${esc(m.state)}</div>
      ${tasks ? `<ul>${tasks}</ul>` : ""}
    </div>`;
  }).join("");
}

function renderMemories(data) {
  const items = (data && data.items) || [];
  if (!items.length) return "<em>No memories yet.</em>";
  return items.map((m) => {
    const md = m.metadata || {};
    const ts = md.timestamp
      ? new Date(Number(md.timestamp) * 1000).toLocaleString()
      : "";
    return `<div class="card">
      <div>${esc(m.text || "")}</div>
      <div class="meta">${esc(ts)} · ${esc(md.type || "manual")}</div>
    </div>`;
  }).join("");
}

function renderPrefs(data) {
  const top = (data && data.top) || [];
  if (!top.length) return "<em>No preference patterns logged yet.</em>";
  return `<div class="card"><ul>${
    top.map((p) =>
      `<li><strong>${esc(p.type)}</strong> = ${esc(p.value)}
       <span class="meta">×${esc(p.count)}</span></li>`,
    ).join("")
  }</ul></div>`;
}

function renderIcebox(data) {
  const items = ((data && data.items) || []).filter((i) => !i.promoted_to && !i.dropped);
  if (!items.length) return "<em>Icebox is empty.</em>";
  return items.map((i) =>
    `<div class="card"><div>${esc(i.text)}</div>
     <div class="meta">${esc(i.id)}</div></div>`,
  ).join("");
}

async function loadView(name) {
  const el = document.getElementById(name);
  if (!el) return;
  const endpoints = {
    roadmap: ["/api/roadmap", renderRoadmap],
    memories: ["/api/memories", renderMemories],
    prefs: ["/api/prefs", renderPrefs],
    icebox: ["/api/icebox", renderIcebox],
  };
  const [url, render] = endpoints[name];
  el.innerHTML = "<em>loading…</em>";
  const data = await fetchJson(url);
  if (data && data.error) {
    el.innerHTML = `<em>error: ${esc(data.error)}</em>`;
    return;
  }
  el.innerHTML = render(data);
}

function switchView(name) {
  document.querySelectorAll("nav button").forEach((b) => {
    b.classList.toggle("active", b.dataset.view === name);
  });
  document.querySelectorAll(".view").forEach((v) => {
    v.classList.toggle("active", v.id === name);
  });
  loadView(name);
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("nav button").forEach((b) => {
    b.addEventListener("click", () => switchView(b.dataset.view));
  });
  ["roadmap", "memories", "prefs", "icebox"].forEach(loadView);
  setInterval(() => {
    const active = document.querySelector(".view.active");
    if (active) loadView(active.id);
  }, 15000);
});
