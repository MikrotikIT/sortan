(() => {
  const display = document.querySelector('[data-balance-display]');
  const toggle = document.querySelector('[data-balance-toggle]');
  if (!display || !toggle) return;

  const openEye = toggle.querySelector('[data-eye-open]');
  const closedEye = toggle.querySelector('[data-eye-closed]');
  const setVisibility = (visible) => {
    display.textContent = visible ? display.dataset.balanceValue : '••••••';
    toggle.setAttribute('aria-pressed', String(visible));
    toggle.setAttribute('aria-label', visible ? 'إخفاء الرصيد' : 'إظهار الرصيد');
    if (openEye) openEye.hidden = !visible;
    if (closedEye) closedEye.hidden = visible;
  };

  toggle.addEventListener('click', () => {
    setVisibility(toggle.getAttribute('aria-pressed') !== 'true');
  });
})();
