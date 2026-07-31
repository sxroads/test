# Technical Deep Dive

Bu dokuman sunum veya teknik soru-cevap sirasinda projeyi savunabilmek icin yazildi.
Amac, sadece "ne yaptik" degil, "neden boyle yaptik" ve "bunu nasil calistirdik" sorularina
hazir olmaktir.

Proje bir production payment gateway degildir. Paynkolay Sanal POS entegrasyonlarini test
etmek, UAT davranisini gozlemlemek, 3D Secure akislarini otomatik veya manuel tamamlamak,
PaymentList ile sonucu dogrulamak ve bunlari okunabilir evidence olarak saklamak icin
gelistirilmis bir test automation platformudur.

## 1. Executive Technical Summary

Sistemin merkezinde FastAPI tabanli bir web/API uygulamasi var. Kullanici UI'dan bir odeme
veya paralel test baslatir. Backend request'i Pydantic modelleriyle validate eder, Paynkolay
form payload'ina cevirir, gerekli hash'i hesaplar, provider'a gonderir, sonucu parse eder ve
session state'e kaydeder.

3D Secure gereken islemlerde Paynkolay'in dondugu banka form HTML'i gecici olarak saklanir.
Bu form ya kullaniciya render edilir ya da Playwright ile arka planda tamamlanir. Otomasyon
sadece guvenli OTP kaynagi bulursa submit eder. Son durumda PaymentList sorgulanir ve nihai
durum evidence'a yazilir.

Projeyi temsil eden ana fikir:

```text
Tester UI / Smoke Tool
        |
        v
FastAPI API Layer
        |
        v
Payment Initializer
        |
        v
Paynkolay Client + Hash Helpers
        |
        v
Paynkolay UAT / Mock Provider
        |
        v
Session + PaymentList + Evidence
```

Bu ayrim sayesinde UI, provider field isimlerini veya hash detaylarini bilmez. Provider
entegrasyonu `clients/`, `models/` ve `security/` katmanlarinda tutulur.

## 2. Neden Bu Mimari Secildi?

Projede uc farkli kullanici tipi var:

- Business analyst: UI'dan kart secer, test calistirir, sonucu okur.
- QA: tekrarli smoke/regression kosulari alir, rapor ve evidence inceler.
- Developer: provider response, ACS ekranlari, PaymentList timing ve framework hatalarini
  ayirir.

Bu yuzden mimari sadece test yazan developer'a gore degil, UI kullanan tester'a da gore
tasarlandi.

Kararlar:

- FastAPI secildi cunku hem browser UI hem JSON API ayni uygulamada sade sekilde sunuluyor.
- Pydantic secildi cunku payment request/response alanlari tipli ve validasyonlu olmali.
- HTTPX async client secildi cunku provider cagrilari ve paralel run'lar async modele uygun.
- Playwright secildi cunku 3D Secure bank/ACS ekranlari gercek browser davranisi istiyor.
- In-memory store secildi cunku proje test automation araci; production kalici DB ihtiyaci yok.
- Evidence sanitization merkezi yapildi cunku kart ve merchant datasi asla loglara sizmamali.

## 3. Web Uygulama Katmani

App factory:

- `src/paynkolay_pos/api/app.py`

Burada FastAPI app olusturulur, static dosyalar mount edilir, HTML template route'lari
tanimlanir ve API router'lari eklenir.

App state icinde uc ana store vardir:

- `PaymentSessionStore`: tekil payment session bilgileri.
- `ThreeDSFormStore`: Paynkolay'dan gelen gecici 3DS HTML formlari.
- `ParallelRunStore`: paralel run ve item state bilgileri.

Bu store'lar process icinde tutulur. Bunun nedeni projenin test araci olmasi ve basit bir
local/UAT workflow hedeflemesidir. Production ortamda bu katman DB veya queue-backed store'a
tasinarak genisletilebilir.

UI route'lari:

- `/`: Payment screen
- `/parallel`: Parallel screen
- `/settings`: Settings screen
- `/reports`: Reports screen
- `/result`: Result lookup screen

API route'lari:

- `/api/payments`
- `/api/parallel-runs`
- `/api/cards`
- `/api/config`
- `/api/reports`
- `/payments/{order_id}/three-ds`
- result/callback endpoint'leri

