(() => {
  const section = document.querySelector("[data-chat-groups]");
  if (!section) return;

  const endpoint = section.dataset.liveStatsUrl;
  const groupIds = [...section.querySelectorAll("[data-group-member-count]")]
    .map((node) => node.dataset.groupMemberCount)
    .filter(Boolean);
  if (!endpoint || !groupIds.length) return;

  let refreshing = false;
  const refreshCounts = async () => {
    if (refreshing || document.visibilityState !== "visible") return;
    refreshing = true;
    try {
      const params = new URLSearchParams({ groups: groupIds.join(",") });
      const response = await fetch(`${endpoint}?${params}`, {
        credentials: "same-origin",
        cache: "no-store",
        headers: { "Accept": "application/json" },
      });
      if (!response.ok) return;
      const data = await response.json();
      data.groups?.forEach((group) => {
        const count = section.querySelector(`[data-group-member-count="${Number(group.id)}"]`);
        if (count) count.textContent = String(group.display_member_count);
      });
    } catch { /* The page remains usable if live stats cannot be reached. */ }
    finally { refreshing = false; }
  };

  refreshCounts();
  const timer = window.setInterval(refreshCounts, 3000);
  window.addEventListener("beforeunload", () => window.clearInterval(timer));
})();
