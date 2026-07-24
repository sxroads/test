(function () {
  const parallelRunStatus = document.getElementById("parallel-run-status");
  const parallelMode = document.getElementById("parallel-mode");
  const parallelAmount = document.getElementById("parallel-amount");
  const parallelRandomCountField = document.getElementById("parallel-random-count-field");
  const parallelRandomCount = document.getElementById("parallel-random-count");
  const parallelManualPanel = document.getElementById("parallel-manual-panel");
  const parallelCardSelect = document.getElementById("parallel-card-select");
  const parallelRepeatCount = document.getElementById("parallel-repeat-count");
  const parallelAddCard = document.getElementById("parallel-add-card");
  const parallelSelectionBody = document.getElementById("parallel-selection-body");
  const parallelRunButton = document.getElementById("parallel-run-button");
  const parallelRunId = document.getElementById("parallel-run-id");
  const parallelProgress = document.getElementById("parallel-progress");
  const parallelSuccessRate = document.getElementById("parallel-success-rate");
  const parallelSelectedTotal = document.getElementById("parallel-selected-total");
  const parallelProfileSummary = document.getElementById("parallel-profile-summary");
  const parallelAcsPeak = document.getElementById("parallel-acs-peak");
  const parallelThroughput = document.getElementById("parallel-throughput");
  const parallelP95Duration = document.getElementById("parallel-p95-duration");
  const parallelMessage = document.getElementById("parallel-message");
  const parallelEvidencePath = document.getElementById("parallel-evidence-path");
  const parallelResultsBody = document.getElementById("parallel-results-body");
  let parallelRunPoll = null;
  let parallelSelections = [];
  let lastParallelRun = null;

  function setParallelRunStatus(text, kind) {
    parallelRunStatus.textContent = text;
    parallelRunStatus.className = `status-pill ${kind}`;
  }

  function formatDuration(value) {
    if (value === null || value === undefined) {
      return "-";
    }
    if (value < 1000) {
      return `${value} ms`;
    }
    return `${(value / 1000).toFixed(2)} s`;
  }

  function renderParallelMode() {
    const randomMode = parallelMode.value === "random";
    parallelRandomCountField.classList.toggle("hidden", !randomMode);
    parallelManualPanel.classList.toggle("hidden", randomMode);
    renderParallelSelections();
  }

  function renderParallelSelections() {
    const total = parallelSelections.reduce((sum, selection) => sum + selection.repeat_count, 0);
    parallelSelectionBody.replaceChildren(
      ...parallelSelections.map((selection, index) => {
        const row = document.createElement("tr");
        for (const value of [selection.alias, String(selection.repeat_count)]) {
          const cell = document.createElement("td");
          cell.textContent = value;
          row.append(cell);
        }
        const actionCell = document.createElement("td");
        const removeButton = document.createElement("button");
        removeButton.className = "secondary-action";
        removeButton.type = "button";
        removeButton.textContent = "Remove";
        removeButton.addEventListener("click", () => {
          parallelSelections.splice(index, 1);
          renderParallelSelections();
        });
        actionCell.append(removeButton);
        row.append(actionCell);
        return row;
      }),
    );
    parallelSelectedTotal.textContent = String(total);
    parallelRunButton.disabled = parallelMode.value === "manual" && total === 0;
  }

  function loadParallelCards() {
    window.PaynkolayApi.getCards()
      .then((payload) => {
        parallelCardSelect.replaceChildren(
          ...payload.cards.map((card) => {
            const option = document.createElement("option");
            option.value = card.alias;
            option.textContent = `${card.alias} (${card.brand.toUpperCase()} ${card.flow_type}, ${automationLabel(card)})`;
            option.title = card.automation_reason || "";
            return option;
          }),
        );
      })
      .catch((error) => {
        parallelMessage.textContent = error.message;
        setParallelRunStatus("Config error", "error");
      });
  }

  function automationLabel(card) {
    if (card.automation_status === "success_auto") {
      return "auto";
    }
    if (card.automation_status === "automation_diagnostic") {
      return "diagnostic";
    }
    if (card.automation_status === "manual_only") {
      return "manual";
    }
    if (card.automation_status === "quarantined") {
      return "quarantine";
    }
    return "unknown";
  }

  function parallelPayload() {
    const mode = parallelMode.value;
    const payload = {
      mode,
      amount: parallelAmount.value,
      currency: "TRY",
      concurrency: 10,
      execution_profile: "stable",
      auto_complete_3ds: true,
    };
    if (mode === "random") {
      payload.random_count = Number(parallelRandomCount.value);
      return payload;
    }
    payload.manual_cards = parallelSelections;
    return payload;
  }

  function renderParallelRun(run) {
    lastParallelRun = run;
    parallelRunId.textContent = run.run_id;
    parallelProgress.textContent = `${run.completed + run.failed}/${run.total}`;
    parallelSuccessRate.textContent = formatSuccessRate(run.items || []);
    parallelProfileSummary.textContent = window.PaynkolayI18n.t("stable_demo");
    parallelAcsPeak.textContent = formatAcsPeak(run);
    parallelThroughput.textContent = formatThroughput(run.metrics);
    parallelP95Duration.textContent = formatDuration(run.metrics?.p95_duration_ms);
    parallelMessage.textContent = window.PaynkolayI18n.humanizeStatus(run.message);
    parallelEvidencePath.textContent = run.evidence_path || "-";
    parallelRunButton.disabled = run.status === "running";
    if (run.status === "running") {
      setParallelRunStatus("Running", "neutral");
      startParallelPolling(run.run_id);
    } else if (run.status === "completed") {
      setParallelRunStatus("Completed", "success");
    } else if (run.status === "completed_with_failures") {
      setParallelRunStatus("Attention", "error");
    } else if (run.status === "failed") {
      setParallelRunStatus("Failed", "error");
    } else {
      setParallelRunStatus("Idle", "neutral");
    }
    renderParallelItems(run.items || []);
  }

  function formatAcsPeak(run) {
    const scheduler = run.acs_scheduler;
    if (!scheduler) {
      return "-";
    }
    return `${scheduler.peak_concurrency}/${scheduler.requested_concurrency}`;
  }

  function formatThroughput(metrics) {
    if (!metrics || metrics.throughput_per_second === null) {
      return "-";
    }
    return `${metrics.throughput_per_second.toFixed(2)} tx/s`;
  }

  function renderParallelItems(items) {
    parallelResultsBody.replaceChildren(
      ...items.map((item) => {
        const row = document.createElement("tr");
        row.className = parallelItemOutcomeClass(item);
        const values = [
          item.card_alias,
          window.PaynkolayI18n.humanizeStatus(item.status),
          window.PaynkolayI18n.humanizeStatus(item.classification),
          window.PaynkolayI18n.humanizeStatus(item.payment_list_status || item.payment_list_error || "-"),
          formatAutomationSummary(item.three_ds_automation),
          formatDuration(item.duration_ms),
        ];
        for (const value of values) {
          const cell = document.createElement("td");
          cell.textContent = value;
          cell.title = value;
          row.append(cell);
        }
        return row;
      }),
    );
  }

  function parallelItemOutcomeClass(item) {
    if (item.classification === "completed") {
      return "parallel-item-success";
    }
    if (item.status === "failed" || item.classification === "provider_failed") {
      return "parallel-item-failure";
    }
    if (["pending", "running", "pending_3ds"].includes(item.classification)) {
      return "";
    }
    return item.classification ? "parallel-item-failure" : "";
  }

  function formatSuccessRate(items) {
    const completedItems = items.filter((item) => item.classification === "completed").length;
    const finishedItems = items.filter(
      (item) => !["pending", "running"].includes(item.classification),
    ).length;
    const denominator = finishedItems || items.length;
    if (denominator === 0) {
      return "-";
    }
    const rate = (completedItems / denominator) * 100;
    return `${completedItems}/${denominator} (${rate.toFixed(1)}%)`;
  }

  function formatAutomationSummary(automation) {
    if (!automation) {
      return "-";
    }
    const source = window.PaynkolayI18n.humanizeStatus(automation.otp_source_type || "no-source");
    const submitted = window.PaynkolayI18n.humanizeStatus(automation.submitted ? "submitted" : "not-submitted");
    const details = [
      window.PaynkolayI18n.humanizeStatus(automation.status),
      submitted,
      source,
      window.PaynkolayI18n.humanizeStatus(automation.reason),
    ].filter(Boolean);
    return details.join(" ");
  }

  function startParallelPolling(runId) {
    if (parallelRunPoll !== null) {
      return;
    }
    parallelRunPoll = window.setInterval(() => {
      window.PaynkolayApi.getParallelRun(runId)
        .then((run) => {
          renderParallelRun(run);
          if (run.status !== "running" && parallelRunPoll !== null) {
            window.clearInterval(parallelRunPoll);
            parallelRunPoll = null;
          }
        })
        .catch((error) => {
          parallelMessage.textContent = error.message;
          setParallelRunStatus("Error", "error");
          if (parallelRunPoll !== null) {
            window.clearInterval(parallelRunPoll);
            parallelRunPoll = null;
          }
        });
    }, 1500);
  }

  parallelMode.addEventListener("change", renderParallelMode);
  parallelRandomCount.addEventListener("input", renderParallelSelections);

  parallelAddCard.addEventListener("click", () => {
    if (!parallelCardSelect.value) {
      return;
    }
    const repeatCount = Number(parallelRepeatCount.value);
    const currentTotal = parallelSelections.reduce(
      (sum, selection) => sum + selection.repeat_count,
      0,
    );
    if (currentTotal + repeatCount > 150) {
      parallelMessage.textContent = "Manual selection can include at most 150 test items.";
      setParallelRunStatus("Limit", "error");
      return;
    }
    parallelSelections.push({
      alias: parallelCardSelect.value,
      repeat_count: repeatCount,
    });
    parallelMessage.textContent = "Selection updated.";
    setParallelRunStatus("Idle", "neutral");
    renderParallelSelections();
  });

  window.addEventListener("paynkolay-language-change", () => {
    if (lastParallelRun) renderParallelRun(lastParallelRun);
  });

  parallelRunButton.addEventListener("click", () => {
    parallelRunButton.disabled = true;
    parallelMessage.textContent = "Starting parallel run";
    setParallelRunStatus("Starting", "neutral");
    window.PaynkolayApi.createParallelRun(parallelPayload())
      .then(renderParallelRun)
      .catch((error) => {
        parallelRunButton.disabled = false;
        parallelMessage.textContent = error.message;
        setParallelRunStatus("Error", "error");
      });
  });

  renderParallelMode();
  renderParallelSelections();
  loadParallelCards();
})();
