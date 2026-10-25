(() => {
  const counter = document.querySelector("[data-online-counter]");
  if (!counter) return;

  const value = counter.querySelector("[data-online-counter-value]");
  const url = counter.dataset.counterUrl;

  const refreshCounter = async () => {
    try {
      const response = await fetch(url, {
        credentials: "same-origin",
        cache: "no-store",
        headers: { "X-Requested-With": "XMLHttpRequest" },
      });
      if (!response.ok) return;

      const result = await response.json();
      if (!result.enabled) {
        counter.hidden = true;
        return;
      }

      value.textContent = Number(result.count).toLocaleString("en-US");
      counter.hidden = false;
    } catch {
      // Keep the last displayed value if a temporary network error occurs.
    }
  };

  refreshCounter();
  window.setInterval(refreshCounter, 5000);
})();
