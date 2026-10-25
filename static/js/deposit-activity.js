(() => {
  const toast = document.querySelector("[data-deposit-activity]");
  if (!toast) return;

  const randomInteger = (minimum, maximum) => Math.floor(Math.random() * (maximum - minimum + 1)) + minimum;
  const countries = [
    {
      name: "سوريا",
      code: "syria",
      phone: () => Math.random() < 0.5
        ? `096398${randomInteger(0, 9)}***`
        : `0963934${randomInteger(0, 9)}***`,
    },
    {
      name: "العراق",
      code: "iraq",
      phone: () => `${["0770", "0781", "0750"][randomInteger(0, 2)]}${randomInteger(1000, 9999)}***`,
    },
    {
      name: "الأردن",
      code: "jordan",
      phone: () => `07${[7, 8, 9][randomInteger(0, 2)]}${randomInteger(1000, 9999)}***`,
    },
    {
      name: "السودان",
      code: "sudan",
      phone: () => `09${[1, 2, 3, 5, 6, 9][randomInteger(0, 5)]}${randomInteger(1000, 9999)}***`,
    },
    {
      name: "لبنان",
      code: "lebanon",
      phone: () => `${["03", "70", "71", "76", "78"][randomInteger(0, 4)]}${randomInteger(100, 999)}***`,
    },
  ];
  const amounts = [100, 150, 200, 300, 350, 500, 750, 1000, 1500, 2000, 3000, 5000, 7500, 10000];
  const weights = amounts.map((amount) => 10000 / amount);

  const chooseAmount = () => {
    let target = Math.random() * weights.reduce((total, weight) => total + weight, 0);
    for (let index = 0; index < amounts.length; index += 1) {
      target -= weights[index];
      if (target <= 0) return amounts[index];
    }
    return amounts[0];
  };

  const hideToast = () => {
    toast.hidden = true;
  };

  const showActivity = () => {
    const country = countries[randomInteger(0, countries.length - 1)];
    const amount = chooseAmount();
    toast.querySelectorAll("[data-activity-flag]").forEach((flag) => {
      flag.hidden = flag.dataset.activityFlag !== country.code;
    });
    toast.querySelector("[data-activity-country]").textContent = `من ${country.name}`;
    toast.querySelector("[data-activity-phone]").textContent = country.phone();
    toast.querySelector("[data-activity-amount]").textContent = `${amount.toLocaleString("en-US")}$`;
    toast.hidden = false;
    window.setTimeout(hideToast, 4500);
    window.setTimeout(showActivity, randomInteger(5000, 15000));
  };

  toast.querySelector("[data-activity-close]").addEventListener("click", hideToast);
  window.setTimeout(showActivity, randomInteger(5000, 15000));
})();
