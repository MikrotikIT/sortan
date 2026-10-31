# نقل إشعارات Firebase إلى خادم جديد

هذا الدليل يشرح إعداد موقع Django وتطبيق Android الحاليين على خادم جديد.

- مشروع Firebase: `kodi-fbcf3`
- معرّف تطبيق Android: `com.twomcrypto.kodi`
- سجل الأجهزة المسجلة: `investments.PushDevice`
- ملف بيئة Django على الخادم: `/etc/sortan.env`

## 1. تجهيز الخادم ونقل الموقع

انشر نسخة الموقع على الخادم الجديد، وثبّت المتطلبات، وانقل قاعدة البيانات وملفات المستخدمين المطلوبة. يجب أن تستخدم النسخة الجديدة قاعدة البيانات نفسها إذا أردت الاحتفاظ بسجلات الأجهزة المسجلة ورموزها.

خصص مساحة دائمة وخاصة لمفتاح Firebase خارج مجلدات الملفات العامة. أضف إلى `/etc/sortan.env`:

```env
DJANGO_PRIVATE_MEDIA_ROOT=/var/lib/sortan/private_media
FIREBASE_PROJECT_ID=kodi-fbcf3
```

أنشئ المجلد واجعل مالكه مستخدم خدمة Django/Celery. اعرف المستخدم والمجموعة الفعليين أولاً، واستبدل `www-data` في الأمر إذا كانت خدماتك تعمل باسم مختلف:

```bash
systemctl show sortan-gunicorn.service sortan-celery.service -p User -p Group
install -d -o www-data -g www-data -m 700 /var/lib/sortan/private_media
```

ثم ثبّت المتطلبات وشغّل فحص إعدادات Django:

```bash
cd /var/www/sortan
/var/www/sortan/venv/bin/pip install -r requirements.txt
/var/www/sortan/venv/bin/python manage.py migrate --noinput
/var/www/sortan/venv/bin/python manage.py check
```

## 2. رفع مفتاح Firebase من لوحة الموقع

1. في Google Cloud Console، ألغِ أي مفتاح خدمة سبق كشفه، وأنشئ مفتاحاً جديداً لحساب خدمة مشروع `kodi-fbcf3`. لا تستخدم الملف الذي سبق كشف محتواه.
2. انشر نسخة الموقع التي تتضمن صفحة إعداد Firebase، ثم أعد تشغيل خدمات الموقع:

   ```bash
   systemctl restart sortan-gunicorn sortan-celery.service sortan-celery-beat.service
   ```

3. سجّل الدخول إلى الموقع بحساب **مدير أعلى (Superuser)**.
4. افتح `/management/firebase-settings/`، واختر ملف JSON الجديد، ثم اضغط «رفع المفتاح». تتحقق الصفحة من نوع الملف ومعرّف المشروع قبل حفظه.

يُحفظ المفتاح على الخادم داخل مساحة `DJANGO_PRIVATE_MEDIA_ROOT` بصلاحيات خاصة؛ لا يُحفظ في قاعدة البيانات ولا يظهر مرة أخرى في الصفحة. بعد الرفع يستطيع نظام الإرسال استخدامه مباشرة. عند استبداله مستقبلاً، ارفع المفتاح الجديد وألغِ القديم من Google Cloud Console.

## 3. إذا كان هناك أكثر من خادم للموقع

كل خادم يشغّل مهام إرسال الإشعارات يحتاج إلى ملف الاعتماد نفسه. ارفع المفتاح من لوحة كل خادم، أو استخدم مساحة تخزين خاصة دائمة ومشتركة بين تلك الخوادم. لا تضع الملف تحت `MEDIA_ROOT` أو `STATIC_ROOT`، ولا ترفعه إلى Git أو إلى تطبيق Android.

## 4. التحقق من تسجيل جهاز

اعرض المنصة ووقت التسجيل فقط؛ لا تطبع قيمة `token` لأنها سر خاص بالجهاز. استبدل `LAST4` بآخر أربعة أرقام من هاتف الحساب:

```bash
/var/www/sortan/venv/bin/python manage.py shell -c "from investments.models import PushDevice; print(list(PushDevice.objects.filter(user__phone__endswith='LAST4').values('platform', 'updated_at')))"
```

إذا لم يظهر الجهاز، افتح التطبيق وسجّل الدخول مع السماح بالإشعارات كي يعيد تسجيل رمزه على الخادم.

## 5. إرسال إشعار اختبار لمستخدم واحد

نفّذ الأمر عبر `systemd-run` ليستخدم ملف بيئة الإنتاج. استبدل `LAST4` بآخر أربعة أرقام من هاتف الحساب:

```bash
systemd-run --wait --pipe --collect \
  -p EnvironmentFile=/etc/sortan.env \
  -p WorkingDirectory=/var/www/sortan \
  /var/www/sortan/venv/bin/python manage.py shell -c "from investments.models import PushDevice; from investments.push_services import send_push_to_user; d=PushDevice.objects.filter(user__phone__endswith='LAST4').select_related('user').first(); assert d, 'No registered device'; print(send_push_to_user(d.user, title='Kodi test', body='Test notification'))"
```

عند نجاح الإرسال يُتوقع ظهور `success_count: 1` و`failure_count: 0`. يجب أن يكون الجهاز متصلاً بالإنترنت وأن تكون إشعارات التطبيق مسموحة. اختبر مستخدماً واحداً أولاً قبل الإرسال للجميع.

## 6. عند تغيير مشروع Firebase

نقل الخادم مع إبقاء المشروع `kodi-fbcf3` لا يتطلب إعادة بناء تطبيق Android. أما الانتقال إلى مشروع Firebase آخر فيتطلب تحديث إعداد الخادم وملف `google-services.json` للتطبيق، ثم إنشاء نسخة Android جديدة وتثبيتها على الأجهزة.

## إلغاء مفتاح خدمة مكشوف

إذا سبق إرسال محتوى ملف الاعتماد في محادثة أو نشره في مكان عام، فاعتبره مكشوفاً: احذفه من صفحة **IAM & Admin → Service Accounts → الحساب → Keys** في Google Cloud Console، ثم أنشئ مفتاحاً بديلاً وارفعه من صفحة إعداد Firebase في الموقع.
