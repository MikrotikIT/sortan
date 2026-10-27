(() => {
  const toast = document.querySelector("[data-deposit-activity]");
  const data = document.getElementById("deposit-activity-data");
  if (!toast || !data) return;

  let examples;
  try {
    examples = JSON.parse(data.textContent);
  } catch {
    return;
  }
  if (!Array.isArray(examples) || examples.length === 0) return;

  const country = toast.querySelector("[data-activity-country]");
  const phone = toast.querySelector("[data-activity-phone]");
  const amount = toast.querySelector("[data-activity-amount]");
  const close = toast.querySelector("[data-activity-close]");
  const interval = Math.max(5, Number(toast.dataset.activityInterval) || 10) * 1000;

  const hideToast = () => {
    toast.hidden = true;
  };

  const showActivity = () => {
    const item = examples[Math.floor(Math.random() * examples.length)];
    if (!item || !country || !phone || !amount) return;
    country.textContent = `من ${item.country}`;
    phone.textContent = item.phone;
    const numericAmount = Number(item.amount);
    amount.textContent = `${Number.isFinite(numericAmount) ? numericAmount.toLocaleString("en-US", { maximumFractionDigits: 2 }) : item.amount} USDT`;
    toast.hidden = false;
    window.setTimeout(() => {
      hideToast();
      window.setTimeout(showActivity, Math.max(500, interval - 4500));
    }, 4500);
  };

  close?.addEventListener("click", hideToast);
  window.setTimeout(showActivity, Math.min(4000, interval));
})();
