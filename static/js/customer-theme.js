(() => {
  const root = document.documentElement;
  const customerId = root.dataset.customerId;
  if (!customerId) return;

  const storageKey = `customer-theme:${customerId}`;
  const isDark = () => root.dataset.customerTheme === "dark";

  const syncToggle = () => {
    document.querySelectorAll("[data-customer-theme-toggle]").forEach((button) => {
      const dark = isDark();
      const label = dark ? "تفعيل الوضع النهاري" : "تفعيل الوضع الليلي";
      button.setAttribute("aria-label", label);
      button.setAttribute("title", label);
      button.setAttribute("aria-pressed", String(dark));
      const icon = button.querySelector("[data-customer-theme-icon]");
      if (icon) icon.textContent = dark ? "☀" : "☾";
    });
  };

  try {
    if (window.localStorage.getItem(storageKey) === "dark") {
      root.dataset.customerTheme = "dark";
    }
  } catch {
    // Keep the light theme if browser storage is unavailable.
  }

  document.addEventListener("DOMContentLoaded", syncToggle);
  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-customer-theme-toggle]");
    if (!button) return;
    const dark = !isDark();
    if (dark) root.dataset.customerTheme = "dark";
    else delete root.dataset.customerTheme;
    try {
      window.localStorage.setItem(storageKey, dark ? "dark" : "light");
    } catch {
      // The theme still changes for the current page.
    }
    syncToggle();
  });
})();
