# Paynkolay Sandbox Integration Notes

Bu dosya sonraki oturumlarda Paynkolay sandbox entegrasyon bilgisini kaybetmemek icin
tutulur. `credentials/` klasoru git tarafindan ignore ediliyor; yine de token, secret,
PAN, CVV ve OTP gibi degerleri gereksiz yere baska dosyalara veya commit'e tasima.

## Kaynaklar

- Paynkolay entegrasyon ana sayfa:
  `https://paynkolay.com.tr/entegrasyon/`
- Odeme entegrasyon servisleri:
  `https://paynkolay.com.tr/entegrasyon/01-payment-integration-services.php`
- Ornek form kullanimi:
  `https://paynkolay.com.tr/entegrasyon/02-example-form.php`
- Request hash testi:
  `https://paynkolay.com.tr/entegrasyon/04-hash-request.php`
- Odeme sonucu:
  `https://paynkolay.com.tr/entegrasyon/06-payment-result.php`
- Test kartlari:
  `https://paynkolay.com.tr/entegrasyon/07-test-cards.php`
- Odeme iptal/iade:
  `https://paynkolay.com.tr/entegrasyon/09-cancel-refund-payment.php`
- Islem dogrulama servisi:
  `https://paynkolay.com.tr/entegrasyon/10-verification-service.php`

## Local Credential/Input Files

Mevcut local dosyalar:

- `credentials/test_ortam.md`
  - Test ve prod VPOS URL bilgileri.
- `credentials/odeme_entegrasyonu.php`
  - Paynkolay form post ornegi ve `hashDataV2` hesaplama sirasi.
- `credentials/paynkolay.postman_collection.json`
  - Postman koleksiyonu.
- `credentials/paynkolay_merchants.csv`
  - Merchant token/secret benzeri bilgiler.
- `credentials/param_merchants.csv`
  - Kart listesi: banka, kart no, expiry, CVV, ticari kart, kart tipi.
- `credentials/param_test_kartlari.csv`
  - Paynkolay test kartlari: banka, kart semasi, expiry, CVC, 3DS sifre.
- `credentials/param_hata_kodlari.csv`
  - CVV bazli hata kodu ve hata aciklamalari.
- `credentials/base64.md`
  - Base64 encode edilmis 3DS form ornegi.
- `credentials/ornek_3dsecure.png`
  - 3DS ekran ornegi.
- `credentials/ornek_odeme_paneli.png`
  - Odeme paneli ornegi.
- `credentials/hata_senaryolari_notlari.md`
  - Negative scenario fikirleri ve uygulama sirasi.

## Environment URLs

Dokumantasyon ve local notlara gore:

- Test VPOS URL:
  `https://paynkolaytest.nkolayislem.com.tr/Vpos`
- Prod VPOS URL:
  `https://paynkolay.nkolayislem.com.tr/Vpos`

Framework config karsiliklari:

- `base_url`: test icin `https://paynkolaytest.nkolayislem.com.tr`
- payment endpoint path: `/Vpos`
- prod icin ayrica `https://paynkolay.nkolayislem.com.tr`

## Payment Form Flow

Paynkolay ortak odeme/form akisi HTTP POST ile VPOS URL'ine yapiliyor.

Onemli form alanlari:

- `sx`: Web servis token/giris kodu.
- `successUrl`: Basarili islem sonucu POST edilecek URL.
- `failUrl`: Basarisiz islem sonucu POST edilecek URL.
- `amount`: Tutar. Kurus ayraci `.` olmali.
- `currencyCode`: TL icin `949`, USD icin `840`, EUR icin `978`.
- `clientRefCode`: Merchant tarafindaki benzersiz referans/order id.
- `use3D`: `true` gonderilirse 3D Secure zorlanir.
- `rnd`: Islem tarihi/random degeri.
- `agentCode`: Alt temsilci kodu, varsa.
- `transactionType`: Satis icin `SALES`, on provizyon icin `PRESALES`.
- `hashDataV2`: SHA-512 + Base64 request hash.
- `cardHolderIP`: Kart sahibinin IP adresi.
- `instalments`: Taksit sayisi. `1` tek cekim, bos birakilirsa varsayilan davranis.
- `customerKey`: Kart saklama gibi akislar icin kullaniliyor; bos olabilir.
- `detail`: Ortak odeme sayfasinda ek bilgi alinmasi icin opsiyonel.

