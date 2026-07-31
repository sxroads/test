# Paynkolay Sanal POS Otomasyon ve Test Framework Geliştirme - Genel Bakış

**Son Güncelleme:** Anıl Tangül (N Kolay Bilgi Teknolojileri Genel Müdür Yardımcısı) | [cite_start]1 Temmuz 2026 [cite: 3, 4]
[cite_start]**Kurum:** N Kolay Ödeme ve Elektronik Para Kuruluşu A.Ş. [cite: 5]
[cite_start]**Görev:** Bilgi Teknolojileri - Staj Proje Görevi [cite: 6]

---

## İçindekiler
1. [cite_start]Proje Özeti ve Amacı [cite: 12]
2. [cite_start]Teknik Kapsam ve Gereksinimler [cite: 13]
   - 2.1. [cite_start]Desteklenmesi Gereken Senaryolar [cite: 14]
   - 2.2. [cite_start]Konfigürasyon ve Veri Yönetimi [cite: 15]
   - 2.3. [cite_start]Teknik Beklentiler ve Teslimatlar [cite: 16]
3. [cite_start]Önerilen Teknoloji Yığını (Tech Stack) [cite: 17]
4. [cite_start]Uygulama Adımları ve Yol Haritası [cite: 41]
5. [cite_start]Önemli Tavsiyeler [cite: 58]

---

## 1. Proje Özeti ve Amacı
Bu projenin temel amacı; [cite_start]Paynkolay Sanal POS servislerinin entegrasyon süreçlerini deneyimlemek, finansal teknoloji ekosistemindeki ödeme akışlarını (Payment Rails) öğrenmek ve yüksek hacimli test senaryolarını otomatize edebilen kurumsal standartlarda bir test framework'ü geliştirmektir[cite: 20].

[cite_start]Farklı kart tipleri, bankalar ve ödeme yöntemleri ile binlerce test senaryosunu "tek tıkla" tetikleyebilen, veri odaklı (Data-Driven) ve raporlama yeteneği olan bir uygulama geliştirilmesi beklenmektedir[cite: 21].

---

## 2. Teknik Kapsam ve Gereksinimler

