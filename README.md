# Kodi TV — Django

منصة عربية RTL لإدارة استثمارات الأفلام، مبنية باستخدام Django.

## التشغيل المحلي

يتطلب Python 3.10 أو أحدث.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
py manage.py migrate
py manage.py create_demo_accounts
py manage.py create_missing_wallets
py manage.py runserver
```

افتح `http://127.0.0.1:8000/` للمستخدمين، و`http://127.0.0.1:8000/management/` للوحة الإدارة الخاصة، و`http://127.0.0.1:8000/admin/` لإدارة Django.

حسابا التجربة:

- العميل: الهاتف `123`، كلمة المرور `123`.
- الإدارة: الهاتف `12`، كلمة المرور `12`.

هذه الحسابات للاستخدام المحلي فقط.

## إعداد محافظ TRON

ينشئ التسجيل عنوان TRON مستقلاً لكل حساب. يظهر العنوان للعميل في صفحة الإيداع، ويخزن المفتاح الخاص مشفراً في قاعدة البيانات. صفحة المحافظ تعرض العناوين والأرصدة، وتسمح للمدير الأعلى بكشف المفتاح ونسخه.

قبل استخدام أرصدة حقيقية:

1. أنشئ مفتاح Fernet مرة واحدة:

   ```powershell
   py -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

2. احفظه سراً في متغير البيئة `WALLET_ENCRYPTION_KEY`، واضبط `TRONGRID_API_KEY` من حساب TronGrid. استخدم المفتاح نفسه باستمرار وخزّن نسخة احتياطية آمنة؛ فقدانه يمنع فك تشفير مفاتيح المحافظ. أثناء التطوير المحلي فقط، إذا لم تحدد مفتاح Fernet، يستخدم التطبيق مفتاحاً مشتقاً من `DJANGO_SECRET_KEY`.
3. إذا انتقلت من مفتاح التطوير إلى مفتاح Fernet مستقل، اضبط `WALLET_ENCRYPTION_KEY` ثم شغّل `py manage.py reencrypt_wallet_keys` قبل تغيير `DJANGO_SECRET_KEY`.
4. شغّل Redis (أو اضبط CELERY_BROKER_URL لوسيط متاح)، ثم شغّل الواركر وBeat كلاهما في نافذة منفصلة:
   إذا كان Docker مثبتاً ولا يعمل Redis لديك، شغّله أولاً: docker run --name Kodi TV-redis -p 127.0.0.1:6379:6379 -d redis:7-alpine

   python -m celery -A config worker --pool=solo --loglevel=info
   python -m celery -A config beat --loglevel=info
   شغّل Beat واحداً فقط للجدول.
   في Windows للتطوير المحلي استخدم مجموعة solo للواركر؛ Celery لا يعلن دعم Windows رسمياً، لذلك شغّل مهام Celery في Linux لبيئة الإنتاج.

   يجدول Beat مهمة مزامنة إيداعات TRON كل 5 دقائق افتراضياً (يمكن تغييرها عبر TRON_DEPOSIT_SYNC_INTERVAL_SECONDS). للمزامنة اليدوية لمرة واحدة، استخدم py manage.py sync_tron_deposits أو زر المزامنة في صفحة المحافظ.

الإعداد الافتراضي يستخدم عقد USDT على TRON Mainnet. يمكن تغيير الشبكة أو العقد عبر `TRONGRID_BASE_URL` و`TRON_USDT_CONTRACT`. سجلات TRONGrid المؤكدة هي مصدر الإيداعات التي تُضاف إلى الرصيد؛ يجب إرسال USDT عبر شبكة TRC20 إلى عنوان العميل الصحيح.

## لوحة الإدارة

- **العملاء:** البحث وفتح ملف يحوي معلومات الحساب والأرصدة والاستثمارات والقسائم والإيداعات والسحوبات والدعوات والعمولات.
- **المحافظ:** عناوين TRC20، رصيد كل محفظة، المجموع، نسخ العنوان، وكشف/نسخ المفتاح الخاص للمدير الأعلى.
- **المالية:** إيداعات اليوم، الإجمالي اليومي ومخطط آخر 30 أو 60 أو 90 يوماً، وآخر الإيداعات.
- **الإيداعات:** متابعة الإيداعات المسجلة يدوياً ومراجعتها.

من إعدادات المنصة يمكن ضبط القسائم والسحب والضريبة وعمولات الدعوة. شغّل `py manage.py settle_investments` دورياً لاحتساب الاستثمارات المستحقة. تُراجع طلبات السحب وتُحوّل يدوياً من المشرف.

قبل النشر، اضبط `DJANGO_SECRET_KEY` و`WALLET_ENCRYPTION_KEY` و`TRONGRID_API_KEY` و`DJANGO_DEBUG=0` و`DJANGO_ALLOWED_HOSTS` في بيئة التشغيل.