Dokumantasyondaki akis:

1. Merchant form alanlarini VPOS URL'ine POST eder.
2. Paynkolay form bilgilerini dogrular.
3. Eksik/hata varsa hata mesaji ile akis sonlanir.
4. Dogru ise kart bilgilerinin girilecegi ortak odeme sayfasi veya 3DS akisina gidilir.
5. Basarili sonuc `successUrl` adresine POST edilir.
6. Basarisiz sonuc `failUrl` adresine POST edilir.

## Request Hash: hashDataV2

Ornek form ve dokumantasyona gore request hash string sirasi:

```text
sx|clientRefCode|amount|successUrl|failUrl|rnd|customerKey|merchantSecretKey
```

Hesaplama:

1. String UTF-8 olarak encode edilir.
2. SHA-512 digest alinir.
3. Digest Base64 encode edilir.

Framework'te bunun karsiligi:

- `src/paynkolay_pos/security/paynkolay_hashes.py`
- `hashDataV2` uretimi ve verification testleri.

Kontrol edilmesi gereken nokta:

- Dokumanda `hashDataV2`, bazi response alanlarinda `hashDataV2` veya `hashDatav2`
  yazimi gorulebilir. Parser case/alias toleransli olmali.

## 3D Secure / OTP Notes

3DS zorlamak icin:

```text
use3D=true
```

Mevcut local bilgiler:

- `credentials/param_test_kartlari.csv` icinde bazi kartlarda `Sifre` kolonu var.
- `credentials/param_merchants.csv` icinde bazi kart aciklamalarinda `3DS Sifre`
  notu var.
- `credentials/base64.md` icinde base64 encoded 3DS provider form ornegi var.

Framework tarafinda mevcut destek:

- `BANK_REQUEST_MESSAGE` veya base64 HTML render edilebiliyor.
- `/payments/{order_id}/three-ds` transient 3DS formu gosteriyor.
- Playwright helper generic selector kullaniyor:
  - OTP input: `input[name="otp"]`
  - submit: `button[type="submit"]`

Hala gercek sandbox denemesinde dogrulanacaklar:

- Gercek ACS OTP input selector'u.
- Submit button selector'u.
- Yanlis OTP davranisi.
- Basarili OTP sonrasi redirect sekli.
- Timeout/kullanici iptali davranisi.

## Test Cards

Kart kaynaklari:

- `credentials/param_test_kartlari.csv`
- `credentials/param_merchants.csv`
- Dokumantasyon: `07-test-cards.php`

CSV'lerden uretilecek framework alanlari:

- `alias`: deterministic alias, ornek `garanti_mastercard_001`.
- `pan`: kart numarasi.
- `expiry_month`
- `expiry_year`
- `cvv`
- `bank`
- `scheme`: Visa/MasterCard/Troy/Amex.
- `card_kind`: `credit` veya `debit`.
- `is_commercial`: ticari kart bilgisi varsa.
- `otp`: 3DS sifre kolonu/aciklamasi varsa.
- `supports_3ds`: OTP veya 3DS notu varsa true.
- `supports_moto`: dokumanda net degil; local/mock icin scenario metadata ile set edilebilir.
- `supported_installments`: dokumanda kart bazli net degil; taksit servisinden veya sandbox
  denemeden dogrulanmali.

## Error Codes / Negative Scenarios

`credentials/param_hata_kodlari.csv` icindeki CVV bazli hata ornekleri:

- CVV `120` -> hata kodu `12`, gecersiz islem.
- CVV `130` -> hata kodu `13`, gecersiz tutar.
- CVV `340` -> hata kodu `34`, fraud suphesi.
- CVV `370` -> hata kodu `37`, calinti kart.
- CVV `510` -> hata kodu `51`, limit yetersiz.

Framework scenario uretiminde kullanilacak alanlar:

- `scenario_id`
- `card_alias`
- `amount`
- `currency`
- `use_3d`
- `installments`
- `payment_channel`
- `moto`
- `expected_initial_status`
- `expected_final_status`
- `expected_error_code`
- `expected_error_message`
- `tags`

