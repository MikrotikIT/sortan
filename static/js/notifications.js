(() => {
  const bell = document.querySelector("[data-notification-bell]");
  const badge = bell?.querySelector("[data-notification-count]");
  const countUrl = bell?.dataset.countUrl;
  if (!bell || !badge || !countUrl) return;

  let refreshInProgress = false;
  const refreshCount = async () => {
    if (document.visibilityState === "hidden" || refreshInProgress) return;
    refreshInProgress = true;
    try {
      const response = await fetch(countUrl, {
        credentials: "same-origin",
        cache: "no-store",
        headers: { Accept: "application/json", "Cache-Control": "no-cache" },
      });
      if (!response.ok) return;
      const data = await response.json();
      const count = Number(data?.count);
      if (!Number.isSafeInteger(count) || count < 0) return;
      const badgeText = count > 99 ? "99+" : String(count);
      if (badge.textContent !== badgeText) badge.textContent = badgeText;
      if (badge.hidden !== (count === 0)) badge.hidden = count === 0;
      bell.setAttribute(
        "aria-label",
        count ? `الإشعارات، ${count} غير مقروء` : "الإشعارات",
      );
    } catch {
      // Keep the last server-rendered count if polling temporarily fails.
    } finally {
      refreshInProgress = false;
    }
  };

  refreshCount();
  window.setInterval(refreshCount, 30000);
  document.addEventListener("visibilitychange", refreshCount);
})();
