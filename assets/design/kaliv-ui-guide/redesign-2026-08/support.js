/*
 * Kaliv redesign handoff runtime helpers.
 *
 * The large static HTML mockup predates DDR-001 and contains legacy inline
 * color literals.  kaliv-ui-tokens.json schema v2 is authoritative; normalize
 * the two contrast-sensitive legacy literals at load so the rendered handoff
 * cannot drift from the gated token values.
 */
(function normalizeDdr001Colors() {
  "use strict";

  const replacements = new Map([
    ["#f6efe2", "#2b1c05"], // gold.on: AA text on #B08A3E
    ["#9c7a28", "#7e621c"], // light gold accent: AA on light surfaces
  ]);

  function normalizeInlineStyles(root) {
    root.querySelectorAll("[style]").forEach((element) => {
      const original = element.getAttribute("style");
      if (!original) return;

      let normalized = original;
      replacements.forEach((next, previous) => {
        normalized = normalized.replaceAll(previous, next);
        normalized = normalized.replaceAll(previous.toUpperCase(), next.toUpperCase());
      });

      if (normalized !== original) {
        element.setAttribute("style", normalized);
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => normalizeInlineStyles(document));
  } else {
    normalizeInlineStyles(document);
  }
})();
