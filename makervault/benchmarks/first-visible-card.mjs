// Self-contained so Playwright can serialize this into each fresh document.
export function installFirstVisibleCardProbe() {
  const result = window.__mvFirstVisibleCard = {
    schema: 1, clock: "navigation", atMs: null, submittedAtMs: null,
  };
  let frame = null;
  const stop = () => {
    observer.disconnect();
    if (frame !== null) cancelAnimationFrame(frame);
    frame = null;
    window.removeEventListener("resize", schedule);
    document.removeEventListener("load", schedule, true);
  };
  const check = () => {
    frame = null;
    if (result.atMs !== null) return;
    for (const card of document.querySelectorAll('[title="Double-click to open large preview"]')) {
      const rect = card.getBoundingClientRect();
      const style = getComputedStyle(card);
      if (rect.width > 0 && rect.height > 0 && rect.bottom > 0 && rect.right > 0 &&
          rect.top < innerHeight && rect.left < innerWidth && style.visibility !== "hidden" &&
          style.visibility !== "collapse" && style.display !== "none" && style.opacity !== "0") {
        const at = performance.now();
        if (Number.isFinite(at) && at >= 0) result.atMs = at;
        stop();
        break;
      }
    }
  };
  const schedule = () => {
    if (result.atMs === null && frame === null) frame = requestAnimationFrame(check);
  };
  const observer = new MutationObserver(schedule);
  observer.observe(document, { childList: true, subtree: true, attributes: true,
    attributeFilter: ["class", "style", "hidden", "title"] });
  document.addEventListener("submit", () => {
    if (result.submittedAtMs === null) result.submittedAtMs = performance.now();
  }, true);
  document.addEventListener("load", schedule, true);
  window.addEventListener("resize", schedule);
  window.addEventListener("pagehide", stop, { once: true });
  schedule();
}
