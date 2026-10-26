(() => {
  document.querySelectorAll('[data-balance-card]').forEach((card) => {
    const display = card.querySelector('[data-balance-display]');
    const toggle = card.querySelector('[data-balance-toggle]');
    if (!display || !toggle) return;

    const openEye = toggle.querySelector('[data-eye-open]');
    const closedEye = toggle.querySelector('[data-eye-closed]');
    const setVisibility = (visible) => {
      display.textContent = visible ? display.dataset.balanceValue : '••••••';
      toggle.setAttribute('aria-pressed', String(visible));
      const label = display.dataset.balanceLabel || 'الرصيد';
      toggle.setAttribute('aria-label', `${visible ? 'إخفاء' : 'إظهار'} ${label}`);
      if (openEye) openEye.hidden = visible;
      if (closedEye) closedEye.hidden = !visible;
    };

    setVisibility(false);
    toggle.addEventListener('click', () => {
      setVisibility(toggle.getAttribute('aria-pressed') !== 'true');
    });
  });
})();
