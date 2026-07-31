senaryo arayuzu

kart bilgilerinin oldugu arayuzden kart cekicez.

transaction icin arayuz

otp kodu

otp based callback

error handling - try catch exception handling

kart cesitliligi, ekleme cikarma

kart bilgilerinin girilecegi bi arayuz

expired mi degil mi testi - kart valid mi degil mi testi

param test kartları - nkolay test kartları --> csv dosyasi haline getirip pd data frame uzerinden halledicez.

base64 entegration for otp, formdan otp doldurma sureci

tek cekim ve taksitli islemler

react, web hook

mastercard formu



taksit, pesin kismi



"KART SECIMI DASHBOARD, aliastaki hazir kartlardan ekleyebiliyor olmam lazim tek butonla, alias kisminda kart ekleme butonu olacak, csv guncellenecek. taksit icin servis gelecek, oradan taksit seciliyor. kart secilip tutar girilince servise call -> taksit secenekleri gelecek. default=1, kac islem yapilacaksa ekrana girilecek ona gore playwright paralel bi sekilde oto otp yapacak.

secure ve nonsecure (moto) akislari farkli --> boolean attribute ekleyecegiz csv'ye."


birden fazla ayni karti ekleme ozelligi: ayni karti 10 kere isleme tabi tutma - 5 tane farkli karti ayni anda isleme tabi tutma
playwright ile arkada browser aacilip otomatik otp doldurma
aldigin butun sonuclar console log'a gidiyor, log gorunutluyoruz.
rate limiting islem sayisina limit koyalim, sistem kitlenmesin

3d moto bugini cozucem

secure vs nonsecure : requestler arasindakli fark gozukecek, iki farkli yol var servise gitmede.


-----------------------------


### NOTES ON JUL 14

>>> 2nd troy card w/3ds -> different from the 'provider payment initialization failed', here, initialization has been succeeded. the failure is in the handoff from paynkoaly's returned 3ds form to the actual acs/troy browser challenge.

>>> TROY init succeeds
>>>  -> Paynkolay returns a 3DS gateway form
>>>  -> our UI opens the local form-render route
>>>  -> the returned form is invisible/hidden
>>>  -> the form does not auto-submit
>>>  -> browser stays on a blank white local page

"""

What you see                        What it usually means
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   pending_3ds + 3DS Browser button    Paynkolay init worked and
                                       returned a 3DS form
  ──────────────────────────────────  ──────────────────────────────────
   Blank localhost /three-ds page      Provider form rendered but did
                                       not visibly submit/navigate
  ──────────────────────────────────  ──────────────────────────────────
   Garanti ERR_EMPTY_RESPONSE          Browser reached Garanti ACS, but
                                       Garanti sent no response
  ──────────────────────────────────  ──────────────────────────────────
   “action is failed” page             ACS/gateway rejected the 3DS
                                       action
  ──────────────────────────────────  ──────────────────────────────────
   SMS/OTP page appears                ACS challenge worked; now
                                       manual/OTP step is needed
  ──────────────────────────────────  ──────────────────────────────────
   Same card works later               UAT ACS/simulator behavior is
                                       intermittent or stateful

"""




---------------------------------------------------------------------------------------------------------------
## 3DS Result Handling

Payment initialization success does not mean the ACS challenge will succeed.

It only means Paynkolay returned the data needed to start the 3DS flow. After this point, the issuer bank's ACS controls the result.

For this reason, we should not group every failure as a general **3DS bug**. The framework must classify each result separately:

* `provider_failed`
* `network_error`
* `acs_manual_required`
* `acs_error`
* `blank_or_redirect_error`
* `pending_3ds`
* `completed`

The UAT environment may produce different results for different cards. Some cards are stable, some are intermittent, and some may fail because of:

* issuer bank behavior
* request timing
* ACS availability
* simulator state

These different results are expected and should be recorded with the correct classification.
---------------------------------------------------------------------------------------------------------------

