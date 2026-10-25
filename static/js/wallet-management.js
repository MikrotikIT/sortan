(() => {
  const clearKey = (form) => {
    const key = form.querySelector(".revealed-private-key");
    const copy = form.querySelector(".private-key-copy");
    const reveal = form.querySelector('button[type="submit"]');
    if (key) {
      key.textContent = "";
      key.hidden = true;
    }
    if (copy) copy.hidden = true;
    if (reveal) reveal.textContent = "كشف المفتاح";
  };

  document.querySelectorAll(".wallet-reveal-form").forEach((form) => {
    let clearTimer;
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const reveal = form.querySelector('button[type="submit"]');
      const key = form.querySelector(".revealed-private-key");
      const copy = form.querySelector(".private-key-copy");
      const csrf = form.querySelector('[name="csrfmiddlewaretoken"]')?.value;
      reveal.disabled = true;
      try {
        const response = await fetch(form.action, {
          method: "POST",
          credentials: "same-origin",
          headers: { "X-CSRFToken": csrf, "X-Requested-With": "XMLHttpRequest" },
        });
        if (!response.ok) throw new Error("تعذر كشف المفتاح. تأكد من صلاحيات الحساب.");
        const data = await response.json();
        key.textContent = data.private_key;
        key.hidden = false;
        copy.hidden = false;
        reveal.textContent = "إخفاء المفتاح";
        clearTimeout(clearTimer);
        clearTimer = setTimeout(() => clearKey(form), 30000);
      } catch (error) {
        window.alert(error.message || "تعذر كشف المفتاح.");
      } finally {
        reveal.disabled = false;
      }
    });
    form.querySelector('button[type="submit"]').addEventListener("click", (event) => {
      if (event.currentTarget.textContent.includes("إخفاء")) {
        event.preventDefault();
        clearTimeout(clearTimer);
        clearKey(form);
      }
    });
  });

  document.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-copy-target]");
    if (!button) return;
    const target = document.getElementById(button.dataset.copyTarget);
    if (!target) return;
    const value = target.textContent.trim();
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(value);
      } else {
        const temporary = document.createElement("textarea");
        temporary.value = value;
        temporary.style.position = "fixed";
        temporary.style.opacity = "0";
        document.body.appendChild(temporary);
        temporary.select();
        document.execCommand("copy");
        temporary.remove();
      }
      const original = button.textContent;
      button.textContent = "تم النسخ ✓";
      setTimeout(() => (button.textContent = original), 1400);
    } catch {
      window.alert("لم يتمكن المتصفح من النسخ؛ حدد النص وانسخه يدوياً.");
    }
  });

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) document.querySelectorAll(".wallet-reveal-form").forEach(clearKey);
  });
})();
