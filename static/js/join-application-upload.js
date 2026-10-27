(() => {
  const form = document.querySelector("[data-join-application-upload]");
  if (!form || !window.XMLHttpRequest || !window.FormData) return;

  const optimizedSize = 700 * 1024;

  async function makeUploadImage(file) {
    if (!window.createImageBitmap || !window.File) return file;
    const bitmap = await createImageBitmap(file);
    try {
      if (bitmap.width * bitmap.height > 40_000_000) throw new Error("image-too-large");
      const canvas = document.createElement("canvas");
      for (const dimension of [1400, 1200, 1000, 850]) {
        const scale = Math.min(1, dimension / Math.max(bitmap.width, bitmap.height));
        canvas.width = Math.max(1, Math.round(bitmap.width * scale));
        canvas.height = Math.max(1, Math.round(bitmap.height * scale));
        const context = canvas.getContext("2d");
        if (!context) return file;
        context.fillStyle = "#fff";
        context.fillRect(0, 0, canvas.width, canvas.height);
        context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);

        for (const quality of [0.84, 0.76, 0.68, 0.60, 0.52, 0.46]) {
          const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", quality));
          if (blob && blob.size <= optimizedSize) {
            return new File([blob], "profile.jpg", { type: "image/jpeg", lastModified: Date.now() });
          }
        }
      }
      throw new Error("image-could-not-be-compressed");
    } finally {
      bitmap.close();
    }
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();

    const progress = form.querySelector("[data-upload-progress]");
    const bar = form.querySelector("[data-upload-progress-bar]");
    const label = form.querySelector("[data-upload-progress-label]");
    const submitButton = form.querySelector('button[type="submit"]');
    const originalButtonText = submitButton ? submitButton.textContent : "";
    const xhr = new XMLHttpRequest();

    if (progress) {
      progress.hidden = false;
      progress.dataset.state = "uploading";
    }
    if (label) label.textContent = "جارٍ رفع الصورة والطلب...";
    if (submitButton) {
      submitButton.disabled = true;
      submitButton.textContent = "جارٍ الإرسال...";
    }

    const formData = new FormData(form);
    const imageInput = form.querySelector('input[type="file"][name="profile_image"]');
    const originalImage = imageInput && imageInput.files && imageInput.files[0];
    if (originalImage) {
      if (progress) progress.dataset.state = "processing";
      if (label) label.textContent = "جارٍ ضغط الصورة وتجهيز الطلب...";
      try {
        const uploadImage = await makeUploadImage(originalImage);
        formData.set("profile_image", uploadImage, uploadImage.name || originalImage.name);
      } catch (_) {
        // The server validates and compresses the original when browser compression is unavailable.
      }
    }
    if (progress) progress.dataset.state = "uploading";
    if (label) label.textContent = "جارٍ رفع الصورة والطلب...";

    xhr.open(form.method || "POST", form.action || window.location.href);
    xhr.upload.addEventListener("progress", (uploadEvent) => {
      if (!uploadEvent.lengthComputable) return;
      const percentage = Math.min(100, Math.round((uploadEvent.loaded / uploadEvent.total) * 100));
      if (bar) {
        bar.style.width = `${percentage}%`;
        bar.setAttribute("aria-valuenow", String(percentage));
      }
      if (label) {
        label.textContent = percentage >= 100
          ? "اكتمل الرفع، جارٍ ضغط الصورة وحفظ الطلب..."
          : `جارٍ رفع الصورة والطلب... ${percentage}%`;
      }
    });

    xhr.addEventListener("load", () => {
      const currentPath = window.location.pathname;
      let responsePath = currentPath;
      try {
        responsePath = new URL(xhr.responseURL, window.location.href).pathname;
      } catch (_) {
        // Keep the current page when the browser does not expose responseURL.
      }

      if (responsePath !== currentPath) {
        window.location.assign(xhr.responseURL);
        return;
      }

      document.open();
      document.write(xhr.responseText);
      document.close();
    });

    xhr.addEventListener("error", () => {
      if (label) label.textContent = "تعذر إكمال الرفع. تحقق من اتصالك وحاول مرة أخرى.";
      if (submitButton) {
        submitButton.disabled = false;
        submitButton.textContent = originalButtonText;
      }
    });

    xhr.addEventListener("abort", () => {
      if (label) label.textContent = "توقف الرفع قبل اكتماله. أعد المحاولة.";
      if (submitButton) {
        submitButton.disabled = false;
        submitButton.textContent = originalButtonText;
      }
    });

    xhr.send(formData);
  });
})();