Ek negative scenario aileleri:

- Yanlis OTP.
- Gecersiz PAN / Luhn fail.
- Gecmis expiry.
- Yetersiz bakiye / limit yetersiz.
- Duplicate `clientRefCode`.
- Unsupported installments.
- PaymentList'te bulunamayan islem.
- Cancel/refund invalid state.
- Callback signature mismatch.
- Callback timeout.

## Payment Result Flow

Paynkolay basarili veya basarisiz sonucu merchant URL'lerine POST ediyor:

- `successUrl`
- `failUrl`

Framework endpointleri:

- `/payments/result/success`
- `/payments/result/fail`

UAT davranisi:

- `callback_base_url` final callback endpoint olarak kullanilir; path eklenmez.

Mevcut framework davranisi:

- GET query veya POST form payload parse eder.
- `hashDataV2` verify eder.
- Payment session state'i final hale getirir.
- Sensitive data gostermeden result page render eder.
- External event logging aciksa sanitized event gonderir.

Gercek sandbox ile dogrulanacaklar:

- Result payload alan adlari.
- Success/fail hash string sirasi.
- Basarili islem status/result code mapping.
- Declined islem status/result code mapping.

## Transaction Verification / PaymentList

Dokumantasyonda "Islem Dogrulama Servisi" bulunuyor.

Mevcut framework'te Paynkolay client tarafinda PaymentList destegi var:

- endpoint path: `/Payment/PaymentList`
- list token alanlari `sx list` ile iliskili.
- Provider row -> internal transaction status mapping mevcut.

Dokumandan netlesen contract:

- Method: `POST`
- URL: `https://paynkolaytest.nkolayislem.com.tr/Vpos/Payment/PaymentList`
- Body type: `multipart/form-data`
- Parametreler:
  - `sx`: zorunlu, listeleme SX degeri.
  - `startDate`: zorunlu, `DD.MM.YYYY`.
  - `endDate`: zorunlu, `DD.MM.YYYY`.
  - `clientRefCode`: opsiyonel; ama her islemde benzersiz kullanilmali.
  - `hashDatav2`: zorunlu.
- Tarih araligi en fazla 1 ay olmali.
- `clientRefCode` bos gonderilirse tarih araligindaki tum islemler doner.
- Ayni `clientRefCode` birden fazla islemde kullanilirsa sorgu birden fazla kayit dondurur.

PaymentList hash sirasi:

```text
sx|startDate|endDate|clientRefCode|merchantSecretKey
```

Basarili servis cevabi:

- Ust seviye `result.RESPONSE_CODE = "2"` servis cagrisinin basarili oldugunu gosterir.
- Odeme basarisi icin asil bakilacak alan `LIST[*].STATUS` alanidir.

Onemli response alanlari:

- `REFERENCE_CODE`
- `AUTH_CODE`
- `AUTHORIZATION_AMOUNT`
- `TRANSACTION_AMOUNT`
- `CLIENT_REFERENCE_CODE`
- `STATUS`
- `TRANSACTION_TYPE`
- `TRX_DATE`
- `CARD_HOLDER_NAME`
- `IS_3D`
- `POS_TYPE`
- `CARD_BANK_NAME`
- `INSTALLMENT_COUNT`
- `DESCRIPTION`

`TRANSACTION_TYPE` degerleri:

- `cancel`
- `refund`
- `sales`

`STATUS` degerleri:

- `SUCCESS`: islem basarili.
- `ERROR`: islem hatali/basarisiz.
- `NEW`: islem baslatilmis ama tamamlanmamis; odeme alinmamis, complete payment methodu
  cagrilmamis veya akista yarida kalmis.

Framework mapping:

- `SUCCESS` -> `captured`
- `ERROR` -> `failed`
- `NEW` -> `created/pending`

Gercek UAT ile yine de gozlenecekler:

- `clientRefCode` ile sorgulama davranisi.
- Bos `LIST` davranisi.
- `DESCRIPTION` alaninin bankaya gore dolu/bos gelme davranisi.
- Ayni clientRefCode ile birden fazla islem donerse en son kaydin secilmesi.

## Reporting Service / PfTransactionReportList

Dokumandaki raporlama servisi PaymentList'ten ayridir.

Contract:

