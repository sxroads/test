# Sandbox Skeleton

Bu dokuman, `PROJECT_GAP_ANALYSIS.md` icindeki kalan isler icin credential gerektirmeden
hazirlanan proje iskeletini aciklar.

## Eklenen Parcalar

### Callback Receiver Skeleton

Dosya:

- `src/paynkolay_pos/callbacks/receiver.py`

Amac:

- Gercek Paynkolay callback payload'ini JSON olarak kabul etmek
- Payload schema validation yapmak
- Callback signature/hash dogrulamak
- Callback'i `CallbackStore` icine yazmak
- HTTP response body'lerinde sensitive data maskelenmis donmek

Bu receiver yeni dependency eklemez; Python stdlib `http.server` uzerinden calisir.
Production server degildir, sandbox E2E testlerinde callback yakalamak icin minimal
test aracidir.

### Sandbox Scenario Template

Dosya:

- `examples/scenarios/sandbox_e2e_scenarios.example.json`

Amac:

- Gercek sandbox kart alias'lari belli olunca kopyalanip private scenario file olarak
  kullanilacak senaryo sozlesmesini hazir tutmak
- 3DS success, 3DS declined, MoTo, taksit ve PaymentList negative case ailelerini
  simdiden modellemek

Gercek kullanimda bu dosyayi repo disina kopyalayip `PAYNKOLAY_SCENARIO_CATALOG` ile
isaretlemek daha dogru olur.

### Sandbox Test Skeleton

Dosya:

- `tests/sandbox/test_sandbox_e2e_skeleton.py`

Amac:

- Private config dosyasinin yuklenebildigini dogrulamak
- Placeholder credential kalmadigini kontrol etmek
- Scenario card alias'larinin config icindeki kartlarla eslestigini kontrol etmek
- Ag cagrisi yapmadan Paynkolay payment form payload ve hash uretimini dogrulamak
- Gercek ag cagrisi testini `PAYNKOLAY_ENABLE_LIVE_E2E=1` kapisi arkasinda tutmak

`PAYNKOLAY_CONFIG_FILE` set edilmemisse bu testler skip olur.

### Makefile Targets

Eklenen komutlar:

- `make sandbox`
- `make sandbox-3ds`
- `make sandbox-moto`
- `make sandbox-report`

Bu komutlar `PAYNKOLAY_CONFIG_FILE` olmadan calismaz. Normal `make check` local/mock
dogrulama olarak kalir.

## Credential Gelince Calisma Sirasi

1. Private config dosyasini hazirla:

```bash
cp examples/config/paynkolay-settings.example.json /path/outside/git/paynkolay-settings.json
```

2. Placeholder alanlari gercek sandbox bilgileriyle doldur:

- `base_url`
- `callback_base_url`
- `merchant_id`
- `terminal_id`
- `api_key`
- `cancel_refund_api_key`
- `secret_key`
- `cards`

3. Sandbox scenario template'ini private dosyaya kopyala:

```bash
cp examples/scenarios/sandbox_e2e_scenarios.example.json /path/outside/git/sandbox-scenarios.json
```

4. Scenario `card_alias` alanlarini private config icindeki gercek kart alias'lariyla
eslestir.

5. Env var'lari set et:

```bash
export PAYNKOLAY_CONFIG_FILE=/path/outside/git/paynkolay-settings.json
export PAYNKOLAY_ENV=uat
export PAYNKOLAY_SCENARIO_CATALOG=/path/outside/git/sandbox-scenarios.json
```

6. Once agsiz sandbox skeleton kontrolunu calistir:

```bash
make sandbox
```

7. Callback receiver kullanilacaksa test callback URL'ini disaridan erisilebilir hale
getir:

```bash
export PAYNKOLAY_CALLBACK_SECRET=replace-with-sandbox-callback-secret
python -m paynkolay_pos.callbacks.receiver
```

Farkli port veya path icin:

```bash
python -m paynkolay_pos.callbacks.receiver --host 127.0.0.1 --port 8081 --path /callbacks/paynkolay
```

8. Gercek ag cagrisi testleri hazirlaninca live gate'i ac:

```bash
export PAYNKOLAY_ENABLE_LIVE_E2E=1
make sandbox
```

## Henuz Bilerek Bos Birakilanlar

- Gercek sandbox credential degerleri
- Gercek 100+ kart katalogu
- Gercek ACS/3DS selector'lari
- Gercek callback URL exposure yontemi
- Paynkolay dokumanindaki nihai field/endpoint farklari
- Live E2E testinin provider'a POST eden son implementasyonu

Bu bosluklar credential ve sandbox sozlesmesi geldikten sonra doldurulacak.
