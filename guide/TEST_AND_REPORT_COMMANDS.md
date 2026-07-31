# Test And Report Commands

Bu dokuman, projedeki testleri Makefile komutlariyla calistirmak ve Allure HTML raporu
olusturmak icin kullanilir.

## 1. Standart Kontrol

Tum temel kalite kontrollerini calistirir:

```bash
make check
```

Bu komut sirasiyla sunlari calistirir:

- `poetry check`
- `ruff`
- `mypy`
- `pytest`

Beklenen sonuc:

- lint hatasi olmamali
- type error olmamali
- pytest suite basarili olmali
- sandbox credential gerektiren testler skip olabilir

`make check`, UAT/demo komutu degildir. Temiz local/mock kalite kontrolu icin
calistirilir. Daha once UAT icin export yapildiysa once temizlemek faydalidir:

```bash
unset PAYNKOLAY_CONFIG_FILE
unset PAYNKOLAY_SCENARIO_CATALOG
unset PAYNKOLAY_ENV
unset PAYNKOLAY_ENABLE_LIVE_E2E
make check
```

## 2. Sadece Testleri Calistirma

Tum pytest suite:

```bash
make test
```

Paralel test:

```bash
make parallel
```

## 3. Odakli Test Komutlari

Smoke testler:

```bash
make smoke
```

API/client testleri:

```bash
make api
```

Callback testleri:

```bash
make callback
```

3DS testleri:

```bash
make three-ds
```

Scenario catalogue testleri:

```bash
make scenarios
```

Negative testler:

```bash
make negative
```

## 4. Generated Scale Demo

100 kart ve 1000 scenario uretip mock flow uzerinden calistirir:

```bash
make scale-demo
```

Paralel calistirmak icin:

```bash
make scale-demo-parallel
```

Degerleri override etmek icin:

```bash
make scale-demo COUNT=100 SCENARIO_COUNT=1000
```

## 5. Private Scenario File Ile Test

Private veya generated scenario dosyasini calistirmak icin:

```bash
make scenarios-file SCENARIO_FILE=/tmp/paynkolay-synthetic-scenarios.json
```

## 6. Sandbox Readiness

Gercek odeme calistirmadan private sandbox config ve scenario dosyasini dogrular:

```bash
export PAYNKOLAY_CONFIG_FILE=/path/outside/git/paynkolay-settings.json
export PAYNKOLAY_SCENARIO_CATALOG=/path/outside/git/sandbox-scenarios.json
make sandbox-ready
```

Bu komut:

- placeholder credential var mi kontrol eder
- scenario card alias'lari config kartlariyla eslesiyor mu kontrol eder
- kart sayisi 100+ mi kontrol eder
- MoTo ve 3DS metadata tutarli mi kontrol eder
- sandbox tag'leri var mi kontrol eder

## 7. Sandbox Testleri

Private sandbox config gerektirir:

```bash
make sandbox
```

Sadece sandbox 3DS testleri:

```bash
make sandbox-3ds
```

Sadece sandbox MoTo testleri:

```bash
make sandbox-moto
```

Gercek provider cagrilari default olarak kapali tutulur. Gercek sandbox E2E hazir oldugunda
su gate acilir:

```bash
export PAYNKOLAY_ENABLE_LIVE_E2E=1
make sandbox
```

## 8. UAT Demo Komutlari

Manuel UAT web arayuzu:

```bash
make uat-web
```

UAT web arayuzunu belirli portta ve auto-reload ile acmak:

```bash
make uat-web WEB_PORT=8001 WEB_RELOAD=--reload
```

3DS OTP otomasyonu web akislarda varsayilan olarak headless calisir. Bu mod parallel
testlerde 10 kart icin 10 gorunur Chromium penceresi acmaz; Playwright isi arka planda
yapar.

```bash
make uat-web WEB_PORT=8001 WEB_RELOAD=--reload
```

3DS otomasyonunu gorsel debug icin headed modda acmak gerekirse:

```bash
make uat-web WEB_PORT=8001 WEB_RELOAD=--reload WEB_3DS_HEADED=1 WEB_3DS_CLOSE_DELAY=5
```

Headless override'i acikca vermek istersen:

```bash
make uat-web WEB_PORT=8001 WEB_RELOAD=--reload WEB_3DS_HEADED=0 WEB_3DS_CLOSE_DELAY=0
```

Port doluysa:

```bash
make uat-web WEB_PORT=8001
```

Tarayici:

```text
http://127.0.0.1:8000
http://127.0.0.1:8001
```

Canli UAT 3DS smoke:

```bash
make uat-3ds-smoke
make uat-3ds-smoke UAT_3DS_BROWSER=--headed
```

Canli UAT MoTo + cancel smoke:

```bash
make uat-cancel-smoke
```

Notlar:

- `make uat-web`, manuel demo icin asil komuttur.
- `make uat-web` icin web 3DS otomasyonu default headless'tir; parallel auto 3DS
  kosularda PC'yi kilitleyen coklu gorunur tab/window acilmaz.
- Headed browser sadece debug icin `WEB_3DS_HEADED=1 WEB_3DS_CLOSE_DELAY=5` ile acilir.
- `make uat-3ds-smoke`, terminalden 3DS init/browser evidence toplar.
- `make uat-cancel-smoke`, yeni bir UAT MoTo odeme acar ve ayni gun iptal dener.
- Bu komutlar gercek UAT istegi atar.

## 9. Allure HTML Raporu Olusturma

Allure CLI kurulu degilse:

```bash
brew install allure
```

HTML raporu uretmek icin:

```bash
make report
```

Bu komut:

1. Testleri `--alluredir=allure-results` ile calistirir.
2. `allure-results/` klasorune raw test result dosyalarini yazar.
3. `allure-report/` klasorune HTML rapor uretir.

Raporu acmak icin:

```bash
allure open allure-report
```

Direkt `open allure-report/index.html` kullanma. Allure raporu fetch istekleri kullandigi
icin local server uzerinden acilmalidir.

## 10. Sandbox Raporu

Private sandbox config ile Allure raporu uretmek icin:

```bash
export PAYNKOLAY_CONFIG_FILE=/path/outside/git/paynkolay-settings.json
export PAYNKOLAY_SCENARIO_CATALOG=/path/outside/git/sandbox-scenarios.json
make sandbox-report
allure open allure-report
```

## 11. Temiz Rapor Uretme

Rapor bozuk acilirsa veya eski result dosyalari karistiysa:

```bash
rm -rf allure-results allure-report
poetry run pytest --alluredir=allure-results
allure generate allure-results -o allure-report --clean
allure open allure-report
```

## 12. Temizlik

Generated local artifact'leri temizlemek icin:

```bash
make clean
```

Bu komut cache ve rapor klasorlerini temizler.

## 13. Beklenen Skip'ler

Asagidaki skip'ler normaldir:

- `PAYNKOLAY_CONFIG_FILE` yoksa sandbox testleri skip olur.
- `PAYNKOLAY_ENABLE_LIVE_E2E=1` yoksa gercek provider E2E skip olur.
- Managed terminal socket acmaya izin vermezse callback HTTP integration test skip olabilir.
- Chromium bu ortamda baslamazsa browser-backed 3DS testleri skip olabilir.

Chromium testini normal terminalde dogrulamak icin:

```bash
poetry run pytest tests/three_ds/test_challenge_browser.py -q
```

Beklenen sonuc:

```text
2 passed
```
