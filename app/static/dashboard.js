const $ = (id) => document.getElementById(id);
const escapeHTML = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (ch) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        ch
      ],
  );
const labels = {
  HEALTHY: "Working",
  DEGRADED: "Slow",
  FAILED: "Failed",
  STALE: "Out of date",
  UNKNOWN: "Not checked",
};
const causes = {
  AUTHENTICATION_FAILURE: "Access denied",
  RATE_LIMITED: "Too many requests",
  UPSTREAM_FAILURE: "Service unavailable",
  HTTP_ERROR: "Unexpected HTTP error",
  TIMEOUT: "No response before the deadline",
  NETWORK_ERROR: "Could not connect",
  RESPONSE_VALIDATION_FAILURE: "Unexpected response data",
  HIGH_LATENCY: "Response slower than expected",
  UNSAFE_TARGET: "Destination blocked by target policy",
  CONFIGURATION_ERROR: "Credentials need operator attention",
  UNEXPECTED_STATUS: "Unexpected HTTP status",
};
let busy = false,
  refreshPromise = null,
  initialized = false,
  actionFailed = false,
  services = [],
  policy = { failure_threshold: 3, recovery_threshold: 2 };
function timestamp(value) {
  return value ? new Date(value).toLocaleString() : "Not checked yet";
}
function badge(status) {
  const known = labels[status] ? status : "UNKNOWN";
  return '<span class="status ' + known + '">' + labels[known] + "</span>";
}
function showError(message) {
  $("error").textContent = message;
  $("error").hidden = false;
}
async function json(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    signal: AbortSignal.timeout(40000),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const error = new Error(
      typeof body.detail === "string"
        ? body.detail
        : "The request could not be completed (" + response.status + ").",
    );
    error.status = response.status;
    throw error;
  }
  return response.status === 204 ? null : response.json();
}
const post = (url, payload) =>
  json(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    ...(payload === undefined ? {} : { body: JSON.stringify(payload) }),
  });
