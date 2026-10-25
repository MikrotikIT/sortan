(() => {
  const dismissToast = (toast) => {
    if (toast.dataset.dismissed) return;
    toast.dataset.dismissed = "true";
    toast.classList.add("is-leaving");
    window.setTimeout(() => toast.remove(), 200);
  };

  document.querySelectorAll("[data-toast]").forEach((toast) => {
    toast.querySelector("[data-toast-dismiss]")?.addEventListener("click", () => dismissToast(toast));

    const delay = Number(toast.dataset.toastDelay);
    if (delay > 0) window.setTimeout(() => dismissToast(toast), delay);
  });
})();
