(() => {
  if (typeof window.intlTelInput !== "function") return;

  const phoneInputs = document.querySelectorAll("[data-intl-phone]");
  phoneInputs.forEach((input) => {
    const form = input.form;
    const countryCode = form && form.querySelector("[data-phone-country-code]");
    if (!countryCode) return;

    const phonePicker = window.intlTelInput(input, {
      initialCountry: "sy",
      countryOrder: ["sy"],
      countryNameLocale: "ar",
      countryNameOverrides: { sy: "سوريا" },
      countrySearch: true,
      separateDialCode: true,
      strictMode: true,
      uiTranslations: {
        selectedCountryAriaLabel: "تغيير الدولة لرقم الهاتف، المحددة ${countryName} (${dialCode})",
        noCountrySelected: "اختر دولة لرقم الهاتف",
        countryListAriaLabel: "قائمة الدول",
        searchPlaceholder: "ابحث عن دولة أو رمز الاتصال",
        clearSearchAriaLabel: "مسح البحث",
        closeCountrySelectorAriaLabel: "إغلاق قائمة الدول",
        searchEmptyState: "لم يتم العثور على نتائج",
        searchSummaryAria: (count) => count === 1 ? "تم العثور على نتيجة واحدة" : `تم العثور على ${count} نتيجة`,
      },
    });

    const syncCountryCode = () => {
      const selectedCountry = phonePicker.getSelectedCountryData();
      if (selectedCountry && selectedCountry.iso2) {
        countryCode.value = selectedCountry.iso2.toUpperCase();
      }
    };

    input.addEventListener("countrychange", syncCountryCode);
    form.addEventListener("submit", syncCountryCode);
    syncCountryCode();
  });
})();