## 4. Single Payment Flow Nasil Calisiyor?

Tekil payment akisi su sirayla ilerler:

1. UI `POST /api/payments` endpoint'ine request gonderir.
2. Request `PaymentFormRequest` ile validate edilir.
3. Yeni bir order/session olusturulur.
4. `PaynkolayPaymentInitializer.initialize()` cagrilir.
5. Initializer UI request'ini `PaymentInitializeRequest` domain modeline cevirir.
6. `PaynkolayClient.initialize_payment_form()` Paynkolay `/v1/Payment` endpoint'ine gider.
7. Provider response parse edilir.
8. Response final result ise session tamamlanir veya failed olur.
9. Response 3DS init ise session `pending_3ds` olur ve 3DS form saklanir.
10. Final durum PaymentList ile dogrulanir.
11. UI sonucu readable alanlarla gosterir.

Buradaki onemli ayrim: route sadece orchestration yapar. Paynkolay field mapping, hash ve
provider parse isleri route icine yayilmadi.

## 5. Paynkolay Payload ve Hash Nasil Uretildi?

Paynkolay form entegrasyonu provider'in bekledigi field sirasi ve hash kontratina bagli.
Bu yuzden bu is `src/paynkolay_pos/security/paynkolay_hashes.py` ve
`src/paynkolay_pos/clients/paynkolay_client.py` tarafinda tutulur.

Genel yaklasim:

1. Domain request modeli olusturulur.
2. Provider'in bekledigi form field isimlerine map edilir.
3. Hash icin canonical string dokumandaki field sirasi ile kurulur.
4. SHA-512 digest alinir.
5. Base64 encode edilir.
6. `hashDatav2` olarak payload'a eklenir.

Bu tasarim su soruna karsi korur: UI veya test kodu provider'in field isimlerini bilmez.
Provider kontrati degisirse degisiklik client/security katmaninda kalir.

## 6. Response Parsing Nasil Yapildi?

Paynkolay response'lari her zaman ayni sekilde gelmeyebilir. Bazilari final result, bazilari
3DS init, bazilari null/sparse alanlarla gelebilir.

Parser'in temel ayrimi:

- `BANK_REQUEST_MESSAGE` doluysa bu bir 3DS initialize response'dur.
- `BANK_REQUEST_MESSAGE` yoksa veya null ise final provider result olarak parse edilir.

Bu ayrim onemliydi. Cunku UAT'ta `BANK_REQUEST_MESSAGE: null` olan basarili MoTo cevaplari
goruldu. Bunlari 3DS sanmak parser bug'ina yol aciyordu.

Final result tarafinda provider response code, response data, auth code, reference code ve
hash evidence parse edilir. Basarili approval icin hash evidence korunur ve status PaymentList
ile desteklenir.

## 7. UAT Callback Karari

UAT ortaminda callback base URL normal dev/mock gibi path eklenen bir base URL olarak
davranmiyor. Paynkolay tarafindan verilen endpoint final callback URL olarak kullaniliyor:

```text
https://paynkolay.com.tr/test/callback
```

Bu yuzden UAT icin:

- success URL = callback URL
- fail URL = callback URL
- callback URL = callback URL

Dev/mock icin ise path-based davranis korunur:

- `/payments/result/success`
- `/payments/result/fail`
- `/callbacks/paynkolay`

Bu karar `PaynkolayPaymentInitializer._result_urls()` ve `_callback_url()` icinde ayrilir.

## 8. PaymentList Verification Nasil Calisiyor?

Payment initialize response tek basina yeterli kabul edilmedi. Final sonucu Paynkolay
PaymentList ile de dogruluyoruz.

Neden?

- Provider init basarili gorunebilir ama islem listede henuz gorunmeyebilir.
- 3DS callback donmus olabilir ama final status gec yazilabilir.
- Business tarafinin bekledigi kanit genellikle PaymentList row'udur.

Bu nedenle `verify_transaction_status_with_retry()` eklendi:

- ilk deneme hemen yapilir,
- sonra 2s, 5s, 10s backoff ile tekrar denenir,
- sadece status verification seviyesinde retry uygulanir,
- provider initialize ve OTP submit retry edilmez.

