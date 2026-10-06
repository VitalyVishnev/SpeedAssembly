/* Material owns navigation/history; this only warms the browser's HTTP cache. */
(() => {
  const base = new URL(`${JSON.parse(document.getElementById("__config").textContent).base}/`, location);
  const locale = url => url.pathname.startsWith(`${base.pathname}ru/`) ? "ru" : "en";
  let timer;
  let controller;
  let pending;

  function cancel() {
    clearTimeout(timer);
    controller?.abort();
    controller = undefined;
    pending = undefined;
  }

  function schedule(event) {
    if (event.pointerType && event.pointerType !== "mouse") return;
    const link = event.target.closest?.("a[href]");
    let url;
    if (link && !link.target && !link.hasAttribute("download")) {
      const candidate = new URL(link.href);
      // Only generated article links, not assets, external sites or anchors.
      if (candidate.origin === location.origin && !candidate.search &&
          candidate.pathname.startsWith(base.pathname) &&
          locale(candidate) === document.documentElement.lang &&
          candidate.pathname !== location.pathname &&
          candidate.pathname.endsWith("/") &&
          link.closest(".md-nav, .md-content")) {
        candidate.hash = "";
        url = candidate.href;
      }
    }
    if (url === pending) return;
    cancel();
    if (!url || navigator.connection?.saveData) return;
    pending = url;
    timer = setTimeout(async () => {
      const request = controller = new AbortController();
      try {
        const response = await fetch(url, {
          signal: request.signal,
          credentials: "same-origin",
          priority: "low",
        });
        // Consume the body so a completed response can satisfy Material's XHR.
        await response.arrayBuffer();
      } catch {
        // Speculation is optional; a click still uses normal navigation.
        if (controller === request) pending = undefined;
      }
    }, 100);
  }

  document.addEventListener("pointerover", schedule);
  document.addEventListener("focusin", schedule);
  document.addEventListener("pointerout", event => {
    if (!event.relatedTarget) cancel();
  });
  document.addEventListener("focusout", cancel);
  document.addEventListener("click", event => {
    const link = event.target.closest?.("a[href]");
    const url = link && new URL(link.href);
    // Let an in-flight fetch of the clicked page finish warming the HTTP cache.
    if (!url || url.href.split("#")[0] !== pending) cancel();
    if (!link || link.target || link.hasAttribute("download")) return;
    // Search can link to the other locale too; it needs its translated shell.
    if (url.origin === location.origin && url.pathname.startsWith(base.pathname) &&
        locale(url) !== document.documentElement.lang) link.target = "_self";
  }, true);
  window.addEventListener("pagehide", cancel);

  document$.subscribe(() => {
    cancel();
    // Material replaces the article/head but retains our custom header links.
    // Locale changes reload the shell so search, labels and html.lang agree.
    for (const link of document.querySelectorAll(".sa-language a[hreflang]")) {
      const alternate = document.querySelector(
        `link[rel="alternate"][hreflang="${link.hreflang}"]`
      );
      if (alternate) link.href = alternate.href;
    }
  });
})();
