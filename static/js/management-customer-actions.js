(() => {
  const dialog = document.querySelector("[data-customer-block-dialog]");
  const blockForm = document.querySelector("[data-customer-block-form]");
  const blockName = document.querySelector("[data-customer-block-name]");
  const reasonField = document.querySelector("#customer-block-reason");

  document.querySelectorAll("[data-customer-block-open]").forEach((button) => {
    button.addEventListener("click", () => {
      if (!dialog || !blockForm || !reasonField) return;
      blockForm.action = button.dataset.blockUrl;
      if (blockName) blockName.textContent = button.dataset.customerPhone || "العميل";
      reasonField.value = "";
      dialog.showModal();
      reasonField.focus();
    });
  });

  document.querySelector("[data-customer-block-cancel]")?.addEventListener("click", () => dialog?.close());
  blockForm?.addEventListener("submit", (event) => {
    if (!reasonField?.value.trim()) {
      event.preventDefault();
      reasonField?.setCustomValidity("اكتب سبب الحظر.");
      reasonField?.reportValidity();
      return;
    }
    reasonField?.setCustomValidity("");
  });
  reasonField?.addEventListener("input", () => reasonField.setCustomValidity(""));

  document.querySelectorAll(".customer-unblock-form").forEach((form) => {
    form.addEventListener("submit", (event) => {
      const phone = form.dataset.customerPhone || "هذا العميل";
      if (!window.confirm(`هل تريد رفع الحظر عن ${phone} وإعادة حالة حسابه السابقة؟`)) {
        event.preventDefault();
      }
    });
  });
})();
