(() => {
  document.querySelectorAll("[data-notification-form]").forEach((form) => {
    const source = form.querySelector("[data-notification-html-source]");
    const preview = form.querySelector("[data-notification-preview]");
    if (!source || !preview) return;

    const renderPreview = () => {
      preview.srcdoc = `<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; form-action 'none'; base-uri 'none'"><style>body{margin:18px;background:#fff;color:#263f46;font:14px/1.8 Tajawal,Arial,sans-serif}a{color:#087f9f}blockquote{margin:10px 0;padding:5px 12px;border-inline-start:3px solid #69bfd1;background:#f2fafc}pre,code{direction:ltr;background:#f1f5f6;padding:3px;border-radius:4px}table{border-collapse:collapse}td,th{border:1px solid #dce7e9;padding:5px 8px}</style></head><body>${source.value}</body></html>`;
    };

    form.querySelectorAll("[data-insert-before]").forEach((button) => {
      button.addEventListener("click", () => {
        const before = button.dataset.insertBefore || "";
        const after = button.dataset.insertAfter || "";
        const start = source.selectionStart;
        const end = source.selectionEnd;
        const selected = source.value.slice(start, end);
        source.setRangeText(`${before}${selected}${after}`, start, end, "select");
        if (selected) {
          const caret = start + before.length + selected.length + after.length;
          source.setSelectionRange(caret, caret);
        } else {
          const caret = start + before.length;
          source.setSelectionRange(caret, caret);
        }
        source.focus();
        renderPreview();
      });
    });

    source.addEventListener("input", renderPreview);
    renderPreview();
  });
})();
