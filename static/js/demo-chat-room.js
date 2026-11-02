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
  let lastMessageId = Number(root.dataset.lastMessageId || 0);
  let sending = false;

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

  window.requestAnimationFrame(() => { transcript.scrollTop = transcript.scrollHeight; });
  window.setInterval(loadNewMessages, 2000);
})();