- Method: `POST`
- URL: `https://paynkolaytest.nkolayislem.com.tr/Vpos/Payment/PfTransactionReportList`
- Body type: `multipart/form-data`
- Parametreler:
  - `sx`: zorunlu, listeleme SX degeri.
  - `startDate`: zorunlu, `DD.MM.YYYY`.
  - `endDate`: zorunlu, `DD.MM.YYYY`.
  - `clientReferenceCode`: opsiyonel, merchant referansi.
  - `referenceCode`: opsiyonel, Paynkolay referansi; ornek `IKSIRPF...`.
  - `hashDatav2`: zorunlu.
  - `pageCount`: opsiyonel, 1'den baslayan sayfa indeksi.
  - `pageSize`: opsiyonel, sayfa boyutu.
- Tarih araligi en fazla 1 ay olmali.
- `clientReferenceCode` bos gonderilirse tarih araligindaki islemler doner.
- Dogru sonuc icin `clientReferenceCode` benzersiz kullanilmali.

Raporlama hash sirasi:

```text
sx|startDate|endDate|clientReferenceCode|referenceCode|merchantSecretKey
```

Onemli ayrim:

- `PaymentList` hash sirasi `clientRefCode` ile biter:
  `sx|startDate|endDate|clientRefCode|merchantSecretKey`
- `PfTransactionReportList` hash sirasi hem `clientReferenceCode` hem `referenceCode`
  icerir:
  `sx|startDate|endDate|clientReferenceCode|referenceCode|merchantSecretKey`

Raporlama response formati PaymentList'ten farkli casing kullanir:

- `List`
- `responseCode`
- `responseData`
- row alanlari camelCase:
  - `authCode`
  - `trxDate`
  - `installmentCount`
  - `authorizationAmount`
  - `referenceCode`
  - `clientReferenceCode`
  - `status`
  - `transactionType`
  - `cardHolderName`
  - `is3d`
  - `posType`
  - `currencyCode`

Raporlama `status` degerleri:

- `SUCCESS`
- `ERROR`
- `NEW`

Kullanim karari:

- UAT transaction final validation icin asil servis `PaymentList` olmali.
- Teslim raporu veya operasyonel listeleme gerekiyorsa `PfTransactionReportList` ayrica
  eklenmeli; mevcut parser PaymentList casing'i ile yazildigi icin reporting parser'i ayri
  model istemeli.

## Cancel / Refund

Dokumantasyonda "Odeme Iptal ve Iade" sayfasi var.

Mevcut framework'te cancel/refund destegi var:

- endpoint path: `/v1/CancelRefundPayment`
- `sx iptal` token kullanimi local bilgilerde mevcut.
- Request/response parser ve mocked tests mevcut.

Gercek sandbox ile dogrulanacaklar:

- Satis iptal icin gecerlilik suresi.
- Partial refund destekleniyor mu?
- Ayni isleme ikinci cancel/refund davranisi.
- Declined/failed islemde cancel/refund response'u.
- Expected error code/message mapping.

## Request Hash Rules

Kaynak: `04-hash-request.php`.

Genel kural:

- Her request icin `hashDatav2/hashDataV2` gonderilmeli.
- Hash string UTF-8 encode edilir.
- SHA-512 digest alinir.
- Digest Base64 encode edilir.
- Secret/token degerleri panelden alinmali: `sx`, `sx-list`, `sx-cancel`,
  `merchantSecretKey`.

Resolved hash siralari:

### Ortak Odeme / API Payment

```text
sx|clientRefCode|amount|successUrl|failUrl|rnd|customerKey|merchantSecretKey
```

Notlar:

- Kart saklama hizmeti alinmiyorsa `customerKey` bos string olmalidir.
- Sakli karttan odeme akisi `customerKey` yerine `csCustomerKey` mantigi kullanir.

### Cancel / Refund

```text
sx|referenceCode|type|amount|trxDate|merchantSecretKey
```

### PaymentList / Islem Dogrulama

```text
sx|startDate|endDate|clientRefCode|merchantSecretKey
```

### PfTransactionReportList / Raporlama

```text
sx|startDate|endDate|clientReferenceCode|referenceCode|merchantSecretKey
```

