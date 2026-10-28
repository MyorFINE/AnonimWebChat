# Anonim Chat by Hevorix

Telegram uslubidagi zamonaviy chat platforma: umumiy guruh chat, shaxsiy yozishmalar (lichka), profillar va a'zolar ro'yxati.
Foydalanuvchilar **hech qanday buyruq yozmaydi** — shunchaki yozishadi. Moderatsiya (mute/ban/admin) tugmalar orqali.
**FastAPI + SQLite + WebSocket**, frontend: vanilla HTML/CSS/JS (qat'iy CSP, inline skript/uslub yo'q, SRI).


## Uchdan-uchga shifrlash (E2EE, v5)

**Maqsad:** xabar matni, fayl mazmuni va fayl nomi serverga **hech qachon** ochiq holda bormaydi. Server, hosting egasi va admin faqat shifrni ko'radi.
Foydalanuvchi chat sarlavhasidagi **🔒 tugmasi** (yoki ☰ → *Shifrlash*) orqali oynacha ochadi: u yerda xabar qanday shifrlanishi, serverga nima ketishi,
server bazasida AYNAN nima yotgani va admin logida nima ko'rinishi **haqiqiy ma'lumot bilan** ko'rsatiladi.

**Qatlamlar:**
1. **Xabar (E2EE):** brauzerda AES-256-GCM bilan shifrlanadi, ECDSA bilan imzolanadi. Server `e2e1:…` konvertini saqlaydi va uzatadi, ocha olmaydi.
2. **Kanal:** brauzer↔server o'rtasida alohida ECDH+AES-GCM kanali (Wireshark/DevTools faqat shifr ko'radi) — v3 dan o'zgarmagan. HTTPS baribir shart.
3. **Bazada:** E2EE konvertlar bazaga o'zgartirilmay yoziladi; eski ma'lumotlar server kalitida shifrlangan.

**E2EE protokoli** (kod: `app/static/js/e2ee.js`, tekshiruvchi: `app/e2ee.py`, Python nusxasi: `tests/e2e_client.py`)
- **Parol:** serverga parolning o'zi bormaydi. Brauzer `PBKDF2-SHA256(parol, SHA256("anonim-chat/e2ee/v1/"+username), 600 000)` dan 512 bit oladi:
  birinchi 256 bit — maxfiy kalitlarni o'rash kaliti (qurilmadan chiqmaydi), ikkinchi 256 bit — serverga ketadigan *kirish kaliti* (server uni yana scrypt bilan hash qiladi).
- **Shaxsiy kalitlar:** har bir foydalanuvchida ECDH P-256 (shifrlash) va ECDSA P-256 (imzo) juftligi. Maxfiy qismi parol kalitida o'ralib serverda *zaxira* sifatida turadi
  (boshqa qurilmadan kirish uchun); qurilmada IndexedDB'da eksport qilib bo'lmaydigan `CryptoKey` sifatida saqlanadi.
- **Lichka:** `HKDF(ECDH(mening maxfiy, uning ommaviy))` → AES-256-GCM kaliti.
- **Umumiy chat:** guruh kaliti (AES-256-GCM, "avlod/epoch"lar bilan). Server unda yo'q: faqat har bir a'zoning ommaviy kaliti bilan o'ralgan nusxa (`room_keys`) bor.
  Birinchi a'zo kalitni yaratadi; kaliti bor onlayn a'zo yangi a'zolar uchun uni o'rab beradi; o'ralgan kalit `check` bilan tekshiriladi (poyga/soxta o'rashga qarshi).
  **Ban/akkaunt o'chirilganda** admin mijozi guruh kalitini yangilaydi (yangi avlod, faqat joriy a'zolarga).
- **Konvert:** `e2e1:` + base64url(JSON{v,k,ep,n,c,s}); AAD = `ac/e2e1|<xona>|<yuboruvchi id>|<epoch>` (shifr boshqa xonaga/yuboruvchiga ko'chirilsa ochilmaydi);
  imzo `ECDSA(AAD‖iv‖shifr)`. Matn 64 baytga to'ldiriladi (uzunlik yashiriladi). Javob (reply), fayl nomi/turi/kaliti — hammasi shifr ichida.
- **Fayllar:** brauzerda har fayl uchun alohida AES kalit bilan shifrlanadi, server `data/media/*.e2e` ni o'zgartirmay saqlaydi. Rasmlar yuborishdan oldin qayta kodlanadi (EXIF/GPS yo'qoladi),
  kichik xira nusxa ham shifr ichida ketadi.
