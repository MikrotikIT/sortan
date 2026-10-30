import re
import unicodedata


# ISO 3166-1 alpha-2, Arabic name, and ITU calling code.
COUNTRIES = (
    ('IS', 'آيسلندا', '354'),
    ('AZ', 'أذربيجان', '994'),
    ('AM', 'أرمينيا', '374'),
    ('AW', 'أروبا', '297'),
    ('AU', 'أستراليا', '61'),
    ('AF', 'أفغانستان', '93'),
    ('AL', 'ألبانيا', '355'),
    ('DE', 'ألمانيا', '49'),
    ('AG', 'أنتيغوا وبربودا', '1'),
    ('AD', 'أندورا', '376'),
    ('AO', 'أنغولا', '244'),
    ('AI', 'أنغويلا', '1'),
    ('UY', 'أورغواي', '598'),
    ('UZ', 'أوزبكستان', '998'),
    ('UG', 'أوغندا', '256'),
    ('UA', 'أوكرانيا', '380'),
    ('IE', 'أيرلندا', '353'),
    ('ET', 'إثيوبيا', '251'),
    ('ER', 'إريتريا', '291'),
    ('ES', 'إسبانيا', '34'),
    ('EE', 'إستونيا', '372'),
    ('IL', 'إسرائيل', '972'),
    ('SZ', 'إسواتيني', '268'),
    ('ID', 'إندونيسيا', '62'),
    ('IR', 'إيران', '98'),
    ('IT', 'إيطاليا', '39'),
    ('AR', 'الأرجنتين', '54'),
    ('JO', 'الأردن', '962'),
    ('IO', 'الإقليم البريطاني في المحيط الهندي', '246'),
    ('EC', 'الإكوادور', '593'),
    ('AE', 'الإمارات', '971'),
    ('BH', 'البحرين', '973'),
    ('BR', 'البرازيل', '55'),
    ('PT', 'البرتغال', '351'),
    ('BA', 'البوسنة والهرسك', '387'),
    ('CZ', 'التشيك', '420'),
    ('ME', 'الجبل الأسود', '382'),
    ('DZ', 'الجزائر', '213'),
    ('DK', 'الدنمارك', '45'),
    ('CV', 'الرأس الأخضر', '238'),
    ('SA', 'السعودية', '966'),
    ('SV', 'السلفادور', '503'),
    ('SN', 'السنغال', '221'),
    ('SD', 'السودان', '249'),
    ('SE', 'السويد', '46'),
    ('EH', 'الصحراء الغربية', '212'),
    ('SO', 'الصومال', '252'),
    ('CN', 'الصين', '86'),
    ('IQ', 'العراق', '964'),
    ('GA', 'الغابون', '241'),
    ('VA', 'الفاتيكان', '39'),
    ('PH', 'الفلبين', '63'),
    ('CM', 'الكاميرون', '237'),
    ('CG', 'الكونغو - برازافيل', '242'),
    ('CD', 'الكونغو - كينشاسا', '243'),
    ('KW', 'الكويت', '965'),
    ('MA', 'المغرب', '212'),
    ('MX', 'المكسيك', '52'),
    ('NO', 'النرويج', '47'),
    ('AT', 'النمسا', '43'),
    ('NE', 'النيجر', '227'),
    ('IN', 'الهند', '91'),
    ('US', 'الولايات المتحدة', '1'),
    ('JP', 'اليابان', '81'),
    ('YE', 'اليمن', '967'),
    ('GR', 'اليونان', '30'),
    ('PG', 'بابوا غينيا الجديدة', '675'),
    ('PY', 'باراغواي', '595'),
    ('PK', 'باكستان', '92'),
    ('PW', 'بالاو', '680'),
    ('BB', 'بربادوس', '1'),
    ('BM', 'برمودا', '1'),
    ('BN', 'بروناي', '673'),
    ('GB', 'بريطانيا', '44'),
    ('BE', 'بلجيكا', '32'),
    ('BG', 'بلغاريا', '359'),
    ('BZ', 'بليز', '501'),
    ('BD', 'بنغلاديش', '880'),
    ('PA', 'بنما', '507'),
    ('BJ', 'بنين', '229'),
    ('BT', 'بوتان', '975'),
    ('BW', 'بوتسوانا', '267'),
    ('PR', 'بورتوريكو', '1'),
    ('BF', 'بوركينا فاسو', '226'),
    ('BI', 'بوروندي', '257'),
    ('PL', 'بولندا', '48'),
    ('BO', 'بوليفيا', '591'),
    ('PF', 'بولينيزيا الفرنسية', '689'),
    ('PE', 'بيرو', '51'),
    ('BY', 'بيلاروس', '375'),
    ('TH', 'تايلاند', '66'),
    ('TW', 'تايوان', '886'),
    ('TM', 'تركمانستان', '993'),
    ('TR', 'تركيا', '90'),
    ('TT', 'ترينيداد وتوباغو', '1'),
    ('TD', 'تشاد', '235'),
    ('CL', 'تشيلي', '56'),
    ('TZ', 'تنزانيا', '255'),
    ('TG', 'توغو', '228'),
    ('TV', 'توفالو', '688'),
    ('TK', 'توكيلاو', '690'),
    ('TN', 'تونس', '216'),
    ('TO', 'تونغا', '676'),
    ('TL', 'تيمور - ليشتي', '670'),
    ('JM', 'جامايكا', '1'),
    ('GI', 'جبل طارق', '350'),
    ('AX', 'جزر آلاند', '358'),
    ('BS', 'جزر البهاما', '1'),
    ('KM', 'جزر القمر', '269'),
    ('MQ', 'جزر المارتينيك', '596'),
    ('MV', 'جزر المالديف', '960'),
    ('TC', 'جزر توركس وكايكوس', '1'),
    ('SB', 'جزر سليمان', '677'),
    ('FO', 'جزر فارو', '298'),
    ('FK', 'جزر فوكلاند', '500'),
    ('VI', 'جزر فيرجن الأمريكية', '1'),
    ('VG', 'جزر فيرجن البريطانية', '1'),
    ('KY', 'جزر كايمان', '1'),
    ('CK', 'جزر كوك', '682'),
    ('CC', 'جزر كوكوس (كيلينغ)', '61'),
    ('MH', 'جزر مارشال', '692'),
    ('MP', 'جزر ماريانا الشمالية', '1'),
    ('WF', 'جزر والس وفوتونا', '681'),
    ('AC', 'جزيرة أسينشيون', '247'),
    ('CX', 'جزيرة كريسماس', '61'),
    ('IM', 'جزيرة مان', '44'),
    ('NF', 'جزيرة نورفولك', '672'),
    ('CF', 'جمهورية أفريقيا الوسطى', '236'),
    ('DO', 'جمهورية الدومينيكان', '1'),
    ('ZA', 'جنوب أفريقيا', '27'),
    ('SS', 'جنوب السودان', '211'),
    ('GE', 'جورجيا', '995'),
    ('DJ', 'جيبوتي', '253'),
    ('JE', 'جيرسي', '44'),
    ('DM', 'دومينيكا', '1'),
    ('RW', 'رواندا', '250'),
    ('RU', 'روسيا', '7'),
    ('RO', 'رومانيا', '40'),
    ('RE', 'روينيون', '262'),
    ('ZM', 'زامبيا', '260'),
    ('ZW', 'زيمبابوي', '263'),
    ('CI', 'ساحل العاج', '225'),
    ('WS', 'ساموا', '685'),
    ('AS', 'ساموا الأمريكية', '1'),
    ('BL', 'سان بارتليمي', '590'),
    ('PM', 'سان بيير ومكويلون', '508'),
    ('MF', 'سان مارتن', '590'),
    ('SM', 'سان مارينو', '378'),
    ('VC', 'سانت فنسنت وجزر غرينادين', '1'),
    ('KN', 'سانت كيتس ونيفيس', '1'),
    ('LC', 'سانت لوسيا', '1'),
    ('SX', 'سانت مارتن', '1'),
    ('SH', 'سانت هيلينا', '290'),
    ('ST', 'ساو تومي وبرينسيبي', '239'),
    ('LK', 'سريلانكا', '94'),
    ('SJ', 'سفالبارد وجان ماين', '47'),
    ('SK', 'سلوفاكيا', '421'),
    ('SI', 'سلوفينيا', '386'),
    ('SG', 'سنغافورة', '65'),
    ('SY', 'سوريا', '963'),
    ('SR', 'سورينام', '597'),
    ('CH', 'سويسرا', '41'),
    ('SL', 'سيراليون', '232'),
    ('SC', 'سيشل', '248'),
    ('RS', 'صربيا', '381'),
    ('TJ', 'طاجيكستان', '992'),
    ('OM', 'عُمان', '968'),
    ('GM', 'غامبيا', '220'),
    ('GH', 'غانا', '233'),
    ('GD', 'غرينادا', '1'),
    ('GL', 'غرينلاند', '299'),
    ('GT', 'غواتيمالا', '502'),
    ('GP', 'غوادلوب', '590'),
    ('GU', 'غوام', '1'),
    ('GF', 'غويانا الفرنسية', '594'),
    ('GY', 'غيانا', '592'),
    ('GG', 'غيرنزي', '44'),
    ('GN', 'غينيا', '224'),
    ('GQ', 'غينيا الاستوائية', '240'),
    ('GW', 'غينيا بيساو', '245'),
    ('VU', 'فانواتو', '678'),
    ('FR', 'فرنسا', '33'),
    ('PS', 'فلسطين', '970'),
    ('VE', 'فنزويلا', '58'),
    ('FI', 'فنلندا', '358'),
    ('VN', 'فيتنام', '84'),
    ('FJ', 'فيجي', '679'),
    ('CY', 'قبرص', '357'),
    ('QA', 'قطر', '974'),
    ('KG', 'قيرغيزستان', '996'),
    ('KZ', 'كازاخستان', '7'),
    ('NC', 'كاليدونيا الجديدة', '687'),
    ('HR', 'كرواتيا', '385'),
    ('KH', 'كمبوديا', '855'),
    ('CA', 'كندا', '1'),
    ('CU', 'كوبا', '53'),
    ('CW', 'كوراساو', '599'),
    ('KR', 'كوريا الجنوبية', '82'),
    ('KP', 'كوريا الشمالية', '850'),
    ('CR', 'كوستاريكا', '506'),
    ('XK', 'كوسوفو', '383'),
    ('CO', 'كولومبيا', '57'),
    ('KI', 'كيريباتي', '686'),
    ('KE', 'كينيا', '254'),
    ('LV', 'لاتفيا', '371'),
    ('LA', 'لاوس', '856'),
    ('LB', 'لبنان', '961'),
    ('LU', 'لوكسمبورغ', '352'),
    ('LY', 'ليبيا', '218'),
    ('LR', 'ليبيريا', '231'),
    ('LT', 'ليتوانيا', '370'),
    ('LI', 'ليختنشتاين', '423'),
    ('LS', 'ليسوتو', '266'),
    ('MT', 'مالطا', '356'),
    ('ML', 'مالي', '223'),
    ('MY', 'ماليزيا', '60'),
    ('YT', 'مايوت', '262'),
    ('MG', 'مدغشقر', '261'),
    ('EG', 'مصر', '20'),
    ('MK', 'مقدونيا الشمالية', '389'),
    ('MW', 'ملاوي', '265'),
    ('MO', 'منطقة ماكاو الإدارية الخاصة', '853'),
    ('MN', 'منغوليا', '976'),
    ('MR', 'موريتانيا', '222'),
    ('MU', 'موريشيوس', '230'),
    ('MZ', 'موزمبيق', '258'),
    ('MD', 'مولدوفا', '373'),
    ('MC', 'موناكو', '377'),
    ('MS', 'مونتسرات', '1'),
    ('MM', 'ميانمار (بورما)', '95'),
    ('FM', 'ميكرونيزيا', '691'),
    ('NA', 'ناميبيا', '264'),
    ('NR', 'ناورو', '674'),
    ('NP', 'نيبال', '977'),
    ('NG', 'نيجيريا', '234'),
    ('NI', 'نيكاراغوا', '505'),
    ('NZ', 'نيوزيلندا', '64'),
    ('NU', 'نيوي', '683'),
    ('HT', 'هايتي', '509'),
    ('HN', 'هندوراس', '504'),
    ('HU', 'هنغاريا', '36'),
    ('NL', 'هولندا', '31'),
    ('BQ', 'هولندا الكاريبية', '599'),
    ('HK', 'هونغ كونغ الصينية (منطقة إدارية خاصة)', '852'),
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


def masked_phone_number(phone, country_code="", *, hidden_digits=3):
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
    if national_number:
        try:
            hidden_digits = int(hidden_digits)
        except (TypeError, ValueError):
            hidden_digits = 3
        hidden_digits = min(max(1, hidden_digits), len(national_number))
        visible_digits = len(national_number) - hidden_digits
        masked = f"{national_number[:visible_digits]}{'*' * hidden_digits}"
    else:
        masked = "***"
    if dial_code:
        return f"+{dial_code} {masked}"
    return f"+{masked}" if str(phone).strip().startswith("+") else masked