Bu ayrim bilincli: odeme baslatma veya OTP submit tekrar denenirse cift islem riski dogar.
PaymentList read-only bir verification oldugu icin retry daha guvenlidir.

## 9. 3D Secure Flow Nasil Calisiyor?

3D Secure akisi iki modda calisir:

- Manual: kullanici ACS ekranini kendisi acar ve tamamlar.
- Auto: Playwright ACS otomasyonu arka planda calisir.

Provider 3DS init response geldiginde:

1. `BANK_REQUEST_MESSAGE` saklanir.
2. Session `pending_3ds` olur.
3. UI'ya `/payments/{order_id}/three-ds` linki verilir.
4. Auto mode secildiyse Playwright otomasyonu baslar.

3DS HTML render katmani:

- HTML bos mu kontrol eder.
- Duz HTML ise form var mi dogrular.
- Base64 ise decode edip form var mi dogrular.
- Raw HTML'i evidence olarak saklamaz.

## 10. ACS Automation Nasil Tasarlandi?

3DS ACS ekranlari banka/simulator'a gore degisir. Bu yuzden otomasyon "tek selector bul,
submit et" gibi basit kurulmamaliydi.

Katmanlar:

- `acs_profile.py`: ekrani classify eder.
- `otp_resolver.py`: OTP kaynaginin guvenli olup olmadigina karar verir.
- `acs_action.py`: sadece izin varsa OTP fill + submit yapar.
- `acs_browser.py`: Playwright browser lifecycle ve frame/page interaction'i yonetir.

Automation strategy:

1. Paynkolay'in verdigi gateway form browser'a set edilir.
2. Form auto-submit degilse form manuel submit edilir.
3. Browser banka/ACS sayfasina gider.
4. Page ve frame evidence sanitize edilerek okunur.
5. ACS profile detect edilir.
6. OTP input selector'u bulunur.
7. OTP source resolve edilir.
8. Resolver `should_auto_submit=true` derse OTP girilir.
9. Submit control bulunur ve tiklanir.
10. Callback URL'e donus beklenir.

Otomasyonun guvenlik kurali:

```text
OTP kaynagi yoksa submit yok.
Manual approval gerekiyorsa submit yok.
Unsupported/error ACS ekraninda submit yok.
```

Bu sayede otomasyon provider ekranina rastgele veri basmaz.

## 11. Headless 3DS Problemi Nasil Cozuldu?

Sorun ilk basta "headless calismiyor, tab acilmadan OTP bulunamiyor" gibi gorunuyordu.
Canli UAT diagnostic sonucunda asil sebep bulundu:

- QNB ACS/simulator headless Chromium'u `HeadlessChrome` user-agent'indan taniyordu.
- Bu durumda ACS normal OTP ekranini gostermek yerine `_404 / 404-QPG97-STATUS` sayfasina
  dusuyordu.
- Sistem bunu once `otp_selector_not_found` gibi gosteriyordu.

Cozum:

- Headless Playwright context icin normal Chrome-like user-agent uretildi.
- Headed mode ayni birakildi.
- QNB `_404 / 404-QPG97-STATUS` ozel olarak `acs_browser_client_rejected` sinifina alindi.
- Dynamic visible OTP kartlar icin static `expected_otp` zorunlulugu kaldirildi.
- ACS frame evidence icinde OTP, hash, token, card-like degerler sanitize edildi.

Sonuc:

- Browser tab acilmadan 3DS tamamlandi.
- UI'da `completed submitted source=visible_page reason=otp_submitted` goruldu.
- PaymentList `captured` dondu.

Sunumda kisa cevap:

```text
Sorun Playwright'in headless olmasi degil, ACS tarafinin HeadlessChrome user-agent'ini
reddetmesiydi. Headless context'i normal Chrome user-agent ile actik, OTP'yi visible page'den
okuduk, submit ettik ve callback + PaymentList ile sonucu dogruladik.
```

## 12. Parallel Testing Nasil Calisiyor?

Parallel run endpoint:

- `POST /api/parallel-runs`
- `GET /api/parallel-runs/{run_id}`
- `GET /api/parallel-runs/{run_id}/items`

Bir run baslatildiginda:

