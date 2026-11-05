(() => {
  const form = document.querySelector("[data-auto-post-schedule-form]");
  const publishersUrl = form?.dataset.publishersUrl;
  const groupSelect = form?.querySelector('select[name="group"]');
  const senderSelect = form?.querySelector('select[name="sender"]');
  if (!form || !publishersUrl || !groupSelect || !senderSelect) return;

  let requestGeneration = 0;
  const loadPublishers = async () => {
    const groupId = groupSelect.value;
    const generation = ++requestGeneration;
    if (!groupId) {
      senderSelect.replaceChildren(new Option("اختر مجموعة أولاً", ""));
      senderSelect.disabled = true;
      return;
    }
    const previousValue = senderSelect.value;
    senderSelect.disabled = true;
    senderSelect.replaceChildren(new Option("جارٍ تحميل الناشرين…", ""));
    try {
      const url = new URL(publishersUrl, window.location.origin);
      url.searchParams.set("group", groupId);
      const response = await fetch(url, {
        credentials: "same-origin",
        cache: "no-store",
        headers: { "Accept": "application/json" },
      });
      const data = await response.json();
      if (generation !== requestGeneration) return;
      if (!response.ok || !data.ok) throw new Error(data.error || "تعذر تحميل الناشرين.");
      const options = [new Option("اختر الناشر", "")];
      (data.publishers || []).forEach((publisher) => {
        const option = new Option(publisher.label, String(publisher.id));
        option.selected = String(publisher.id) === previousValue;
        options.push(option);
      });
      senderSelect.replaceChildren(...options);
      senderSelect.disabled = false;
      if (options.length === 1) senderSelect.options[0].textContent = "لا يوجد أعضاء مسموح لهم بالنشر";
    } catch (error) {
      if (generation !== requestGeneration) return;
      senderSelect.replaceChildren(new Option(error.message || "تعذر تحميل الناشرين", ""));
      senderSelect.disabled = true;
    }
  };

  senderSelect.disabled = !groupSelect.value;
  groupSelect.addEventListener("change", loadPublishers);
})();