- **Kalit o'zgarishi:** boshqa foydalanuvchilarning barmoq izlari birinchi ko'rilganda qadab qo'yiladi (TOFU); o'zgarsa ogohlantirish chiqadi va lichka bloklanadi (🔒 oynasidan qabul qilinadi).

**Admin nimani ko'radi:** ⋮ → *Xabarlar* va `/logs` — FAQAT shifrlangan konvertlar (epoch, hajm, imzo hajmi). Tahrir/o'chirish tarixi ham faqat shifr. Harakatlar logiga xabar matni yozilmaydi.
**Shikoyat:** server matnni bilmagani uchun shikoyatchi *xohlasa* o'sha BITTA xabar matnini ochib beradi; admin buni o'z qurilmasida asl shifrlangan xabarga solishtirib tekshiradi (✅/⚠).
**Moderatsiya:** mute, ban, o'chirish, sekin rejim, qulf, spamga qarshi — ishlaydi (matn kerak emas). Taqiqlangan so'zlar filtri E2EE'da **ishlamaydi** (server matnni ko'rmaydi).

**Eski akkauntlar va xabarlar:** eski akkaunt birinchi kirishda parolni qayta kiritadi — kalitlar brauzerda yaratiladi, parol hash'i almashadi (`/api/e2ee/setup`).
`@Hevorix` ham shunday o'tadi (shundan keyin `TERMCHAT_ADMIN_PASSWORD` o'zgarishi parolni almashtirmaydi). Eski (E2EE'dan oldingi) xabarlarni server hali o'qiy oladi: ular 🔓 belgisi bilan chiqadi;
ega ularni ⋮ → *Moderatsiya* → *Eski xabarlarni o'chirish* orqali butunlay o'chira oladi. `TERMCHAT_REQUIRE_E2EE=1` (standart) bo'lsa, server ochiq matnli xabarni umuman qabul qilmaydi.

**Muhim chegaralar (halol):**
- Umumiy chat — ochiq guruh: ro'yxatdan o'tgan har kim kalit oladi, shu jumladan o'z qurilmasida admin ham (a'zo sifatida). E2EE serverdan va log/bazadan himoya qiladi, a'zolardan emas.
- Zararli server yashirincha soxta a'zo qo'shib unga kalit o'ratishi mumkin: barmoq izlarini (🔒 → *Kalitlar*) tekshiring.
- Sahifa kodini ham server beradi: SRI tashqi o'zgarishdan himoya qiladi, lekin zararli serverdan emas. To'liq ishonch uchun kodni tekshiring yoki serverni o'zingiz yuriting.
- Metama'lumotlar (kim, qachon, kimga, hajm, IP), profil ma'lumotlari va avatarlar ochiq.
- Parol yo'qolsa, kalit zaxirasini tiklab bo'lmaydi. Lichkada oldinga maxfiylik (forward secrecy) yo'q.
- Brauzerning WebCrypto'si faqat HTTPS/localhost'da ishlaydi; ECDH kanalini faol hujumchidan TLS sertifikati himoya qiladi.

**Boshqa choralar:** SRI (`integrity="sha384-…"` avtomatik), qat'iy CSP, HSTS, `Permissions-Policy`, COOP/CORP, WebSocket `Origin` tekshiruvi, SQL parametrlangan, DOM'ga faqat `textContent`.