Not: `04-hash-request.php` genel raporlama orneginde sadece `clientRefCode` iceren
formul de gosteriyor; `28-reporting-service.php` sayfasinda `PfTransactionReportList`
icin guncel ve spesifik formul `clientReferenceCode|referenceCode` alanlarini birlikte
kullaniyor. Implementasyonda endpoint'e gore ayrim yap.

### Pay By Link

```text
sx|full_name|email|gsm|amount|link_expiration_time|merchantSecretKey
```

### Duzenli Odeme

```text
sx|gsm|amount|clientRefCode|merchantSecretKey
```

### Duzenli Odeme Iptal

```text
sx|InstructionNumber|merchantSecretKey
```

### Kart Saklama

Kart kaydetme:

```text
sx|cardNumber|cvv|merchantSecretKey
```

Kayitli kart listeleme:

```text
sx|customerKey|merchantSecretKey
```

Kayitli kart silme:

```text
sx|customerKey|tranId|token|merchantSecretKey
```

Sakli karttan odeme:

```text
sx|clientRefCode|amount|successUrl|failUrl|rnd|csCustomerKey|merchantSecretKey
```

### Sigorta Sirketleri TCKN ile Odeme

```text
sx|clientRefCode|amount|successUrl|failUrl|rnd|CardBinNumber|CardLastFour|CardHolderIdentity|merchantSecretKey
```

## Response Hash Rules

Kaynak: `05-hash-response.php`.

Her odeme sonunda donen `hashDataV2` mutlaka kontrol edilmeli. Hash tutmuyorsa islem
guvenli kabul edilmemeli ve akis sonlandirilmali.

Paynkolay'in dondugu `RND`, request hash'te bizim gonderdigimiz `rnd` degeri degildir;
Paynkolay tarafindan olusturulan yeni random degerdir. Response hash hesaplanirken
response payload'undaki `RND` kullanilmalidir.

Response payload ornek alanlari:

- `RESPONSE_CODE`
- `RESPONSE_DATA`
- `REFERENCE_CODE`
- `USE_3D`
- `MERCHANT_NO`
- `AUTH_CODE`
- `CLIENT_REFERENCE_CODE`
- `TIMESTAMP`
- `TRANSACTION_AMOUNT`
- `AUTHORIZATION_AMOUNT`
- `COMMISION`
- `COMMISION_RATE`
- `INSTALLMENT`
- `RND`
- `CURRENCY_CODE`
- `hashData`
- `hashDataV2`

Response hash sirasi:

```text
MERCHANT_NO|REFERENCE_CODE|AUTH_CODE|RESPONSE_CODE|USE_3D|RND|INSTALLMENT|AUTHORIZATION_AMOUNT|CURRENCY_CODE|MERCHANT_SECRET_KEY
```

Basari yorumu:

- `successUrl`'e donmek tek basina basari kaniti degildir.
- Payment result icin `hashDataV2` dogrulanmali.
- Payment success icin `RESPONSE_CODE = 2` ve dolu/gecerli `AUTH_CODE` beklenmeli.
- `AUTH_CODE` bos, `0` veya `00` ise response code tek basina yeterli sayilmamali.

Framework karsiligi:

- `PaynkolayPaymentResult.verify_hash`
- `/payments/result/success`
- `/payments/result/fail`
- `/callbacks/paynkolay`

Callback notu:

- Callback zorunlu kabul edildi.
- Callback payload'i odeme sonucu alanlariyla geldigi surece response hash sirasi ile
  dogrulanacak.
- Generic HMAC callback verifier sadece mock/local callback modeli icin kalabilir;
  Paynkolay UAT callback'i `hashDataV2` odeme sonucu dogrulamasini kullanmali.

## TLS Troubleshooting

Kaynak: `17-tls-errors.php`.

Paynkolay servisleri TLS tarafi guvenli standartlara gore ayarlanmis; hata durumunda
client/OS/runtime uyumlulugu kontrol edilmeli.

Kontrol listesi:

- Minimum TLS 1.2 kullanilmali.
- Eski OS'lerde TLS 1.2 kapali olabilir; OS default TLS ayarlari kontrol edilmeli.
- Windows sunucularda registry uzerinden TLS 1.2 etkinlestirme gerekebilir.
- Linux tarafinda OpenSSL ayarlari ve `/etc/ssl/openssl.cnf` kontrol edilmeli.
- Kullanilan HTTP client/kutuphanenin TLS ayarlari kontrol edilmeli.
- Python icin runtime OpenSSL surumu ve `httpx`/`ssl` stack'i TLS 1.2 desteklemeli.

