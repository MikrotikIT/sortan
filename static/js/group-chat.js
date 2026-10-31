(() => {
  const root = document.querySelector("[data-chat-room]");
  const list = root?.querySelector("[data-chat-messages]");
  const listViewport = root?.querySelector(".chat-message-list-wrap");
  if (!root || !list || !listViewport) return;

  const status = root.querySelector("[data-chat-status]");
  const historyStatus = root.querySelector("[data-chat-history-status]");
  const errorBox = root.querySelector("[data-chat-error]");
  const userId = Number(root.dataset.currentUser);
  const canModerate = root.dataset.canModerate === "true";
  const canPost = root.dataset.canPost === "true";
  const canReact = root.dataset.canReact === "true";
  const isAdmin = root.dataset.isAdmin === "true";
  const demoGrowthUrlTemplate = root.dataset.demoGrowthUrlTemplate || "";
  const readUrl = root.dataset.readUrl || "";
  const compose = root.querySelector("[data-chat-compose]");
  const messageInput = compose?.querySelector('textarea[name="text"]');
  const attachmentInputs = [...(compose?.querySelectorAll('.chat-attachment-options input[type="file"]') || [])];
  const attachmentPreview = compose?.querySelector("[data-attachment-preview]");
  const attachmentPreviewItems = compose?.querySelector("[data-attachment-preview-items]");
  const composeSendButton = compose?.querySelector("[data-compose-send]");
  const attachmentSendButton = compose?.querySelector("[data-attachment-send]");
  const replyIdInput = compose?.querySelector("[data-reply-id]");
  const replyPreview = compose?.querySelector("[data-reply-preview]");
  const replySender = compose?.querySelector("[data-reply-sender]");
  const replyText = compose?.querySelector("[data-reply-text]");
  const glyphs = { like: "👍", heart: "❤️", fire: "🔥", clap: "👏", dislike: "👎" };
  const labels = { like: "إعجاب", heart: "قلب", fire: "نار", clap: "تصفيق", dislike: "عدم إعجاب" };
  let socket;
  let reconnectTimer;
  let retryCount = 0;
  let manuallyClosed = false;
  let lastReadMessageId = 0;
  let hasOlderMessages = root.dataset.hasOlderMessages === "true";
  let loadingOlderMessages = false;

  const escapeText = (value) => String(value ?? "");
  const markMessageRead = async (messageId) => {
    const id = Number(messageId);
    const csrf = compose?.querySelector('[name="csrfmiddlewaretoken"]')?.value;
    if (!readUrl || isAdmin || !csrf || !Number.isSafeInteger(id) || id <= lastReadMessageId) return;
    lastReadMessageId = id;
    try {
      const response = await fetch(readUrl, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Accept": "application/json", "X-CSRFToken": csrf },
        body: new URLSearchParams({ message_id: String(id) }),
      });
      if (!response.ok && lastReadMessageId === id) lastReadMessageId = 0;
    } catch {
      if (lastReadMessageId === id) lastReadMessageId = 0;
    }
  };
  const messageDateInfo = (message) => {
    const stamp = String(message.created_at || "");
    const match = stamp.match(/^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})/);
    return {
      day: message.created_day || match?.[1] || "",
      time: message.created_time || match?.[2] || stamp,
    };
  };

  const dayDividerLabel = (dayKey) => {
    const match = dayKey.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (!match) return dayKey;
    const [, yearText, monthText, dayText] = match;
    const year = Number(yearText);
    const month = Number(monthText);
    const day = Number(dayText);
    const today = new Date();
    const dayNumber = Date.UTC(year, month - 1, day);
    const todayNumber = Date.UTC(today.getFullYear(), today.getMonth(), today.getDate());
    const difference = Math.round((todayNumber - dayNumber) / 86400000);
    if (difference === 0) return "اليوم";
    if (difference === 1) return "أمس";
    const date = new Date(year, month - 1, day);
    const options = { calendar: "gregory", day: "numeric", month: "long" };
    if (year !== today.getFullYear()) options.year = "numeric";
    return new Intl.DateTimeFormat("ar", options).format(date);
  };

  const createDayDivider = (day) => {
    const divider = document.createElement("li");
    divider.className = "chat-day-divider";
    divider.dataset.day = day;
    const label = document.createElement("span");
    label.textContent = dayDividerLabel(day);
    divider.append(label);
    return divider;
  };

  const syncDayDividers = () => {
    [...list.children].filter((item) => item.classList.contains("chat-day-divider")).forEach((item) => item.remove());
    let previousDay = null;
    [...list.children].filter((item) => item.hasAttribute("data-message-id")).forEach((messageItem) => {
      const day = messageItem.dataset.messageDay || "";
      if (day && day !== previousDay) list.insertBefore(createDayDivider(day), messageItem);
      previousDay = day;
    });
  };

  const syncLastDayDivider = () => {
    const messages = [...list.children].filter((item) => item.hasAttribute("data-message-id"));
    const current = messages[messages.length - 1];
    if (!current) return;
    const day = current.dataset.messageDay || "";
    const previousDay = messages[messages.length - 2]?.dataset.messageDay || "";
    if (!day || day === previousDay) return;
    const adjacentDivider = current.previousElementSibling;
    if (adjacentDivider?.classList.contains("chat-day-divider") && adjacentDivider.dataset.day === day) return;
    list.insertBefore(createDayDivider(day), current);
  };

  const createSvgIcon = (className, paths, circles = []) => {
    const namespace = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(namespace, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");
    if (className) svg.setAttribute("class", className);
    paths.forEach((data) => {
      const path = document.createElementNS(namespace, "path");
      path.setAttribute("d", data);
      svg.append(path);
    });
    circles.forEach(({ cx, cy, r }) => {
      const circle = document.createElementNS(namespace, "circle");
      circle.setAttribute("cx", String(cx));
      circle.setAttribute("cy", String(cy));
      circle.setAttribute("r", String(r));
      svg.append(circle);
    });
    return svg;
  };

  const positionReactionMenu = (picker) => {
    if (!picker.open) return;
    const trigger = picker.querySelector("summary");
    const options = picker.querySelector(".chat-reaction-options");
    if (!trigger || !options) return;
    const anchor = trigger.getBoundingClientRect();
    const menu = options.getBoundingClientRect();
    const padding = 10;
    const viewportWidth = document.documentElement.clientWidth || window.innerWidth;
    const viewportHeight = window.innerHeight;
    let left = anchor.left;
    if (left + menu.width > viewportWidth - padding) left = anchor.right - menu.width;
    left = Math.min(Math.max(padding, left), Math.max(padding, viewportWidth - menu.width - padding));
    let top = anchor.top - menu.height - 8;
    if (top < padding) top = anchor.bottom + 8;
    top = Math.min(Math.max(padding, top), Math.max(padding, viewportHeight - menu.height - padding));
    options.style.left = `${left}px`;
    options.style.top = `${top}px`;
  };

  const positionMessageActionMenu = (menu) => {
    if (!menu.open) return;
    const trigger = menu.querySelector("summary");
    const options = menu.querySelector(".chat-message-action-options");
    if (!trigger || !options) return;
    const anchor = trigger.getBoundingClientRect();
    const panel = options.getBoundingClientRect();
    const padding = 8;
    const viewportWidth = document.documentElement.clientWidth || window.innerWidth;
    const viewportHeight = window.innerHeight;
    let left = anchor.left;
    if (left + panel.width > viewportWidth - padding) left = anchor.right - panel.width;
    left = Math.min(Math.max(padding, left), Math.max(padding, viewportWidth - panel.width - padding));
    let top = anchor.bottom + 5;
    if (top + panel.height > viewportHeight - padding) top = anchor.top - panel.height - 5;
    top = Math.min(Math.max(padding, top), Math.max(padding, viewportHeight - panel.height - padding));
    options.style.left = `${left}px`;
    options.style.top = `${top}px`;
  };

  const copyTextToClipboard = async (value) => {
    if (navigator.clipboard?.writeText) {
      try {
        await navigator.clipboard.writeText(value);
        return;
      } catch { /* Fall back to a temporary selection for browsers with restricted clipboard access. */ }
    }
    const field = document.createElement("textarea");
    field.value = value;
    field.setAttribute("readonly", "");
    field.style.position = "fixed";
    field.style.opacity = "0";
    document.body.append(field);
    field.select();
    const copied = document.execCommand("copy");
    field.remove();
    if (!copied) throw new Error("تعذر نسخ الرسالة.");
  };

  const showCopyFeedback = (card) => {
    let feedback = card.querySelector(".chat-copy-feedback");
    if (!feedback) {
      feedback = document.createElement("small");
      feedback.className = "chat-copy-feedback";
      feedback.setAttribute("role", "status");
      card.append(feedback);
    }
    feedback.textContent = "تم نسخ الرسالة";
    window.clearTimeout(feedback.dismissTimer);
    feedback.dismissTimer = window.setTimeout(() => feedback.remove(), 1800);
  };

  const createReactionPicker = (messageId) => {
    const picker = document.createElement("details");
    picker.className = "chat-reaction-picker";
    picker.dataset.reactionPicker = "";
    const toggle = document.createElement("summary");
    toggle.textContent = "+";
    toggle.setAttribute("aria-label", "إضافة تفاعل");
    toggle.title = "إضافة تفاعل";
    picker.append(toggle);
    const options = document.createElement("div");
    options.className = "chat-reaction-options";
    Object.entries(glyphs).forEach(([kind, glyph]) => {
      const option = document.createElement("button");
      option.type = "button";
      option.textContent = glyph;
      option.title = labels[kind];
      option.setAttribute("aria-label", labels[kind]);
      option.addEventListener("click", () => {
        if (sendSocket({ action: "react", message_id: messageId, kind })) picker.open = false;
      });
      options.append(option);
    });
    picker.append(options);
    picker.addEventListener("toggle", () => {
      if (picker.open) window.requestAnimationFrame(() => positionReactionMenu(picker));
      else { options.style.removeProperty("left"); options.style.removeProperty("top"); }
    });
    return picker;
  };

  const isNearLatest = () => listViewport.scrollHeight - listViewport.scrollTop - listViewport.clientHeight < 140;
  const scrollToLatest = (behavior = "auto") => {
    const scroll = () => listViewport.scrollTo({ top: listViewport.scrollHeight, behavior });
    window.requestAnimationFrame(() => {
      scroll();
      window.requestAnimationFrame(scroll);
    });
  };

  const resizeMessageInput = () => {
    if (!messageInput) return;
    messageInput.style.height = "auto";
    messageInput.style.height = `${Math.min(messageInput.scrollHeight, 132)}px`;
    messageInput.style.overflowY = messageInput.scrollHeight > 132 ? "auto" : "hidden";
  };

  let previewObjectUrls = [];
  const refreshAttachmentPreview = () => {
    previewObjectUrls.forEach((url) => URL.revokeObjectURL(url));
    previewObjectUrls = [];
    if (!attachmentPreview || !attachmentPreviewItems) return;
    attachmentPreviewItems.replaceChildren();
    const selectedFiles = attachmentInputs.flatMap((input) => [...(input.files || [])]);
    attachmentPreview.hidden = selectedFiles.length === 0;
    if (composeSendButton) composeSendButton.hidden = selectedFiles.length > 0;
    selectedFiles.forEach((file) => {
      const item = document.createElement("div");
      item.className = "chat-attachment-preview-item";
      if (file.type.startsWith("image/")) {
        const image = document.createElement("img");
        const objectUrl = URL.createObjectURL(file);
        previewObjectUrls.push(objectUrl);
        image.src = objectUrl;
        image.alt = `معاينة ${file.name}`;
        item.append(image);
      } else {
        const icon = document.createElement("span");
        icon.className = "chat-attachment-preview-icon";
        icon.append(createSvgIcon("", ["M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z", "M14 2v6h6", "M8 13h8", "M8 17h8"]));
        item.append(icon);
      }
      const details = document.createElement("div");
      details.className = "chat-attachment-preview-details";
      const name = document.createElement("strong");
      name.textContent = file.name;
      const size = document.createElement("small");
      const bytes = Number(file.size || 0);
      size.textContent = bytes < 1024 * 1024
        ? `${Math.max(1, Math.round(bytes / 1024))} كيلوبايت`
        : `${(bytes / (1024 * 1024)).toFixed(1)} ميغابايت`;
      details.append(name, size);
      item.append(details);
      attachmentPreviewItems.append(item);
    });
  };

  const clearSelectedAttachments = () => {
    attachmentInputs.forEach((input) => { input.value = ""; });
    refreshAttachmentPreview();
  };

  const clearReplySelection = () => {
    if (replyIdInput) replyIdInput.value = "";
    if (replyPreview) replyPreview.hidden = true;
  };

  const selectReplyTarget = (message) => {
    if (!canPost || !compose || !replyIdInput || !replyPreview) return;
    replyIdInput.value = String(message.id);
    if (replySender) replySender.textContent = `رد على ${escapeText(message.sender)}`;
    if (replyText) {
      replyText.textContent = message.text || (message.image ? "صورة مرفقة" : message.attachment ? `ملف مرفق: ${message.attachment_name || "ملف"}` : "رسالة");
    }
    replyPreview.hidden = false;
    compose.querySelector('textarea[name="text"]')?.focus();
  };

  const appendAdminDemoControls = (card, message) => {
    if (!isAdmin || !demoGrowthUrlTemplate) return;
    const settings = message.demo_growth_settings || {};
    const details = document.createElement("details");
    details.className = "chat-demo-admin-settings";
    const summary = document.createElement("summary");
    summary.textContent = settings.enabled ? "إدارة الزيادة التجريبية · مفعّلة" : "إدارة الزيادة التجريبية";
    details.append(summary);

    const note = document.createElement("p");
    note.textContent = "هذه الإعدادات للإدارة فقط. الزيادة تجريبية، وإيقافها لا يغلق تفاعلات الأعضاء الحقيقية.";
    details.append(note);

    const form = document.createElement("form");
    form.className = "chat-demo-admin-form";
    form.method = "post";
    form.action = demoGrowthUrlTemplate.replace(/\/0\/demo-growth\/?$/, `/${Number(message.id)}/demo-growth/`);
    const csrf = compose?.querySelector('[name="csrfmiddlewaretoken"]')?.value;
    if (csrf) {
      const csrfInput = document.createElement("input");
      csrfInput.type = "hidden";
      csrfInput.name = "csrfmiddlewaretoken";
      csrfInput.value = csrf;
      form.append(csrfInput);
    }

    const enabledLabel = document.createElement("label");
    enabledLabel.className = "chat-demo-admin-toggle";
    const enabled = document.createElement("input");
    enabled.type = "checkbox";
    enabled.name = "demo_growth_enabled";
    enabled.checked = Boolean(settings.enabled);
    const enabledText = document.createElement("span");
    enabledText.textContent = "تفعيل الزيادة الآلية لهذه الرسالة";
    enabledLabel.append(enabled, enabledText);
    form.append(enabledLabel);

    const addNumberField = (name, labelText, value, min, max) => {
      const label = document.createElement("label");
      label.className = "chat-demo-admin-field";
      const text = document.createElement("span");
      text.textContent = labelText;
      const input = document.createElement("input");
      input.type = "number";
      input.name = name;
      input.min = String(min);
      input.max = String(max);
      input.required = true;
      input.value = String(value ?? min);
      label.append(text, input);
      form.append(label);
    };

    const durationLabel = document.createElement("label");
    durationLabel.className = "chat-demo-admin-field";
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
    form.append(durationLabel);

    addNumberField("demo_growth_interval_min_seconds", "أقل فاصل (ثانية)", settings.interval_min_seconds, 1, 15);
    addNumberField("demo_growth_interval_max_seconds", "أعلى فاصل (ثانية)", settings.interval_max_seconds, 1, 15);
    addNumberField("demo_growth_step_min", "أقل زيادة في المرة", settings.step_min, 1, 5);
    addNumberField("demo_growth_step_max", "أعلى زيادة في المرة", settings.step_max, 1, 5);
    addNumberField("demo_like_percent", "👍 الإعجاب %", settings.like_percent, 0, 100);
    addNumberField("demo_heart_percent", "❤️ القلب %", settings.heart_percent, 0, 100);
    addNumberField("demo_fire_percent", "🔥 النار %", settings.fire_percent, 0, 100);
    addNumberField("demo_clap_percent", "👏 التصفيق %", settings.clap_percent, 0, 100);
    addNumberField("demo_dislike_percent", "👎 عدم الإعجاب %", settings.dislike_percent, 0, 100);

    const submit = document.createElement("button");
    submit.type = "submit";
    submit.className = "chat-demo-admin-save";
    submit.textContent = settings.enabled ? "حفظ أو إيقاف الزيادة" : "حفظ أو تفعيل الزيادة";
    enabled.addEventListener("change", () => {
      submit.textContent = enabled.checked ? "حفظ أو تفعيل الزيادة" : "حفظ أو إيقاف الزيادة";
    });
    form.append(submit);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      submit.disabled = true;
      try {
        const response = await fetch(form.action, {
          method: "POST",
          body: new FormData(form),
          headers: { "Accept": "application/json", "X-Requested-With": "XMLHttpRequest" },
          credentials: "same-origin",
        });
        const result = await response.json();
        if (!response.ok || !result.ok) throw new Error(result.error || "تعذر حفظ إعدادات الزيادة.");
        renderMessage(result.message);
      } catch (error) {
        showError(error.message || "تعذر حفظ إعدادات الزيادة.");
      } finally {
        submit.disabled = false;
      }
    });
    details.append(form);
    card.append(details);
  };

  const renderReactions = (container, message) => {
    container.replaceChildren();
    if (!canReact || !message.reactions_enabled) return;
    (message.reactions || []).filter((reaction) => Number(reaction.count || 0) > 0).forEach((reaction) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `chat-reaction${message.user_reaction === reaction.kind ? " is-selected" : ""}`;
      button.dataset.reactionKind = reaction.kind;
      button.setAttribute("aria-label", `${labels[reaction.kind]}: ${reaction.count || 0}`);
      button.title = `حقيقي: ${reaction.real_count || 0} · تجريبي: ${reaction.demo_count || 0}`;
      const glyph = document.createElement("span");
      glyph.textContent = glyphs[reaction.kind] || "•";
      const count = document.createElement("b");
      count.textContent = String(reaction.count || 0);
      button.append(glyph, count);
      if (reaction.demo_count) {
        const demo = document.createElement("small");
        demo.textContent = `تجريبي +${reaction.demo_count}`;
        button.append(demo);
      }
      button.addEventListener("click", () => sendSocket({ action: "react", message_id: message.id, kind: reaction.kind }));
      container.append(button);
    });
    container.append(createReactionPicker(message.id));
  };

  const renderMessage = (message, { prepend = false } = {}) => {
    if (!message || !message.id) return;
    const previous = list.querySelector(`[data-message-id="${Number(message.id)}"]`);
    const item = document.createElement("li");
    item.className = `chat-message${Number(message.sender_id) === userId ? " is-mine" : ""}`;
    item.dataset.messageId = String(message.id);
    const dateInfo = messageDateInfo(message);
    item.dataset.messageDay = dateInfo.day;
    const card = document.createElement("article");
    card.className = "chat-message-card";

    const header = document.createElement("header");
    header.className = "chat-message-header";
    const author = document.createElement("strong");
    author.textContent = escapeText(message.sender);
    author.title = escapeText(message.sender);
    const time = document.createElement("time");
    time.textContent = escapeText(dateInfo.time);
    if (dateInfo.day && dateInfo.time) time.dateTime = `${dateInfo.day}T${dateInfo.time}`;
    header.append(author, time);
    if (message.edited) {
      const edited = document.createElement("small");
      edited.className = "chat-edited-label";
      edited.textContent = "معدّلة";
      header.append(edited);
    }
    const ownMessage = Number(message.sender_id) === userId;
    const tools = document.createElement("div");
    tools.className = "chat-message-tools";
    const actionMenu = document.createElement("details");
    actionMenu.className = "chat-message-actions-menu";
    actionMenu.dataset.messageActionsMenu = "";
    const menuToggle = document.createElement("summary");
    menuToggle.setAttribute("aria-label", "خيارات الرسالة");
    menuToggle.title = "خيارات الرسالة";
    menuToggle.append(createSvgIcon("chat-message-menu-icon", [], [
      { cx: 12, cy: 5, r: 1.5 },
      { cx: 12, cy: 12, r: 1.5 },
      { cx: 12, cy: 19, r: 1.5 },
    ]));
    const menuOptions = document.createElement("div");
    menuOptions.className = "chat-message-action-options";
    const addMessageAction = (label, className, onClick) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = className || "";
      button.textContent = label;
      button.addEventListener("click", onClick);
      menuOptions.append(button);
    };

    if (ownMessage && message.text) {
      addMessageAction("تعديل", "", () => {
        actionMenu.open = false;
        const updated = window.prompt("تعديل الرسالة", message.text);
        if (updated !== null) sendSocket({ action: "edit", message_id: message.id, text: updated });
      });
    }
    if (ownMessage || canModerate) {
      addMessageAction("حذف", "is-danger", () => {
        actionMenu.open = false;
        if (window.confirm("حذف هذه الرسالة؟")) sendSocket({ action: "delete", message_id: message.id });
      });
    }
    addMessageAction("نسخ", "", async () => {
      const value = message.text || (message.media_url ? new URL(message.media_url, window.location.origin).href : "");
      if (!value) {
        actionMenu.open = false;
        showError("لا يوجد محتوى لنسخه.");
        return;
      }
      try {
        await copyTextToClipboard(value);
        actionMenu.open = false;
        showCopyFeedback(card);
      } catch (error) {
        showError(error.message || "تعذر نسخ الرسالة.");
      }
    });
    actionMenu.append(menuToggle, menuOptions);
    actionMenu.addEventListener("toggle", () => {
      if (actionMenu.open) window.requestAnimationFrame(() => positionMessageActionMenu(actionMenu));
      else { menuOptions.style.removeProperty("left"); menuOptions.style.removeProperty("top"); }
    });
    tools.append(actionMenu);
    card.classList.add("has-message-tools");
    header.append(tools);
    card.append(header);

    if (message.reply_to) {
      const quote = document.createElement(message.reply_to.deleted ? "div" : "button");
      quote.className = `chat-reply-quote${message.reply_to.deleted ? " is-deleted" : ""}`;
      quote.dataset.replyTargetId = String(message.reply_to.id);
      if (!message.reply_to.deleted) {
        quote.type = "button";
        quote.addEventListener("click", () => {
          const target = list.querySelector(`[data-message-id="${Number(message.reply_to.id)}"]`);
          if (!target) return;
          target.scrollIntoView({ behavior: "smooth", block: "center" });
          target.classList.add("is-reply-target");
          window.setTimeout(() => target.classList.remove("is-reply-target"), 1800);
        });
      }
      quote.textContent = `${escapeText(message.reply_to.sender)}: ${escapeText(message.reply_to.preview)}${message.reply_to.deleted ? " · الرسالة الأصلية محذوفة" : ""}`;
      card.append(quote);
    }

    if (message.text) {
      const body = document.createElement("p");
      body.className = "chat-message-text";
      body.textContent = escapeText(message.text);
      card.append(body);
    }
    if (message.image && message.media_url) {
      const imageLink = document.createElement("a");
      imageLink.className = "chat-message-image-link";
      imageLink.href = message.media_url;
      imageLink.target = "_blank";
      imageLink.rel = "noopener noreferrer";
      const image = document.createElement("img");
      image.src = message.media_url;
      image.alt = "صورة مرفقة";
      image.loading = "lazy";
      imageLink.append(image);
      card.append(imageLink);
    } else if (message.attachment && message.media_url) {
      const attachment = document.createElement("a");
      attachment.className = "chat-message-attachment";
      attachment.href = message.media_url;
      const icon = createSvgIcon("chat-message-attachment-icon", ["M21.44 11.05 12.25 20.24a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.82-2.83l8.49-8.48"]);
      const name = document.createElement("span");
      name.textContent = escapeText(message.attachment_name || "تنزيل الملف");
      attachment.append(icon, name);
      attachment.setAttribute("download", "");
      card.append(attachment);
    }

    if (message.demo_growth_active || message.demo_reactions_present) {
      const note = document.createElement("small");
      note.className = "chat-demo-note";
      note.textContent = message.demo_growth_active
        ? "تتضمن هذه الرسالة محاكاة تفاعلات تجريبية. التفاعل الحقيقي متاح دائماً."
        : "تتضمن الأعداد محاكاة تجريبية؛ التفاعل الحقيقي متاح دائماً.";
      card.append(note);
    }
    appendAdminDemoControls(card, message);
    const reactions = document.createElement("div");
    reactions.className = "chat-reactions";
    renderReactions(reactions, message);
    const footer = document.createElement("div");
    footer.className = "chat-message-footer";
    if (canPost) {
      const reply = document.createElement("button");
      reply.type = "button";
      reply.className = "chat-reply-action";
      reply.textContent = "رد";
      reply.addEventListener("click", () => selectReplyTarget(message));
      footer.append(reply);
    }
    if (reactions.childElementCount) footer.append(reactions);
    if (footer.childElementCount) card.append(footer);
    item.append(card);
    if (previous) previous.replaceWith(item);
    else if (prepend) list.prepend(item);
    else list.append(item);
    return item;
  };

  const loadOlderMessages = async () => {
    if (!hasOlderMessages || loadingOlderMessages) return;
    const firstMessage = list.querySelector("[data-message-id]");
    const beforeId = firstMessage?.dataset.messageId;
    if (!beforeId) return;

    loadingOlderMessages = true;
    const originalTop = firstMessage.getBoundingClientRect().top;
    if (historyStatus) {
      historyStatus.hidden = false;
      historyStatus.classList.remove("is-error", "is-end");
      historyStatus.textContent = "جارٍ تحميل الرسائل الأقدم…";
    }
    try {
      const url = new URL(root.dataset.historyUrl, window.location.origin);
      url.searchParams.set("before", beforeId);
      const response = await fetch(url, {
        credentials: "same-origin",
        cache: "no-store",
        headers: { "Accept": "application/json" },
      });
      const result = await response.json();
      if (!response.ok || !result.ok) throw new Error(result.error || "تعذر تحميل الرسائل الأقدم.");

      const olderMessages = result.messages || [];
      hasOlderMessages = Boolean(result.has_more);
      [...olderMessages].reverse().forEach((message) => renderMessage(message, { prepend: true }));
      syncDayDividers();
      if (historyStatus) {
        historyStatus.hidden = true;
        if (!hasOlderMessages) {
          historyStatus.textContent = "وصلت إلى بداية المحادثة";
          historyStatus.classList.add("is-end");
          historyStatus.hidden = false;
          window.setTimeout(() => { historyStatus.hidden = true; }, 2400);
        }
      }

      if (olderMessages.length) {
        window.requestAnimationFrame(() => {
          const preservedMessage = list.querySelector(`[data-message-id="${Number(beforeId)}"]`);
          if (preservedMessage) {
            listViewport.scrollTop += preservedMessage.getBoundingClientRect().top - originalTop;
          }
        });
      }
    } catch (error) {
      if (historyStatus) {
        historyStatus.textContent = error.message || "تعذر تحميل الرسائل الأقدم.";
        historyStatus.classList.add("is-error");
        historyStatus.hidden = false;
        window.setTimeout(() => { historyStatus.hidden = true; }, 3000);
      }
    } finally {
      loadingOlderMessages = false;
    }
  };

  const sendSocket = (data) => {
    if (socket?.readyState !== WebSocket.OPEN) {
      showError("انقطع الاتصال بالمحادثة. أعد المحاولة بعد عودة الاتصال.");
      return false;
    }
    socket.send(JSON.stringify(data));
    return true;
  };

  const showError = (message) => {
    if (!errorBox) return;
    errorBox.textContent = message;
    errorBox.hidden = false;
    window.setTimeout(() => { errorBox.hidden = true; }, 6000);
  };

  const updateReactionCounts = (payload) => {
    const messageItem = list.querySelector(`[data-message-id="${Number(payload.message_id)}"]`);
    if (!messageItem) return;
    const container = messageItem.querySelector(".chat-reactions");
    if (!container || !canReact) return;
    let selectedKind = container.querySelector("[data-reaction-kind].is-selected")?.dataset.reactionKind || null;
    if (Object.prototype.hasOwnProperty.call(payload, "user_reaction")) {
      selectedKind = payload.user_reaction;
    } else if (Number(payload.actor_id) === userId) {
      selectedKind = payload.actor_reaction;
    }
    (payload.reactions || []).forEach((reaction) => {
      const total = Number(reaction.count || 0);
      let button = container.querySelector(`[data-reaction-kind="${reaction.kind}"]`);
      if (total <= 0) {
        button?.remove();
        return;
      }
      if (!button) {
        button = document.createElement("button");
        button.type = "button";
        button.className = "chat-reaction";
        button.dataset.reactionKind = reaction.kind;
        const glyph = document.createElement("span");
        glyph.textContent = glyphs[reaction.kind] || "•";
        const count = document.createElement("b");
        button.append(glyph, count);
        button.addEventListener("click", () => sendSocket({ action: "react", message_id: payload.message_id, kind: reaction.kind }));
      }
      button.classList.toggle("is-selected", selectedKind === reaction.kind);
      const count = button.querySelector("b");
      if (count) count.textContent = String(total);
      button.title = `حقيقي: ${reaction.real_count || 0} · تجريبي: ${reaction.demo_count || 0}`;
      button.setAttribute("aria-label", `${labels[reaction.kind]}: ${total}`);
      let demo = button.querySelector("small");
      if (reaction.demo_count) {
        if (!demo) { demo = document.createElement("small"); button.append(demo); }
        demo.textContent = `تجريبي +${reaction.demo_count}`;
      } else if (demo) demo.remove();
      const picker = container.querySelector("[data-reaction-picker]");
      container.insertBefore(button, picker || null);
    });
    if (!container.querySelector("[data-reaction-picker]")) {
      container.append(createReactionPicker(Number(payload.message_id)));
    }
  };

  const updateMemberCount = (payload) => {
    const total = Number(payload.actual_member_count || 0) + Number(payload.demo_member_offset || 0);
    root.dataset.memberCount = String(payload.actual_member_count || 0);
    root.dataset.demoMemberOffset = String(payload.demo_member_offset || 0);
    root.querySelectorAll("[data-room-member-count]").forEach((node) => { node.textContent = String(total); });
  };

  let pollingStats = false;
  const refreshLiveStats = async () => {
    if (pollingStats || document.visibilityState !== "visible") return;
    const endpoint = root.dataset.chatLiveStatsUrl;
    if (!endpoint) return;
    const messageIds = [...list.querySelectorAll("[data-message-id]")]
      .map((node) => node.dataset.messageId)
      .filter(Boolean)
      .slice(-100);
    const params = new URLSearchParams({
      groups: root.dataset.groupId || "",
      messages: messageIds.join(","),
    });
    pollingStats = true;
    try {
      const response = await fetch(`${endpoint}?${params}`, {
        credentials: "same-origin",
        cache: "no-store",
        headers: { "Accept": "application/json" },
      });
      if (!response.ok) return;
      const data = await response.json();
      data.groups?.forEach(updateMemberCount);
      data.messages?.forEach((message) => updateReactionCounts({ ...message, message_id: message.id }));
    } catch { /* WebSocket updates remain active if the polling fallback is unavailable. */ }
    finally { pollingStats = false; }
  };

  const connect = () => {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    socket = new WebSocket(`${protocol}//${window.location.host}${root.dataset.wsPath}`);
    socket.addEventListener("open", () => {
      retryCount = 0;
      if (status) {
        status.textContent = "متصل";
        status.title = "المحادثة متصلة مباشرة";
        status.classList.add("is-connected");
      }
    });
    socket.addEventListener("message", (event) => {
      let payload;
      try { payload = JSON.parse(event.data); } catch { return; }
      if (payload.type === "ready") return;
      if (payload.type === "error") { showError(payload.message || "تعذر تنفيذ الإجراء."); return; }
      if (payload.type === "message_accepted") { compose?.reset(); clearReplySelection(); return; }
      if (payload.type === "access_revoked" || payload.type === "group_closed") {
        manuallyClosed = true;
        if (status) status.textContent = payload.message || "تم إيقاف المجموعة";
        compose?.querySelectorAll("input,textarea,button").forEach((control) => { control.disabled = true; });
        socket.close();
        window.setTimeout(() => window.location.reload(), 900);
        return;
      }
      if (payload.type === "message_created" || payload.type === "message_updated") {
        const followLatest = isNearLatest() || Number(payload.message?.sender_id) === userId;
        renderMessage(payload.message);
        if (payload.type === "message_created" && followLatest && document.visibilityState === "visible") {
          markMessageRead(payload.message?.id);
        }
        if (payload.type === "message_created") syncLastDayDivider();
        if (payload.type === "message_created" && followLatest) scrollToLatest("smooth");
      } else if (payload.type === "message_deleted") {
        const deletedId = Number(payload.message_id);
        if (replyIdInput?.value === String(deletedId)) {
          clearReplySelection();
          showError("حُذفت الرسالة التي كنت ترد عليها. اختر رسالة أخرى.");
        }
        list.querySelectorAll(`[data-reply-target-id="${deletedId}"]`).forEach((quote) => {
          quote.classList.add("is-deleted");
          quote.textContent += " · الرسالة الأصلية محذوفة";
          if (quote instanceof HTMLButtonElement) quote.disabled = true;
        });
        list.querySelector(`[data-message-id="${deletedId}"]`)?.remove();
        syncDayDividers();
      } else if (payload.type === "reaction_updated") {
        updateReactionCounts(payload);
      } else if (payload.type === "group_stats") {
        updateMemberCount(payload);
      }
    });
    socket.addEventListener("close", () => {
      if (status) {
        status.textContent = "التحديث الفوري غير متصل";
        status.title = "يمكنك إرسال الرسائل، وسيُعاد الاتصال تلقائياً";
        status.classList.remove("is-connected");
      }
      if (!manuallyClosed) {
        retryCount += 1;
        reconnectTimer = window.setTimeout(connect, Math.min(15000, 1000 * retryCount));
      }
    });
    socket.addEventListener("error", () => socket.close());
  };

  try {
    const initial = JSON.parse(document.getElementById("chat-initial-messages")?.textContent || "[]");
    initial.forEach(renderMessage);
    syncDayDividers();
    scrollToLatest();
  } catch { /* Ignore invalid cached initial data and keep the live room available. */ }

  listViewport.addEventListener("scroll", () => {
    root.querySelectorAll("[data-reaction-picker][open]").forEach((picker) => { picker.open = false; });
    root.querySelectorAll("[data-message-actions-menu][open]").forEach((menu) => { menu.open = false; });
    if (isNearLatest() && document.visibilityState === "visible") {
      const latestMessage = [...list.querySelectorAll("[data-message-id]")].at(-1);
      markMessageRead(latestMessage?.dataset.messageId);
    }
    if (listViewport.scrollTop <= 72) loadOlderMessages();
  }, { passive: true });
  window.addEventListener("resize", () => {
    root.querySelectorAll("[data-reaction-picker][open]").forEach(positionReactionMenu);
    root.querySelectorAll("[data-message-actions-menu][open]").forEach(positionMessageActionMenu);
  });

  compose?.querySelector("[data-reply-cancel]")?.addEventListener("click", clearReplySelection);
  messageInput?.addEventListener("input", resizeMessageInput);
  attachmentInputs.forEach((input) => {
    input.addEventListener("change", () => {
      if (input.files?.length) input.closest("details")?.removeAttribute("open");
      refreshAttachmentPreview();
    });
  });
  compose?.querySelector("[data-attachment-cancel]")?.addEventListener("click", clearSelectedAttachments);
  root.addEventListener("click", (event) => {
    root.querySelectorAll("details[open]").forEach((details) => {
      if (!details.contains(event.target)) details.open = false;
    });
  });
  refreshAttachmentPreview();
  resizeMessageInput();
  compose?.addEventListener("submit", async (event) => {
    event.preventDefault();
    let button = event.submitter instanceof HTMLButtonElement ? event.submitter : null;
    if (!button || button.hidden) button = attachmentPreview?.hidden ? composeSendButton : attachmentSendButton;
    const buttonText = button?.textContent || "إرسال";
    const buttonLabel = button?.getAttribute("aria-label");
    const iconOnlyButton = button?.hasAttribute("data-compose-send");
    if (button) {
      button.disabled = true;
      if (iconOnlyButton) {
        button.classList.add("is-loading");
        button.setAttribute("aria-label", "جارٍ الإرسال…");
      } else {
        button.textContent = "جارٍ الإرسال…";
      }
    }
    if (errorBox) errorBox.hidden = true;
    try {
      const formData = new FormData(compose);
      const response = await fetch(compose.action, {
        method: "POST",
        body: formData,
        headers: { "Accept": "application/json", "X-Requested-With": "XMLHttpRequest" },
        credentials: "same-origin",
      });
      const result = await response.json();
      if (!response.ok || !result.ok) throw new Error(result.error || "تعذر إرسال الرسالة.");
      renderMessage(result.message);
      syncLastDayDivider();
      compose.reset();
      refreshAttachmentPreview();
      clearReplySelection();
      resizeMessageInput();
      scrollToLatest("smooth");
    } catch (error) {
      showError(error.message || "تعذر إرسال الرسالة.");
    } finally {
      if (button) {
        button.disabled = false;
        if (iconOnlyButton) {
          button.classList.remove("is-loading");
          if (buttonLabel) button.setAttribute("aria-label", buttonLabel);
        } else {
          button.textContent = buttonText;
        }
      }
    }
  });

  connect();
  refreshLiveStats();
  const liveStatsTimer = window.setInterval(refreshLiveStats, 3000);
  window.addEventListener("beforeunload", () => {
    manuallyClosed = true;
    window.clearTimeout(reconnectTimer);
    window.clearInterval(liveStatsTimer);
    socket?.close();
  });
})();
