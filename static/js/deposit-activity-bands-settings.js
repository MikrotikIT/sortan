(() => {
  const editor = document.querySelector("[data-deposit-bands-editor]");
  if (!editor) return;

  const hiddenInput = editor.querySelector('input[name="deposit_activity_amount_bands"]');
  const list = editor.querySelector("[data-deposit-band-list]");
  const totalLabel = editor.querySelector("[data-deposit-band-total]");
  const addButton = editor.querySelector("[data-add-deposit-band]");
  const form = editor.closest("form");
  if (!hiddenInput || !list || !totalLabel || !addButton || !form) return;
  const fallbackBands = [
    { min_amount: "50", max_amount: "500", probability: "70" },
    { min_amount: "1000", max_amount: "3000", probability: "20" },
    { min_amount: "4000", max_amount: "10000", probability: "7" },
    { min_amount: "10000", max_amount: "40000", probability: "3" },
  ];

  let bands;
  try {
    bands = JSON.parse(hiddenInput.value);
  } catch {
    bands = fallbackBands;
  }
  if (!Array.isArray(bands) || !bands.length) bands = fallbackBands;

  const clearChildren = (element) => {
    while (element.firstChild) element.removeChild(element.firstChild);
  };

  const syncValueAndTotal = () => {
    hiddenInput.value = JSON.stringify(bands);
    const total = bands.reduce((sum, band) => sum + (Number(band.probability) || 0), 0);
    const isValid = Math.abs(total - 100) < 0.00001;
    totalLabel.textContent = `${Number(total.toFixed(2)).toLocaleString("en-US")}%`;
    totalLabel.classList.toggle("is-valid", isValid);
    totalLabel.classList.toggle("is-invalid", !isValid);
    addButton.disabled = bands.length >= 20;
  };

  const createInputField = (labelText, key, value, min, max, step) => {
    const label = document.createElement("label");
    label.className = "deposit-band-field";
    const caption = document.createElement("span");
    caption.textContent = labelText;
    const input = document.createElement("input");
    input.type = "number";
    input.min = String(min);
    input.max = String(max);
    input.step = String(step);
    input.value = value ?? "";
    input.dataset.bandField = key;
    label.append(caption, input);
    return label;
  };

  const render = (focusLast = false) => {
    clearChildren(list);
    bands.forEach((band, index) => {
      const card = document.createElement("article");
      card.className = "deposit-band-card";
      card.dataset.bandIndex = String(index);

      const heading = document.createElement("div");
      heading.className = "deposit-band-heading";
      const title = document.createElement("strong");
      title.textContent = `الشريحة ${index + 1}`;
      const removeButton = document.createElement("button");
      removeButton.type = "button";
      removeButton.className = "deposit-band-remove";
      removeButton.textContent = "حذف";
      removeButton.disabled = bands.length <= 1;
      removeButton.setAttribute("aria-label", `حذف الشريحة ${index + 1}`);
      removeButton.addEventListener("click", () => {
        const removed = bands.splice(index, 1)[0];
        if (bands.length) {
          bands[0].probability = ((Number(bands[0].probability) || 0) + (Number(removed.probability) || 0)).toFixed(2);
        }
        render();
      });
      heading.append(title, removeButton);

      const fields = document.createElement("div");
      fields.className = "deposit-band-fields";
      fields.append(
        createInputField("من المبلغ (USDT)", "min_amount", band.min_amount, 50, 1000000, 50),
        createInputField("إلى المبلغ (USDT)", "max_amount", band.max_amount, 50, 1000000, 50),
        createInputField("احتمالية الظهور (%)", "probability", band.probability, 0, 100, 0.01),
      );
      card.append(heading, fields);
      list.append(card);
    });
    syncValueAndTotal();
    if (focusLast) list.lastElementChild?.querySelector('[data-band-field="min_amount"]')?.focus();
  };

  list.addEventListener("input", (event) => {
    const input = event.target.closest("[data-band-field]");
    if (!input) return;
    const index = Number(input.closest("[data-band-index]")?.dataset.bandIndex);
    if (!Number.isInteger(index) || !bands[index]) return;
    bands[index][input.dataset.bandField] = input.value;
    syncValueAndTotal();
  });

  addButton.addEventListener("click", () => {
    const largestProbabilityIndex = bands.reduce(
      (best, band, index) => (Number(band.probability) > Number(bands[best].probability) ? index : best),
      0,
    );
    const transferredProbability = Math.min(5, Number(bands[largestProbabilityIndex].probability) || 0);
    bands[largestProbabilityIndex].probability = (
      (Number(bands[largestProbabilityIndex].probability) || 0) - transferredProbability
    ).toFixed(2);
    const largestAmount = Math.max(...bands.map((band) => Number(band.max_amount) || 0));
    let minAmount = Math.ceil((largestAmount + 50) / 50) * 50;
    if (minAmount > 1000000) minAmount = 50;
    bands.push({
      min_amount: String(minAmount),
      max_amount: String(Math.min(1000000, minAmount + 500)),
      probability: transferredProbability.toFixed(2),
    });
    render(true);
  });

  form.addEventListener("submit", syncValueAndTotal);
  render();
})();
