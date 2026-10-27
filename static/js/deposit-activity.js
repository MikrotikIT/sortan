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
  const flag = toast.querySelector("[data-activity-flag]");
  const phone = toast.querySelector("[data-activity-phone]");
  const amount = toast.querySelector("[data-activity-amount]");
  const close = toast.querySelector("[data-activity-close]");
  const interval = Math.max(5, Number(toast.dataset.activityInterval) || 10) * 1000;
  const wrapFlagSvg = (contents) => `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 20" role="img">${contents}</svg>`;
  const countryFlags = new Map();
  const addCountryFlag = (names, contents) => {
    const flagSvg = wrapFlagSvg(contents);
    names.forEach((name) => countryFlags.set(name, flagSvg));
  };
  addCountryFlag(["سوريا", "سورية", "syria"], '<rect width="30" height="6.67" fill="#007a3d"/><rect y="6.67" width="30" height="6.66" fill="#fff"/><rect y="13.33" width="30" height="6.67" fill="#000"/><polygon points="7.5,8.3 8.1,10 9.9,10 8.45,11.05 9,12.8 7.5,11.75 6,12.8 6.55,11.05 5.1,10 6.9,10" fill="#ce1126"/><polygon points="22.5,8.3 23.1,10 24.9,10 23.45,11.05 24,12.8 22.5,11.75 21,12.8 21.55,11.05 20.1,10 21.9,10" fill="#ce1126"/>');
  addCountryFlag(["العراق", "iraq"], '<rect width="30" height="6.67" fill="#ce1126"/><rect y="6.67" width="30" height="6.66" fill="#fff"/><rect y="13.33" width="30" height="6.67" fill="#000"/><text x="15" y="12" text-anchor="middle" font-size="4.2" font-family="Arial,sans-serif" font-weight="700" fill="#007a3d">الله أكبر</text>');
  addCountryFlag(["الأردن", "اردن", "jordan"], '<rect width="30" height="6.67" fill="#000"/><rect y="6.67" width="30" height="6.66" fill="#fff"/><rect y="13.33" width="30" height="6.67" fill="#007a3d"/><polygon points="0,0 12,10 0,20" fill="#ce1126"/><polygon points="4.7,6.6 5.35,8.55 7.4,8.55 5.75,9.75 6.4,11.7 4.7,10.5 3,11.7 3.65,9.75 2,8.55 4.05,8.55" fill="#fff"/>');
  addCountryFlag(["السودان", "sudan"], '<rect width="30" height="6.67" fill="#ce1126"/><rect y="6.67" width="30" height="6.66" fill="#fff"/><rect y="13.33" width="30" height="6.67" fill="#000"/><polygon points="0,0 12,10 0,20" fill="#007a3d"/>');
  addCountryFlag(["لبنان", "lebanon"], '<rect width="30" height="20" fill="#fff"/><rect width="30" height="3.5" fill="#ed1c24"/><rect y="16.5" width="30" height="3.5" fill="#ed1c24"/><path d="M15 5.3 13.9 8.4 12.1 7.6 13.1 9.5 11.8 10.3 14.2 10.1 14 13.4 16 13.4 15.8 10.1 18.2 10.3 16.9 9.5 17.9 7.6 16.1 8.4Z" fill="#007a3d"/>');
  const fallbackFlag = wrapFlagSvg('<circle cx="15" cy="10" r="8" fill="#e8f2f4"/><path d="M12.5 7.5a2.7 2.7 0 1 1 4.3 2.2c-1.2.9-1.8 1.3-1.8 2.8" fill="none" stroke="#607980" stroke-width="1.5" stroke-linecap="round"/><circle cx="15" cy="15.5" r=".8" fill="#607980"/>');

  const hideToast = () => {
    toast.hidden = true;
  };

  const showActivity = () => {
    const item = examples[Math.floor(Math.random() * examples.length)];
    if (!item || !country || !flag || !phone || !amount) return;
    flag.innerHTML = countryFlags.get(item.country.trim().toLocaleLowerCase()) || fallbackFlag;
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
