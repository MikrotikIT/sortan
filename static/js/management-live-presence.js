(() => {
  const panel = document.querySelector("[data-live-presence-url]");
  if (!panel) return;

  const total = panel.querySelector("[data-online-total]");
  const rows = panel.querySelector("[data-online-groups]");
  let updating = false;

  const refreshPresence = async () => {
    if (updating || document.visibilityState === "hidden") return;
    updating = true;
    panel.classList.add("is-refreshing");
    try {
      const response = await fetch(panel.dataset.livePresenceUrl, {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
      if (!response.ok) return;
      const data = await response.json();
      total.textContent = String(Number(data.total) || 0);

      const fragment = document.createDocumentFragment();
      for (const group of data.groups || []) {
        const row = document.createElement("tr");
        const name = document.createElement("td");
        name.textContent = group.title || "مجموعة دون اسم";
        const countCell = document.createElement("td");
        const count = document.createElement("span");
        count.className = "live-presence-count";
        count.textContent = String(Number(group.online_count) || 0);
        countCell.append(count);
        row.append(name, countCell);
        fragment.append(row);
      }
      if (!fragment.childNodes.length) {
        const row = document.createElement("tr");
        const empty = document.createElement("td");
        empty.colSpan = 2;
        empty.className = "live-presence-empty";
        empty.textContent = "لا توجد مجموعات نشطة.";
        row.append(empty);
        fragment.append(row);
      }
      rows.replaceChildren(fragment);
    } catch {
      // Keep the last server-rendered counts visible if polling fails.
    } finally {
      updating = false;
      panel.classList.remove("is-refreshing");
    }
  };

  window.setInterval(refreshPresence, 20000);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") refreshPresence();
  });
})();
