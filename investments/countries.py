import re
import unicodedata


# ISO 3166-1 alpha-2, Arabic name, and ITU calling code.
COUNTRIES = (
    ("AF", "أفغانستان", "93"),
    ("DZ", "الجزائر", "213"),
    ("AU", "أستراليا", "61"),
    ("AZ", "أذربيجان", "994"),
    ("BH", "البحرين", "973"),
    ("BD", "بنغلاديش", "880"),
    ("BE", "بلجيكا", "32"),
    ("BR", "البرازيل", "55"),
    ("GB", "بريطانيا", "44"),
    ("BG", "بلغاريا", "359"),
    ("CA", "كندا", "1"),
    ("TD", "تشاد", "235"),
    ("CN", "الصين", "86"),
    ("KM", "جزر القمر", "269"),
    ("DK", "الدنمارك", "45"),
    ("DJ", "جيبوتي", "253"),
    ("EG", "مصر", "20"),
    ("ET", "إثيوبيا", "251"),
    ("FR", "فرنسا", "33"),
    ("DE", "ألمانيا", "49"),
    ("GH", "غانا", "233"),
    ("GR", "اليونان", "30"),
    ("IN", "الهند", "91"),
    ("ID", "إندونيسيا", "62"),
    ("IR", "إيران", "98"),
    ("IQ", "العراق", "964"),
    ("IE", "أيرلندا", "353"),
    ("IT", "إيطاليا", "39"),
    ("JO", "الأردن", "962"),
    ("KE", "كينيا", "254"),
    ("KW", "الكويت", "965"),
    ("LB", "لبنان", "961"),
    ("LY", "ليبيا", "218"),
    ("MY", "ماليزيا", "60"),
    ("MR", "موريتانيا", "222"),
    ("MA", "المغرب", "212"),
    ("NL", "هولندا", "31"),
    ("NZ", "نيوزيلندا", "64"),
    ("NG", "نيجيريا", "234"),
    ("OM", "عُمان", "968"),
    ("PK", "باكستان", "92"),
    ("PS", "فلسطين", "970"),
    ("PH", "الفلبين", "63"),
    ("PL", "بولندا", "48"),
    ("PT", "البرتغال", "351"),
    ("QA", "قطر", "974"),
    ("RO", "رومانيا", "40"),
    ("RU", "روسيا", "7"),
    ("SA", "السعودية", "966"),
    ("SN", "السنغال", "221"),
    ("SG", "سنغافورة", "65"),
    ("SO", "الصومال", "252"),
    ("ZA", "جنوب أفريقيا", "27"),
    ("ES", "إسبانيا", "34"),
    ("SD", "السودان", "249"),
    ("SE", "السويد", "46"),
    ("CH", "سويسرا", "41"),
    ("SY", "سوريا", "963"),
    ("TZ", "تنزانيا", "255"),
    ("TN", "تونس", "216"),
    ("TR", "تركيا", "90"),
    ("AE", "الإمارات", "971"),
    ("UG", "أوغندا", "256"),
    ("UA", "أوكرانيا", "380"),
    ("US", "الولايات المتحدة", "1"),
    ("VN", "فيتنام", "84"),
    ("YE", "اليمن", "967"),
)

COUNTRY_CHOICES = tuple((code, name) for code, name, _ in COUNTRIES)
COUNTRY_NAMES = {code: name for code, name, _ in COUNTRIES}
COUNTRY_DIAL_CODES = {code: dial_code for code, _, dial_code in COUNTRIES}
DIAL_COUNTRY_CODES = {}
for country_code, _, dial_code in COUNTRIES:
    DIAL_COUNTRY_CODES.setdefault(dial_code, []).append(country_code)


def country_flag(code):
    code = (code or "").upper()
    if len(code) != 2 or not code.isascii() or not code.isalpha():
        return ""
    return "".join(chr(127397 + ord(letter)) for letter in code)


def infer_country_code_from_number(phone):
    phone = str(phone or "").strip()
    if not phone.startswith("+"):
        return ""
    try:
        digits = digits_only(phone)
    except ValueError:
        return ""
    matching_dial_codes = [dial for dial in DIAL_COUNTRY_CODES if digits.startswith(dial)]
    if not matching_dial_codes:
        return ""
    longest_dial_code = max(matching_dial_codes, key=len)
    countries = DIAL_COUNTRY_CODES[longest_dial_code]
    return countries[0] if len(countries) == 1 else ""


COUNTRY_FORM_CHOICES = tuple(
    (code, f"{country_flag(code)} {name} (+{dial_code})")
    for code, name, dial_code in sorted(COUNTRIES, key=lambda country: country[1])
)


def digits_only(value):
    digits = []
    for character in str(value or ""):
        try:
            digits.append(str(unicodedata.digit(character)))
        except (TypeError, ValueError):
            if character.isdigit():
                raise ValueError("استخدم أرقام الهاتف المعتادة.")
    return "".join(digits)


def clean_phone_input(value):
    value = (value or "").strip()
    if not value or not re.fullmatch(r"[+\d\s().-]+", value):
        raise ValueError("أدخل رقم هاتف صحيحاً.")
    if value.count("+") > 1 or ("+" in value and not value.startswith("+")):
        raise ValueError("تحقق من صيغة رقم الهاتف.")
    digits = digits_only(value)
    if not digits:
        raise ValueError("أدخل رقم هاتف صحيحاً.")
    return value, digits


def normalize_phone_number(value, country_code):
    value, digits = clean_phone_input(value)
    dial_code = COUNTRY_DIAL_CODES.get(country_code)
    if not dial_code:
        raise ValueError("اختر الدولة ورمز الاتصال.")

    is_international = value.startswith("+") or digits.startswith("00")
    if digits.startswith("00"):
        digits = digits[2:]
        is_international = True
    if is_international:
        if not digits.startswith(dial_code):
            raise ValueError("رمز الدولة لا يطابق رمز الاتصال المحدد.")
        national_number = digits[len(dial_code):]
    else:
        national_number = digits
        if national_number.startswith(dial_code) and len(national_number) > len(dial_code) + 6:
            national_number = national_number[len(dial_code):]

    if national_number.startswith("0"):
        national_number = national_number[1:]
    if not national_number:
        raise ValueError("أدخل رقم الهاتف بعد رمز الدولة.")
    return f"+{dial_code}{national_number}"


def masked_phone_number(phone, country_code=""):
    try:
        _, digits = clean_phone_input(phone)
    except ValueError:
        digits = "".join(character for character in str(phone or "") if character.isdecimal())
        if not digits:
            return str(phone or "")
    dial_code = COUNTRY_DIAL_CODES.get(country_code, "")
    if dial_code and str(phone).strip().startswith("+") and digits.startswith(dial_code):
        national_number = digits[len(dial_code):]
    else:
        national_number = digits
        if dial_code and national_number.startswith("0"):
            national_number = national_number[1:]
    visible_digits = max(1, len(national_number) - 3) if national_number else 0
    masked = f"{national_number[:visible_digits]}***" if national_number else "***"
    if dial_code:
        return f"+{dial_code} {masked}"
    return f"+{masked}" if str(phone).strip().startswith("+") else masked
