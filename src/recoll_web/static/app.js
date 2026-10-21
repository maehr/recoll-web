// SPDX-License-Identifier: AGPL-3.0-only
// The few browser behaviours of recoll-web. The CSP forbids inline script, so they live here.

const preview = () => document.getElementById("preview");

document.addEventListener("keydown", (event) => {
  const tag = document.activeElement?.tagName;
  if (event.key === "/" && !["INPUT", "SELECT", "TEXTAREA"].includes(tag)) {
    event.preventDefault();
    document.getElementById("query").focus();
  }
  if (event.key === "Escape") preview().replaceChildren();
});

document.addEventListener("click", (event) => {
  if (event.target.closest("[data-close-preview]")) preview().replaceChildren();
});

// A history restore fires this event without a target.
document.addEventListener("htmx:afterSwap", (event) => {
  const target = event.detail.target;
  if (target?.id === "results") preview().replaceChildren();
  if (target?.id === "preview") target.scrollIntoView({ behavior: "smooth", block: "start" });
});
