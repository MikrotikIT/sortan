(() => {
  const totalBadge = document.querySelector("[data-chat-unread-total]");
  const groupsRoot = document.querySelector("[data-chat-groups]");
  const endpoint = totalBadge?.dataset.countUrl || groupsRoot?.dataset.chatUnreadUrl;
  if (!endpoint) return;

  const updateBadge = (badge, count, total = false) => {
    const safeCount = Math.max(0, Number(count) || 0);
    badge.hidden = safeCount === 0;
    badge.setAttribute("aria-label", `${safeCount} رسالة غير مقروءة${total ? " في جميع المجموعات" : ""}`);
    if (total) {
      badge.textContent = safeCount > 99 ? "99+" : String(safeCount);
      return;
    }
    const number = badge.querySelector("b");
    if (number) number.textContent = safeCount > 99 ? "99+" : String(safeCount);
  };

  let refreshing = false;
  const refreshUnread = async () => {
    if (refreshing || document.visibilityState !== "visible") return;
    refreshing = true;
    try {
      const response = await fetch(endpoint, {
        credentials: "same-origin",
        cache: "no-store",
        headers: { "Accept": "application/json" },
      });
      if (!response.ok) return;
      const data = await response.json();
      if (totalBadge) updateBadge(totalBadge, data.total, true);
      if (groupsRoot) {
        groupsRoot.querySelectorAll("[data-chat-unread-group]").forEach((badge) => {
          const count = data.groups?.[badge.dataset.chatUnreadGroup] || 0;
          updateBadge(badge, count);
        });
      }
    } catch { /* Keep the server-rendered counts if polling is unavailable. */ }
    finally { refreshing = false; }
  };

  refreshUnread();
  const timer = window.setInterval(refreshUnread, 8000);
  window.addEventListener("beforeunload", () => window.clearInterval(timer));
})();
