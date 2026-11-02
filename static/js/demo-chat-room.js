(() => {
  const root = document.querySelector("[data-demo-chat-room]");
  if (!root) return;
  const transcript = root.querySelector(".demo-chat-transcript");
  const list = root.querySelector("[data-demo-chat-messages]");
  const form = root.querySelector("[data-demo-chat-form]");
  const input = form?.querySelector('textarea[name="text"]');
  const error = root.querySelector("[data-demo-chat-error]");
  const submitButton = form?.querySelector('button[type="submit"]');
  const csrf = form?.querySelector('[name="csrfmiddlewaretoken"]')?.value || "";
  const demoGrowthUrlTemplate = root.dataset.demoGrowthUrlTemplate || "";
  let lastMessageId = 0;
  let sending = false;

  const appendGrowthControls = (card, message) => {
    if (!message.is_demo || !demoGrowthUrlTemplate) return;
    const settings = message.demo_growth_settings || {};
    const details = document.createElement("details");
    details.className = "demo-chat-growth-details";
    const summary = document.createElement("summary");
    const updateSummary = () => {
      summary.textContent = settings.enabled ? "الزيادة الآلية مفعّلة · الإعدادات" : "تفعيل الزيادة الآلية لهذه الرسالة";
    };
    updateSummary();
    details.append(summary);

    const growthForm = document.createElement("form");
    growthForm.className = "demo-chat-growth-form";
    growthForm.action = demoGrowthUrlTemplate.replace(/\/0\/demo-growth\/?$/, `/${Number(message.id)}/demo-growth/`);
    growthForm.method = "post";
    const csrfField = document.createElement("input");
    csrfField.type = "hidden";
    csrfField.name = "csrfmiddlewaretoken";
    csrfField.value = csrf;
    growthForm.append(csrfField);

    const enabledLabel = document.createElement("label");
    enabledLabel.className = "demo-chat-growth-toggle";
    const enabled = document.createElement("input");
    enabled.type = "checkbox";
    enabled.name = "demo_growth_enabled";
    enabled.checked = Boolean(settings.enabled);
    const enabledText = document.createElement("span");
    enabledText.textContent = "تفعيل الزيادة الآلية لهذه الرسالة";
    enabledLabel.append(enabled, enabledText);
    growthForm.append(enabledLabel);

    const durationLabel = document.createElement("label");
    durationLabel.className = "demo-chat-growth-field";
    const durationText = document.createElement("span");
    durationText.textContent = "مدة الزيادة";
    const duration = document.createElement("select");
    duration.name = "demo_growth_duration_hours";
    [[1, "ساعة"], [6, "6 ساعات"], [12, "12 ساعة"], [24, "يوم"], [48, "يومان"], [72, "3 أيام"]].forEach(([value, label]) => {
      const option = document.createElement("option");
      option.value = String(value);
      option.textContent = label;
      option.selected = Number(settings.duration_hours || 24) === Number(value);
      duration.append(option);
    });
    durationLabel.append(durationText, duration);
    growthForm.append(durationLabel);

    const addNumberField = (name, labelText, value, min, max) => {
      const label = document.createElement("label");
      label.className = "demo-chat-growth-field";
      const text = document.createElement("span");
      text.textContent = labelText;
      const number = document.createElement("input");
      number.type = "number";
      number.name = name;
      number.min = String(min);
      number.max = String(max);
      number.required = true;
      number.value = String(value ?? min);
      label.append(text, number);
      growthForm.append(label);
    };
    addNumberField("demo_growth_interval_min_seconds", "أقل فاصل (ثانية)", settings.interval_min_seconds ?? 5, 1, 15);
    addNumberField("demo_growth_interval_max_seconds", "أعلى فاصل (ثانية)", settings.interval_max_seconds ?? 15, 1, 15);
    addNumberField("demo_growth_step_min", "أقل زيادة في المرة", settings.step_min ?? 1, 1, 5);
    addNumberField("demo_growth_step_max", "أعلى زيادة في المرة", settings.step_max ?? 5, 1, 5);
    addNumberField("demo_like_percent", "👍 الإعجاب %", settings.like_percent ?? 30, 0, 100);
    addNumberField("demo_heart_percent", "❤️ القلب %", settings.heart_percent ?? 40, 0, 100);
    addNumberField("demo_fire_percent", "🔥 النار %", settings.fire_percent ?? 15, 0, 100);
    addNumberField("demo_clap_percent", "👏 التصفيق %", settings.clap_percent ?? 10, 0, 100);
    addNumberField("demo_dislike_percent", "👎 عدم الإعجاب %", settings.dislike_percent ?? 5, 0, 100);

    const save = document.createElement("button");
    save.type = "submit";
    save.className = "demo-chat-growth-save";
    save.textContent = "حفظ الإعدادات";
    growthForm.append(save);
    growthForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      save.disabled = true;
      if (error) error.hidden = true;
      try {
        const response = await fetch(growthForm.action, {
          method: "POST",
          body: new FormData(growthForm),
          headers: { Accept: "application/json", "X-Requested-With": "XMLHttpRequest" },
          credentials: "same-origin",
        });
        const result = await response.json();
        if (!response.ok || !result.ok) throw new Error(result.error || "تعذر حفظ إعدادات الزيادة.");
        message.demo_growth_settings = result.message.demo_growth_settings;
        Object.assign(settings, message.demo_growth_settings);
        enabled.checked = Boolean(settings.enabled);
        updateSummary();
      } catch (saveError) {
        if (error) {
          error.textContent = saveError.message || "تعذر حفظ إعدادات الزيادة.";
          error.hidden = false;
        }
      } finally {
        save.disabled = false;
      }
    });
    details.append(growthForm);
    card.append(details);
  };

  const addMessage = (message) => {
    if (!message?.id || list.querySelector(`[data-message-id="${Number(message.id)}"]`)) return;
    const followLatest = transcript.scrollHeight - transcript.scrollTop - transcript.clientHeight < 100;
    list.querySelector("[data-demo-chat-empty]")?.remove();
    const item = document.createElement("li");
    item.className = `demo-chat-message${message.is_demo ? " is-demo" : ""}`;
    item.dataset.messageId = String(message.id);
    const card = document.createElement("article");
    card.className = "demo-chat-message-card";
    const header = document.createElement("header");
    const sender = document.createElement("strong");
    sender.textContent = message.sender || "عضو";
    header.append(sender);
    if (message.is_demo) {
      const badge = document.createElement("span");
      badge.className = "demo-chat-message-badge";
      badge.textContent = "تجريبي";
      header.append(badge);
    } else if (message.sender_is_admin) {
      const badge = document.createElement("span");
      badge.className = "demo-chat-admin-badge";
      badge.textContent = "مشرف";
      header.append(badge);
    }
    const time = document.createElement("time");
    time.textContent = String(message.created_at || "").slice(11, 16);
    header.append(time);
    card.append(header);
    if (message.text) {
      const text = document.createElement("p");
      text.textContent = message.text;
      card.append(text);
    }
    if (message.media_url && (message.image || message.attachment)) {
      const link = document.createElement("a");
      link.href = message.media_url;
      link.textContent = message.image ? "صورة مرفقة" : message.attachment_name || "ملف مرفق";
      if (message.image) {
        link.target = "_blank";
        link.rel = "noopener noreferrer";
      }
      card.append(link);
    }
    appendGrowthControls(card, message);
    item.append(card);
    list.append(item);
    lastMessageId = Math.max(lastMessageId, Number(message.id));
    root.dataset.lastMessageId = String(lastMessageId);
    if (followLatest) transcript.scrollTop = transcript.scrollHeight;
  };

  const loadNewMessages = async () => {
    try {
      const url = new URL(root.dataset.historyUrl, window.location.href);
      url.searchParams.set("after", String(lastMessageId));
      const response = await fetch(url, { credentials: "same-origin", cache: "no-store", headers: { Accept: "application/json" } });
      if (!response.ok) return;
      const payload = await response.json();
      if (payload.ok) payload.messages.forEach(addMessage);
    } catch {
      // A later poll will retry if the connection is temporarily unavailable.
    }
  };

  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = input?.value.trim() || "";
    if (!text || sending) return;
    sending = true;
    if (submitButton) submitButton.disabled = true;
    if (error) error.hidden = true;
    try {
      const response = await fetch(form.action, {
        method: "POST",
        credentials: "same-origin",
        headers: { Accept: "application/json", "X-CSRFToken": csrf },
        body: new URLSearchParams({ text }),
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.error || "تعذر إرسال الرسالة.");
      addMessage(payload.message);
      input.value = "";
      input.focus();
    } catch (sendError) {
      if (error) {
        error.textContent = sendError.message || "تعذر إرسال الرسالة.";
        error.hidden = false;
      }
    } finally {
      sending = false;
      if (submitButton) submitButton.disabled = false;
    }
  });

  try {
    const initialMessages = JSON.parse(document.querySelector("#demo-chat-initial-messages")?.textContent || "[]");
    initialMessages.forEach(addMessage);
  } catch {
    lastMessageId = Number(root.dataset.lastMessageId || 0);
  }
  window.requestAnimationFrame(() => { transcript.scrollTop = transcript.scrollHeight; });
  window.setInterval(loadNewMessages, 2000);
})();