OpenSSL ciphersuite listeleme:

```bash
openssl ciphers -v
```

Paynkolay baglanti testi ornegi:

```bash
curl -vvv --tlsv1.2 --ciphers TLSv1.2:ECDHE-RSA-WITH-AES_128_GCM_SHA256 https://paynkolay.nkolayislem.com.tr
```

Desteklenen ciphersuite'ler:

- `TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256`
- `TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384`
- `TLS_ECDHE_RSA_WITH_AES_128_CBC_SHA256`
- `TLS_ECDHE_RSA_WITH_AES_256_CBC_SHA384`
- `TLS_ECDHE_RSA_WITH_AES_128_CBC_SHA`
- `TLS_ECDHE_RSA_WITH_AES_256_CBC_SHA`
- `TLS_RSA_WITH_AES_128_GCM_SHA256`
- `TLS_RSA_WITH_AES_256_GCM_SHA384`
- `TLS_RSA_WITH_AES_128_CBC_SHA256`
- `TLS_RSA_WITH_AES_256_CBC_SHA256`
- `TLS_RSA_WITH_AES_128_CBC_SHA`
- `TLS_RSA_WITH_AES_256_CBC_SHA`

UAT run sirasinda TLS hatasi gorulurse:

1. `curl -vvv --tlsv1.2 ...` ile endpoint erisimi test et.
2. Python runtime'in kullandigi OpenSSL surumunu kontrol et.
3. Proxy/kurumsal MITM sertifikasi varsa trust store'u kontrol et.
4. HTTP client timeout ile TLS handshake hatasini ayir.

## Error Codes

Kaynak: `43-error-codes.php`.

Odeme response/hata mapping icin POS hata kodlari:

| Kod | Anlam |
| --- | --- |
| `00` | Onaylandi / islem basarili |
| `01` | Kart bankasini arayiniz |
| `02` | Kart bankasini arayiniz |
| `03` | POS tanimlarini kontrol edin |
| `04` | Bloke edilmis kart / karta el koyunuz |
| `05` | Islem onaylanmadi |
| `06` | Islem onaylanmadi |
| `07` | Bloke edilmis kart / karta el koyunuz |
| `08` | Kart bankasini arayiniz |
| `09` | Tekrar deneyebilirsiniz |
| `11` | Islem gerceklestirildi |
| `12` | Gecersiz islem / Sanal POS tanimsiz islem yetkisi |
| `13` | Islem tutarini kontrol edin |
| `14` | Gecersiz kart numarasi |
| `15` | Tanimsiz kart bankasi / kart bankasini arayiniz |
| `17` | Islem iptal edildi |
| `18` | Kart isleme kapali |
| `19` | Tekrar deneyebilirsiniz |
| `21` | Islem iptal edilemedi |
| `25` | Islem sistemde bulunamadi |
| `26` | Islem onaylanmadi |
| `28` | Islem sistemde bulunamadi |
| `29` | Iptal islemi yapilamadi |
| `30` | Format hatasi nedeniyle basarisiz / tekrar deneyiniz |
| `33` | Bloke edilmis kart / karta el koyunuz |
| `34` | Bloke edilmis kart / karta el koyunuz |
| `36` | Bloke edilmis kart / karta el koyunuz |
| `38` | Hatali sifre deneme sayisi asildi |
| `41` | Kayip kart |
| `43` | Kayip kart |
| `46` | Islem onaylanmadi |
| `51` | Yetersiz bakiye / yetersiz kart limiti |
| `52` | Karta tanimli hesap yok |
| `53` | Karta tanimli hesap yok |
| `54` | Kartin son kullanim tarihi dolmus |
| `55` | Hatali kart sifresi girildi |
| `56` | Gecersiz kart numarasi |
| `57` | Karta izin verilmeyen islem |
| `58` | POS tanimlarini kontrol edin |
| `59` | Supheli islem |
| `60` | Karta izin verilmeyen islem |
| `61` | Kart bankasini arayiniz |
| `62` | Kisitlanmis kart / kendi ulkesinde gecerli kart |
| `63` | Bu islem icin yetkiniz bulunmuyor |
| `65` | Kartin islem limitleri asildi |
| `69` | Kart bankasini arayiniz |
| `75` | Sifre deneme sayisi asildi |
| `76` | Hatali kart sifresi girildi |
| `77` | Uyumsuz veri nedeniyle red |
| `78` | Sifre guvenilir bulunmadi |
| `79` | ARQC hatasi |
| `80` | Kredi karti gecerlilik tarihi hatali |
| `81` | Sifreleme hatasi |
| `82` | CVV hatali |
| `83` | Sifre dogrulama hatasi |
| `84` | CVV hatali |
| `85` | Onaylandi |
| `86` | Sifre dogrulama hatasi |
| `88` | Sifreleme hatasi |
| `89` | Sifre dogrulama hatasi |
| `90` | Tekrar deneyiniz / gun sonu islemleri yapiliyor |
| `91` | Kart bankasi yanit vermiyor |
| `92` | Kart bankasi yanit vermiyor |
| `93` | E-ticaret islemlerine kapali kart |
| `94` | Cift islem gonderme |
| `95` | POS gun sonu hatasi |
| `96` | Kart bankasi yanit vermiyor |
| `98` | Cift islem gonderme |
| `99` | Sistem hatasi |

