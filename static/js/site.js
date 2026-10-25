(() => {
  const openers = document.querySelectorAll('[data-open-modal]');
  const closers = document.querySelectorAll('[data-close-modal]');

  openers.forEach((button) => {
    button.addEventListener('click', () => {
      const modal = document.getElementById(button.dataset.openModal);
      if (!modal) return;
      modal.classList.add('is-open');
      modal.setAttribute('aria-hidden', 'false');
      const filmUrl = button.dataset.filmUrl;
      const urlInput = modal.querySelector('input[name="film_url"]');
      if (filmUrl && urlInput) urlInput.value = filmUrl;
      const firstInput = modal.querySelector('input:not([type="hidden"])');
      if (firstInput) firstInput.focus();
      updateInvestmentAmount(modal);
    });
  });

  const closeModal = (modal) => {
    modal.classList.remove('is-open');
    modal.setAttribute('aria-hidden', 'true');
  };

  closers.forEach((button) => button.addEventListener('click', () => closeModal(button.closest('.modal-backdrop'))));
  document.querySelectorAll('.modal-backdrop').forEach((modal) => {
    modal.addEventListener('click', (event) => {
      if (event.target === modal) closeModal(modal);
    });
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') document.querySelectorAll('.modal-backdrop.is-open').forEach(closeModal);
  });

  const updateInvestmentAmount = (root = document) => {
    root.querySelectorAll('.investment-form').forEach((form) => {
      const amountField = form.querySelector('[data-balance-only]');
      if (!amountField) return;
      const selected = form.querySelector('input[name="funding_method"]:checked');
      amountField.hidden = !selected || selected.value !== 'balance';
      if (selected && selected.value === 'balance') {
        const amountInput = amountField.querySelector('input[name="amount"]');
        if (amountInput) amountInput.value = form.dataset.balanceAmount;
      }
    });
  };

  document.querySelectorAll('.investment-form input[name="funding_method"]').forEach((input) => {
    input.addEventListener('change', () => updateInvestmentAmount(input.form));
  });
  updateInvestmentAmount();

  document.querySelectorAll('[data-copy-target]').forEach((button) => {
    button.addEventListener('click', async () => {
      const target = document.getElementById(button.dataset.copyTarget);
      if (!target) return;
      try {
        if (navigator.clipboard && window.isSecureContext) {
          await navigator.clipboard.writeText(target.textContent.trim());
        } else {
          const temporary = document.createElement('textarea');
          temporary.value = target.textContent.trim();
          temporary.style.position = 'fixed';
          temporary.style.opacity = '0';
          document.body.appendChild(temporary);
          temporary.select();
          document.execCommand('copy');
          temporary.remove();
        }
        const original = button.textContent;
        button.textContent = 'تم النسخ';
        window.setTimeout(() => { button.textContent = original; }, 1500);
      } catch (_) {
        button.textContent = 'حدده للنسخ';
      }
    });
  });
})();