1. Runtime card catalog load edilir.
2. Manual veya random card selection yapilir.
3. Her item icin unique `order_id` uretilir.
4. `ParallelRunState` store'a yazilir.
5. FastAPI `BackgroundTasks` ile run arka planda baslatilir.
6. UI polling ile run durumunu okur.

Concurrency:

- `asyncio.Semaphore` ile ayni anda kac item calisacagi sinirlanir.
- Her item kendi try/except blogunda calisir.
- Bir item fail olursa diger item'lar etkilenmez.
- Sonuc her item seviyesinde kaydedilir.

Manual mode:

- Kullanici kart alias'i ve repeat count secer.
- Toplam item limiti su an 50'dir.

Random mode:

- Sadece real card ve `success_auto` behavior'a sahip kartlar secilir.
- Synthetic, diagnostic, manual-only ve quarantined kartlar random success havuzuna girmez.

3DS diagnostic serialization:

- Bazilari teknik olarak OTP submit edebilir ama parallel'de stabil olmayabilir.
- `AUTOMATION_DIAGNOSTIC` status'teki kartlar icin alias bazli serial lock uygulanir.
- Bu, ayni problemli ACS kartinin birden fazla browser action'ini ayni anda bindirmeyi
  azaltir.

## 13. Neden Kart Davranis Katalogu Var?

Canli UAT'ta her kart ayni kalitede simulator davranisi gostermedi.

Ornekler:

- N Kolay Visa dinamik OTP akisi stabil.
- Akbank 7068 otomatik OTP detection ile basarili.
- Garanti 6017 OTP submit'e kadar gelebiliyor ama parallel otomasyonda browser validation
  veya provider finalization problemi gosterebiliyor.
- Yapi Kredi 9085 mobile app approval gerektiriyor.
- Bazi TROY veya banka kartlari ACS blank/error durumuna dusebiliyor.

Bu nedenle kartlari sadece "3DS kart" diye tek kategoriye koymak yanlis olurdu.

`src/paynkolay_pos/testing/card_behaviors.py` icinde secret icermeyen alias metadata tutulur:

- `success_auto`
- `automation_diagnostic`
- `manual_only`
- `quarantined`
- `unknown`

Bu metadata UI'da ve evidence'ta gorunur. Boylece bir kart neden random success run'a
girmedi veya neden diagnostic sayildi aciklanabilir.

## 14. Evidence Sanitization Nasil Yapildi?

Payment testlerinde evidence kritik ama risklidir. PAN, CVV, OTP, merchant secret, SX,
hash, signature veya raw ACS HTML loglanmamali.

Bu yuzden `src/paynkolay_pos/reporting/evidence.py` merkezi sanitize katmanidir.

Kurallar:

- Pydantic `SecretStr` degerleri redacted olur.
- PAN benzeri alanlar maskelenir.
- Sensitive key'ler recursive olarak redacted olur.
- JSON deterministic pretty formatta yazilir.

ACS browser tarafinda ek koruma:

- six-digit OTP-like degerler redacted,
- 12-19 digit card-like degerler redacted,
- hash/signature/token/CVV/PAN/OTP/password line'lari redacted.

Sunumda kisa cevap:

```text
Evidence ihtiyacini kabul ettik ama data riskini merkezi sanitize katmani ile kapattik.
Test sonucunu anlamaya yarayan metadata kaliyor, secret veya kart verisi kalmiyor.
```

## 15. UI Nasil Tasarlandi?

UI hedef kullanicisi business analyst ve QA oldugu icin teknik log viewer gibi degil,
operasyon paneli gibi tasarlandi.

Ekranlar:

- Payment: tek islem, kart secimi, sonuc ve PaymentList evidence.
- Parallel: toplu kosu, progress, item sonuc tablosu.
- Settings: runtime config ve card catalog.
- Reports: Allure, latest run, credential run ve parallel evidence.

Son polish kararlar:

- Payment ekranina dokunulmadi; stabil ve kullanici flow'u net.
- Settings ekranina dokunulmadi; mevcut hali okunabilir.
- Parallel ekran 720px dar genislikten cikarildi, full panel genisligine alindi.
- Reports ekran full width yapildi.
- Summary alanlari iki kolonlu hale getirildi.
- Uzun tablo stringleri dikey yigilmak yerine daha okunur sekilde kisaltiliyor veya panel
  icinde scroll'a birakiliyor.

