(() => {
  const editor = document.querySelector('[data-withdrawal-rules-editor]');
  if (!editor) return;

  const hiddenInput = editor.querySelector('input[type="hidden"]');
  const list = editor.querySelector('[data-rule-list]');
  const addButton = editor.querySelector('[data-add-rule]');
  const form = editor.closest('form');

  const syncValue = () => {
    const rules = [...list.querySelectorAll('[data-rule-row]')]
      .map((row) => {
        const withdrawals = row.querySelector('[data-withdrawal-count]').value.trim();
        const referrals = row.querySelector('[data-referral-count]').value.trim();
        return withdrawals || referrals ? `${withdrawals}:${referrals}` : '';
      })
      .filter(Boolean);
    hiddenInput.value = rules.join(', ');
  };

  const createRow = (withdrawalCount = '', referralCount = '') => {
    const row = document.createElement('div');
    row.className = 'withdrawal-rule-row';
    row.dataset.ruleRow = '';

    const withdrawalLabel = document.createElement('label');
    withdrawalLabel.textContent = 'بعد كم سحب مدفوع؟';
    const withdrawalInput = document.createElement('input');
    withdrawalInput.type = 'number';
    withdrawalInput.min = '1';
    withdrawalInput.step = '1';
    withdrawalInput.value = withdrawalCount;
    withdrawalInput.dataset.withdrawalCount = '';
    withdrawalLabel.append(withdrawalInput);

    const referralLabel = document.createElement('label');
    referralLabel.textContent = 'إجمالي المدعوين المطلوب';
    const referralInput = document.createElement('input');
    referralInput.type = 'number';
    referralInput.min = '1';
    referralInput.step = '1';
    referralInput.value = referralCount;
    referralInput.dataset.referralCount = '';
    referralLabel.append(referralInput);

    const removeButton = document.createElement('button');
    removeButton.type = 'button';
    removeButton.className = 'remove-rule-button';
    removeButton.textContent = 'حذف';
    removeButton.setAttribute('aria-label', 'حذف هذه المرحلة');
    removeButton.addEventListener('click', () => {
      row.remove();
      syncValue();
    });

    row.append(withdrawalLabel, referralLabel, removeButton);
    list.append(row);
    return row;
  };

  const initialRules = (hiddenInput.value || '').split(/[,،]/).map((entry) => entry.trim()).filter(Boolean);
  initialRules.forEach((entry) => {
    const parts = entry.split(':', 2);
    createRow(parts[0] || '', parts[1] || '');
  });
  if (!initialRules.length) createRow();

  list.addEventListener('input', syncValue);
  addButton.addEventListener('click', () => {
    const row = createRow();
    row.querySelector('[data-withdrawal-count]').focus();
  });
  form.addEventListener('submit', syncValue);
  syncValue();
})();
