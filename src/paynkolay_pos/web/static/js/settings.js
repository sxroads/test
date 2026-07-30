(function () {
  const runtimeStatus = document.getElementById("runtime-status");
  const readinessStatus = document.getElementById("readiness-status");
  const cardsStatus = document.getElementById("cards-status");
  const scenariosStatus = document.getElementById("scenarios-status");
  const issueList = document.getElementById("settings-issues");
  const cardTable = document.getElementById("settings-cards");
  const message = document.getElementById("settings-message");
  const merchantForm = document.getElementById("merchant-settings-form");
  const merchantNo = document.getElementById("merchant-no");
  const paymentSx = document.getElementById("payment-sx");
  const paymentSxHint = document.getElementById("payment-sx-hint");
  const merchantSave = document.getElementById("merchant-settings-save");
  const merchantStatus = document.getElementById("merchant-settings-status");
  const merchantMessage = document.getElementById("merchant-settings-message");
  let merchantEnvironment = null;

  const fields = {
    environment: document.getElementById("settings-environment"),
    configSource: document.getElementById("settings-config-source"),
    merchant: document.getElementById("settings-merchant"),
    terminal: document.getElementById("settings-terminal"),
    cancelKey: document.getElementById("settings-cancel-key"),
    callback: document.getElementById("settings-callback"),
    cardCount: document.getElementById("settings-card-count"),
    scenarioCount: document.getElementById("settings-scenario-count"),
    issueCount: document.getElementById("settings-issue-count"),
    scenarioSource: document.getElementById("settings-scenario-source"),
    scenarioTags: document.getElementById("settings-scenario-tags"),
    coverage3ds: document.getElementById("coverage-3ds"),
    coverageMoto: document.getElementById("coverage-moto"),
    coverageSingle: document.getElementById("coverage-single"),
    coverageInstallment: document.getElementById("coverage-installment"),
    coverageNegative: document.getElementById("coverage-negative"),
    coverageChannels: document.getElementById("coverage-channels"),
    coverageStatuses: document.getElementById("coverage-statuses"),
    coverageInstallments: document.getElementById("coverage-installments"),
    coverageErrors: document.getElementById("coverage-errors"),
  };

  function setStatus(element, text, kind) {
    element.textContent = text;
    element.className = `status-pill ${kind}`;
  }

  function text(value) {
    return value || "-";
  }

  function yesNo(value) {
    return value ? "Yes" : "No";
  }

  function countList(values) {
    const entries = Object.entries(values || {});
    if (entries.length === 0) {
      return "-";
    }
    return entries.map(([key, count]) => `${key}: ${count}`).join(", ");
  }

  function renderCoverage(coverage) {
    const summary = coverage || {};
    fields.coverage3ds.textContent = String(summary.three_ds_count || 0);
    fields.coverageMoto.textContent = String(summary.moto_count || 0);
    fields.coverageSingle.textContent = String(summary.single_payment_count || 0);
    fields.coverageInstallment.textContent = String(summary.installment_count || 0);
    fields.coverageNegative.textContent = String(summary.negative_count || 0);
    fields.coverageChannels.textContent = countList(summary.payment_channel_counts);
    fields.coverageStatuses.textContent = countList(summary.final_status_counts);
    fields.coverageInstallments.textContent = countList(summary.installment_counts);
    fields.coverageErrors.textContent = countList(summary.error_code_counts);
  }

  function renderIssues(readiness) {
    issueList.replaceChildren();
    if (!readiness.checked) {
      const item = document.createElement("li");
      item.textContent = readiness.message || "Readiness has not been checked.";
      issueList.append(item);
      return;
    }
    if (readiness.issues.length === 0) {
      const item = document.createElement("li");
      item.textContent = "No readiness issues.";
      issueList.append(item);
      return;
    }
    issueList.append(
      ...readiness.issues.map((issue) => {
        const item = document.createElement("li");
        item.textContent = `${issue.code}: ${issue.message}`;
        return item;
      }),
    );
  }

  function renderCards(cards) {
    cardTable.replaceChildren();
    cardTable.append(
      ...cards.map((card) => {
        const row = document.createElement("tr");
        const values = [
          { text: card.alias },
          { text: card.brand.toUpperCase() },
          { text: yesNo(card.requires_3ds) },
          { text: yesNo(card.has_expected_otp) },
          { text: automationLabel(card), title: card.automation_reason || "" },
        ];
        for (const value of values) {
          const cell = document.createElement("td");
          cell.textContent = value.text;
          cell.title = value.title || "";
          row.append(cell);
        }
        return row;
      }),
    );
  }

  function automationLabel(card) {
    if (card.automation_status === "success_auto") {
      return "Auto";
    }
    if (card.automation_status === "automation_diagnostic") {
      return "Diagnostic";
    }
    if (card.automation_status === "manual_only") {
      return "Manual";
    }
    if (card.automation_status === "quarantined") {
      return "Quarantine";
    }
    return "Unknown";
  }

  function renderOverview(overview) {
    if (!overview.runtime_configured) {
      setStatus(runtimeStatus, "Missing", "error");
      setStatus(readinessStatus, "Blocked", "error");
      setStatus(cardsStatus, "0", "neutral");
      setStatus(scenariosStatus, overview.scenarios.configured ? "Loaded" : "Missing", "neutral");
      fields.configSource.textContent = text(overview.config_source);
      fields.scenarioSource.textContent = text(overview.scenarios.source);
      fields.scenarioCount.textContent = String(overview.scenarios.scenario_count);
      fields.issueCount.textContent = "-";
      fields.scenarioTags.textContent = overview.scenarios.tags.join(", ") || "-";
      renderCoverage(overview.scenarios.coverage);
      renderIssues(overview.readiness);
      renderCards([]);
      message.textContent = overview.message || "Runtime config is not loaded.";
      return;
    }

    setStatus(runtimeStatus, "Configured", "success");
    setStatus(
      readinessStatus,
      overview.readiness.ready ? "Ready" : "Needs input",
      overview.readiness.ready ? "success" : "error",
    );
    setStatus(cardsStatus, String(overview.card_count), "neutral");
    setStatus(scenariosStatus, overview.scenarios.configured ? "Loaded" : "Missing", "neutral");

    fields.environment.textContent = text(overview.active_environment);
    fields.configSource.textContent = text(overview.config_source);
    fields.merchant.textContent = overview.merchant ? overview.merchant.merchant_id : "-";
    fields.terminal.textContent = overview.merchant ? overview.merchant.terminal_id : "-";
    fields.cancelKey.textContent = overview.merchant
      ? yesNo(overview.merchant.has_cancel_refund_key)
      : "-";
    fields.callback.textContent = yesNo(overview.callback_configured);
    fields.cardCount.textContent = String(overview.card_count);
    fields.scenarioCount.textContent = String(overview.scenarios.scenario_count);
    fields.issueCount.textContent = String(overview.readiness.issue_count);
    fields.scenarioSource.textContent = text(overview.scenarios.source);
    fields.scenarioTags.textContent = overview.scenarios.tags.join(", ") || "-";

    renderCoverage(overview.scenarios.coverage);
    renderIssues(overview.readiness);
    renderCards(overview.cards);
    message.textContent = overview.readiness.ready
      ? "Config and scenario catalogue are ready for local validation."
      : "Review readiness issues before running sandbox or local scenario checks.";
  }

  function renderMerchantSettings(settings) {
    merchantEnvironment = settings.environment;
    merchantNo.value = settings.merchant_no;
    paymentSx.value = "";
    paymentSxHint.textContent = settings.payment_sx_configured
      ? "Payment SX is configured. Enter a new value only to replace it."
      : "Payment SX is not configured. Enter a value before running payments.";
    setStatus(
      merchantStatus,
      settings.payment_sx_configured ? "Configured" : "Needs input",
      settings.payment_sx_configured ? "success" : "error",
    );
    if (settings.message) {
      merchantMessage.textContent = settings.message;
    }
  }

  async function loadSettings() {
    const overview = await window.PaynkolayApi.getConfigOverview();
    renderOverview(overview);
    try {
      renderMerchantSettings(await window.PaynkolayApi.getMerchantSettings());
    } catch (error) {
      merchantEnvironment = null;
      merchantNo.value = "";
      paymentSx.value = "";
      merchantSave.disabled = true;
      setStatus(merchantStatus, "Unavailable", "error");
      merchantMessage.textContent = error.message;
    }
  }

  merchantForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!merchantEnvironment) {
      merchantMessage.textContent = "Runtime merchant settings are not loaded.";
      return;
    }

    merchantSave.disabled = true;
    setStatus(merchantStatus, "Saving", "neutral");
    merchantMessage.textContent = "Saving merchant settings for new payment runs.";
    const payload = {
      environment: merchantEnvironment,
      merchant_no: merchantNo.value,
    };
    if (paymentSx.value) {
      payload.payment_sx = paymentSx.value;
    }

    try {
      const updated = await window.PaynkolayApi.updateMerchantSettings(payload);
      renderMerchantSettings(updated);
      renderOverview(await window.PaynkolayApi.getConfigOverview());
    } catch (error) {
      setStatus(merchantStatus, "Error", "error");
      merchantMessage.textContent = error.message;
    } finally {
      paymentSx.value = "";
      merchantSave.disabled = false;
    }
  });

  loadSettings().catch((error) => {
    setStatus(runtimeStatus, "Error", "error");
    setStatus(readinessStatus, "Error", "error");
    setStatus(merchantStatus, "Error", "error");
    message.textContent = error.message;
    merchantMessage.textContent = error.message;
  });
})();