Business analyst icin onemli olan:

- "Bu test basarili mi?"
- "Hangi kartla kosuldu?"
- "PaymentList ne dedi?"
- "3DS otomasyon ne yapti?"
- "Evidence nerede?"

UI bu sorulara hizli cevap verecek sekilde sade tutuldu.

## 16. Reports Nasil Calisiyor?

Reports sayfasi uc farkli ihtiyaci toplar:

- Allure report mevcut mu?
- Son credential scenario run sonucu ne?
- Parallel evidence dosyalari neler?

Parallel evidence:

- run bazinda JSON yazilir,
- item bazinda provider request summary, classification, PaymentList status, automation
  summary ve duration tutulur,
- sensitive data sanitize edilir,
- UI'dan run secilip detay JSON'u incelenebilir.

Bu yaklasim sunumda guclu bir nokta: sadece "test calisti" demiyoruz, her item icin neden
basarili veya basarisiz oldugunu kanit olarak sakliyoruz.

## 17. Error Classification Neden Onemli?

Odeme sistemlerinde tum fail'leri ayni hata gibi gostermek yanilticidir.

Bu projede ayrilan baslica siniflar:

- `completed`: beklenen nihai basari.
- `provider_failed`: Paynkolay/banka basarisiz sonuc dondurdu.
- `pending_3ds`: 3DS tamamlanmadan bekliyor.
- `acs_manual_required`: SMS veya mobil approval gibi manuel aksiyon gerekiyor.
- `acs_error`: ACS hata ekrani.
- `acs_browser_client_rejected`: ACS browser client'i reddetti.
- `blank_or_redirect_error`: ACS/banka blank veya local redirect problemine dustu.
- `payment_list_missing`: PaymentList beklenen transaction'i dogrulayamadi.
- `network_error`: provider response oncesi network seviyesinde fail.
- `framework_error`: uygulama tarafinda beklenmeyen exception.

Bu ayrim sayesinde su soruya cevap verilebilir:

```text
Bu bizim bug'imiz mi, provider davranisi mi, banka simulator problemi mi, yoksa eventual
consistency/timing mi?
```

## 18. Test Stratejisi

Testler risk katmanlarina gore ayrildi:

- Unit tests: hash, model, parser, sanitizer, OTP resolver.
- API tests: FastAPI routes, session behavior, result rendering.
- Mocked E2E: provider'a gitmeden payment lifecycle.
- 3DS browser tests: Playwright ile gercek browser interaction.
- Tool tests: UAT smoke script selection ve output behavior.
- Guarded live UAT smoke: explicit command/env olmadan provider'a gitmez.

Guarded live UAT yaklasimi onemli:

- accidental live provider call riski azalir,
- CI/local testler secrets olmadan kosabilir,
- UAT sadece bilincli komutla calisir.

Latest known validation:

```text
poetry run pytest -q    342 passed, 5 skipped
poetry run ruff check . passed
git diff --check        passed
```

## 19. Neden 100-150 Parallel Hemen Acilmadi?

Su an UI/API limiti 50 item.

50 limiti basit bir UI tercihi degil, kontrollu test kapasitesi karari. 100-150 item icin
sadece `max=150` yapmak yeterli olmaz.

Gerekli tasarim konulari:

- browser context memory kullanimi,
- provider/ACS rate limit veya simulator stabilitesi,
- PaymentList eventual consistency,
- evidence dosya boyutu,
- UI polling yukunun artmasi,
- retry/backoff toplam sureleri,
- cancellation/timeout stratejisi,
- per-card serial veya throttled execution.

Bu yuzden 100-150 item task'i ayri bir scaling story olarak ele alinmali.

## 20. Sunumda Gelebilecek Sorular

### "Bu projeyi tek cumlede nasil anlatirsin?"

Paynkolay Sanal POS odeme akislarini UI, API, 3D Secure automation, PaymentList verification
ve sanitized reporting ile tekrarlanabilir sekilde test eden bir QA automation platformu.

### "Neden FastAPI kullandin?"

