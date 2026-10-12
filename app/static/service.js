const $ = (id) => document.getElementById(id);
const id = Number(location.pathname.split("/").pop());
const esc = (value) =>
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
const badge = (status) =>
  '<span class="status ' +
  (labels[status] ? status : "UNKNOWN") +
  '">' +
  (labels[status] || "Not checked") +
  "</span>";
const time = (value) =>
  value ? new Date(value).toLocaleString() : "Not recorded";
let busy = false,
  refreshPromise = null,
  unavailable = false;
async function json(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    signal: AbortSignal.timeout(40000),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(
      response.status === 404
        ? "This service was not found in your demo. Return to monitoring to add the examples."
        : typeof body.detail === "string"
          ? body.detail
          : "Service history could not be loaded.",
    );
  }
  return response.json();
}
function error(message) {
  $("error").textContent = message;
  $("error").hidden = false;
}
async function refresh() {
  if (refreshPromise) return refreshPromise;
  refreshPromise = (async () => {
    try {
      const [service, statuses, checks, incidents] = await Promise.all([
        json("/api/integrations/" + id),
        json("/api/status"),
        json("/api/integrations/" + id + "/checks"),
        json("/api/incidents?integration_id=" + id),
      ]);
      const status = statuses.find((item) => item.id === id);
      $("service-name").textContent = service.name;
      document.title = service.name + " · IntegrationOps";
      $("current").innerHTML =
        badge(status?.status || "UNKNOWN") +
        '<p class="meta">Last checked ' +
        esc(time(status?.last_checked_at)) +
        '</p><p class="endpoint">' +
        esc(service.endpoint) +
        '</p><p class="small">Expected HTTP ' +
        Number(service.expected_status) +
        " · response threshold " +
        Number(service.latency_threshold_ms || 0) +
        " ms · interval " +
        Number(service.check_interval_seconds) +
        " s</p>";
      $("checks").innerHTML = checks.length
        ? '<table class="history-table"><caption class="small">Latest ' +
          checks.length +
          ' checks</caption><thead><tr><th scope="col">Time</th><th scope="col">Result</th><th scope="col">HTTP</th><th scope="col">Response time</th><th scope="col">Observation</th></tr></thead><tbody>' +
          checks
            .map(
              (check) =>
                "<tr><td>" +
                esc(time(check.checked_at)) +
                "</td><td>" +
                badge(check.outcome) +
                "</td><td>" +
                esc(check.http_status ?? "—") +
                "</td><td>" +
                (check.latency_ms == null
                  ? "—"
                  : Number(check.latency_ms).toFixed(2) + " ms") +
                '</td><td class="history-message">' +
                esc(check.error_message || "Expected response received") +
                "</td></tr>",
            )
            .join("") +
          "</tbody></table>"
        : '<div class="empty">No checks recorded yet. Choose Check now.</div>';
      $("incidents").innerHTML = incidents.length
        ? incidents
            .map(
              (incident) =>
                '<div class="incident"><div class="incident-title">Incident #' +
                Number(incident.id) +
                '<span class="status ' +
                (incident.status === "OPEN" ? "FAILED" : "HEALTHY") +
                '">' +
                (incident.status === "OPEN" ? "Open" : "Resolved") +
                '</span></div><p class="meta">Opened ' +
                esc(time(incident.started_at)) +
                "</p>" +
                (incident.resolved_at
                  ? '<p class="meta">Recovered ' +
                    esc(time(incident.resolved_at)) +
                    "</p>"
                  : "") +
                '<p class="small">' +
                Number(incident.failure_count) +
                " failed observations recorded</p></div>",
            )
            .join("")
        : '<div class="empty">No persistent failures have been recorded.</div>';
      $("error").hidden = true;
      unavailable = false;
      $("check-now").disabled = busy;
    } catch (exc) {
      error(exc.message);
      if ($("service-name").textContent === "Loading service…")
        $("service-name").textContent = "Service unavailable";
      unavailable = true;
      $("check-now").disabled = true;
    }
  })();
  try {
    await refreshPromise;
  } finally {
    refreshPromise = null;
  }
}
$("check-now").addEventListener("click", async () => {
  if (busy || unavailable) return;
  busy = true;
  $("check-now").disabled = true;
  try {
    if (refreshPromise) await refreshPromise;
    let result = await json("/api/integrations/" + id + "/check", {
      method: "POST",
    });
    if (!result.outcome) {
      const deadline = Date.now() + 90000;
      while (Date.now() < deadline) {
        await new Promise((resolve) => setTimeout(resolve, 400));
        const run = await json("/api/runs/" + result.execution_id);
        if (run.check) {
          result = run.check;
          break;
        }
        if (["FAILED", "CANCELLED"].includes(run.status))
          throw new Error("The monitoring run could not finish.");
      }
      if (!result.outcome)
        throw new Error("The check is still waiting for a worker.");
    }
    $("feedback").textContent =
      "Check completed: " + (labels[result.outcome] || result.outcome) + ".";
    await refresh();
  } catch (exc) {
    error(
      exc instanceof TypeError
        ? "Could not connect to the monitoring service."
        : exc.message,
    );
  } finally {
    busy = false;
    $("check-now").disabled = unavailable;
  }
});
refresh();
setInterval(() => {
  if (!busy) refresh();
}, 5000);
