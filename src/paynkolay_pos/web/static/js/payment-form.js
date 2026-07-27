(function () {
  const form = document.getElementById("payment-form");
  const configStatus = document.getElementById("config-status");
  const environmentLabel = document.getElementById("environment-label");
  const submitButton = document.getElementById("submit-payment");
  const message = document.getElementById("form-message");
  const state = document.getElementById("payment-state");
  const cardListButton = document.getElementById("card-list-button");
  const cardListClose = document.getElementById("card-list-close");
  const cardListPanel = document.getElementById("card-list-panel");
  const cardListBody = document.getElementById("card-list-body");
  const cardListSearch = document.getElementById("card-list-search");
  const cardListFlowFilter = document.getElementById("card-list-flow-filter");
  const cardAddToggle = document.getElementById("card-add-toggle");
  const cardAddForm = document.getElementById("card-add-form");
  const cardAddSubmit = document.getElementById("card-add-submit");
  const newCardOtpField = document.getElementById("new-card-otp-field");
  const newCardOtp = document.getElementById("new-card-otp");
  const flowOptions = Array.from(document.querySelectorAll(".flow-option"));
  const installmentSelect = document.getElementById("installment-count");
  const installmentStatus = document.getElementById("installment-status");
  const requires3dsField = document.getElementById("requires-3ds-field");
  const requires3dsInput = document.getElementById("requires-3ds");
  const threeDsModeOptions = Array.from(document.querySelectorAll("[id^='three-ds-mode-']"));
  let installmentTimer = null;
  let installmentRequestSequence = 0;
  let selectedNewCardFlow = "moto";
  let selectedThreeDsMode = "manual";
  let availableCards = [];
  let cardsLoaded = false;

  const resultFields = {
    orderId: document.getElementById("result-order-id"),
    status: document.getElementById("result-status"),
    amount: document.getElementById("result-amount"),
    threeDs: document.getElementById("result-3ds"),
    providerRef: document.getElementById("result-provider-ref"),
    providerCode: document.getElementById("result-provider-code"),
    providerMessage: document.getElementById("result-provider-message"),
    requestRef: document.getElementById("result-request-ref"),
    requestCard: document.getElementById("result-request-card"),
    requestFlow: document.getElementById("result-request-flow"),
    paymentListStatus: document.getElementById("result-payment-list-status"),
    paymentListAuth: document.getElementById("result-payment-list-auth"),
    threeDsAutomation: document.getElementById("result-three-ds-automation"),
  };
  const threeDsLink = document.getElementById("result-three-ds-link");
  let paymentPoll = null;

  function setMessage(text, kind) {
    message.textContent = text;
    state.textContent = kind === "success" ? "Created" : kind === "error" ? "Error" : "Idle";
    state.className = `status-pill ${kind === "success" ? "success" : kind === "error" ? "error" : "neutral"}`;
  }

  function hasValidThreeDsUrl(url) {
    const normalized = String(url || "").trim();
    return Boolean(normalized && normalized !== "#" && normalized !== "/#");
  }

  function hideThreeDsLink() {
    threeDsLink.href = "/#";
    threeDsLink.classList.add("hidden");
    threeDsLink.setAttribute("aria-disabled", "true");
  }

  function showThreeDsLink(url) {
    threeDsLink.href = url;
    threeDsLink.classList.remove("hidden");
    threeDsLink.removeAttribute("aria-disabled");
  }

  function renderThreeDsAutomation(automation) {
    if (!automation) {
      resultFields.threeDsAutomation.textContent = "-";
      return;
    }
    const source = automation.otp_source_type || "no-source";
    const submitted = automation.submitted ? "submitted" : "not-submitted";
    const reason = automation.reason ? ` reason=${automation.reason}` : "";
    resultFields.threeDsAutomation.textContent =
      `${automation.status} ${submitted} source=${source}${reason}`;
  }

  function renderPaymentState(response) {
    resultFields.status.textContent = response.status;
    if (response.payment_list) {
      resultFields.paymentListStatus.textContent =
        response.payment_list.status || response.payment_list.error || "-";
      resultFields.paymentListAuth.textContent = response.payment_list.authorization_code || "-";
    } else {
      resultFields.paymentListStatus.textContent = "-";
      resultFields.paymentListAuth.textContent = "-";
    }
    renderThreeDsAutomation(response.three_ds_automation);
  }

  function startPaymentPolling(orderId) {
    if (paymentPoll !== null) {
      window.clearInterval(paymentPoll);
    }
    paymentPoll = window.setInterval(() => {
      window.PaynkolayApi.getPayment(orderId)
        .then((response) => {
          renderPaymentState(response);
          const automation = response.three_ds_automation;
          const automationDone = automation && automation.status !== "running";
          const statusDone =
            response.status !== "pending_3ds" && response.status !== "three_ds_rendered";
          if (automationDone || statusDone) {
            window.clearInterval(paymentPoll);
            paymentPoll = null;
          }
        })
        .catch(() => {
          window.clearInterval(paymentPoll);
          paymentPoll = null;
        });
    }, 2000);
  }

  function applySelectedCardFlow(card) {
    const requires3ds = Boolean(card.requires_3ds);
    requires3dsInput.checked = requires3ds;
    requires3dsInput.disabled = true;
    requires3dsField.classList.toggle("hidden", !requires3ds);
  }

  function useManualCardFlow() {
    requires3dsInput.disabled = false;
    requires3dsField.classList.remove("hidden");
  }

  function formPayload() {
    const data = new FormData(form);
    const payload = {
      amount: data.get("amount"),
      currency: data.get("currency"),
      card_brand: data.get("card_brand"),
      card_number: String(data.get("card_number") || "").replace(/\s+/g, ""),
      card_holder: data.get("card_holder"),
      expiry_month: Number(data.get("expiry_month")),
      expiry_year: Number(data.get("expiry_year")),
      cvv: data.get("cvv"),
      requires_3ds: requires3dsInput.checked,
      installment_count: Number(data.get("installment_count")),
      auto_complete_3ds: selectedThreeDsMode === "auto",
    };
    const selectedInstallment = installmentSelect.selectedOptions[0];
    const encodedValue = selectedInstallment?.dataset.encodedValue || "";
    if (encodedValue) {
      payload.installment_encoded_value = encodedValue;
    }
    return payload;
  }

  function showCardList() {
    cardListPanel.classList.remove("hidden");
    cardListPanel.scrollIntoView({ block: "start", behavior: "smooth" });
  }

  function hideCardList() {
    cardListPanel.classList.add("hidden");
  }

  function showAddCardForm() {
    cardAddForm.classList.remove("hidden");
  }

  function hideAddCardForm() {
    cardAddForm.classList.add("hidden");
  }

  function textCell(text) {
    const cell = document.createElement("td");
    cell.textContent = text;
    return cell;
  }

  function actionCell(card) {
    const cell = document.createElement("td");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "secondary-action table-action";
    button.textContent = "Add";
    button.addEventListener("click", () => {
      fillCardForm(card);
      hideCardList();
      setMessage(`Selected card ${card.alias}`, "neutral");
    });
    cell.append(button);
    return cell;
  }

  function renderCards(cards) {
    const filteredCards = filteredCardList(cards);
    if (!filteredCards.length) {
      const row = document.createElement("tr");
      const cell = textCell("No cards match the current filter.");
      cell.colSpan = 6;
      row.append(cell);
      cardListBody.replaceChildren(row);
      return;
    }

    cardListBody.replaceChildren(
      ...filteredCards.map((card) => {
        const row = document.createElement("tr");
        row.append(
          textCell(card.alias),
          textCell(card.brand.toUpperCase()),
          textCell(card.card_number),
          textCell(`${String(card.expiry_month).padStart(2, "0")}/${card.expiry_year}`),
          textCell(card.flow_type === "secure" ? "3D Secure" : "MoTo"),
          actionCell(card),
        );
        return row;
      }),
    );
  }

  function filteredCardList(cards) {
    const search = cardListSearch.value.trim().toLowerCase();
    const flow = cardListFlowFilter.value;
    return cards.filter((card) => {
      const matchesFlow = flow === "all" || card.flow_type === flow;
      const matchesSearch =
        !search ||
        card.alias.toLowerCase().includes(search) ||
        card.card_number.includes(search);
      return matchesFlow && matchesSearch;
    });
  }

  async function loadCards() {
    const response = await window.PaynkolayApi.getCards();
    availableCards = response.cards;
    renderCards(availableCards);
    cardsLoaded = true;
  }

  function fillCardForm(card) {
    document.getElementById("card-number").value = card.card_number;
    document.getElementById("card-brand").value = card.brand;
    document.getElementById("card-holder").value = card.card_holder;
    document.getElementById("expiry-month").value = card.expiry_month;
    document.getElementById("expiry-year").value = card.expiry_year;
    document.getElementById("cvv").value = card.cvv;
    applySelectedCardFlow(card);
    hideThreeDsLink();
    setDefaultInstallments();
    scheduleInstallmentRefresh();
  }

  function installmentPayload() {
    const data = new FormData(form);
    return {
      amount: data.get("amount"),
      currency: data.get("currency"),
      card_brand: data.get("card_brand"),
      card_number: String(data.get("card_number") || "").replace(/\s+/g, ""),
      requires_3ds: requires3dsInput.checked,
    };
  }

  function hasInstallmentInputs(payload) {
    return (
      Number(payload.amount) > 0 &&
      payload.card_brand &&
      payload.card_number &&
      payload.card_number.length >= 12
    );
  }

  function setDefaultInstallments() {
    installmentRequestSequence += 1;
    const option = document.createElement("option");
    option.value = "1";
    option.dataset.encodedValue = "";
    option.textContent = "Tek cekim";
    installmentSelect.replaceChildren(option);
    installmentSelect.value = "1";
    installmentStatus.textContent = "Default: Tek cekim";
  }

  function renderInstallmentOptions(response) {
    installmentSelect.replaceChildren(
      ...response.options.map((option) => {
        const element = document.createElement("option");
        element.value = String(option.installment_count);
        element.dataset.encodedValue = option.encoded_value || "";
        element.textContent =
          option.installment_count === 1
            ? `${option.label} (${option.total_amount})`
            : `${option.label} (${option.monthly_amount} x ${option.installment_count})`;
        return element;
      }),
    );
    installmentSelect.value = String(response.default_installment);
    installmentStatus.textContent = `Options loaded from ${response.source}`;
  }

  function scheduleInstallmentRefresh() {
    if (installmentTimer !== null) {
      window.clearTimeout(installmentTimer);
    }
    installmentTimer = window.setTimeout(() => {
      refreshInstallments();
    }, 350);
  }

  function resetAndScheduleInstallmentRefresh() {
    setDefaultInstallments();
    scheduleInstallmentRefresh();
  }

  async function refreshInstallments() {
    const requestSequence = ++installmentRequestSequence;
    const payload = installmentPayload();
    if (!hasInstallmentInputs(payload)) {
      setDefaultInstallments();
      return;
    }
    installmentStatus.textContent = "Loading installment options";
    try {
      const response = await window.PaynkolayApi.getInstallmentOptions(payload);
      if (requestSequence !== installmentRequestSequence) {
        return;
      }
      renderInstallmentOptions(response);
    } catch (error) {
      if (requestSequence !== installmentRequestSequence) {
        return;
      }
      setDefaultInstallments();
      installmentStatus.textContent = error.message;
    }
  }

  function newCardPayload() {
    const data = new FormData(cardAddForm);
    const payload = {
      alias: slugAlias(data.get("alias")),
      brand: data.get("brand"),
      card_number: String(data.get("card_number") || "").replace(/\s+/g, ""),
      expiry_month: Number(data.get("expiry_month")),
      expiry_year: Number(data.get("expiry_year")),
      cvv: data.get("cvv"),
      flow_type: selectedNewCardFlow,
    };
    if (selectedNewCardFlow === "secure") {
      const expectedOtp = String(data.get("expected_otp") || "").trim();
      if (expectedOtp) {
        payload.expected_otp = expectedOtp;
      }
    }
    return payload;
  }

  function slugAlias(value) {
    return String(value || "")
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9_-]+/g, "_")
      .replace(/^_+|_+$/g, "");
  }

  function setNewCardFlow(flow) {
    selectedNewCardFlow = flow;
    flowOptions.forEach((option) => {
      option.classList.toggle("active", option.dataset.flow === flow);
    });
    if (flow === "secure") {
      newCardOtpField.classList.remove("hidden");
      newCardOtp.required = true;
      return;
    }
    newCardOtpField.classList.add("hidden");
    newCardOtp.required = false;
    newCardOtp.value = "";
  }

  function setThreeDsMode(mode) {
    selectedThreeDsMode = mode;
    threeDsModeOptions.forEach((option) => {
      option.classList.toggle("active", option.dataset.mode === mode);
    });
  }

  async function loadConfig() {
    const config = await window.PaynkolayApi.getConfig();
    const currencySelect = document.getElementById("currency");
    const brandSelect = document.getElementById("card-brand");
    currencySelect.replaceChildren(
      ...config.supported_currencies.map((currency) => {
        const option = document.createElement("option");
        option.value = currency;
        option.textContent = currency;
        return option;
      }),
    );
    brandSelect.replaceChildren(
      ...config.supported_card_brands.map((brand) => {
        const option = document.createElement("option");
        option.value = brand;
        option.textContent = brand.toUpperCase();
        return option;
      }),
    );

    if (config.runtime_configured) {
      configStatus.textContent = "Configured";
      configStatus.className = "status-pill success";
      environmentLabel.textContent = `Environment ${config.active_environment}`;
      return;
    }

    configStatus.textContent = "Local";
    configStatus.className = "status-pill neutral";
    environmentLabel.textContent = "Runtime config not loaded";
  }

  cardListButton.addEventListener("click", async () => {
    showCardList();
    if (cardsLoaded) {
      return;
    }

    cardListButton.disabled = true;
    setMessage("Loading test cards", "neutral");
    try {
      await loadCards();
      setMessage("Test cards loaded", "neutral");
    } catch (error) {
      const row = document.createElement("tr");
      const cell = textCell(error.message);
      cell.colSpan = 6;
      row.append(cell);
      cardListBody.replaceChildren(row);
      setMessage(error.message, "error");
    } finally {
      cardListButton.disabled = false;
    }
  });

  cardListClose.addEventListener("click", () => {
    hideCardList();
  });

  cardAddToggle.addEventListener("click", () => {
    if (cardAddForm.classList.contains("hidden")) {
      showAddCardForm();
      return;
    }
    hideAddCardForm();
  });

  flowOptions.forEach((option) => {
    option.addEventListener("click", () => {
      setNewCardFlow(option.dataset.flow);
    });
  });

  threeDsModeOptions.forEach((option) => {
    option.addEventListener("click", () => {
      setThreeDsMode(option.dataset.mode);
    });
  });

  cardAddForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    cardAddSubmit.disabled = true;
    setMessage("Saving test card", "neutral");
    try {
      const createdCard = await window.PaynkolayApi.createCard(newCardPayload());
      availableCards = [...availableCards, createdCard];
      renderCards(availableCards);
      fillCardForm(createdCard);
      cardAddForm.reset();
      setNewCardFlow("moto");
      hideAddCardForm();
      setMessage(`Added card ${createdCard.alias}`, "success");
    } catch (error) {
      setMessage(error.message, "error");
    } finally {
      cardAddSubmit.disabled = false;
    }
  });

  cardListSearch.addEventListener("input", () => {
    renderCards(availableCards);
  });

  cardListFlowFilter.addEventListener("change", () => {
    renderCards(availableCards);
  });

  [
    document.getElementById("amount"),
    document.getElementById("currency"),
    document.getElementById("card-brand"),
    document.getElementById("card-number"),
    requires3dsInput,
  ].forEach((element) => {
    element.addEventListener("input", resetAndScheduleInstallmentRefresh);
    element.addEventListener("change", resetAndScheduleInstallmentRefresh);
  });

  [
    document.getElementById("card-brand"),
    document.getElementById("card-number"),
    document.getElementById("card-holder"),
    document.getElementById("expiry-month"),
    document.getElementById("expiry-year"),
    document.getElementById("cvv"),
  ].forEach((element) => {
    element.addEventListener("input", useManualCardFlow);
    element.addEventListener("change", useManualCardFlow);
  });

  threeDsLink.addEventListener("click", (event) => {
    if (!hasValidThreeDsUrl(threeDsLink.getAttribute("href"))) {
      event.preventDefault();
      hideThreeDsLink();
      setMessage("3D Secure challenge URL was not returned for this payment.", "error");
    }
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    submitButton.disabled = true;
    hideThreeDsLink();
    setMessage("Submitting", "neutral");

    try {
      const response = await window.PaynkolayApi.createPayment(formPayload());
      resultFields.orderId.textContent = response.order_id;
      resultFields.status.textContent = response.status;
      resultFields.amount.textContent = `${response.amount} ${response.currency}`;
      resultFields.threeDs.textContent = response.requires_3ds ? "Required" : "Not required";
      resultFields.providerRef.textContent = response.provider_transaction_id || "-";
      resultFields.providerCode.textContent = response.provider_response_code || "-";
      resultFields.providerMessage.textContent = response.provider_response_data || "-";
      if (response.provider_request) {
        const providerRequest = response.provider_request;
        resultFields.requestRef.textContent = providerRequest.client_ref_code || "-";
        resultFields.requestCard.textContent =
          `${String(providerRequest.card_brand || "").toUpperCase()} ${providerRequest.masked_pan || "-"} ${providerRequest.expiry_month || "-"}/${providerRequest.expiry_year || "-"}`;
        resultFields.requestFlow.textContent =
          `use3D=${providerRequest.use_3d} installment=${providerRequest.installment_no} channel=${providerRequest.payment_channel}`;
      } else {
        resultFields.requestRef.textContent = "-";
        resultFields.requestCard.textContent = "-";
        resultFields.requestFlow.textContent = "-";
      }
      renderPaymentState(response);
      const threeDsUrl = response.three_ds && response.three_ds.render_url;
      if (hasValidThreeDsUrl(threeDsUrl)) {
        showThreeDsLink(threeDsUrl);
        setMessage(response.message, "success");
        startPaymentPolling(response.order_id);
      } else if (response.requires_3ds && response.status === "pending_3ds") {
        hideThreeDsLink();
        setMessage("3D Secure challenge URL was not returned for this payment.", "error");
      } else {
        hideThreeDsLink();
        setMessage(response.message, "success");
      }
    } catch (error) {
      setMessage(error.message, "error");
    } finally {
      submitButton.disabled = false;
    }
  });

  loadConfig().catch((error) => {
    configStatus.textContent = "Error";
    configStatus.className = "status-pill error";
    environmentLabel.textContent = "Config unavailable";
    setMessage(error.message, "error");
  });

  hideThreeDsLink();
  setThreeDsMode("manual");
})();
