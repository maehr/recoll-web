// SPDX-License-Identifier: AGPL-3.0-only
// The few browser behaviours of recoll-web. The CSP forbids inline script, so they live here.

const preview = () => document.getElementById("preview");
const query = () => document.getElementById("query");
const reduceMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

// The link that opened the preview gets the focus back when the preview closes.
let previewOpener = null;

function closePreview() {
  if (!preview().hasChildNodes()) return;
  preview().replaceChildren();
  const opener = previewOpener?.isConnected ? previewOpener : query();
  previewOpener = null;
  opener.focus();
}

// Show the platform key in the shortcut hint.
document.addEventListener("DOMContentLoaded", () => {
  const isMac = /Mac|iPhone|iPad/.test(navigator.userAgent);
  document.querySelectorAll("[data-shortcut]").forEach((key) => {
    key.textContent = isMac ? "⌘ K" : "Ctrl K";
  });
});

// A shortcut with a modifier key, because a single-character shortcut conflicts with speech input (WCAG 2.1.4).
document.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && !event.altKey && event.key.toLowerCase() === "k") {
    event.preventDefault();
    query().focus();
    query().select();
  }
  if (event.key === "Escape" && preview().hasChildNodes()) {
    event.preventDefault();
    closePreview();
  }
});

document.addEventListener("click", (event) => {
  if (event.target.closest("[data-close-preview]")) closePreview();
});

document.addEventListener("htmx:beforeRequest", (event) => {
  const target = event.detail.target;
  if (target?.id === "results") target.setAttribute("aria-busy", "true");
  if (target?.id === "preview") previewOpener = event.detail.elt;
});

document.addEventListener("htmx:afterRequest", (event) => {
  event.detail.target?.removeAttribute("aria-busy");
});

// A history restore fires this event without a target.
document.addEventListener("htmx:afterSwap", (event) => {
  const target = event.detail.target;
  if (target?.id === "results") {
    preview().replaceChildren();
    const status = target.querySelector("[data-status]");
    document.getElementById("status").textContent = status ? status.dataset.status : "";
    const q = query().value.trim();
    document.title = q ? `${q} · Recoll Web` : "Recoll Web";
    // A page link leaves the page with its swap, so the focus moves to the new result summary.
    if (event.detail.requestConfig?.elt?.hasAttribute("data-page-link")) {
      (target.querySelector(".result-summary") ?? target).focus();
    }
  }
  if (target?.id === "preview") {
    target.scrollIntoView({ behavior: reduceMotion() ? "auto" : "smooth", block: "start" });
    const heading = target.querySelector("#preview-title");
    if (heading) heading.focus({ preventScroll: true });
  }
});