Local CSV hata senaryolari ile dokuman mapping'i:

- CVV `120` -> kod `12`: gecersiz islem.
- CVV `130` -> kod `13`: tutar kontrolu.
- CVV `340` -> kod `34`: bloke/fraud/karta el koyunuz sinifi.
- CVV `370` -> kod `37`: local CSV'de var; resmi hata kodu tablosunda `37` gorunmedi.
- CVV `510` -> kod `51`: yetersiz bakiye/limit.

Uygulama karari:

- Response code/hata kodu raporda hem numeric code hem aciklama ile yazilmali.
- Resmi tabloda olmayan local CSV kodlari "provider/local test mapping" olarak
  etiketlenmeli.

## Callback Status

Mevcut framework:

- Callback model, verifier ve in-memory store var.
- Local receiver skeleton var.

Dokumantasyondan henuz netlesen konular:

- Callback payload formatini gercek sample ile dogrulamak gerekiyor.
- Callback signature/hash rule'u gercek sample ile dogrulamak gerekiyor.
- Callback gercek E2E icin public callback URL gerektirebilir.

Olasiliklar:

- Local test icin callback mock edilir.
- Gercek sandbox icin ngrok/webhook.site/kurum ici callback endpoint gerekir.

## Current Engineering Plan

1. CSV kartlarini framework private config formatina cevir. `make uat-inputs` eklendi.
2. Merchant/token bilgilerini private UAT config'e parametre olarak ver. Secret degerler
   commit edilmemeli.
3. Test kartlarindan card catalog uret. Mevcut CSV'ler 37 kart veriyor.
4. CVV/hata kodlarindan negative scenario catalog uret. CVV 51 artik
   `insufficient_funds` tag'i aliyor.
5. 3DS OTP kolonlarini scenario metadata'ya bagla.
6. Proaktif UAT scenario coverage uret:
   - 3DS success
   - wrong OTP
   - MoTo success/negative
   - debit/credit
   - 2/3/6/9/12 installment
   - PaymentList
   - cancel
   - refund
   - CVV hata kodlari
7. `make sandbox-ready` calistir.
8. Web UI ile test VPOS'a kontrollu ilk odeme denemesi yap.
9. Kurum ici `/callbacks/paynkolay` endpoint'i ile callback/result payload yakala.
10. Gercek response/result payload'lari maskeli sekilde kaydet.
11. Parser/hash mapping farklari varsa framework'u guncelle.
12. Allure sandbox report uret.

## Added UAT Development Skeleton

Yeni komutlar:

```bash
make uat-config
make uat-inputs
```

Ornek:

```bash
make uat-inputs \
  UAT_CALLBACK_BASE_URL=https://paynkolay.com.tr/test/callback
```

`make uat-inputs` artik asagidaki degerleri ignored credential artifact'larindan otomatik
okur:

