(() => {
  const panel = document.querySelector("[data-models-url]");
  const datalist = document.getElementById("openrouter-model-options");
  const status = document.querySelector("[data-model-status]");
  if (!panel || !datalist || !status) return;

  const loadModels = async () => {
    try {
      const response = await fetch(panel.dataset.modelsUrl, {
        credentials: "same-origin",
        cache: "no-store",
        headers: { Accept: "application/json" },
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.error || "تعذر تحميل القائمة.");
      const fragment = document.createDocumentFragment();
      payload.models.forEach((model) => {
        const option = document.createElement("option");
        option.value = model.id;
        option.label = model.name;
        fragment.append(option);
      });
      datalist.replaceChildren(fragment);
      status.textContent = `تم تحميل ${payload.models.length} موديل من OpenRouter.`;
      status.classList.remove("is-error");
    } catch (error) {
      status.textContent = error?.message || "تعذر تحميل قائمة الموديلات. يمكنك كتابة معرّف الموديل يدوياً.";
      status.classList.add("is-error");
    }
  };

  loadModels();
})();