async function check(id) {
  let result = await post("/api/integrations/" + id + "/check");
  if (result.execution_id && !result.outcome) {
    const deadline = Date.now() + 90000;
    while (Date.now() < deadline) {
      await new Promise((resolve) => setTimeout(resolve, 400));
      const run = await json("/api/runs/" + result.execution_id);
      if (run.check) return run.check;
      if (["FAILED", "CANCELLED"].includes(run.status))
        throw new Error(
          "The monitoring run could not finish. Please try again.",
        );
    }
    throw new Error(
      "The check is still waiting for a worker. Please try again shortly.",
    );
  }
  return result;
}
async function refresh() {
  if (refreshPromise) return refreshPromise;
  refreshPromise = (async () => {
    try {
      const [overview, statuses, incidents, config, states] = await Promise.all(
        [
          json("/api/overview"),
          json("/api/status"),
          json("/api/incidents"),
          json("/api/config"),
          json("/api/demo"),
        ],
      );
      services = statuses;
      policy = config;
      $("overview").innerHTML = [
        [
          "Monitored services",
          overview.total_integrations,
          "Active connections",
        ],
        [
          "Working normally",
          overview.healthy,
          "Latest result, checked recently",
        ],
        [
          "Open incidents",
          overview.active_incidents,
          "Persistent failures being tracked",
        ],
        [
          "Successful checks · 24h",
          overview.availability_24h == null
            ? "—"
            : overview.availability_24h + "%",
          overview.checks_24h + " recorded checks",
        ],
      ]
        .map(
          ([label, value, note]) =>
            '<div class="stat"><div class="stat-label">' +
            escapeHTML(label) +
            '</div><div class="stat-value">' +
            escapeHTML(value) +
            '</div><div class="stat-note">' +
            escapeHTML(note) +
            "</div></div>",
        )
        .join("");
      $("status-summary").textContent = overview.total_integrations
        ? overview.degraded +
          " slow · " +
          overview.down +
          " failed · " +
          overview.stale +
          " out of date · " +
          overview.unknown +
          " not checked"
        : "No services added yet. Start the example below.";
      $("integrations").innerHTML = statuses.length
        ? statuses
            .map(
              (service) =>
                '<div class="service-row"><div class="service-main"><div class="service-title"><a href="/services/' +
                Number(service.id) +
                '">' +
                escapeHTML(service.name) +
                "</a>" +
                badge(service.status) +
                '</div><div class="meta">Last checked: ' +
                escapeHTML(timestamp(service.last_checked_at)) +
                '</div><div class="meta">Response: ' +
                (service.latency_ms == null
                  ? "Not measured"
                  : escapeHTML(service.latency_ms) + " ms") +
                "</div>" +
                (service.failure_type
                  ? '<div class="failure">' +
                    escapeHTML(
                      causes[service.failure_type] || service.failure_type,
                    ) +
                    "</div>"
                  : "") +
                '</div><button data-check="' +
                Number(service.id) +
                '" ' +
                (busy ? "disabled" : "") +
                ">Check now</button></div>",
            )
            .join("")
        : '<div class="empty"><strong>No monitored services.</strong>Add the examples to explore the demo.</div>';
      const names = new Map(statuses.map((item) => [item.id, item.name]));
      $("incidents").innerHTML = incidents.length
        ? incidents
            .slice(0, 8)
            .map(
              (incident) =>
                '<div class="incident"><div class="incident-title"><a href="/services/' +
                Number(incident.integration_id) +
                '">' +
                escapeHTML(
                  names.get(incident.integration_id) ||
                    "Service #" + incident.integration_id,
                ) +
                '</a><span class="status ' +
                (incident.status === "OPEN" ? "FAILED" : "HEALTHY") +
                '">' +
                (incident.status === "OPEN" ? "Open" : "Resolved") +
                '</span></div><p class="muted">' +
                escapeHTML(
                  causes[incident.cause] ||
                    incident.cause ||
                    "Failure detected",
                ) +
                '</p><p class="meta">Opened ' +
                escapeHTML(timestamp(incident.started_at)) +
                "</p>" +
                (incident.resolved_at
                  ? '<p class="meta">Recovered ' +
                    escapeHTML(timestamp(incident.resolved_at)) +
                    "</p>"
                  : "") +
                "</div>",
            )
            .join("")
        : '<div class="empty"><strong>No incidents recorded.</strong>Cause an outage to see how a failure is tracked.</div>';
      $("metrics").innerHTML = [
        [
          "Average response time",
          overview.avg_latency_ms_24h,
          "Mean of measured checks",
        ],
        [
          "95th percentile response time",
          overview.p95_latency_ms_24h,
          "95% of measured checks were this fast or faster",
        ],
        [
          "Recorded checks · 24h",
          overview.checks_24h,
          "Working, slow, and failed checks",
        ],
      ]
        .map(
          ([label, value, note], index) =>
            '<div><div class="stat-label">' +
            label +
            "</div><strong>" +
            (value == null
              ? "—"
              : escapeHTML(value) + (index < 2 ? " ms" : "")) +
            '</strong><div class="small">' +
            note +
            "</div></div>",
        )
        .join("");
      if (!initialized) {
        $("mode").value =
          states.find((item) => item.service === $("service").value)?.mode ||
          "healthy";
        initialized = true;
      }
      $("freshness").textContent = "Updated " + new Date().toLocaleTimeString();
      $("outage-demo").textContent =
        "Cause outage · " + config.failure_threshold + " checks";
      $("recover-demo").textContent =
        "Restore service · " + config.recovery_threshold + " checks";
      $("monitor-notice").hidden = config.automatic_checks;
      $("monitor-notice").textContent =
        "Manual preview: checks run when you click. The standard demo also checks services automatically.";
      if (!actionFailed) $("error").hidden = true;
    } catch (error) {
      showError(
        "Monitoring data is unavailable. Displayed results may be out of date.",
      );
      $("freshness").textContent = "Connection unavailable";
    }
  })();
  try {
    await refreshPromise;
  } finally {
    refreshPromise = null;
  }
}
async function action(task) {
  if (busy) return;
  busy = true;
  actionFailed = false;
  $("error").hidden = true;
  document
    .querySelectorAll("button,select")
    .forEach((control) => (control.disabled = true));
  try {
    if (refreshPromise) await refreshPromise;
    await task();
    await refresh();
  } catch (error) {
    actionFailed = true;
    showError(
      error instanceof TypeError
        ? "Could not connect to the monitoring service. Please try again."
        : error.name === "TimeoutError"
          ? "The request timed out. Please try again."
          : error.message,
    );
    $("feedback").textContent =
      "Action could not be completed. See the message above.";
  } finally {
    busy = false;
    document
      .querySelectorAll("button,select")
      .forEach((control) => (control.disabled = false));
  }
}
async function examples() {
  return post("/api/demo");
}
async function target(key = $("service").value) {
  let items = services;
  if (!items.some((item) => item.demo_key === key)) items = await examples();
  const service = items.find((item) => item.demo_key === key);
  if (!service) throw new Error("The example service could not be created.");
  return service;
}
async function scenario(mode, service = $("service").value) {
  const deadline = Date.now() + 90000;
  while (true) {
    try {
      await post("/api/demo/scenario", { mode, service });
      break;
    } catch (error) {
      if (
        error.status !== 409 ||
        !error.message.includes("current check") ||
        Date.now() > deadline
      )
        throw error;
      $("feedback").textContent = "Waiting for the current check to finish…";
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
  }
  if (service === $("service").value) $("mode").value = mode;
}
$("create-demo").addEventListener("click", () =>
  action(async () => {
    const items = await examples();
    for (const service of items) await check(service.id);
    $("feedback").textContent =
      "Payment, shipping, and identity services are ready. Choose a service and cause an outage.";
  }),
);
$("outage-demo").addEventListener("click", () =>
  action(async () => {
    const service = await target();
    await scenario("server_error");
    for (let count = 1; count <= policy.failure_threshold; count++) {
      $("feedback").textContent =
        "Checking outage " + count + " of " + policy.failure_threshold + "…";
      await check(service.id);
    }
    $("feedback").textContent =
      "Failed checks recorded. The incident is open. Restore the service to watch recovery.";
  }),
);
$("recover-demo").addEventListener("click", () =>
  action(async () => {
    const service = await target();
    await scenario("healthy");
    for (let count = 1; count <= policy.recovery_threshold; count++) {
      $("feedback").textContent =
        "Checking recovery " + count + " of " + policy.recovery_threshold + "…";
      await check(service.id);
    }
    $("feedback").textContent =
      "Normal responses confirmed. The incident is resolved.";
  }),
);
$("apply-mode").addEventListener("click", () =>
  action(async () => {
    await target();
    await scenario($("mode").value);
    $("feedback").textContent =
      "Scenario applied. Choose Check now on the selected service.";
  }),
);
$("service").addEventListener("change", async () => {
  try {
    const states = await json("/api/demo");
    $("mode").value =
      states.find((item) => item.service === $("service").value)?.mode ||
      "healthy";
  } catch {
    showError("The selected scenario could not be loaded.");
  }
});
$("integrations").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-check]");
  if (button)
    action(async () => {
      const result = await check(button.dataset.check);
      $("feedback").textContent =
        "Check completed: " +
        (labels[result.outcome] || result.outcome) +
        (result.failure_type
          ? " · " + (causes[result.failure_type] || result.failure_type)
          : "") +
        ".";
    });
});
$("run-campaign").addEventListener("click", () =>
  action(async () => {
    const service = await target("payment");
    $("case-results").replaceChildren();
    const sequence = [
      ["healthy", "Normal response"],
      ["healthy", "Confirm normal baseline"],
      ["unauthorized", "Access denied"],
      ["rate_limit", "Rate limit"],
      ["slow", "Slow but valid response"],
      ["malformed", "Unexpected response data"],
      ["server_error", "Service unavailable · check 1"],
      ["server_error", "Service unavailable · check 2"],
      ["server_error", "Service unavailable · check 3"],
      ["healthy", "Recovery · check 1"],
      ["healthy", "Recovery · check 2"],
    ];
    for (const [mode, title] of sequence) {
      $("feedback").textContent = "Case study: " + title + "…";
      await scenario(mode, "payment");
      const result = await check(service.id);
      const row = document.createElement("div");
      row.className = "case-result";
      row.innerHTML =
        "<span>" + escapeHTML(title) + "</span>" + badge(result.outcome);
      $("case-results").append(row);
    }
    $("feedback").textContent =
      "Case study complete. Open Payment API to inspect the check history and incident timeline.";
  }),
);
refresh();
setInterval(() => {
  if (!busy) refresh();
}, 5000);