garanti_bankasi_mastercard_2011	MASTERCARD	554960******2011	08/2027	3D Secure
garanti_bankasi_mastercard_6017	MASTERCARD	554960******6017	01/2027	3D Secure

>> bu ikisi direkt olarak sms dogrulamasi istiyor, csv'ye bakip var mi diye inceleyecegiz.


---------------------------------------------------------------------------

> denizbank 3ds page'te problem var, erisilmiyor: local host'ta kaliyor.

> vakifbank basta failed to fetch verdi, sonra kendi kendine duzeldi ve otp sayfasina atip islem basarisiz dedi: banka acs problemi.

---------------------------------------------------------------------------------------------------------------------

is_bankas_troy_1396	TROY	650173******1396	12/2026	3D Secure -> "Payment provider returned a final payment result."

yabanc_kart_troy_8548	TROY	979200******8548	12/2026	3D Secure -> local blank page'te kaldı, acs/banka tarafi problem.

yapikredi_visa_9085	VISA	450634******9085	09/2026	3D Secure -> mobil app akilli bildirime gidiyor, onun disi basarili.

garanti_bankasi_mastercard_2011	MASTERCARD	554960******2011	08/2027	3D Secure -> otp ekranina gidiyor ama islem gerceklestirilemiyor hatasi aliniyor, banka tarafinda problem var.

garanti_bankasi_mastercard_6017	MASTERCARD	554960******6017	01/2027	3D Secure -> gomulu sifre ile calisiyor, sorunsuz.

denizbank_mastercard_8608	MASTERCARD	520019******8608	01/2030	3D Secure -> local blank page'te kaldı, acs/banka tarafi problem.

akbank_visa_5232	VISA	435509******5232	01/2028	3D Secure -> playwright ile otp detection, sorunsuz calisiyor.

akbank_visa_7068	VISA	435509******7068	11/2040	3D Secure -> playwright ile otp detection, sorunsuz calisiyor.

vakifbank_mastercard_0656	MASTERCARD	542119******0656	04/2028	3D Secure -> direkt otp ekranina gidip dogrulama basarisiz diyor.



# testing

> paralel test yaparken: diyelim ki 10 kartla ayni anda test yapiyoruz. herhangi bir hatada akisi kirmadan devam edip hata veren kartta log yapicaz. bunun implemantasyonu nasil olmali, problemi dissect edip adim adim gitmeyi oneriyorum. buna gore de plan generate etmeni isteyecegim senden. once paralel testing'i apply edelim. yani tester arayuzden test sayisini sececek, en basta 10 tane karti ayni anda teste tabi tutmayi deneyelim sonra sirasiyla yukseltiriz test sayisini. sonra kart secimi yapicaz test sayisi icin, iki secenek olacak: 1- istedigimiz kartlari verilen sayida birden fazla kez ya da bir kez secerek yani a kartini 4 kere, b kartini 2 kere c kartini 1 kere secebiliriz 2- sistem rastgele test olusturup teste tabi tutuyo.



Garanti 6017 şu an başarı kartı değil, provider/UAT
tarafında unstable/failed davranıyor. Default başarı smoke için
nkolay_dynamic_otp_visa_6111 veya akbank_visa_7068 kullanmak daha
doğru.


Akbank Visa ortalama 8/10 başarılı oluyor.

NKolay Test Kartı 10/10 başarılı.

PAYNKOLAY_3DS_AUTOMATION_HEADED_FALLBACK=0 \
  make uat-web WEB_PORT=8001 WEB_RELOAD=--reload WEB_3DS_HEADED=0
  WEB_3DS_CLOSE_DELAY=0   ->  headless

