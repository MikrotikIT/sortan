(() => {
  const root = document.querySelector("[data-chat-room]");
  const list = root?.querySelector("[data-chat-messages]");
  const listViewport = root?.querySelector(".chat-message-list-wrap");
  if (!root || !list || !listViewport) return;
  const hlsScriptUrl = new URL("../vendor/hls.min.js", document.currentScript?.src || `${window.location.origin}/static/js/group-chat.js`).href;
  let hlsLoaderPromise = null;

  const status = root.querySelector("[data-chat-status]");
  const historyStatus = root.querySelector("[data-chat-history-status]");
  const errorBox = root.querySelector("[data-chat-error]");
  const userId = Number(root.dataset.currentUser);
  const canModerate = root.dataset.canModerate === "true";
  const canPost = root.dataset.canPost === "true";
  const canReact = root.dataset.canReact === "true";
  const isAdmin = root.dataset.isAdmin === "true";
  const allowVoiceMessages = root.dataset.allowVoiceMessages === "true";
  const demoGrowthUrlTemplate = root.dataset.demoGrowthUrlTemplate || "";
  const demoAccountId = Number(root.dataset.demoAccountId || 0);
  const demoReactionUrlTemplate = root.dataset.demoReactionUrlTemplate || "";
  const readUrl = root.dataset.readUrl || "";
  const compose = root.querySelector("[data-chat-compose]");
  const messageInput = compose?.querySelector('textarea[name="text"]');
  let attachmentInputs = [...(compose?.querySelectorAll('.chat-attachment-options input[type="file"]') || [])];
  const attachmentPreview = compose?.querySelector("[data-attachment-preview]");
  const attachmentPreviewItems = compose?.querySelector("[data-attachment-preview-items]");
  const composeSendButton = compose?.querySelector("[data-compose-send]");
  const attachmentSendButton = compose?.querySelector("[data-attachment-send]");
  const replyIdInput = compose?.querySelector("[data-reply-id]");
  const replyPreview = compose?.querySelector("[data-reply-preview]");
  const replySender = compose?.querySelector("[data-reply-sender]");
  const replyText = compose?.querySelector("[data-reply-text]");
  let recordedAudioFile = null;
  let audioRecorder = null;
  let audioStream = null;
  let audioChunks = [];
  let recordTimer = null;
  let recordingStartedAt = 0;
  let audioRecordButton = null;
  let audioRecordLabel = null;
  if (!demoAccountId && allowVoiceMessages) {
    const composer = compose?.querySelector(".chat-composer");
    if (composer && composeSendButton) {
      audioRecordButton = document.createElement("button");
      audioRecordButton.type = "button";
      audioRecordButton.className = "chat-audio-record-button";
      audioRecordButton.title = "تسجيل رسالة صوتية";
      audioRecordButton.setAttribute("aria-label", "تسجيل رسالة صوتية");
      const microphoneIcon = document.createElement("span");
      microphoneIcon.className = "chat-audio-record-icon";
      microphoneIcon.setAttribute("aria-hidden", "true");
      microphoneIcon.textContent = "🎙";
      audioRecordLabel = document.createElement("span");
      audioRecordLabel.textContent = "صوت";
      audioRecordButton.append(microphoneIcon, audioRecordLabel);
      composer.insertBefore(audioRecordButton, composeSendButton);
    }
  }
  const glyphs = { like: "👍", heart: "❤️", fire: "🔥", clap: "👏", dislike: "👎" };
  const labels = { like: "إعجاب", heart: "قلب", fire: "نار", clap: "تصفيق", dislike: "عدم إعجاب" };
  const allowedReactions = new Set((root.dataset.allowedReactions || "").split(",").filter((kind) => glyphs[kind]));
  let socket;
  let reconnectTimer;
  let retryCount = 0;
  let manuallyClosed = false;
  let lastReadMessageId = 0;
  let hasOlderMessages = root.dataset.hasOlderMessages === "true";
  let loadingOlderMessages = false;
  let historyRequestGeneration = 0;

  const escapeText = (value) => String(value ?? "");
  const clearChildren = (element) => {
    while (element.firstChild) element.removeChild(element.firstChild);
  };
  const markMessageRead = async (messageId) => {
    const id = Number(messageId);
    const csrf = root.querySelector('[name="csrfmiddlewaretoken"]')?.value;
    if (!readUrl || !csrf || !Number.isSafeInteger(id) || id <= lastReadMessageId) return;
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

  const appendMessageTextWithLinks = (container, value) => {
    const text = String(value ?? "");
    const urlPattern = /(?:https?:\/\/|www\.)[^\s<>"']+/gi;
    const trailingPunctuation = /[.,!?;:،؛؟"'»”’]$/u;
    const pairs = [[")", "("], ["]", "["], ["}", "{"]];
    let cursor = 0;
    let match;

    while ((match = urlPattern.exec(text))) {
      let visibleUrl = match[0];
      while (visibleUrl && trailingPunctuation.test(visibleUrl)) visibleUrl = visibleUrl.slice(0, -1);
      pairs.forEach(([closing, opening]) => {
        while (visibleUrl.endsWith(closing)
          && [...visibleUrl].filter((character) => character === closing).length
            > [...visibleUrl].filter((character) => character === opening).length) {
          visibleUrl = visibleUrl.slice(0, -1);
        }
      });

      if (!visibleUrl) continue;
      const start = match.index;
      const end = start + visibleUrl.length;
      container.append(document.createTextNode(text.slice(cursor, start)));

      const destination = visibleUrl.toLowerCase().startsWith("www.") ? `https://${visibleUrl}` : visibleUrl;
      let parsedUrl;
      try {
        parsedUrl = new URL(destination);
      } catch {
        container.append(document.createTextNode(visibleUrl));
        cursor = end;
        continue;
      }
      if (parsedUrl.protocol !== "http:" && parsedUrl.protocol !== "https:") {
        container.append(document.createTextNode(visibleUrl));
        cursor = end;
        continue;
      }

      const linkGroup = document.createElement("span");
      linkGroup.className = "chat-inline-link-copy";
      linkGroup.dir = "ltr";
      const link = document.createElement("a");
      link.className = "chat-message-link";
      link.href = parsedUrl.href;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = visibleUrl;
      link.dir = "ltr";

      const copyButton = document.createElement("button");
      copyButton.type = "button";
      copyButton.className = "chat-link-copy-button";
      copyButton.setAttribute("aria-label", "نسخ الرابط");
      copyButton.title = "نسخ الرابط";
      copyButton.append(createSvgIcon("chat-link-copy-icon", ["M8 8V4h12v12h-4", "M4 8h12v12H4z"]));
      const copyLabel = document.createElement("span");
      copyLabel.className = "chat-link-copy-label";
      copyLabel.textContent = "نسخ";
      copyButton.append(copyLabel);
      copyButton.addEventListener("click", async () => {
        try {
          await copyTextToClipboard(parsedUrl.href);
          copyButton.classList.add("is-copied");
          copyLabel.textContent = "تم النسخ";
          window.clearTimeout(copyButton.resetLabelTimer);
          copyButton.resetLabelTimer = window.setTimeout(() => {
            copyButton.classList.remove("is-copied");
            copyLabel.textContent = "نسخ";
          }, 1800);
        } catch (error) {
          showError(error.message || "تعذر نسخ الرابط.");
        }
      });

      linkGroup.append(link, copyButton);
      container.append(linkGroup);
      cursor = end;
    }

    container.append(document.createTextNode(text.slice(cursor)));
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
    Object.entries(glyphs).filter(([kind]) => allowedReactions.has(kind)).forEach(([kind, glyph]) => {
      const option = document.createElement("button");
      option.type = "button";
      option.textContent = glyph;
      option.title = labels[kind];
      option.setAttribute("aria-label", labels[kind]);
      option.addEventListener("click", () => {
        if (sendReaction(messageId, kind)) picker.open = false;
      });
      options.append(option);
    });
    options.style.setProperty("--reaction-option-columns", String(Math.max(1, options.childElementCount)));
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
    clearChildren(attachmentPreviewItems);
    const selectedFiles = attachmentInputs.flatMap((input) => [...(input.files || [])]);
    if (recordedAudioFile) selectedFiles.push(recordedAudioFile);
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
      } else if (file.type.startsWith("audio/")) {
        const audio = document.createElement("audio");
        const objectUrl = URL.createObjectURL(file);
        previewObjectUrls.push(objectUrl);
        audio.src = objectUrl;
        audio.controls = true;
        audio.preload = "metadata";
        audio.className = "chat-audio-preview";
        item.append(audio);
      } else if (file.type.startsWith("video/")) {
        const video = document.createElement("video");
        const objectUrl = URL.createObjectURL(file);
        previewObjectUrls.push(objectUrl);
        video.src = objectUrl;
        video.muted = true;
        video.playsInline = true;
        video.preload = "metadata";
        video.className = "chat-video-preview";
        item.append(video);
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
    if (audioRecorder?.state === "recording") {
      audioRecorder.onstop = null;
      audioRecorder.stop();
    }
    audioStream?.getTracks().forEach((track) => track.stop());
    audioStream = null;
    audioRecorder = null;
    audioChunks = [];
    window.clearInterval(recordTimer);
    recordedAudioFile = null;
    audioRecordButton?.classList.remove("is-recording", "has-recording");
    if (audioRecordLabel) audioRecordLabel.textContent = "صوت";
    attachmentInputs.forEach((input) => { input.value = ""; });
    refreshAttachmentPreview();
  };

  const startAudioRecording = async () => {
    if (!audioRecordButton || !audioRecordLabel) return;
    if (audioRecorder?.state === "recording") {
      audioRecorder.stop();
      return;
    }
    if (recordedAudioFile) {
      compose?.requestSubmit(attachmentSendButton || composeSendButton);
      return;
    }
    if (attachmentInputs.some((input) => input.files?.length)) {
      showError("أرسل مرفقاً واحداً في كل رسالة. أزل الملف المحدد قبل التسجيل الصوتي.");
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      showError("تسجيل الصوت غير مدعوم في هذا المتصفح.");
      return;
    }
    try {
      const supportedTypes = ["audio/webm;codecs=opus", "audio/mp4", "audio/ogg;codecs=opus"];
      const mimeType = supportedTypes.find((type) => MediaRecorder.isTypeSupported?.(type));
      audioStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      audioChunks = [];
      audioRecorder = new MediaRecorder(audioStream, mimeType ? { mimeType } : undefined);
      audioRecorder.addEventListener("dataavailable", (event) => {
        if (event.data?.size) audioChunks.push(event.data);
      });
      audioRecorder.addEventListener("stop", () => {
        audioStream?.getTracks().forEach((track) => track.stop());
        audioStream = null;
        audioRecorder = null;
        window.clearInterval(recordTimer);
        audioRecordButton.classList.remove("is-recording");
        if (!audioChunks.length) {
          audioRecordLabel.textContent = "صوت";
          return;
        }
        const blob = new Blob(audioChunks, { type: mimeType || audioChunks[0].type || "audio/webm" });
        const extension = blob.type.includes("ogg") ? "ogg" : blob.type.includes("mp4") ? "m4a" : "webm";
        recordedAudioFile = new File([blob], `voice-message.${extension}`, { type: blob.type });
        audioRecordButton.classList.add("has-recording");
        audioRecordLabel.textContent = "إرسال الصوت";
        refreshAttachmentPreview();
        audioChunks = [];
      });
      audioRecorder.start(1000);
      recordingStartedAt = Date.now();
      audioRecordButton.classList.add("is-recording");
      audioRecordLabel.textContent = "إيقاف 00:00";
      recordTimer = window.setInterval(() => {
        const elapsed = Math.floor((Date.now() - recordingStartedAt) / 1000);
        const minutes = String(Math.floor(elapsed / 60)).padStart(2, "0");
        const seconds = String(elapsed % 60).padStart(2, "0");
        audioRecordLabel.textContent = `إيقاف ${minutes}:${seconds}`;
      }, 500);
    } catch {
      audioStream?.getTracks().forEach((track) => track.stop());
      audioStream = null;
      audioRecorder = null;
      audioRecordLabel.textContent = "صوت";
      showError("لم نتمكن من تشغيل الميكروفون. اسمح للموقع باستخدامه ثم أعد المحاولة.");
    }
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
    summary.textContent = settings.enabled ? "إدارة · مفعّلة" : "إدارة";
    details.append(summary);

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
    if (demoAccountId) {
      const demoAccountInput = document.createElement("input");
      demoAccountInput.type = "hidden";
      demoAccountInput.name = "demo_account_id";
      demoAccountInput.value = String(demoAccountId);
      form.append(demoAccountInput);
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
        renderMessageSafely(result.message);
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
    clearChildren(container);
    if (!canReact || !message.reactions_enabled) return;
    (message.reactions || []).filter((reaction) => allowedReactions.has(reaction.kind) && Number(reaction.count || 0) > 0).forEach((reaction) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `chat-reaction${message.user_reaction === reaction.kind ? " is-selected" : ""}`;
      button.dataset.reactionKind = reaction.kind;
      button.setAttribute("aria-label", `${labels[reaction.kind]}: ${reaction.count || 0}`);
      const glyph = document.createElement("span");
      glyph.textContent = glyphs[reaction.kind] || "•";
      const count = document.createElement("b");
      count.textContent = String(reaction.count || 0);
      button.append(glyph, count);
      button.addEventListener("click", () => sendReaction(message.id, reaction.kind));
      container.append(button);
    });
    container.append(createReactionPicker(message.id));
  };

  const loadHlsLibrary = () => {
    if (window.Hls) return Promise.resolve(window.Hls);
    if (hlsLoaderPromise) return hlsLoaderPromise;
    hlsLoaderPromise = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = hlsScriptUrl;
      script.async = true;
      script.onload = () => window.Hls ? resolve(window.Hls) : reject(new Error("HLS player did not load."));
      script.onerror = () => reject(new Error("HLS player did not load."));
      document.head.append(script);
    });
    return hlsLoaderPromise;
  };

  const createVideoMessagePlayer = (message) => {
    const player = document.createElement("div");
    player.className = "chat-video-message-player";
    const video = document.createElement("video");
    video.className = "chat-video-message-element";
    video.controls = true;
    video.playsInline = true;
    video.preload = "metadata";
    const quality = document.createElement("small");
    quality.className = "chat-video-quality-label";
    quality.textContent = "جودة تلقائية";

    const useOriginal = () => {
      if (!message.video_fallback_url) {
        quality.textContent = "تعذر تشغيل هذا الفيديو.";
        return;
      }
      if (player._hls) {
        player._hls.destroy();
        player._hls = null;
      }
      video.src = message.video_fallback_url;
      quality.textContent = "تشغيل الملف الأصلي";
    };

    if (message.video_status === "queued" || message.video_status === "processing") {
      const status = document.createElement("div");
      status.className = "chat-video-processing-status";
      status.setAttribute("role", "status");
      status.textContent = "يجري تجهيز الفيديو لجودات مختلفة، سيظهر هنا تلقائياً عند اكتماله.";
      player.append(status);
      return player;
    }

    player.append(video, quality);
    if (message.video_status === "failed") {
      useOriginal();
      return player;
    }
    if (!message.video_stream_url) {
      useOriginal();
      return player;
    }
    if (video.canPlayType("application/vnd.apple.mpegurl")) {
      video.src = message.video_stream_url;
      return player;
    }

    loadHlsLibrary().then((Hls) => {
      if (!player.isConnected) return;
      if (!Hls.isSupported()) {
        useOriginal();
        return;
      }
      const hls = new Hls({ startLevel: -1, capLevelToPlayerSize: true, maxBufferLength: 20 });
      player._hls = hls;
      hls.loadSource(message.video_stream_url);
      hls.attachMedia(video);
      hls.on(Hls.Events.LEVEL_SWITCHED, (_event, data) => {
        const level = hls.levels[data.level];
        quality.textContent = level?.height ? `تلقائي · ${level.height}p` : "جودة تلقائية";
      });
      hls.on(Hls.Events.ERROR, (_event, data) => {
        if (data.fatal) useOriginal();
      });
    }).catch(useOriginal);
    return player;
  };

  const renderMessage = (message, { prepend = false } = {}) => {
    if (!message || !message.id) return;
    const previous = list.querySelector(`[data-message-id="${Number(message.id)}"]`);
    const videoStatusRank = { queued: 1, processing: 2, ready: 3, failed: 3 };
    if (
      previous?.dataset.videoStatus &&
      videoStatusRank[message.video_status] < videoStatusRank[previous.dataset.videoStatus]
    ) return previous;
    const item = document.createElement("li");
    item.className = `chat-message${Number(message.sender_id) === userId ? " is-mine" : ""}`;
    item.dataset.messageId = String(message.id);
    item.dataset.videoStatus = message.video_status || "";
    const dateInfo = messageDateInfo(message);
    item.dataset.messageDay = dateInfo.day;
    const card = document.createElement("article");
    card.className = "chat-message-card";

    const header = document.createElement("header");
    header.className = "chat-message-header";
    const author = document.createElement("strong");
    author.textContent = escapeText(message.sender);
    author.title = escapeText(message.sender);
    header.append(author);
    if (message.sender_is_admin) {
      const role = document.createElement("span");
      role.className = "chat-admin-badge";
      role.textContent = "مشرف";
      header.append(role);
    }
    const time = document.createElement("time");
    time.textContent = escapeText(dateInfo.time);
    if (dateInfo.day && dateInfo.time) time.dateTime = `${dateInfo.day}T${dateInfo.time}`;
    header.append(time);
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
      const mediaUrl = message.media_url || message.video_fallback_url || message.video_stream_url;
      const value = message.text || (mediaUrl ? new URL(mediaUrl, window.location.origin).href : "");
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
      appendMessageTextWithLinks(body, message.text);
      card.append(body);
    }
    if (message.voice_message && message.media_url) {
      const voicePlayer = document.createElement("div");
      voicePlayer.className = "chat-voice-message-player";
      const audio = document.createElement("audio");
      audio.controls = true;
      audio.preload = "metadata";
      audio.src = message.media_url;
      voicePlayer.append(audio);
      card.append(voicePlayer);
    }
    if (message.video) card.append(createVideoMessagePlayer(message));
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
    if (previous) {
      previous.querySelectorAll(".chat-video-message-player").forEach((player) => player._hls?.destroy());
      previous.replaceWith(item);
    }
    else if (prepend) list.prepend(item);
    else list.append(item);
    return item;
  };

  const renderBasicMessage = (message, { prepend = false } = {}) => {
    if (!message || !message.id) return null;
    const previous = list.querySelector(`[data-message-id="${Number(message.id)}"]`);
    const item = document.createElement("li");
    item.className = `chat-message${Number(message.sender_id) === userId ? " is-mine" : ""}`;
    item.setAttribute("data-message-id", String(message.id));
    if (message.created_day) item.setAttribute("data-message-day", String(message.created_day));

    const card = document.createElement("article");
    card.className = "chat-message-card";
    const header = document.createElement("header");
    header.className = "chat-message-header";
    const author = document.createElement("strong");
    author.textContent = String(message.sender || "عضو");
    header.appendChild(author);
    if (message.sender_is_admin) {
      const badge = document.createElement("span");
      badge.className = "chat-admin-badge";
      badge.textContent = "مشرف";
      header.appendChild(badge);
    }
    const time = document.createElement("time");
    time.textContent = String(message.created_time || "");
    header.appendChild(time);
    card.appendChild(header);

    if (message.reply_to) {
      const reply = document.createElement("div");
      reply.className = "chat-reply-quote";
      reply.textContent = `${message.reply_to.sender || "عضو"}: ${message.reply_to.preview || "رسالة"}`;
      card.appendChild(reply);
    }
    if (message.text) {
      const body = document.createElement("p");
      body.className = "chat-message-text";
      appendMessageTextWithLinks(body, message.text);
      card.appendChild(body);
    }
    if (message.voice_message && message.media_url) {
      const voicePlayer = document.createElement("div");
      voicePlayer.className = "chat-voice-message-player";
      const audio = document.createElement("audio");
      audio.controls = true;
      audio.preload = "metadata";
      audio.src = message.media_url;
      voicePlayer.append(audio);
      card.appendChild(voicePlayer);
    }
    if (message.video) card.appendChild(createVideoMessagePlayer(message));
    if (message.media_url && !message.voice_message && !message.video) {
      const media = document.createElement("a");
      media.className = message.image ? "chat-message-image-link" : "chat-message-attachment";
      media.href = String(message.media_url);
      if (message.image) {
        const image = document.createElement("img");
        image.src = String(message.media_url);
        image.alt = "صورة مرفقة";
        media.appendChild(image);
      } else {
        media.textContent = String(message.attachment_name || "تنزيل الملف");
      }
      card.appendChild(media);
    }

    item.appendChild(card);
    if (previous && previous.parentNode) {
      previous.querySelectorAll(".chat-video-message-player").forEach((player) => player._hls?.destroy());
      previous.parentNode.replaceChild(item, previous);
    }
    else if (prepend) list.insertBefore(item, list.firstChild);
    else list.appendChild(item);
    return item;
  };

  let basicRenderNoticeShown = false;
  const renderMessageSafely = (message, options) => {
    try {
      return renderMessage(message, options);
    } catch (error) {
      console.error("Could not render a group chat message; using basic rendering", error);
      if (!basicRenderNoticeShown && historyStatus) {
        basicRenderNoticeShown = true;
        const errorName = error?.name || "Error";
        const errorMessage = error?.message || String(error);
        historyStatus.textContent = `استخدم التطبيق عرضاً مبسطاً للرسائل. سبب المشكلة: ${errorName}: ${errorMessage}`;
        historyStatus.classList.add("is-error");
        historyStatus.hidden = false;
      }
      try {
        return renderBasicMessage(message, options);
      } catch (fallbackError) {
        console.error("Could not render a group chat message in basic mode", fallbackError);
        if (historyStatus) {
          const details = fallbackError?.message ? ` (${fallbackError.message})` : "";
          historyStatus.textContent = `تعذر عرض الرسائل${details}. حدّث الصفحة وحاول مجدداً.`;
          historyStatus.classList.add("is-error");
          historyStatus.hidden = false;
        }
        return null;
      }
    }
  };

  const loadOlderMessages = async () => {
    if (!hasOlderMessages || loadingOlderMessages) return;
    const firstMessage = list.querySelector("[data-message-id]");
    const beforeId = firstMessage?.dataset.messageId;
    if (!beforeId) return;

    loadingOlderMessages = true;
    const requestGeneration = historyRequestGeneration;
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

      if (requestGeneration !== historyRequestGeneration) return;
      const olderMessages = result.messages || [];
      hasOlderMessages = Boolean(result.has_more);
      [...olderMessages].reverse().forEach((message) => renderMessageSafely(message, { prepend: true }));
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
      if (requestGeneration !== historyRequestGeneration) return;
      if (historyStatus) {
        historyStatus.textContent = error.message || "تعذر تحميل الرسائل الأقدم.";
        historyStatus.classList.add("is-error");
        historyStatus.hidden = false;
        window.setTimeout(() => { historyStatus.hidden = true; }, 3000);
      }
    } finally {
      if (requestGeneration === historyRequestGeneration) loadingOlderMessages = false;
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

  const sendReaction = (messageId, kind) => {
    if (!demoAccountId) return sendSocket({ action: "react", message_id: messageId, kind });
    if (!demoReactionUrlTemplate) {
      showError("تعذر تحديد هوية التفاعل التجريبي.");
      return false;
    }
    const url = demoReactionUrlTemplate.replace(/\/0\/reaction\/?$/, `/${Number(messageId)}/reaction/`);
    const csrf = root.querySelector('[name="csrfmiddlewaretoken"]')?.value || "";
    fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Accept": "application/json", "X-CSRFToken": csrf },
      body: new URLSearchParams({ kind }),
    }).then(async (response) => {
      const result = await response.json();
      if (!response.ok || !result.ok) throw new Error(result.error || "تعذر حفظ التفاعل.");
      updateReactionCounts({ ...result.message, message_id: result.message.id });
    }).catch((error) => showError(error.message || "تعذر حفظ التفاعل."));
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
    if (payload.demo_account_id) {
      if (Number(payload.demo_account_id) === demoAccountId) selectedKind = payload.actor_reaction;
    } else if (demoAccountId) {
      if (Object.prototype.hasOwnProperty.call(payload, "user_reaction")) selectedKind = payload.user_reaction;
    } else if (Object.prototype.hasOwnProperty.call(payload, "user_reaction")) {
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
        button.addEventListener("click", () => sendReaction(payload.message_id, reaction.kind));
      }
      button.classList.toggle("is-selected", selectedKind === reaction.kind);
      const count = button.querySelector("b");
      if (count) count.textContent = String(total);
      button.setAttribute("aria-label", `${labels[reaction.kind]}: ${total}`);
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
    if (demoAccountId) params.set("demo_account_id", String(demoAccountId));
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
        let message = payload.message;
        if (payload.type === "message_updated" && message && (demoAccountId || payload.demo_account_id)) {
          const eventDemoAccountId = Number(payload.demo_account_id || 0);
          const matchesDemoAccount = demoAccountId > 0 && eventDemoAccountId === demoAccountId;
          if (!matchesDemoAccount) {
            const selectedReaction = list.querySelector(`[data-message-id="${Number(message.id)}"] .chat-reactions [data-reaction-kind].is-selected`)?.dataset.reactionKind || null;
            message = { ...message, user_reaction: selectedReaction };
          }
        }
        renderMessageSafely(message);
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
      } else if (payload.type === "group_messages_cleared") {
        historyRequestGeneration += 1;
        loadingOlderMessages = false;
        hasOlderMessages = false;
        list.replaceChildren();
        clearReplySelection();
        if (historyStatus) historyStatus.hidden = true;
        if (errorBox) errorBox.hidden = true;
        listViewport.scrollTop = 0;
      } else if (payload.type === "reaction_updated") {
        updateReactionCounts(payload);
      } else if (payload.type === "reaction_settings_updated") {
        window.location.reload();
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
    initial.forEach((message) => renderMessageSafely(message));
    syncDayDividers();
    scrollToLatest();
  } catch (error) {
    console.error("Could not render initial group chat messages", error);
    if (historyStatus) {
      const details = error?.message ? ` (${error.message})` : "";
      historyStatus.textContent = `تعذر عرض الرسائل${details}. حدّث الصفحة وحاول مجدداً.`;
      historyStatus.classList.add("is-error");
      historyStatus.hidden = false;
    }
  }

  listViewport.addEventListener("scroll", () => {
    root.querySelectorAll("[data-reaction-picker][open]").forEach((picker) => { picker.open = false; });
    root.querySelectorAll("[data-message-actions-menu][open]").forEach((menu) => { menu.open = false; });
    if (isNearLatest() && document.visibilityState === "visible") {
      const messages = list.querySelectorAll("[data-message-id]");
      const latestMessage = messages[messages.length - 1];
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
  messageInput?.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || !event.ctrlKey || event.isComposing) return;
    event.preventDefault();
    if (!compose?.querySelector('button[type="submit"]:disabled')) compose?.requestSubmit();
  });
  attachmentInputs.forEach((input) => {
    input.addEventListener("change", () => {
      if (input.files?.length && audioRecorder?.state === "recording") {
        input.value = "";
        showError("أوقف التسجيل الصوتي قبل اختيار ملف.");
        return;
      }
      if (input.files?.length && recordedAudioFile) {
        recordedAudioFile = null;
        audioRecordButton?.classList.remove("has-recording");
        if (audioRecordLabel) audioRecordLabel.textContent = "صوت";
      }
      if (input.files?.length) input.closest("details")?.removeAttribute("open");
      refreshAttachmentPreview();
    });
  });
  audioRecordButton?.addEventListener("click", startAudioRecording);
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
      if (recordedAudioFile) formData.set("voice_message", recordedAudioFile, recordedAudioFile.name);
      const response = await fetch(compose.action, {
        method: "POST",
        body: formData,
        headers: { "Accept": "application/json", "X-Requested-With": "XMLHttpRequest" },
        credentials: "same-origin",
      });
      const result = await response.json();
      if (!response.ok || !result.ok) throw new Error(result.error || "تعذر إرسال الرسالة.");
      renderMessageSafely(result.message);
      syncLastDayDivider();
      compose.reset();
      clearSelectedAttachments();
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
