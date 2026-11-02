(() => {
  document.querySelector("[data-demo-account-group-filter]")?.addEventListener("change", (event) => {
    event.currentTarget.requestSubmit();
  });

  const form = document.querySelector("#demo-account-create-form");
  if (form) {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const count = Math.max(1, Math.min(20, Number(form.querySelector('[name="count"]')?.value || 1)));
      const status = form.querySelector("[data-create-status]");
      const button = form.querySelector("[data-create-demo-accounts]");
      const windows = Array.from({ length: count }, () => {
        const opened = window.open("about:blank", "_blank");
        if (opened) {
          opened.document.title = "فتح محادثة تجريبية";
          opened.document.body.textContent = "جارٍ فتح المحادثة التجريبية…";
        }
        return opened;
      });
      const csrf = form.querySelector('[name="csrfmiddlewaretoken"]')?.value || "";
      if (status) {
        status.hidden = false;
        status.textContent = "جارٍ إنشاء الحسابات وفتح صفحات المحادثة…";
      }
      if (button) button.disabled = true;
      try {
        const response = await fetch(form.action, {
          method: "POST",
          credentials: "same-origin",
          headers: { Accept: "application/json", "X-CSRFToken": csrf },
          body: new FormData(form),
        });
        const result = await response.json();
        if (!response.ok || !result.ok) throw new Error(result.error || "تعذر إنشاء الحسابات التجريبية.");
        result.accounts.forEach((account, index) => {
          if (windows[index]) windows[index].location.replace(account.url);
        });
        const blocked = windows.filter((item) => !item).length;
        const destination = new URL(result.page_url, window.location.href);
        if (blocked) destination.searchParams.set("popup_blocked", String(blocked));
        window.location.assign(destination.href);
      } catch (error) {
        windows.forEach((opened) => opened?.close());
        if (status) status.textContent = error.message || "تعذر إنشاء الحسابات التجريبية.";
        if (button) button.disabled = false;
      }
    });
  }

  document.querySelector("[data-open-all-accounts]")?.addEventListener("click", (event) => {
    const links = [...document.querySelectorAll("[data-demo-account-url]")];
    let openedCount = 0;
    links.forEach((link) => {
      const opened = window.open(link.href, "_blank");
      if (opened) openedCount += 1;
    });
    if (openedCount < links.length) {
      event.currentTarget.textContent = `تم فتح ${openedCount} من ${links.length}؛ اسمح بالنوافذ المنبثقة`;
    }
  });
})();