- `credentials/paynkolay.postman_collection.json`: `sx`, `sx-list`, `sx-cancel`,
  `merchantSecretKey`
- `credentials/base64.md`: `SUBMERCHANTID` merchant id adayi, `clientid` terminal/client id
  adayi

Explicit `UAT_MERCHANT_ID`, `UAT_TERMINAL_ID`, `UAT_PAYMENT_SX`, `UAT_LIST_SX`,
`UAT_CANCEL_REFUND_SX`, `UAT_SECRET_KEY` verilirse otomatik okunan degerleri ezmez;
sadece `replace-with-*` / local mock placeholder'lari doldurur.

Bu komutlar su dosyalari uretir:

```text
/tmp/paynkolay-uat-settings.json
/tmp/paynkolay-credential-scenarios.json
```

Export:

```bash
export PAYNKOLAY_CONFIG_FILE=/tmp/paynkolay-uat-settings.json
export PAYNKOLAY_SCENARIO_CATALOG=/tmp/paynkolay-credential-scenarios.json
export PAYNKOLAY_ENV=uat
```

Mevcut CSV'lerle son duman testi:

```text
cards=37
scenarios=223
```

Default callback placeholder ile calistirilirsa `make sandbox-ready` su iki uyarıyı verir:

```text
placeholder_value: callback_base_url still contains a placeholder value
insufficient_cards: configured card count is 37; expected at least 100
```

Callback uyarisi beklenen bir deployment girdisi eksigi: local/tunnel kullanmayacagiz, bu
alan deployed/kurum ici uygulama base URL'i olmali. Kart sayisi uyarisi da mevcut veri
eksigi; credential dosyalarinda 100+ gercek kart yok.

FastAPI callback endpoint:

```text
/callbacks/paynkolay
```

Bu endpoint Paynkolay payment-result payload'ini `hashDataV2` ile dogrular. Web session
takip ediliyorsa session state'i final hale getirir; session bilinmiyorsa dogrulanmis
callback'i yine `202 Accepted` ile kabul eder.

## Code Alignment After Contract Review

Paynkolay dokumanlari ile repo karsilastirildiktan sonra yapilan UAT-safety duzeltmeleri:

- `sx-list` icin config'e `list_api_key` alani eklendi.
- `PaymentList` artik `list_api_key` kullanir; geriye uyumluluk icin yoksa `api_key`
  fallback'i vardir.
- `make uat-inputs` artik `UAT_LIST_SX` parametresini alir.
- Sandbox readiness `list_api_key` placeholder/eksik degerini kontrol eder.
- Paynkolay provider response modelleri ekstra alanlari ignore eder. Bunun nedeni gercek
  `PaymentList` response'larinda dokumanda cok sayida ek alan bulunmasidir:
  `CORE_TRX_ID_RESERVED`, `sessionId`, `COMMISION`, `CARD_BANK_CODE`, `USER_EMAIL`,
  `OID`, `POS_TYPE`, `TERMINAL_NAME`, `CARD_BANK_NAME` vb.
- Internal domain/config/scenario modelleri strict kalir; sadece provider payload modelleri
  toleranslidir.

## Open Questions

- 3DS OTP selector ve redirect davranisi nedir?
- Kart bazli taksit destek bilgisi nereden alinacak?
- MoTo icin `use3D=false` yeterli mi, yoksa merchant/kart yetkisi gerekiyor mu?
- 100+ kart hedefi icin ek gercek/UAT kart datasini nereden alacagiz?
- Resmi hata kodu tablosunda olmayan local CSV hata kodlari UAT'de nasil yorumlanacak?

## Safety Notes

- `credentials/` git ignore altinda kalmali.
- Full PAN/CVV/OTP/API key/secret/hash degerleri README, guide veya commit edilen dosyalara
  tasinmamali.
- Allure ve external logs sanitize edilmeli.
- Gercek sandbox testleri explicit gate ile calismali:

```bash
export PAYNKOLAY_CONFIG_FILE=/path/outside/git/paynkolay-settings.json
export PAYNKOLAY_SCENARIO_CATALOG=/path/outside/git/sandbox-scenarios.json
export PAYNKOLAY_ENABLE_LIVE_E2E=1
make sandbox
```
