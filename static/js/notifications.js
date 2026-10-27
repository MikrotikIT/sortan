(() => {
  const bell = document.querySelector("[data-notification-bell]");
  const badge = bell?.querySelector("[data-notification-count]");
  const countUrl = bell?.dataset.countUrl;
  if (!bell || !badge || !countUrl) return;

  const refreshCount = async () => {
    if (document.visibilityState === "hidden") return;
    try {
      const response = await fetch(countUrl, {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      if (!response.ok) return;
      const data = await response.json();
      const count = Math.max(0, Number(data.count) || 0);
      badge.textContent = count > 99 ? "99+" : String(count);
      badge.hidden = count === 0;
      bell.setAttribute(
        "aria-label",
        count ? `الإشعارات، ${count} غير مقروء` : "الإشعارات",
      );
    } catch {
      // Keep the last server-rendered count if polling temporarily fails.
    }
  };

  window.setInterval(refreshCount, 30000);
  document.addEventListener("visibilitychange", refreshCount);
})();
