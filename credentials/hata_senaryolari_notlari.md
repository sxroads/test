# Hata Senaryolari Notu

Bu not, `param_hata_kodlari.csv`'deki CVV tabanli hatalarin yanina local/mock akista eklenebilecek diger hata siniflarini kaydetmek icin tutulur.

Tokenlar ve sandbox bilgileri yenilendiginde implementasyon bu sirayla tamamlanacak:

## 1. Kart Doğrulama Hatalari

- Gecersiz kart numarasi
- Eksik hane uzunlugu
- Harf iceren PAN
- Luhn fail
- Gecersiz son kullanma tarihi
- Gecmis son kullanma tarihi

## 2. Guvenlik ve 3DS Hatalari

- Yanlis OTP
- OTP suresi dolmus durumda
- 3DS challenge iptali
- 3DS dogrulama basarisizligi
- 3DS kartla MoTo denemesi
- MoTo kartla 3DS beklenmesi

## 3. Bakiye ve Limit Hatalari

- Yetersiz bakiye
- Limit yetersiz
- Ticari kart engeli
- Banka reddi

## 4. Islem Akisi Hatalari

- Duplicate order_id
- Ayni islem icin idempotency ihlali
- Tutar sifir
- Negatif tutar
- Format hatali tutar
- Desteklenmeyen taksit sayisi

## 5. Callback ve Sorgu Hatalari

- Callback signature mismatch
- Callback gelmemesi / timeout
- PaymentList'te islem bulunamamasi
- Cancel / refund icin gecersiz state
- Zaten iptal edilmis islem
- Zaten iade edilmis islem

## 6. Test Matrisi Alanlari

Sonraki implementationda her hata kaydi su alanlarla tutulacak:

- `scenario`
- `input_condition`
- `expected_status`
- `expected_error_code`
- `expected_error_message`
- `notes`

## 7. Uygulama Sirasi

1. Yanlis OTP
2. Gecmis kart / invalid PAN
3. Yetersiz bakiye / limit yetersiz
4. Duplicate order / idempotency
5. Callback signature ve timeout
6. Cancel / refund invalid state
7. Taksit desteklenmiyor