PAYNKOLAY_3DS_AUTOMATION_HEADED_FALLBACK=1 \
  make uat-web WEB_PORT=8001 WEB_RELOAD=--reload WEB_3DS_HEADED=1
  WEB_3DS_CLOSE_DELAY=5   -> tabli



 - Garanti Mastercard paralelde stabil değil.
  - Negatif test kartları resmi/stabil veri gelmeden güvenilir
    otomasyona alınamaz.

  - 100-150 paralel test ayrı scaling işi.
  - Installment gerçek endpoint contract’ı yoksa stub/limited kalır.

---------------------------------------------------------------------------------------------------------------

## MERCHANT-BASED SX FEEDBACK — JUL 27

Status: discussion/design note only. No implementation has been requested or made yet.

### Current assumption

- Payment form requests read `sx` from the active runtime merchant config.
- Installment lookups use a separate configured installment `sx`.
- Both values are currently treated as static for the lifetime of the runtime config.
- This worked for the active UAT merchant, including the successful live three-installment
  parallel baseline.

### New requirement

The `sx` included in a provider request is merchant-specific and must be resolved through a
service call. A static runtime value is therefore not sufficient for multiple merchants,
credential rotation, or dynamically issued values.

The most important invariant is:

> The `sx` written to the payment request and the `sx` used while calculating `hashDatav2`
> must be the exact same resolved value.

Changing only the outbound request field would produce a hash mismatch.

### Proposed direction

- Introduce a merchant credential resolver/provider instead of reading `sx` directly from
  settings inside the Paynkolay client.
- Resolve by environment, merchant ID, terminal ID, and operation type when the provider
  contract requires them.
- Keep the current static config implementation for local/mock use.
- Use a service-backed implementation in UAT once its contract is confirmed.
- Never expose resolved `sx` values in API responses, logs, exceptions, or evidence.
- If the value is reusable and expiring, cache it by merchant and operation with an async
  lock to prevent parallel runs from issuing duplicate service calls.
- If it is single-use, resolve a new value for every payment item and do not cache it.
- Fail before sending a provider payment when SX resolution fails.
- Do not silently fall back to a static UAT SX unless that behavior is explicitly approved.

### Contract questions to answer before implementation

1. What are the endpoint, HTTP method, request fields, and response schema?
2. How is the SX service itself authenticated?
3. Is the returned SX permanent, expiring, or single-use?
4. Is it scoped only to merchant ID, or also to terminal/environment?
5. Do payment, installment, PaymentList, and cancel/refund use the same SX or separate
   operation-specific values?
6. Does the service also return merchant secret/terminal metadata?
7. Is merchant selected once per run, or can parallel items belong to different merchants?
8. What refresh/retry behavior is expected when the provider reports an invalid/expired SX?
9. Should a parallel run fail at preflight for a shared merchant lookup failure, or classify
   affected items independently?
10. Is any static UAT fallback permitted?

Until these questions are answered, the current merchant-SX behavior must be treated as a
known architectural assumption, not as the final multi-merchant design.

---------------------------------------------------------------------------------------------------------------

## MERCHANT SETTINGS FOLLOW-UP — JUL 30

Status: approved implementation direction; supersedes the service-backed assumption above
for the current project scope.

- Settings must expose editable Merchant No and primary Payment/Sales SX controls.
- Static starting values come from the ignored runtime credential/config generation path.
- Real Merchant No and SX values must not be committed to tracked files.
- Merchant No may be shown to the local tester. The current SX must never be returned to the
  browser; the password field stays empty and only replaces SX when a new value is entered.
- Updates apply to new single and parallel payment runs. Existing runs retain their
  credential snapshot.
- The updated SX must be used consistently for the outbound `sx` field and `hashDatav2`.
- Paynkolay API v1 does not receive a separate outbound `MERCHANT_NO` form field; that value
  remains merchant context/metadata and a provider result field.
- PaymentList uses the selected Payment/Sales SX. Installment remains private runtime input;
  cancel/refund is out of the current delivery scope.
- Re-running `make uat-web` restores defaults by regenerating the private runtime config.
- A service-backed credential resolver is out of scope unless a provider contract is
  supplied in a later requirement.
