# Paynkolay UAT - Answered vs Open Questions

Bu dosya CTO/senior engineer'a sorulacak konulari azaltmak icin hazirlandi. Once
elimizdeki dokuman, Postman collection ve CSV dosyalarindan cevaplanabilenleri ayirir;
sadece gercekten eksik kalanlari soru olarak birakir.

## Cevaplanan Konular

### 1. UAT Entegrasyonu Yapilacak mi?

Cevap: Evet. Proje Paynkolay UAT/test ortamina baglanacak sekilde ilerletilecek.

Kullanilacak test VPOS host:

```text
https://paynkolaytest.nkolayislem.com.tr/Vpos
```

Prod host sadece referans:

```text
https://paynkolay.nkolayislem.com.tr/Vpos
```

### 2. Ana Teknik Akis: API Entegrasyonu

Elimizdeki Postman collection ve dokumantasyon, kart bilgisini framework/web UI tarafinda
alip Paynkolay API'ye form-data POST yapabilecegimizi gosteriyor.

Ana endpoint:

```text
POST https://paynkolaytest.nkolayislem.com.tr/Vpos/v1/Payment
```

Postman collection'daki ana payment request alanlari:

- `sx`
- `clientRefCode`
- `successUrl`
- `failUrl`
- `amount`
- `installmentNo`
- `cardHolderName`
- `month`
- `year`
- `cvv`
- `cardNumber`
- `use3D`
- `transactionType`
- `rnd`
- `hashDatav2`
- `environment=API`
- `currencyNumber=949`
- `MerchantCustomerNo`
- `cardHolderIP`
- musteri bilgileri: `namesurname`, `tckn`, `phone`, `email`, `adress`

Sonuc: "Ortak odeme sayfasi mi API mi?" sorusu buyuk olcude cevaplandi. Bu proje icin
ana yol API entegrasyonu olarak alinabilir. Ortak odeme/form dokumani yine hash ve genel
akis referansi olarak kullanilabilir.

### 3. Payment Request Hash

Request `hashDataV2/hashDatav2` sirasi dokumanda ve PHP ornekte net:

```text
sx|clientRefCode|amount|successUrl|failUrl|rnd|customerKey|merchantSecretKey
```

Hesaplama:

1. UTF-8 string.
2. SHA-512 digest.
3. Base64 encode.

Framework'te bu zaten `generate_payment_request_hash` ile mevcut.

### 4. 3DS Baslatma Akisi

3DS zorlamak icin:

```text
use3D=true
```

API v1 dokumani, `use3D=true` oldugunda payment response icinde `BANK_REQUEST_MESSAGE`
donecegini ve bu formun ekranda calistirilacagini soyluyor.

`credentials/base64.md` decode edilince banka/ACS tarafina auto-submit eden bir HTML form
cikiyor. Ornekte su alanlar var:

- form action: `https://torus-stage-ziraat.asseco-see.com.tr/fim/est3Dgate`
- `okurl`: Paynkolay UAT ok URL'i
- `failUrl`: Paynkolay UAT fail URL'i
- `oid`
- `pan`
- `storetype=3D`
- `hashAlgorithm=ver3`

Sonuc: 3DS init ve ACS'e yonlendirme akisi yeterince net. Framework'un mevcut
`BANK_REQUEST_MESSAGE` render destegi bu akisa uygun.

### 5. Success / Fail Donusu ve Response Hash

Dokumantasyondaki odeme sonucu bilgisi su kritik kurali veriyor:

- Sadece `successUrl`'e donmek odemenin basarili oldugu anlamina gelmez.
- Basari icin:
  - `RESPONSE_CODE = 2`
  - `AUTH_CODE` bos, `0` veya `00` olmamali.
- Her donuste `hashDataV2` verify edilmeli.

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

Framework'te bu zaten `generate_payment_response_hash` ile mevcut.

`base64.md` icindeki `okurl` ve `failUrl` Paynkolay'in banka ACS sonrasi kendi UAT
endpointlerine dondugunu gosteriyor. Ancak merchant `successUrl/failUrl`'e final POST
payload'i yine yukaridaki response result alanlariyla beklenmeli.

### 6. PaymentList / Transaction Verification

Islem dogrulama servisi net:

```text
POST https://paynkolaytest.nkolayislem.com.tr/Vpos/Payment/PaymentList
```

Body:

- `sx`: listeleme token'i
- `startDate`: `DD.MM.YYYY`
- `endDate`: `DD.MM.YYYY`
- `clientRefCode`: opsiyonel ama unique kullanilmali
- `hashDatav2`

Hash sirasi:

```text
sx|startDate|endDate|clientRefCode|merchantSecretKey
```

Response icinde `LIST` donuyor. Her kayitta onemli alanlar:

- `REFERENCE_CODE`
- `STATUS`: ornek `SUCCESS` veya `ERROR`
- `TRANSACTION_TYPE`
- `AUTHORIZATION_AMOUNT`
- `CLIENT_REFERENCE_CODE`
- `TRX_DATE`
- `IS_3D`
- `CARD_BANK_NAME`
- `INSTALLMENT_COUNT`

Sonuc: PaymentList final transaction validation kapsamda kullanilabilir.

### 7. Cancel / Refund

Iptal/iade endpoint'i net:

```text
POST https://paynkolaytest.nkolayislem.com.tr/Vpos/v1/CancelRefundPayment
```

Cancel:

- ayni gun yapilan islemler icin
- `type=cancel`

Refund:

- sonraki gunlerde de yapilabilir
- `type=refund`

Body:

- `sx`: cancel/refund token, satis token'inden farkli
- `referenceCode`
- `type`
- `amount`
- `trxDate`: `yyyy.aa.gg`
- `hashDatav2`

Hash sirasi:

```text
sx|referenceCode|type|amount|trxDate|merchantSecretKey
```

Basari kriteri:

```text
responseCode = 2
```

Hash kurallari `04-hash-request.php` sayfasinda ayrica verilmis durumda. Bu nedenle
iptal/iade hash sirasi artik soru degil, resolved contract olarak kabul edilmeli.

### 7.1 Diger Hash Kurallari

`04-hash-request.php` sayfasi sadece odeme request hash'ini degil, diger servislerin hash
siralarini da veriyor.

Resolved hash siralari:

- Odeme/API:
  `sx|clientRefCode|amount|successUrl|failUrl|rnd|customerKey|merchantSecretKey`
- Iptal/iade:
  `sx|referenceCode|type|amount|trxDate|merchantSecretKey`
- Raporlama / PaymentList:
  `sx|startDate|endDate|clientRefCode|merchantSecretKey`
- Pay By Link:
  `sx|full_name|email|gsm|amount|link_expiration_time|merchantSecretKey`
- Duzenli odeme:
  `sx|gsm|amount|clientRefCode|merchantSecretKey`
- Duzenli odeme iptal:
  `sx|InstructionNumber|merchantSecretKey`
- Kart kayit:
  `sx|cardNumber|cvv|merchantSecretKey`
- Kayitli kart listeleme:
  `sx|customerKey|merchantSecretKey`
- Kayitli kart silme:
  `sx|customerKey|tranId|token|merchantSecretKey`
- Sakli karttan odeme:
  `sx|clientRefCode|amount|successUrl|failUrl|rnd|csCustomerKey|merchantSecretKey`

Bu projenin ana scope'u icin ilk uc hash sirasi kritik: odeme, PaymentList ve
cancel/refund.

### 8. Test Kartlari ve OTP

Elimizde kart kaynaklari var:

- `credentials/param_test_kartlari.csv`
- `credentials/param_merchants.csv`
- Paynkolay test kartlari dokuman sayfasi

`param_test_kartlari.csv` icinde bazi kartlar icin `Sifre` kolonu var. Ornek OTP/sifre
degerleri:

- YAPIKREDI karti: sifre var.
- GARANTI kartlari: sifre var.
- DENIZBANK/AKBANK/VAKIFBANK gibi bazi kartlarda `123456` sifre var.

`param_merchants.csv` icinde debit/credit ve ticari kart bilgisi daha net:

- Halk Bankasi karti Debit / Mastercard olarak isaretli.
- Yabanci Kart Debit / Troy olarak isaretli.
- Bazi kartlar ticari kart olarak isaretli.
- Bazi kart aciklamalarinda 3DS sifre notu var.

Sonuc: kart katalogu ve 3DS OTP mapping buyuk olcude CSV'lerden uretilebilir.

### 9. CVV Bazli Hata Kodlari

`param_hata_kodlari.csv` bize negative scenario icin dogrudan mapping veriyor:

- CVV `120` -> `12` / Gecersiz Islem
- CVV `130` -> `13` / Gecersiz Tutar
- CVV `340` -> `34` / Fraud Suphesi
- CVV `370` -> `37` / Calinti Kart
- CVV `510` -> `51` / Limit Yetersiz

Sonuc: Bu hata senaryolari icin ayrica soru sormaya gerek yok; scenario catalog'a
eklenebilir.

### 10. Success / Fail / Callback Endpoint Stratejisi

Karar: Kurum ici endpoint kullanilacak.

Bu nedenle ngrok/tunnel stratejisi artik CTO/senior engineer'a sorulacak bir konu degil.
Framework tarafinda yapilacak is:

- `successUrl` kurum ici endpoint'e ayarlanacak.
- `failUrl` kurum ici endpoint'e ayarlanacak.
- Callback kullanilacaksa callback endpoint de kurum ici host uzerinden verilecek.
- Local FastAPI UI testleri mock/local kalabilir; UAT callback/result capture kurum ici
  endpoint uzerinden yapilir.

