(function () {
  async function requestJson(url, options) {
    const response = await fetch(url, {
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      ...options,
    });
    const payload = await response.json();
    if (!response.ok) {
      const detail = Array.isArray(payload.detail)
        ? payload.detail.map((item) => item.msg).join("; ")
        : payload.detail || response.statusText;
      throw new Error(detail);
    }
    return payload;
  }

  window.PaynkolayApi = {
    getConfig() {
      return requestJson("/api/config");
    },
    getConfigOverview() {
      return requestJson("/api/config/overview");
    },
    getMerchantSettings() {
      return requestJson("/api/config/merchant");
    },
    updateMerchantSettings(payload) {
      return requestJson("/api/config/merchant", {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
    },
    getCards() {
      return requestJson("/api/cards");
    },
    createCard(payload) {
      return requestJson("/api/cards", {
        method: "POST",
        body: JSON.stringify(payload),
      });
    },
    getInstallmentOptions(payload) {
      return requestJson("/api/installments/options", {
        method: "POST",
        body: JSON.stringify(payload),
      });
    },
    getLatestReport() {
      return requestJson("/api/reports/latest");
    },
    getReportHistory() {
      return requestJson("/api/reports/history");
    },
    getParallelEvidence() {
      return requestJson("/api/reports/parallel-runs");
    },
    getParallelEvidenceDetail(runId) {
      return requestJson(`/api/reports/parallel-runs/${encodeURIComponent(runId)}`);
    },
    getCredentialReportRun() {
      return requestJson("/api/reports/credential-run");
    },
    startCredentialReportRun() {
      return requestJson("/api/reports/credential-run", {
        method: "POST",
      });
    },
    createParallelRun(payload) {
      return requestJson("/api/parallel-runs", {
        method: "POST",
        body: JSON.stringify(payload),
      });
    },
    getParallelRun(runId) {
      return requestJson(`/api/parallel-runs/${encodeURIComponent(runId)}`);
    },
    createPayment(payload) {
      return requestJson("/api/payments", {
        method: "POST",
        body: JSON.stringify(payload),
      });
    },
    getPayment(orderId) {
      return requestJson(`/api/payments/${encodeURIComponent(orderId)}`);
    },
  };
})();
