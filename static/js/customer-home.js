(() => {
  document.querySelectorAll('[data-balance-card]').forEach((card) => {
    const display = card.querySelector('[data-balance-display]');
    const toggle = card.querySelector('[data-balance-toggle]');
    if (!display || !toggle) return;

    const openEye = toggle.querySelector('[data-eye-open]');
    const closedEye = toggle.querySelector('[data-eye-closed]');
    const storageKey = `customer-home:balance-visibility:${card.dataset.balanceUser}:${card.dataset.balanceVisibilityKey}`;
    const setVisibility = (visible) => {
      display.textContent = visible ? display.dataset.balanceValue : '••••••';
      toggle.setAttribute('aria-pressed', String(visible));
      const label = display.dataset.balanceLabel || 'الرصيد';
      toggle.setAttribute('aria-label', `${visible ? 'إخفاء' : 'إظهار'} ${label}`);
      if (openEye) openEye.hidden = visible;
      if (closedEye) closedEye.hidden = !visible;
    };

    let savedVisibility = false;
    try {
      savedVisibility = window.localStorage.getItem(storageKey) === 'visible';
    } catch {
      // Keep the default hidden state when browser storage is unavailable.
    }
    setVisibility(savedVisibility);
    toggle.addEventListener('click', () => {
      const visible = toggle.getAttribute('aria-pressed') !== 'true';
      setVisibility(visible);
      try {
        window.localStorage.setItem(storageKey, visible ? 'visible' : 'hidden');
      } catch {
        // The current page still updates if browser storage is unavailable.
      }
    });
  });
})();