Hem browser UI hem API endpoint'lerini hafif ve async bir uygulamada toplamak istedim.
Provider cagrilari async oldugu icin FastAPI + HTTPX dogal uydu.

### "3DS'i nasil otomatik tamamladin?"

Paynkolay'in dondugu `BANK_REQUEST_MESSAGE` HTML'ini browser'a yukledim, gateway formunu ACS'e
submit ettim, ACS ekranini profile ettim, guvenli OTP kaynagini resolve ettim ve sadece
`should_auto_submit=true` ise OTP fill + submit yaptim. Sonra callback ve PaymentList ile
dogruladim.

### "Tab acmadan nasil calisti?"

Playwright headless calisiyor. QNB simulator headless browser'i user-agent'dan reddettigi
icin headless context'e normal Chrome-like user-agent verdim. Boylece browser arkada kaldi
ama ACS normal OTP ekranini verdi.

### "Garanti neden parallel'de sorun cikardi?"

Garanti static OTP akisi submit'e kadar gelebiliyor, fakat parallel otomasyonda bazen browser
required-field validation veya provider finalization failure goruldu. Bu nedenle success
pool'dan cikarilip diagnostic status'e alindi. Bu framework crash'i degil, UAT ACS/provider
stability davranisi olarak evidence'a yaziliyor.

### "Neden random mode her karti secmiyor?"

Random mode regression baseline icin var. Bu nedenle sadece `success_auto` kartlari seciyor.
Manual veya diagnostic test icin diger kartlar bilincli olarak secilebilir.

### "PaymentList retry neden var?"

3DS callback'ten hemen sonra PaymentList bazen final row'u gec gosteriyor. Bu eventual
consistency durumunu azaltmak icin read-only PaymentList verification retry edildi. Payment
initialize veya OTP submit retry edilmedi, cunku onlar tekrarlandiginda cift islem riski var.

### "Secret'lari nasil korudun?"

Private config `credentials/` veya `/tmp` altinda. Tracked dosyalarda PAN/CVV/OTP/secret yok.
Evidence merkezi sanitizer'dan geciyor; SecretStr redacted, PAN maskeleniyor, ACS HTML ve
hash/token gibi alanlar saklanmiyor.

### "Bu production'a uygun mu?"

Hayir, amaci production payment gateway olmak degil. Test automation ve UAT validation
platformu. Production icin kalici store, auth, audit, distributed queue ve stricter ops
kontrolleri gerekir.

### "En zor teknik problem neydi?"

Headless 3DS. Ilk belirti OTP selector bulunamiyor gibiydi ama asil sebep ACS'in headless
browser identity'yi reddetmesiydi. Bunu canli UAT evidence ile ayirdik ve user-agent + daha
dogru classification ile cozdum.

### "Bu proje neden guvenilir?"

Her layer testli, provider cagrilari guarded, secret handling merkezi, parallel item'lar
izole, PaymentList ile final status dogrulaniyor ve her sonuc sanitize evidence olarak
saklaniyor.

## 21. Demo Akisi Onerisi

Sunumda teknik derinlik icin iyi akisi:

1. README'den proje amacini goster.
2. UI Payment ekraninda tekil basarili 3DS sonucu goster.
3. Parallel ekraninda 10/50 item run mantigini anlat.
4. Reports ekraninda evidence ve latest run okunabilirligini goster.
5. `card_behaviors.py` ile neden her kartin random'a girmedigini anlat.
6. `acs_browser.py` icinde headless user-agent ve ACS classification kararini goster.
7. `payment_list_retry.py` ile provider eventual consistency icin read-only retry'i anlat.
8. `evidence.py` ile secret redaction'i anlat.

## 22. Kisa Teknik Savunma

Bu proje test automation icin dogru sinirlari ciziyor:

- UI tester dostu.
- Provider kontrati izole.
- 3DS automation kontrollu.
- Parallel execution item bazinda izole.
- Evidence okunabilir ama sanitized.
- Random success pool canli UAT evidence'a dayali.
- Provider/banka hatalari framework hatalarindan ayriliyor.

Bu yuzden proje sadece "calisan script" degil, devredilebilir ve sunulabilir bir test
platformu olarak duruyor.