### 2.1. Desteklenmesi Gereken Senaryolar
[cite_start]Geliştirilecek uygulama, aşağıdaki ödeme akışlarını uçtan uca simüle edebilmelidir[cite: 24]:
* [cite_start]**Ödeme Tipleri:** Tek Çekim, Taksitli İşlemler[cite: 25].
* [cite_start]**Güvenlik Katmanları:** 3D Secure (Browser tabanlı onay süreci dahil) ve MoTo (Mail Order/Telephone Order - 3DS'siz) işlemler[cite: 26].
* [cite_start]**Kart Çeşitliliği:** Farklı bankalara ait Debit ve Kredi kartları[cite: 27].
* [cite_start]**İşlem Hacmi:** Konfigürasyona bağlı olarak birkaç bin adet test işlemini ardışık veya paralel olarak gerçekleştirebilme kapasitesi[cite: 28].

### 2.2. Konfigürasyon ve Veri Yönetimi
[cite_start]Sistem, kod değişikliği gerektirmeden dış kaynaklardan beslenebilir yapıda olmalıdır[cite: 30]:
* [cite_start]**Ortam Yönetimi:** UAT, DEV ve TEST ortam bilgileri konfigüre edilebilir olmalıdır[cite: 31].
* [cite_start]**Merchant Yönetimi:** Test edilecek Üye İşyeri (Merchant) bilgileri dış dosyadan okunmalıdır[cite: 32].
* [cite_start]**Test Veri Seti:** Yaklaşık 100+ kart bilgisi (Kart No, CVV, Expiry Date, 3D OTP vb.) JSON veya benzeri bir formatta tutulmalı ve uygulama tarafından dinamik olarak tüketilmelidir[cite: 33].

### 2.3. Teknik Beklentiler ve Teslimatlar
* [cite_start]**One-Click Execution:** Tüm senaryoların kolayca tetiklenebildiği bir çalıştırma mekanizması[cite: 35].
* [cite_start]**Raporlama:** Test sonuçlarının (Başarı/Hata durumu, Response kodları, İşlem süreleri) özetlendiği profesyonel bir HTML raporu[cite: 36].
* [cite_start]**Dokümantasyon:** Projenin kurulumu, bağımlılıkları, çalıştırma adımları ve mimari anlatımını içeren kapsamlı bir README.md dosyası[cite: 37].

---

## 3. Önerilen Teknoloji Yığını (Tech Stack) / Java yerine Python da tercih edilebilir. Stack opsiyonel!

[cite_start]Fintech dünyasında kabul görmüş kurumsal standartları öğrenmeniz adına aşağıdaki teknoloji yığınının kullanılması şiddetle önerilmektedir[cite: 39]:

| Bileşen | Önerilen Teknoloji | Açıklama |
| :--- | :--- | :--- |
| **Dil** | Java 21+ | [cite_start]Kurumsal uygulama geliştirme standardı. [cite: 40] |
| **Build Tool** | Maven veya Gradle | [cite_start]Bağımlılık ve yaşam döngüsü yönetimi. [cite: 40] |
| **Test Framework** | TestNG | [cite_start]Veri odaklı testler ve `@DataProvider` ile parametrizasyon için. [cite: 40] |
| **API Client** | RestAssured | [cite_start]REST API isteklerinin oluşturulması ve doğrulanması için. [cite: 40] |
| **UI Automation** | Playwright Java | [cite_start]3D Secure browser yönlendirmeleri ve OTP girişleri için. [cite: 40] |
| **Config Mgmt.** | Jackson / Gson | [cite_start]JSON dosyalarının POJO sınıflarına eşlenmesi (Mapping) için. [cite: 40] |
| **Reporting** | Allure / ExtentReports | [cite_start]Görselleştirilmiş, detaylı HTML raporlama için. [cite: 40] |

---

## 4. Uygulama Adımları ve Yol Haritası

### [cite_start]Adım 1: Analiz ve Hazırlık [cite: 42]
* [cite_start]Paynkolay Entegrasyon Dokümanı'nın detaylıca incelenmesi[cite: 43].
* [cite_start]API uç noktalarının (End-points) ve gerekli request/response parametrelerinin belirlenmesi[cite: 45].

### [cite_start]Adım 2: Mimari Tasarım [cite: 46]
* [cite_start]Konfigürasyon dosyalarının (JSON) yapısının tasarlanması[cite: 47].
* [cite_start]Veri katmanı (Data Layer) ve Servis katmanı (Service Layer) ayrımının yapılması[cite: 48].

### [cite_start]Adım 3: Geliştirme (Kodlama) [cite: 49]
* [cite_start]RestAssured ile API entegrasyonunun sağlanması[cite: 51].
* [cite_start]Playwright ile 3D Secure browser akışının kurgulanması[cite: 52].
* [cite_start]TestNG ile veri odaklı test senaryolarının yazılması[cite: 54].

### [cite_start]Adım 4: Raporlama ve Optimizasyon [cite: 55]
* [cite_start]Test sonuçlarının HTML raporuna aktarılması[cite: 56].
* [cite_start]Performans ve stabilite kontrollerinin yapılması[cite: 57].

---

## 5. Önemli Tavsiyeler
* [cite_start]**Yapay Zeka Kullanımı:** Geliştirme sürecinde GitHub Copilot, ChatGPT veya Claude gibi AI araçlarını; kod optimizasyonu, hata ayıklama ve tasarım desenleri (Design Patterns) konusunda kullanmanız gelişiminizi hızlandıracaktır[cite: 59, 60].
* [cite_start]**Hata Yönetimi:** Sadece başarılı senaryoları değil; hatalı kart, yetersiz bakiye, yanlış OTP gibi "Negative Test" senaryolarını da kurgulamanız projenize değer katacaktır[cite: 61].
* [cite_start]**Temiz Kod (Clean Code):** Kodun okunabilirliği, isimlendirme standartları ve modüler yapısı değerlendirme kriterleri arasındadır[cite: 62].

[cite_start]Başarılar dileriz! [cite: 63]