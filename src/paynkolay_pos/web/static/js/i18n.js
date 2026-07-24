(function () {
  const translations = {
    en: {
      payment: "Payment", parallel: "Parallel", settings: "Settings", reports: "Reports",
      environment_pending: "Environment pending", primary: "Primary navigation",
      language: "Language", turkish: "Turkish", english: "English",
      payment_result: "Payment Result", parallel_tests: "Parallel Tests", parallel_test: "Parallel Test",
      test_cards: "Test Cards", list: "List", close: "Close", add_card: "Add card",
      alias: "Alias", brand: "Brand", card: "Card", month: "Month", year: "Year", cvv: "CVV",
      flow: "Flow", expected_otp: "Expected OTP", save_card: "Save card", search: "Search",
      alias_or_card: "Alias or card", all: "All", secure_3ds: "3D Secure", moto: "MoTo",
      action: "Action", cards_not_loaded: "Cards are not loaded.", card_number: "Card number",
      card_holder: "Card holder", amount: "Amount", currency: "Currency", installment: "Installment",
      one_shot: "Single payment", default_one_shot: "Default: Single payment", three_ds: "3D Secure",
      three_ds_completion: "3DS Completion", manual: "Manual", auto: "Auto", create_payment: "Create payment",
      result: "Result", idle: "Idle", order_id: "Order ID", status: "Status", provider_ref: "Provider ref",
      provider_code: "Provider code", provider_message: "Provider message", request_ref: "Request ref",
      request_card: "Request card", request_flow: "Request flow", three_ds_auto: "3DS automation",
      payment_list: "PaymentList", payment_list_ref: "PaymentList ref", auth_code: "Auth code",
      failure: "Failure", updated: "Updated", execution_profile: "Execution profile", stable_demo: "Stable Demo",
      load_test: "Load Test", mode: "Mode", manual_selection: "Manual selection", random_cards: "Random real cards",
      concurrency: "Concurrency", acs_cap: "ACS concurrency cap", random_count: "Random count", repeat: "Repeat",
      start_parallel: "Start parallel run", run_id: "Run ID", progress: "Progress", success_rate: "Success Rate",
      selected_tests: "Selected Tests", acs_peak: "ACS Peak", throughput: "Throughput", p95: "P95 Duration",
      message: "Message", evidence: "Evidence", time: "Time", parallel_note: "Parallel 3D Secure runs complete automatically and record sanitized ACS automation evidence.",
      runtime: "Runtime", checking: "Checking", environment: "Environment", config_file: "Config file", merchant: "Merchant",
      terminal: "Terminal", cancel_key: "Cancel/refund key", callback: "Callback", readiness: "Readiness", scenarios: "Scenarios", issues: "Issues",
      local_mock_run: "Local Mock Run", tester: "Tester", cards: "Cards", automation: "Automation", scenario_coverage: "Scenario coverage",
      source: "Source", channels: "Channels", final_statuses: "Final statuses", installments: "Installments", error_codes: "Error codes", tags: "Tags",
      loading_configuration: "Loading configuration overview.", allure: "Allure", path: "Path", entrypoint: "Entrypoint",
      latest_run: "Latest Run", results_path: "Results path", total: "Total", status_counts: "Status counts", duration: "Duration", finished: "Finished",
      test: "Test", suite: "Suite", credential_run: "Credential Run", local_mock: "Local/mock", run_now: "Run now",
      started: "Started", exit_code: "Exit code", output_tail: "Output tail", parallel_evidence: "Parallel Evidence", evidence_path: "Evidence path",
      lookup_payment: "Lookup payment", inspect_order: "Enter an order ID to inspect payment state.", three_ds_browser: "3DS Browser",
      add: "Add", remove: "Remove", selection_updated: "Selection updated.", starting: "Starting parallel run", ready: "Ready"
    },
    tr: {
      payment: "Ödeme", parallel: "Paralel", settings: "Ayarlar", reports: "Raporlar",
      environment_pending: "Ortam bekleniyor", primary: "Ana navigasyon", language: "Dil", turkish: "Türkçe", english: "İngilizce",
      payment_result: "Ödeme Sonucu", parallel_tests: "Paralel Testler", parallel_test: "Paralel Test",
      test_cards: "Test Kartları", list: "Listele", close: "Kapat", add_card: "Kart ekle", alias: "Takma ad", brand: "Marka", card: "Kart", month: "Ay", year: "Yıl", cvv: "CVV",
      flow: "Akış", expected_otp: "Beklenen OTP", save_card: "Kartı kaydet", search: "Ara", alias_or_card: "Takma ad veya kart", all: "Tümü", secure_3ds: "3D Secure", moto: "MoTo",
      action: "İşlem", cards_not_loaded: "Kartlar yüklenemedi.", card_number: "Kart numarası", card_holder: "Kart sahibi", amount: "Tutar", currency: "Para birimi", installment: "Taksit",
      one_shot: "Tek çekim", default_one_shot: "Varsayılan: Tek çekim", three_ds: "3D Secure", three_ds_completion: "3DS Tamamlama", manual: "Manuel", auto: "Otomatik", create_payment: "Ödeme oluştur",
      result: "Sonuç", idle: "Hazır", order_id: "Sipariş ID", status: "Durum", provider_ref: "Sağlayıcı referansı", provider_code: "Sağlayıcı kodu", provider_message: "Sağlayıcı mesajı", request_ref: "İstek referansı", request_card: "İstek kartı", request_flow: "İstek akışı", three_ds_auto: "3DS otomasyonu",
      payment_list: "PaymentList", payment_list_ref: "PaymentList referansı", auth_code: "Onay kodu", failure: "Hata", updated: "Güncellendi", execution_profile: "Çalıştırma profili", stable_demo: "Stabil Demo", load_test: "Yük Testi",
      mode: "Mod", manual_selection: "Manuel seçim", random_cards: "Gerçek kartlardan rastgele", concurrency: "Eşzamanlılık", acs_cap: "ACS eşzamanlılık üst sınırı", random_count: "Rastgele adet", repeat: "Tekrar", start_parallel: "Paralel testi başlat", run_id: "Çalışma ID", progress: "İlerleme", success_rate: "Başarı oranı", selected_tests: "Seçilen testler", acs_peak: "ACS tepe değeri", throughput: "İşlem hızı", p95: "P95 süresi", message: "Mesaj", evidence: "Kanıt", time: "Süre", parallel_note: "Paralel 3D Secure testleri otomatik tamamlanır ve temizlenmiş ACS otomasyon kanıtı kaydedilir.",
      runtime: "Çalışma zamanı", checking: "Kontrol ediliyor", environment: "Ortam", config_file: "Yapılandırma dosyası", merchant: "Üye işyeri", terminal: "Terminal", cancel_key: "İptal/iade anahtarı", callback: "Callback", readiness: "Hazırlık durumu", scenarios: "Senaryolar", issues: "Sorunlar", local_mock_run: "Yerel Mock Çalışması", tester: "Testçi", cards: "Kartlar", automation: "Otomasyon", scenario_coverage: "Senaryo kapsamı", source: "Kaynak", channels: "Kanallar", final_statuses: "Son durumlar", installments: "Taksitler", error_codes: "Hata kodları", tags: "Etiketler", loading_configuration: "Yapılandırma özeti yükleniyor.",
      allure: "Allure", path: "Yol", entrypoint: "Giriş noktası", latest_run: "Son Çalışma", results_path: "Sonuç yolu", total: "Toplam", status_counts: "Durum sayıları", duration: "Süre", finished: "Bitiş", test: "Test", suite: "Test grubu", credential_run: "Kimlik Bilgisi Çalışması", local_mock: "Yerel/mock", run_now: "Şimdi çalıştır", started: "Başlangıç", exit_code: "Çıkış kodu", output_tail: "Çıktı sonu", parallel_evidence: "Paralel Kanıt", evidence_path: "Kanıt yolu", lookup_payment: "Ödemeyi sorgula", inspect_order: "Ödeme durumunu incelemek için sipariş ID girin.", three_ds_browser: "3DS Tarayıcı", add: "Ekle", remove: "Kaldır", selection_updated: "Seçim güncellendi.", starting: "Paralel test başlatılıyor", ready: "Hazır"
    }
  };

  Object.assign(translations.en, {
    config: "Config", expiry: "Expiry", save_card: "Save card", cards_not_loaded: "Cards are not loaded.",
    three_ds_completion: "3DS Completion", request_flow: "Request flow", class_name: "Class", three_ds_auto: "3DS Auto",
    lookup_payment: "Lookup payment", ready: "Ready", configured: "Configured", local: "Local", error: "Error",
    running: "Running", completed: "Completed", attention: "Attention", failed: "Failed", add_card: "Add card",
    loading_options: "Loading installment options", runtime_config_not_loaded: "Runtime config not loaded", config_unavailable: "Config unavailable",
    remove: "Remove", selection_updated: "Selection updated.", starting: "Starting parallel run",
    manual_limit: "Manual selection can include at most 150 test items.", report_check: "Checking report status",
    loading_evidence: "Loading evidence", view: "View"
  });
  Object.assign(translations.tr, {
    config: "Yapılandırma", expiry: "Son kullanma", save_card: "Kartı kaydet", cards_not_loaded: "Kartlar yüklenemedi.",
    three_ds_completion: "3DS Tamamlama", request_flow: "İstek akışı", class_name: "Sınıf", three_ds_auto: "3DS Otomasyonu",
    lookup_payment: "Ödemeyi sorgula", ready: "Hazır", configured: "Yapılandırıldı", local: "Yerel", error: "Hata",
    running: "Çalışıyor", completed: "Tamamlandı", attention: "Dikkat", failed: "Başarısız", add_card: "Kart ekle",
    loading_options: "Taksit seçenekleri yükleniyor", runtime_config_not_loaded: "Çalışma zamanı yapılandırması yüklenmedi", config_unavailable: "Yapılandırmaya ulaşılamıyor",
    remove: "Kaldır", selection_updated: "Seçim güncellendi.", starting: "Paralel test başlatılıyor",
    manual_limit: "Manuel seçim en fazla 150 test içerebilir.", report_check: "Rapor durumu kontrol ediliyor",
    loading_evidence: "Kanıt yükleniyor", view: "Görüntüle"
  });

  const language = localStorage.getItem("paynkolay-language") || "en";
  let currentLanguage = translations[language] ? language : "en";

  function translate(key) { return translations[currentLanguage][key] || translations.en[key] || key; }
  function translateStaticText() {
    const textToKey = new Map();
    Object.keys(translations.en).forEach((key) => {
      textToKey.set(translations.en[key], key);
      textToKey.set(translations.tr[key], key);
    });
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach((node) => {
      const parent = node.parentElement;
      if (!parent || ["SCRIPT", "STYLE", "CODE"].includes(parent.tagName)) return;
      const original = node.__paynkolayI18nOriginal || node.textContent.trim();
      const key = textToKey.get(original);
      if (!key) return;
      node.__paynkolayI18nOriginal = original;
      const translated = translate(key);
      const nextText = node.textContent.replace(original, translated);
      if (node.textContent !== nextText) node.textContent = nextText;
    });
  }
  function applyLanguage(next) {
    currentLanguage = translations[next] ? next : "en";
    localStorage.setItem("paynkolay-language", currentLanguage);
    document.documentElement.lang = currentLanguage;
    const pageTitle = document.documentElement.dataset.paynkolayTitle || document.title;
    document.documentElement.dataset.paynkolayTitle = pageTitle;
    const titleKey = { "Paynkolay POS": "payment", "Parallel Tests": "parallel_tests", Settings: "settings", Reports: "reports", "Payment Result": "payment_result" }[pageTitle];
    if (titleKey) document.title = translate(titleKey);
    document.querySelectorAll("[data-i18n]").forEach((element) => { element.textContent = translate(element.dataset.i18n); });
    document.querySelectorAll("[data-i18n-placeholder]").forEach((element) => { element.placeholder = translate(element.dataset.i18nPlaceholder); });
    document.querySelectorAll("[data-i18n-aria-label]").forEach((element) => { element.setAttribute("aria-label", translate(element.dataset.i18nAriaLabel)); });
    translateStaticText();
    document.querySelectorAll("[data-lang-button]").forEach((button) => { button.classList.toggle("active", button.dataset.langButton === currentLanguage); });
    window.dispatchEvent(new CustomEvent("paynkolay-language-change", { detail: currentLanguage }));
  }
  window.PaynkolayI18n = { t: translate, apply: applyLanguage, get language() { return currentLanguage; } };
  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-lang-button]").forEach((button) => button.addEventListener("click", () => applyLanguage(button.dataset.langButton)));
    applyLanguage(currentLanguage);
    const observer = new MutationObserver(() => translateStaticText());
    observer.observe(document.body, { childList: true, subtree: true });
  });
})();