### 11. Callback Kapsami ve Hash Yaklasimi

Karar: Callback zorunlu.

Elimizdeki Paynkolay dokumani callback adinda ayri bir hash bolumu gostermiyor; ancak
odeme sonucu ve provider donusu icin `hashDataV2` dogrulamasi net. Bu nedenle UAT
callback payload'i odeme sonucu alanlariyla geliyorsa callback verification da response
hash sirasi ile yapilmali:

```text
MERCHANT_NO|REFERENCE_CODE|AUTH_CODE|RESPONSE_CODE|USE_3D|RND|INSTALLMENT|AUTHORIZATION_AMOUNT|CURRENCY_CODE|MERCHANT_SECRET_KEY
```

`04-hash-request.php` icindeki hash kurallari ise outbound request/servis cagri hash'leri
icin resolved contract olarak kullanilacak:

- Odeme/API request
- Iptal/iade request
- Raporlama / PaymentList request
- Pay By Link request
- Duzenli odeme request
- Kart saklama requestleri

Uygulama notu:

- Mevcut `src/paynkolay_pos/callbacks/verifier.py` generic HMAC mock callback mantigi
  kullaniyor.
- Paynkolay UAT icin callback verifier, gelen Paynkolay result payload'ini parse edip
  `hashDataV2` response hash mantigi ile dogrulayacak sekilde adapte edilmeli.
- Callback payload'i gercek UAT'de success/fail result payload'i ile ayni alanlari
  tasiyorsa mevcut result parser/verifier yeniden kullanilmali.

## Kismen Cevaplanan Konular

### 1. Taksit Destegi

Postman collection'da:

- `installmentNo`
- `PaymentInstallments`
- `GetMerchandInformation`

endpointleri var.

Ancak kart bazinda hangi taksitlerin desteklendigi statik CSV'de net degil.

Uygulama karari:

- Taksit destek bilgisini runtime'da `PaymentInstallments` veya `GetMerchandInformation`
  endpointinden cekmek daha dogru.

Soru olarak sadece su kalir:

- UAT senaryolari icin ozellikle test edilmesi gereken taksit sayilari var mi?

Not: Kullanici karari geregi UAT scenario listesi proaktif olusturulacak. Bu nedenle bu
soru da bloke edici degil; biz 1, 2, 3, 6, 9, 12 gibi makul taksit varyasyonlarini deneyip
desteklenmeyenleri raporda expected/observed olarak isaretleyebiliriz.

## Hala Sorulmasi Gereken Gercek Sorular

### 1. 3DS ACS selector bilgisi

`BANK_REQUEST_MESSAGE` render akisi net, ama banka ACS ekraninda OTP input/submit selector'u
gercek kosumda gorulecek.

```text
3DS OTP ekranini Playwright ile otomatik gecmem bekleniyor mu, yoksa manuel OTP girisi
yeterli mi? Otomatik gecilecekse bilinen ACS selector'lari var mi?
```

### 2. MoTo kapsam netligi

API'de `use3D=false` ile 3DS'siz akisa gidilebilir. Ancak bunun proje icinde MoTo olarak
kabul edilip edilmeyecegi ve hangi kart/merchant ile calisacagi net degil.

```text
MoTo senaryosu icin `use3D=false` yeterli kabul ediliyor mu? Bu akis icin ozel merchant
yetkisi veya kart seti gerekiyor mu?
```

## Proaktif UAT Scenario Listesi

Final scenario listesi icin tekrar onay beklemeyecegiz; elimizdeki kart, OTP, hata kodu ve
endpoint contract'larindan proaktif katalog uretilecek.

Onerilen minimum UAT catalog:

- Basarili 3DS tek cekim.
- Basarili 3DS taksitli.
- 3DS yanlis OTP / fail.
- MoTo / `use3D=false` tek cekim.
- Debit kart odeme.
- Kredi karti odeme.
- Ticari kart odeme.
- CVV `120`: gecersiz islem.
- CVV `130`: gecersiz tutar.
- CVV `340`: fraud suphesi.
- CVV `370`: calinti kart.
- CVV `510`: limit yetersiz.
- PaymentList ile basarili islem dogrulama.
- PaymentList ile hatali islem dogrulama.
- Ayni gun cancel.
- Sonraki gun refund veya refund flow icin uygun mevcut referans varsa refund.

## CTO/Senior Engineer'a Sorulacak Kisa Liste

1. 3DS OTP akisi manuel mi gecilecek, Playwright ile otomatik mi gecilecek? Otomatikse ACS
   selector bilgisi var mi?
2. MoTo icin `use3D=false` yeterli mi, yoksa ozel merchant/kart yetkisi gerekiyor mu?
