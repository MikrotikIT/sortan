(() => {
  const page = document.querySelector("[data-deposit-notifications]");
  if (!page) return;

  let latestId = Number(page.dataset.afterId) || 0;
  let checking = false;

  const showDepositToast = (deposit) => {
    let viewport = document.querySelector(".toast-viewport");
    if (!viewport) {
      viewport = document.createElement("div");
      viewport.className = "toast-viewport";
      viewport.setAttribute("aria-label", "إشعارات الإيداع");
      viewport.setAttribute("aria-live", "polite");
      viewport.setAttribute("aria-atomic", "false");
      document.body.append(viewport);
    }

    const toast = document.createElement("article");
    toast.className = "app-toast app-toast-success";
    toast.setAttribute("role", "status");
    toast.setAttribute("aria-live", "polite");
    toast.setAttribute("aria-atomic", "true");

    const icon = document.createElement("span");
    icon.className = "app-toast-icon";
    icon.setAttribute("aria-hidden", "true");
    icon.textContent = "✓";

    const copy = document.createElement("div");
    copy.className = "app-toast-copy";
    const heading = document.createElement("strong");
    heading.textContent = "تم استلام إيداع مباشر";
    const message = document.createElement("p");
    message.textContent = `أُضيف ${deposit.amount} USDT إلى رصيدك.`;
    copy.append(heading, message);

    if (deposit.transaction_id) {
      const link = document.createElement("a");
      link.href = `https://tronscan.org/#/transaction/${encodeURIComponent(deposit.transaction_id)}`;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = "عرض المعاملة";
      message.append(" ", link);
    }

    const close = document.createElement("button");
    close.type = "button";
    close.className = "app-toast-close";
    close.setAttribute("aria-label", "إغلاق الإشعار");
    close.textContent = "×";
    const dismiss = () => {
      toast.classList.add("is-leaving");
      window.setTimeout(() => toast.remove(), 200);
    };
    close.addEventListener("click", dismiss, { once: true });

    toast.append(icon, copy, close);
    viewport.append(toast);
    window.setTimeout(dismiss, 9000);
  };

  const refreshDeposits = async () => {
    if (checking || document.hidden) return;
    checking = true;
    try {
      const url = new URL(page.dataset.notificationsUrl, window.location.origin);
      url.searchParams.set("after", String(latestId));
      const response = await fetch(url, {
        credentials: "same-origin",
        cache: "no-store",
        headers: { "X-Requested-With": "XMLHttpRequest" },
      });
      if (!response.ok) return;

      const result = await response.json();
      for (const deposit of result.deposits || []) {
        const id = Number(deposit.id);
        if (!Number.isSafeInteger(id) || id <= latestId) continue;
        latestId = id;
        showDepositToast(deposit);
      }
    } catch {
      // A later poll will retry if the connection is temporarily unavailable.
    } finally {
      checking = false;
    }
  };

  window.setTimeout(refreshDeposits, 5000);
  window.setInterval(refreshDeposits, 20000);
})();