## Ovozli xabar (v6)
**Ishlatish:** yozuv maydoni bo'sh bo'lganda 🎤 tugmasi chiqadi. **1-bosish** — yozish boshlanadi (taymer, qizil nuqta), **2-bosish** — to'xtaydi va yuboriladi. 🗑 yoki `Esc` — bekor qilish. Android, iOS va kompyuter brauzerlarida ishlaydi (HTTPS yoki localhost shart; mikrofon ruxsati so'raladi).
Qabul qiluvchida: ▶ / ⏸ tugmasi, progress (bosib o'tish mumkin), vaqt va tezlik (1x / 1.5x / 2x).

**Ovoz o'zgartirish** (`app/static/js/voice.js`, hammasi qurilmada): ovoz **qalinlashtiriladi** (balandligi VA tembri ≈ 3–5 yarim ton pasayadi, tezligi o'zgarmaydi):
mono 16 kHz → past chastota filtri → resampling (r ∈ 0.74…0.82, **har xabarda tasodifiy**) → WSOLA bilan tezlik tiklanadi → 16-bit WAV (metama'lumotsiz). Qalinlikni `SHIFT_MIN/SHIFT_MAX` bilan sozlang.
**Xom ovoz qurilmadan chiqmaydi:** "asl ovozni yuborish" kod yo'li yo'q; o'zgargan ovoz oddiy fayl kabi E2EE bilan shifrlanadi (har xabarga alohida AES-256-GCM kalit, serverda faqat `.e2e` shifr). Server va admin na ovozni, na uning ovoz ekanini biladi.

**Xavfsizlik choralari:**
- `Permissions-Policy: microphone=(self)` (faqat shu sayt; boshqa ruxsatlar yopiq), CSP o'zgarmagan (skript/uslub faqat `'self'`).
- Mikrofon yozuv tugashi/bekor qilinishi bilan **darhol o'chadi** (brauzer indikatori ham). Ilova fonga o'tsa, sahifa yopilsa, chat almashsa, mikrofon uzilsa — yozuv bekor qilinadi (yashirin yozib qolish yo'q).
- Eng ko'pi 5 daqiqa (chegaraga yetsa avtomatik yuboriladi), 0,8 soniyadan qisqasi yuborilmaydi. Mute, qulflangan chat, o'chirilgan akkaunt tekshiruvlari oddiy xabardagidek; yuklash tezligi cheklovi (`/api/e2ee/blob`) amal qiladi.
- Oluvchi tomonda ovoz faqat `audio/wav` bo'lsa va faqat qurilmada ochiladi (`blob:` URL, ijro tugagach/xabar o'chganda bekor qilinadi); "ovozli xabar" belgisiga faqat shifr ichidagi imzolangan ma'lumot asosida ishoniladi.

**Halol chegaralar:** bu *niqoblash*, mutlaq anonimlik emas. Gap uslubi, so'z tanlash, til, urg'u va fon shovqini odamni baribir ayon qilishi mumkin; kuchli maxsus tahlil qiluvchi hujumchi pasaytirishni qisman qaytarishga urinishi mumkin (tasodifiy nisbat buni qiyinlashtiradi). Metama'lumotlar (kim, qachon, kimga, hajm) ochiq qoladi. Kuchliroq niqob kerak bo'lsa `SHIFT_MIN` ni kamaytiring.
Test: `node tests/voice_dsp_test.mjs` (ovoz balandligi pasayishi, davomiylik, WAV, tasodifiy nisbat).

## Yangiliklar (v4)
- **Har qanday fayl, 50 MB gacha**: 📎 tugmasi, Ctrl+V yoki sudrab tashlash. Rasm — metadata tozalanib ko'rsatiladi; video/audio — «ijro etish»; boshqalari (pdf, zip, exe...) faqat yuklab olinadi (hech qachon sahifa sifatida ochilmaydi). Limit: `TERMCHAT_MAX_MEDIA_BYTES`.
- **Fayllar diskda shifrlangan** (`data/media/*.enc`): AES-256-GCM, har bir fayl uchun alohida kalit (master kalit bilan o'ralgan); fayl nomi bazada shifrlangan. Fayl faqat tizimga kirgan foydalanuvchiga beriladi (lichka — faqat ikki ishtirokchiga). Eski ochiq fayllar birinchi ishga tushishda avtomatik shifrlanadi.
- **Media boshqaruvi** (⋮ → *Media boshqaruvi*): umumiy chatdagi fayllar tur/hajm/yuboruvchi bo'yicha filtrlanadi, tanlab o'chiriladi. Fayl nomi va mazmuni ko'rsatilmaydi (adminga ham), lichka fayllari kirmaydi; logga faqat o'chirilgan SON yoziladi.
- **Loglarni o'chirish**: Harakatlar — tanlanganlarni yoki filtrdagi hammasini; Xabarlar — «Tarixni tozalash». Eganing yozuvlarini faqat ega o'chira oladi.
- **Emoji nishon** (galochka o'rniga): ega/adminlar o'zlariga, shuningdek oddiy foydalanuvchilarga ham beradi. 10 ta CSS-animatsiya (puls, sakrash, aylanish, nur, kamalak...), 50+ emoji yoki o'zingiznikini kiriting.
- **Moderatsiya**: ogohlantirishlar (3 tadan keyin 1 soat avtomatik mute, `/warn /unwarn`), foydalanuvchi xabarlarini tozalash (`/purge`), sekin rejim, chatni qulflash, taqiqlangan so'zlar (`so'z*` — prefiks), spamga avtomatik mute, foydalanuvchi shikoyatlari («Shikoyat qilish» → admin *Shikoyatlar*).

## Tezkor ishga tushirish
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python run.py            # http://localhost:8000
```
Docker: `docker compose up -d --build`

**Ega — doim `@Hevorix`.** Bu username band (Hevorix, HEVORIX, hevorix — hammasi band) va ishga tushganda avtomatik yaratiladi.
Paroli `TERMCHAT_ADMIN_PASSWORD` dan olinadi; bermasangiz, birinchi ishga tushishda tasodifiy parol yaratilib **logga bir marta** yoziladi (kirgach profilda almashtiring).
Eski (v1) baza bo'lsa ham bo'ladi: ishga tushganda yangi ustunlar avtomatik qo'shiladi, ma'lumotlar saqlanadi.

## Imkoniyatlar
- **Telegramga o'xshash interfeys**: chap tomonda chatlar ro'yxati (qidiruv, o'qilmagan xabarlar soni), o'ngda suhbat; telefonda to'liq ekranli, orqaga tugmali
- **Xabarlar**: o'zimniki o'ngda, boshqalarniki chapda, bir odamning ketma-ket xabarlari guruhlanadi, kun ajratgichlari, vaqt, "tahrirlangan", lichkada ✓ / ✓✓ (o'qildi)
- **Xabarga amallar** (o'ng tugma / telefonda uzoq bosish / ⌄ tugma): nusxalash, tahrirlash, o'chirish, profilni ko'rish
- **Guruh a'zolari**: chat sarlavhasini bosing — a'zolar ro'yxati (onlayn birinchi, qidiruv bilan). A'zoni bossangiz — uning profili
- **Profil**: rasm, nickname, @username, bio, onlayn holati, qo'shilgan sana, "Xabar yozish" tugmasi
- **Shaxsiy yozishmalar**: istalgan a'zoga lichkada yozish; faqat ikki ishtirokchi ko'radi (adminlar ham ko'rmaydi, `/logs` ga ham tushmaydi)
- **Premium admin dizayni**: ega va adminlarda ismi yonida galochka (tasdiqlangan belgi: egada oltin, adminda binafsha), gradient ism, nurli avatar halqasi, xabar ramkasi, profilda premium banner
- **Moderatsiya** (profil oynasidagi panel; harakatlar logiga yoziladi): mute (10 daqiqa / 1 soat / 1 kun / doimiy), ban/unban; ega esa admin tayinlaydi/oladi. Adminga faqat ega mute/ban qila oladi
- Profil sozlamalari (menyu ☰): 3 tagacha rasm (faollashtirish/o'chirish), nickname, bio, parol, tungi/kunduzgi mavzu
- **Rasm yuborish** (📎 yoki Ctrl+V): izoh (caption) bilan yoki izohsiz, umumiy chatda ham, lichkada ham; bosilsa kattalashadi. Katta fotolar yuborishdan oldin avtomatik kichraytiriladi
- **Javob berish (reply)**: xabarni o'ng tugma / uzoq bosish / ⌄ → «Javob berish»; iqtibos bosilsa asl xabarga o'tadi
- **Profil rangi**: ega va adminlar profil sozlamalarida o'z rangini tanlaydi (ism, galochka, ramka, profil banneri shu rangda)
- **Admin paneli** (faqat adminlarga ko'rinadigan ⋮ tugmasi, chap panel tepasida):
  - *IP lar* — qaysi IP'dan qaysi profil (@username) necha marta kirgan, nechta sessiya/xabar, xato urinishlar; IP yoki username bo'yicha qidirish
  - *Harakatlar* — barcha harakatlar logi (kirish/chiqish, xabar, rasm, tahrir, o'chirish, profil, parol, moderatsiya, blok), IP/username/amal bo'yicha filtr
  - *Bloklanganlar* — IP'ni bloklash/blokdan ochish (spamga qarshi). Bloklangan IP'dan sayt ochilmaydi, ulanishlar darhol uziladi
- Real vaqt (WebSocket), avtomatik qayta ulanish, onlayn/oflayn holati

## Yozish qoidalari
Xabar uzunligi ≤ 1000 belgi; Enter — yuborish, Shift+Enter — yangi qator (telefonda Enter yangi qator, yuborish tugmasi bor). Bo'sh input'da ↑ — oxirgi xabarni tahrirlash.

## WebSocket protokoli (`/ws?k=<kid>`, barcha kadrlar shifrlangan; birinchi kadr `{"a":"<token>"}`)
Quyida shifrlanishdan OLDINGI (ochiq) JSON ko'rsatilgan.
Mijoz → server:
```json
{"type":"send","text":"salom"}                 // umumiy chat
{"type":"send","text":"salom","to":12}         // lichka (user id)
{"type":"send","text":"javob","reply_to":7}      // xabarga javob (rasm: POST /api/messages/image)
{"type":"edit","id":5,"text":"yangi matn"}
{"type":"delete","id":5}
{"type":"read","with":12}                      // lichkani o'qilgan deb belgilash
{"type":"cmd","text":"/mute user 10"}          // moderatsiya (UI tugmalari ishlatadi)
```
Server → mijoz: `init`, `message`, `message_edited`, `message_deleted`, `read`, `presence`, `user_update`, `members_changed`, `system`, `banned`.

## HTTP API (`Authorization: Bearer <token>`; amalda `POST /api/x` shifrlangan konvert ichida)
| Yo'l | Vazifa |
|---|---|
| `POST /api/register` `POST /api/login` `POST /api/logout` `GET /api/me` | kirish |
| `GET /api/username/{name}` | username bo'shmi (katta-kichik harfsiz) |
| `POST /api/messages/image` | rasm + `caption`, `to?`, `reply_to?` (multipart) |
| `GET /api/admin/ips?q=` `GET /api/admin/activity?ip=&user=&action=&before=` `GET /api/admin/messages?q=&state=deleted|edited&before=` (shifrdan ochilgan xabarlar logi) | admin: IP jamlanmasi, harakatlar logi |
| `GET/POST /api/admin/blocks` `POST /api/admin/unblock` | admin: IP bloklash |
| `GET /api/members` | a'zolar + onlayn id'lar (adminga ban/mute holati ham) |
| `GET /api/dialogs` | lichka suhbatlari (oxirgi xabar, o'qilmaganlar) |
| `GET /api/dm/{user_id}` | lichka tarixi |
| `PATCH /api/profile` `{nickname?, bio?, color?}` (`color` — faqat ega/adminlar) | profilni yangilash |
| `POST /api/password` `{old, new}` | parolni almashtirish |
| `GET /api/avatars` `POST /api/avatar` `POST /api/avatars/{id}/use` `DELETE /api/avatars/{id}` `POST /api/avatar/clear` | profil rasmlari |

## Tuzilma
```
app/
  main.py            ilova fabrikasi, xavfsizlik sarlavhalari (CSP), xato ishlovchilar
  config.py          sozlamalar (TERMCHAT_* / .env)
  db.py              SQLite ulanishi, sxema va avtomatik migratsiya
  security.py        scrypt, token hash, RateLimiter
  roles.py errors.py constants.py schemas.py
  repositories/      faqat SQL (users, sessions, messages, avatars, logs)
  services/          biznes mantiq (auth, chat, directory, moderation, avatars, views)
  commands/          moderatsiya buyruqlari reyestri (UI tugmalari shularni chaqiradi)
  realtime/          ConnectionManager + events (xabarni to'g'ri auditoriyaga yetkazish)
  api/               HTTP/WS endpointlar (auth, social, avatars, ws)
  static/            index.html, css/style.css, js/theme.js, js/app.js, js/voice.js (ovozli xabar)
tests/               pytest (test_core: servis+buyruqlar, test_api: HTTP/WS)
deploy/              nginx.conf, systemd unit
```
Rasmlar `data/uploads/`, profil rasmlari `data/avatars/` da (tasodifiy 32 belgili nom bilan, `/uploads/...`).
Qatlamlar: `api/commands → services → repositories → db`. Servislar WebSocket'ni bilmaydi; real vaqt xabarlarini chaqiruvchi (api/commands) `realtime.events` orqali yuboradi: umumiy chat — hammaga, lichka — faqat ikki ishtirokchiga.

## Moderatsiya buyruqlari (ixtiyoriy)
Oddiy foydalanuvchilarga kerak emas. Admin tugmalari ichida shu buyruqlar ishlaydi: `/mute /unmute /ban /unban` (admin), `/addadmin /rmadmin` (ega), `/logs` (o'chirilgan/tahrirlangan umumiy xabarlar logi). Yangi buyruq qo'shish: `app/commands/` ichida `@command(...)`.

## Sozlamalar
`.env.example` ga qarang. Muhimlari: `TERMCHAT_DATA_DIR` (baza va rasmlar), `TERMCHAT_TZ_OFFSET` (`/logs` vaqti).

## Render.com'ga joylash
1. Loyihani GitHub'ga yuklang (`.env` va `data/` `.gitignore` da).
2. Render → **New → Blueprint** → repozitoriyni tanlang (`render.yaml` avtomatik o'qiladi).
3. `TERMCHAT_ADMIN_PASSWORD` so'ralganda **@Hevorix** uchun parol kiriting (kamida 6 belgi).
4. Deploy tugagach saytga kirib `Hevorix` + shu parol bilan kiring.

**Doimiy disk shart:** `render.yaml` da `starter` reja va `/var/data` disk bor. Bepul rejada disk yo'q — bazadagi foydalanuvchilar, xabarlar va rasmlar har qayta ishga tushishda yo'qoladi (shuningdek, bepul xizmat 15 daqiqa harakatsizlikda uxlaydi).
**IP aniqlash:** Render proxy ortida haqiqiy IP `CF-Connecting-IP` dan olinadi. Deploydan keyin admin panelida *IP lar* bo'limida o'z IP'ingiz to'g'ri ko'rinayotganini tekshiring (ichki `10.x` manzillar chiqsa, IP bloklash ishlamaydi).
**Ma'lumot:** harakatlar logi 90 kun saqlanadi (`TERMCHAT_ACTIVITY_DAYS`). Parollar va shaxsiy xabarlar matni/qabul qiluvchisi logga yozilmaydi.

## Production (o'z serveringiz)
- `deploy/nginx.conf` (WebSocket upgrade bilan) + `certbot` orqali HTTPS; `deploy/termchat.service` (systemd).
- **Faqat 1 ta worker** ishga tushiring: onlayn ulanishlar va tezlik limitlari xotirada. Ko'p worker kerak bo'lsa, Redis pub/sub qo'shiladi.
- `--forwarded-allow-ips=*` ni faqat ilova nginx ortida bo'lganda ishlating (klient IP'si limitlar uchun kerak).
- `data/` papkasini zaxiralang (`chat.db` + `avatars/`).

## Testlar
E2EE: `tests/test_e2ee.py` (server xizmatlari + brauzer kodi bilan mosligi, `node` kerak), `node tests/e2e_glue_test.mjs` (app.js E2EE mantig'i), `node tests/e2e_js_interop.mjs` (JS↔Python).
```bash
pip install -r requirements-dev.txt
pytest        # test_core, test_secure (shifrlash), test_api (HTTP/WS)
```

## Xavfsizlik
Parollar scrypt bilan; tokenlar bazada faqat SHA-256 hash; login/ro'yxatdan o'tish/xabar limitlari; qat'iy CSP (inline skript va uslub yo'q); matn DOM'ga `textContent` bilan chiqariladi; rasmlar real imzo bo'yicha tekshiriladi va tasodifiy nom bilan saqlanadi; lichka faqat ishtirokchilarga yetkaziladi va faqat yuboruvchi o'chira oladi.

## Keyingi versiyalar uchun g'oyalar
"yozmoqda…" holati, xonalar (channels), Redis bilan ko'p worker, xabar qidiruvi.
