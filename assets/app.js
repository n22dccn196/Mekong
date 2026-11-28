(function () {
  "use strict";

  const apiBase = String(window.MEKONG_API_BASE || "").replace(/\/$/, "");
  const el = (id) => document.getElementById(id);
  const ui = {
    stations: [], selectedId: null, detail: null, history: null, period: "24h",
    start: "", end: "", filters: {search: "", country: "all", river: "all", status: "all"},
    references: null, health: null, comparison: null, historyError: null, listInFlight: null,
    detailController: null, historyController: null, healthController: null,
    compareController: null, detailSequence: 0, historySequence: 0,
    healthSequence: 0, compareSequence: 0, detailBusy: false,
    lastSuccessAt: null, permission: null, permissionState: "unknown",
    connectGesture: false, polling: false, globalOffline: false,
    sourceStates: new Map(), alerts: [], alertKeys: new Set(), toastTimer: null
  };
  const SVG_NS = "http://www.w3.org/2000/svg";
  const mapExtent = {west: 99.388, south: 9.084, east: 108.83324, north: 22.66597};
  const colors = ["#27734e", "#287d9d", "#b46e2d", "#7b5ca4", "#b04c47", "#4e7c87"];
  const horizons = {15: "+15 min", 60: "+1 hour", 360: "+6 hours"};

  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, (char) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[char]));
  }
  function svgNode(tag, attrs) {
    const node = document.createElementNS(SVG_NS, tag);
    Object.keys(attrs || {}).forEach((key) => node.setAttribute(key, attrs[key]));
    return node;
  }
  function time(value) {
    if (!value) return "—";
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return "—";
    return parsed.toLocaleString("en-GB", {timeZone: "UTC", year: "numeric", month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false}) + " UTC";
  }
  function dateUtc(value) {
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? "—" : parsed.toISOString().slice(0, 10);
  }
  function statusClass(status) {
    if (["LIVE_VERIFIED", "LIVE_AWAITING_NEXT_MEASUREMENT", "OK", "READY", "AVAILABLE", "RECENT"].includes(status)) return "live";
    if (["STALE", "SOURCE_ERROR", "STALE_OR_ERROR", "METADATA_INCOMPLETE"].includes(status)) return "error";
    return "pending";
  }
  function statusText(status) {
    const labels = {
      LIVE_VERIFIED: "LIVE VERIFIED", LIVE_AWAITING_NEXT_MEASUREMENT: "LIVE · WAITING",
      LIVE_BLOCKED: "LIVE BLOCKED", NOT_COLLECTED: "NOT COLLECTED", STALE: "STALE",
      SOURCE_ERROR: "SOURCE ERROR", METADATA_INCOMPLETE: "METADATA CHECK",
      NOT_ELIGIBLE_NO_VERIFIED_BENCHMARK: "NO VERIFIED MODEL"
    };
    return labels[status] || String(status || "CHECKING").replace(/_/g, " ");
  }
  function timeoutError() {
    const error = new Error("Request timed out after 8 seconds");
    error.name = "TimeoutError";
    return error;
  }
  async function requestJson(path, controller) {
    const ctl = controller || new AbortController();
    let timedOut = false;
    const timer = window.setTimeout(() => { timedOut = true; ctl.abort(); }, 8000);
    try {
      const response = await fetch(apiBase + path, {
        method: "GET", cache: "no-store", headers: {Accept: "application/json"}, signal: ctl.signal
      });
      const body = await response.text();
      if (timedOut) throw timeoutError();
      if (!response.ok) throw new Error("HTTP " + response.status);
      try { return JSON.parse(body); }
      catch (_) { throw new Error("Response was not valid JSON"); }
    } catch (error) {
      if (timedOut) throw timeoutError();
      throw error;
    } finally {
      window.clearTimeout(timer);
    }
  }

  function sourceBad(station) {
    const poll = station.source_poll_status;
    return ["SOURCE_ERROR", "ERROR"].includes(poll) || ["SOURCE_ERROR", "STALE"].includes(station.status);
  }
  function addAlert(kind, title, detail, key, when) {
    if (ui.alertKeys.has(key)) return;
    ui.alertKeys.add(key);
    const item = {kind, title, detail, when: when || new Date().toISOString()};
    ui.alerts.unshift(item);
    ui.alerts = ui.alerts.slice(0, 40);
    renderAlerts();
    showToast(title + " — " + detail);
  }
  function processSourceAlerts(stations) {
    (stations || []).forEach((station) => {
      const id = String(station.station_id || "");
      const bad = sourceBad(station);
      const previous = ui.sourceStates.get(id);
      if (previous === false && bad) {
        addAlert("loss", "MRC source unavailable", (station.name || id) + " · " + (station.observation_reason || "latest request did not yield a current measurement"), "source:loss:" + id + ":" + (station.source_poll_at_utc || station.status), station.source_poll_at_utc);
      } else if (previous === true && !bad) {
        addAlert("recovery", "MRC source recovered", (station.name || id) + " · latest station state " + statusText(station.status), "source:recovery:" + id + ":" + (station.source_poll_at_utc || station.status), station.source_poll_at_utc);
      }
      ui.sourceStates.set(id, bad);
      processThresholdAlerts(station);
    });
  }
  function verifiedThresholds(station) {
    const metadata = station.observation_metadata || {};
    const block = station.threshold_status || {};
    if (block.status !== "VERIFIED" || !Array.isArray(block.thresholds)) return [];
    const now = Date.now();
    return block.thresholds.filter((threshold) => {
      const level = Number(threshold.level_m == null ? threshold.threshold_m : threshold.level_m);
      const starts = threshold.effective_from_utc ? Date.parse(threshold.effective_from_utc) : NaN;
      const ends = threshold.effective_through_utc ? Date.parse(threshold.effective_through_utc) : NaN;
      return threshold.verified === true && Number.isFinite(level)
        && String(threshold.unit || "").toLowerCase() === String(metadata.unit || "m").toLowerCase()
        && String(threshold.vertical_datum || "") === String(metadata.vertical_datum || station.vertical_datum || "")
        && Number.isFinite(starts) && Number.isFinite(ends) && starts <= now && now <= ends;
    });
  }
  function processThresholdAlerts(station) {
    const thresholds = verifiedThresholds(station);
    if (!thresholds.length) return;
    const measurement = station.latest_measurement || {};
    thresholds.forEach((threshold) => {
      const level = Number(threshold.level_m == null ? threshold.threshold_m : threshold.level_m);
      if (Number(measurement.water_level_m) >= level && measurement.measured_at_utc) {
        addAlert("threshold", "Observed threshold exceeded", (station.name || station.station_id) + " · " + threshold.label + " · " + Number(measurement.water_level_m).toFixed(3) + " m", "threshold:obs:" + station.station_id + ":" + threshold.id + ":" + measurement.measured_at_utc, measurement.measured_at_utc);
      }
      if (station.forecast_status === "READY") (station.forecast || []).forEach((forecast) => {
        if (forecast.benchmark_status === "POINT_FORECAST_VERIFIED" && Number(forecast.predicted_water_level_m) >= level && forecast.target_at_utc) {
          addAlert("threshold", "Forecast threshold exceedance", (station.name || station.station_id) + " · " + threshold.label + " · valid " + time(forecast.target_at_utc), "threshold:forecast:" + station.station_id + ":" + threshold.id + ":" + forecast.target_at_utc, forecast.generated_at_utc || station.forecast_generated_at_utc);
        }
      });
    });
  }
  function renderAlerts() {
    el("alert-count").textContent = String(ui.alerts.length);
    const root = el("alert-list");
    if (!ui.alerts.length) {
      root.innerHTML = '<li class="muted">No events recorded in this page session. Source loss and recovery events appear here.</li>';
      return;
    }
    root.innerHTML = ui.alerts.map((item) => '<li class="alert-item"><span class="alert-kind ' + (item.kind === "loss" ? "loss" : "") + '">' + esc(item.kind.toUpperCase()) + '</span><span class="alert-text"><b>' + esc(item.title) + '</b><br>' + esc(item.detail) + '<small>' + esc(time(item.when)) + ' · MRC / dashboard check</small></span></li>').join("");
  }
  function showToast(message) {
    const toast = el("alert-toast");
    toast.textContent = message;
    toast.hidden = false;
    if (ui.toastTimer) window.clearTimeout(ui.toastTimer);
    ui.toastTimer = window.setTimeout(() => { toast.hidden = true; }, 6500);
    el("toast").textContent = message;
  }
  function setOnline(data) {
    const live = (data.stations || []).some((station) => ["LIVE_VERIFIED", "LIVE_AWAITING_NEXT_MEASUREMENT"].includes(station.status));
    el("connection-label").textContent = live ? "MRC telemetry connected" : "MRC data needs attention";
    el("overall-state").textContent = live ? "LIVE DATA" : "CHECK STATUS";
    el("overall-state").className = "state-chip " + (live ? "state-live" : "state-wait");
    el("connection-dot").classList.toggle("on", live);
    el("footer-source").textContent = live ? "Source status: live verification retained" : "Source status: blocked or stale measurements";
    el("updated-at").textContent = "Checked " + time(data.server_time_utc);
    el("freshness-limit").textContent = String(data.freshness_limit_minutes || 30) + " minutes";
    el("hero-count").textContent = (data.stations || []).length + " catalog stations";
    el("connection-notice").hidden = true;
    if (ui.globalOffline) {
      ui.globalOffline = false;
      addAlert("recovery", "Dashboard connection restored", "The public API is responding again.", "dashboard:recovery", data.server_time_utc);
    }
  }
  function setOffline(message) {
    if (!ui.stations.length && ui.connectGesture && ui.permissionState !== "granted") {
      showPermissionGate(ui.permissionState === "denied");
      return;
    }
    el("connection-label").textContent = "Service unavailable";
    el("overall-state").textContent = "OFFLINE · STALE";
    el("overall-state").className = "state-chip state-stale";
    el("connection-dot").classList.remove("on");
    el("footer-source").textContent = "Source status: disconnected; last values are stale";
    el("connection-notice").hidden = false;
    el("connection-notice").textContent = (message || "Connection lost.") + " Last values remain in this page only; forecasts are hidden. Use Retry after connectivity returns.";
    if (!ui.globalOffline) {
      ui.globalOffline = true;
      addAlert("loss", "Dashboard connection lost", "Public API requests failed; readings are marked stale and forecasts are hidden.", "dashboard:loss", new Date().toISOString());
    }
    renderStations();
    if (ui.detail) renderDetail(true, message);
  }
  function showPermissionGate(denied) {
    el("connection-label").textContent = denied ? "Local network access denied" : "Local network access needed";
    el("overall-state").textContent = denied ? "ALLOW IN SITE SETTINGS" : "CONNECT TO LIVE DATA";
    el("overall-state").className = "state-chip state-wait";
    el("connection-dot").classList.remove("on");
    el("footer-source").textContent = "Source status: waiting for browser local-network permission";
    el("connection-notice").hidden = false;
    el("connection-notice").textContent = denied
      ? "Local network access is blocked. Allow it in site permissions, then click Check permission."
      : "Allow Local network access for this site, then click Connect. MRC readings refresh automatically.";
    el("retry-button").textContent = denied ? "Check permission" : "Connect";
    if (!ui.stations.length) {
      el("station-grid").innerHTML = '<div class="empty-card"><p>Allow local network access to load the MRC station catalog.</p></div>';
      el("station-detail").innerHTML = '<div class="empty-card"><p>Station detail, history and verified forecasts load after connection.</p></div>';
    }
  }
  function startPolling() {
    if (ui.polling) return;
    ui.polling = true;
    el("retry-button").textContent = "Retry";
    refreshStations();
    window.setInterval(refreshStations, 30000);
  }
  async function onPermissionChange() {
    if (!ui.permission) return;
    ui.permissionState = ui.permission.state;
    if (ui.permissionState === "granted") {
      el("connection-notice").hidden = true;
      startPolling();
    } else if (ui.permissionState === "denied") {
      showPermissionGate(true);
    } else if (!ui.polling) {
      showPermissionGate(false);
    }
  }
  async function initNetworkPermission() {
    let origin = "";
    try { origin = new URL(apiBase || location.href, location.href).origin; } catch (_) { /* invalid base is reported by fetch */ }
    if (!apiBase || origin === location.origin) {
      ui.permissionState = "granted";
      startPolling();
      return;
    }
    if (!navigator.permissions || !navigator.permissions.query) {
      ui.permissionState = "unsupported";
      showPermissionGate(false);
      return;
    }
    try {
      ui.permission = await navigator.permissions.query({name: "local-network"});
      ui.permissionState = ui.permission.state;
      if (ui.permission.addEventListener) ui.permission.addEventListener("change", onPermissionChange);
      else ui.permission.onchange = onPermissionChange;
      if (ui.permissionState === "granted") startPolling();
      else showPermissionGate(ui.permissionState === "denied");
    } catch (_) {
      ui.permissionState = "unsupported";
      showPermissionGate(false);
    }
  }
  async function connectFromGesture() {
    ui.connectGesture = true;
    if (ui.permissionState === "denied" && navigator.permissions && navigator.permissions.query) {
      try {
        ui.permission = await navigator.permissions.query({name: "local-network"});
        ui.permissionState = ui.permission.state;
      } catch (_) { ui.permissionState = "denied"; }
      if (ui.permissionState === "denied") { showPermissionGate(true); return; }
    }
    el("retry-button").textContent = "Connecting…";
    const pending = refreshStations();
    if (!ui.polling) pending.then(() => {
      if (ui.stations.length) startPolling();
      else if (ui.permissionState !== "granted") showPermissionGate(ui.permissionState === "denied");
    });
  }

  function filteredStations() {
    const q = ui.filters.search.trim().toLocaleLowerCase();
    return ui.stations.filter((station) => {
      const text = [station.station_id, station.name, station.river, station.country].join(" ").toLocaleLowerCase();
      const status = station.status || "";
      const live = ["LIVE_VERIFIED", "LIVE_AWAITING_NEXT_MEASUREMENT"].includes(status);
      const stale = ["STALE", "SOURCE_ERROR"].includes(status);
      return (!q || text.includes(q)) && (ui.filters.country === "all" || station.country === ui.filters.country)
        && (ui.filters.river === "all" || station.river === ui.filters.river)
        && (ui.filters.status === "all" || (ui.filters.status === "live" && live)
          || (ui.filters.status === "stale" && stale)
          || (ui.filters.status === "blocked" && !live && !stale));
    });
  }
  function selectedStation() {
    return ui.stations.find((station) => String(station.station_id) === String(ui.selectedId)) || null;
  }
  function renderStationListOptions() {
    const selectedCountry = el("country-filter").value || "all";
    const selectedRiver = el("river-filter").value || "all";
    const countryValues = Array.from(new Set(ui.stations.map((station) => station.country || "Unknown country"))).sort();
    const riverValues = Array.from(new Set(ui.stations.map((station) => station.river || "Unknown river"))).sort();
    if (el("country-filter").dataset.values !== countryValues.join("|") ) {
      el("country-filter").innerHTML = '<option value="all">All countries</option>' + countryValues.map((value) => '<option value="' + esc(value) + '">' + esc(value) + '</option>').join("");
      el("country-filter").dataset.values = countryValues.join("|");
      if (countryValues.includes(selectedCountry)) el("country-filter").value = selectedCountry;
    }
    if (el("river-filter").dataset.values !== riverValues.join("|") ) {
      el("river-filter").innerHTML = '<option value="all">All rivers</option>' + riverValues.map((value) => '<option value="' + esc(value) + '">' + esc(value) + '</option>').join("");
      el("river-filter").dataset.values = riverValues.join("|");
      if (riverValues.includes(selectedRiver)) el("river-filter").value = selectedRiver;
    }
    const root = el("compare-stations");
    const chosen = Array.from(root.selectedOptions || []).map((option) => option.value);
    root.innerHTML = ui.stations.map((station) => '<option value="' + esc(station.station_id) + '">' + esc(station.name || station.station_id) + ' · ' + esc(station.station_id) + ' · ' + esc(station.country || "country unavailable") + '</option>').join("");
    chosen.forEach((id) => { const option = Array.from(root.options).find((row) => row.value === id); if (option) option.selected = true; });
  }
  function renderStations() {
    const rows = filteredStations();
    el("visible-count").textContent = rows.length + " shown";
    el("station-count").textContent = ui.stations.length + " catalog stations · select a marker or row";
    drawMap(rows);
    if (!rows.length) {
      el("station-grid").innerHTML = '<div class="empty-card"><p>No stations match these filters.</p></div>';
      return;
    }
    el("station-grid").innerHTML = rows.map((station) => {
      const id = String(station.station_id);
      const reading = station.latest_measurement || {};
      const stale = ui.globalOffline;
      const cls = stale ? "error" : statusClass(station.status);
      const label = stale ? "STALE · LAST KNOWN" : statusText(station.status);
      return '<button type="button" class="station-row ' + (id === String(ui.selectedId) ? "selected" : "") + '" data-station-id="' + esc(id) + '" aria-pressed="' + (id === String(ui.selectedId) ? "true" : "false") + '"><span><span class="station-name">' + esc(station.name || id) + '</span><span class="station-id">MRC ' + esc(id) + ' · ' + esc(station.river || "River not verified") + '</span><span class="status-label ' + cls + '">' + esc(label) + '</span></span><span class="row-reading"><strong>' + (reading.water_level_m == null ? "—" : Number(reading.water_level_m).toFixed(3) + " m") + '</strong><small>' + esc(time(reading.measured_at_utc)) + '</small></span></button>';
    }).join("");
  }
  function drawMap(rows) {
    const map = el("station-map");
    map.replaceChildren();
    const points = (rows || []).filter((station) => Number.isFinite(Number(station.latitude)) && Number.isFinite(Number(station.longitude)))
      .map((station) => ({station, lat: Number(station.latitude), lon: Number(station.longitude)}));
    if (!points.length) {
      const empty = svgNode("text", {x: 310, y: 255, "text-anchor": "middle", class: "map-axis"});
      empty.textContent = "Verified station coordinates are unavailable";
      map.append(empty);
      return;
    }
    const inside = points.every((point) => point.lon >= mapExtent.west && point.lon <= mapExtent.east && point.lat >= mapExtent.south && point.lat <= mapExtent.north);
    let bounds = mapExtent;
    if (!inside) {
      const minLon = Math.min(...points.map((point) => point.lon));
      const maxLon = Math.max(...points.map((point) => point.lon));
      const minLat = Math.min(...points.map((point) => point.lat));
      const maxLat = Math.max(...points.map((point) => point.lat));
      const pad = Math.max(.2, (maxLon - minLon) * .06, (maxLat - minLat) * .06);
      bounds = {west: minLon - pad, east: maxLon + pad, south: minLat - pad, north: maxLat + pad};
    } else {
      map.append(svgNode("image", {href: "./assets/station-basemap.svg", x: 0, y: 0, width: 620, height: 520, "aria-hidden": "true"}));
    }
    const left = 150, right = 470, top = 22, bottom = 490;
    const mercator = (lat) => Math.log(Math.tan(Math.PI / 4 + Math.max(-85, Math.min(85, lat)) * Math.PI / 360));
    const northY = mercator(bounds.north), southY = mercator(bounds.south), spanY = Math.max(.001, northY - southY);
    for (let index = 0; index <= 5; index += 1) {
      const x = left + (right - left) * index / 5;
      const y = top + (bottom - top) * index / 5;
      map.append(svgNode("line", {x1: x, y1: top, x2: x, y2: bottom, class: "map-grid"}));
      map.append(svgNode("line", {x1: left, y1: y, x2: right, y2: y, class: "map-grid"}));
      const longitude = svgNode("text", {x, y: 508, "text-anchor": "middle", class: "map-axis"});
      longitude.textContent = (bounds.west + (bounds.east - bounds.west) * index / 5).toFixed(1) + "°E";
      const latitudeValue = 2 * Math.atan(Math.exp(northY - spanY * index / 5)) - Math.PI / 2;
      const latitude = svgNode("text", {x: 143, y: y + 3, "text-anchor": "end", class: "map-axis"});
      latitude.textContent = (latitudeValue * 180 / Math.PI).toFixed(1) + "°N";
      map.append(longitude, latitude);
    }
    const note = svgNode("text", {x: left + 5, y: 15, class: "map-note"});
    note.textContent = inside ? "MRC station coordinates · Natural Earth context only" : "MRC station coordinates · generalized extent";
    map.append(note);
    points.forEach(({station, lat, lon}) => {
      const x = left + (lon - bounds.west) / Math.max(.0001, bounds.east - bounds.west) * (right - left);
      const y = top + (northY - mercator(lat)) / spanY * (bottom - top);
      const group = svgNode("g", {
        class: "station-marker " + (station.country === "Viet Nam" ? "vietnam" : "upstream") + " " + statusClass(station.status) + (String(station.station_id) === String(ui.selectedId) ? " selected" : ""),
        tabindex: "0", role: "button", "data-station-id": station.station_id,
        "aria-label": "Select " + (station.name || "station") + " " + station.station_id + ", " + statusText(station.status)
      });
      const title = svgNode("title", {});
      title.textContent = (station.name || "Unknown") + " · " + station.station_id + " · " + (station.river || "River unavailable") + " · " + statusText(station.status);
      group.append(title, svgNode("circle", {cx: x, cy: y, r: 9, class: "marker-halo"}), svgNode("circle", {cx: x, cy: y, r: 4, class: "marker-dot"}));
      group.addEventListener("click", () => selectStation(station.station_id));
      group.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); selectStation(station.station_id); } });
      map.append(group);
    });
  }

  function historyRequest(period, start, end, id) {
    const params = new URLSearchParams({period});
    if (period === "custom") { params.set("start", start); params.set("end", end); }
    return "/v1/public/stations/" + encodeURIComponent(id) + "/history?" + params.toString();
  }
  function stationById(id) { return ui.stations.find((station) => String(station.station_id) === String(id)); }
  async function selectStation(id, options) {
    const station = stationById(id);
    if (!station) return;
    const quiet = Boolean(options && options.quiet);
    ui.selectedId = String(id);
    const sequence = ++ui.detailSequence;
    if (ui.detailController) ui.detailController.abort();
    if (ui.historyController) ui.historyController.abort();
    ui.detailController = new AbortController();
    ui.historyController = new AbortController();
    const detailController = ui.detailController;
    const historyController = ui.historyController;
    ui.detailBusy = true;
    if (!ui.detail || String(ui.detail.station && ui.detail.station.station_id) !== String(id)) { ui.history = null; ui.historyError = null; }
    renderStations();
    if (ui.detail && String(ui.detail.station && ui.detail.station.station_id) === String(id)) renderDetail(true, "Refreshing selected station; forecast hidden until the request completes.");
    else if (!quiet) el("station-detail").innerHTML = '<div class="empty-card"><span class="spinner"></span><p>Loading station detail and history…</p></div>';
    const period = ui.period;
    const start = el("history-start") ? el("history-start").value : ui.start;
    const end = el("history-end") ? el("history-end").value : ui.end;
    try {
      const detailPath = "/v1/public/stations/" + encodeURIComponent(String(id));
      const historyPath = historyRequest(period, start, end, id);
      const [detailResult, historyResult] = await Promise.allSettled([
        requestJson(detailPath, detailController), requestJson(historyPath, historyController)
      ]);
      if (sequence !== ui.detailSequence || String(ui.selectedId) !== String(id)) return;
      if (detailResult.status !== "fulfilled") throw detailResult.reason;
      const detail = detailResult.value;
      if (!detail.station || String(detail.station.station_id) !== String(id)) throw new Error("Station detail contract mismatch");
      if (historyResult.status === "fulfilled" && String(historyResult.value.station_id) !== String(id)) throw new Error("Station history contract mismatch");
      ui.detail = detail;
      if (historyResult.status === "fulfilled") { ui.history = historyResult.value; ui.historyError = null; }
      else if (!historyController.signal.aborted) ui.historyError = String(historyResult.reason && historyResult.reason.message || "History request failed");
      ui.lastSuccessAt = new Date().toISOString();
      processThresholdAlerts(detail.station);
      renderDetail(false);
      updateThresholdStatus(detail.station);
    } catch (error) {
      if (sequence !== ui.detailSequence || detailController.signal.aborted || historyController.signal.aborted) return;
      const message = String(error && error.message || "Request failed");
      if (ui.detail && String(ui.detail.station && ui.detail.station.station_id) === String(id)) renderDetail(true, message);
      else el("station-detail").innerHTML = '<div class="empty-card"><p>' + esc(message) + '</p><button id="detail-retry" class="button" type="button">Retry station</button></div>';
    } finally {
      if (sequence === ui.detailSequence) ui.detailBusy = false;
    }
  }
  async function refreshHistory() {
    if (!ui.selectedId) return;
    if (ui.period === "custom" && (!el("history-start").value || !el("history-end").value || el("history-start").value > el("history-end").value)) {
      ui.historyError = "Choose a valid custom start and end date.";
      el("history-meta").textContent = "History unavailable: " + ui.historyError;
      return;
    }
    const sequence = ++ui.historySequence;
    if (ui.historyController) ui.historyController.abort();
    ui.historyController = new AbortController();
    const controller = ui.historyController;
    try {
      const history = await requestJson(historyRequest(ui.period, el("history-start").value, el("history-end").value, ui.selectedId), controller);
      if (sequence !== ui.historySequence || String(history.station_id) !== String(ui.selectedId)) return;
      ui.history = history;
      ui.historyError = null;
      renderDetail(ui.globalOffline);
    } catch (error) {
      if (sequence !== ui.historySequence || controller.signal.aborted) return;
      ui.historyError = String(error.message || "request failed");
      el("history-meta").textContent = "History unavailable: " + String(error.message || "request failed") + ". Use Retry.";
    }
  }
  async function refreshStations() {
    if (ui.listInFlight) return ui.listInFlight;
    const run = (async () => {
      try {
        const data = await requestJson("/v1/public/stations");
        if (data.source_type !== "mrc_telemetry" || !Array.isArray(data.stations)) throw new Error("Station list contract mismatch");
        processSourceAlerts(data.stations);
        ui.stations = data.stations;
        if (!ui.references) loadReferences();
        ui.lastSuccessAt = new Date().toISOString();
        renderStationListOptions();
        setOnline(data);
        renderStations();
        if (!ui.selectedId || !stationById(ui.selectedId)) {
          ui.selectedId = stationById("039801") ? "039801" : String((ui.stations[0] || {}).station_id || "");
        }
        if (ui.selectedId && !ui.detailBusy) await selectStation(ui.selectedId, {quiet: true});
        if (document.getElementById("panel-health").hidden === false) loadHealth();
        if (document.getElementById("panel-compare").hidden === false && ui.comparison) loadComparison();
      } catch (error) {
        setOffline(String(error && error.message || "Request failed"));
      }
    })();
    ui.listInFlight = run;
    run.then(() => { if (ui.listInFlight === run) ui.listInFlight = null; }, () => { if (ui.listInFlight === run) ui.listInFlight = null; });
    return run;
  }

  function drawCrossSection(station, stale) {
    const line = el("waterline"), body = el("water-body"), label = el("waterline-label"), mode = el("waterline-mode");
    const forecasts = stale ? [] : ((station && station.forecast) || []);
    const selectedHorizon = mode.value === "observed" ? null : Number(mode.value);
    const forecast = selectedHorizon == null ? null : forecasts.find((item) => Number(item.horizon_minutes) === selectedHorizon);
    Array.from(mode.options).forEach((option) => { if (option.value !== "observed") option.disabled = !forecasts.some((item) => Number(item.horizon_minutes) === Number(option.value)); });
    if (mode.value !== "observed" && !forecast) mode.value = "observed";
    const measurement = station && station.latest_measurement;
    const historyPoints = (ui.history && ui.history.points) || [];
    const values = historyPoints.map((point) => Number(point.water_level_m)).filter(Number.isFinite);
    const value = mode.value === "observed" ? Number(measurement && measurement.water_level_m) : Number(forecast && forecast.predicted_water_level_m);
    if (!Number.isFinite(value)) {
      line.setAttribute("y1", "142"); line.setAttribute("y2", "142"); body.setAttribute("d", "");
      label.textContent = "—"; el("cross-value").textContent = "No valid level"; el("cross-time").textContent = "No verified measurement or forecast";
      return;
    }
    values.push(value);
    let low = Math.min.apply(null, values), high = Math.max.apply(null, values);
    if (high - low < .05) { low -= .05; high += .05; }
    const y = 190 - (value - low) / (high - low) * 92;
    line.setAttribute("y1", String(y)); line.setAttribute("y2", String(y));
    body.setAttribute("d", "M110 " + y + " L170 164 C209 203 253 226 326 230 C402 232 445 204 493 163 L557 " + y + " Z");
    label.setAttribute("y", String(y - 7)); label.textContent = value.toFixed(3) + " " + (station.observation_metadata && station.observation_metadata.unit || "m");
    el("cross-value-label").textContent = mode.value === "observed" ? "Latest observation" : "Forecast · " + horizons[selectedHorizon];
    el("cross-value").textContent = value.toFixed(3) + " " + (station.observation_metadata && station.observation_metadata.unit || "m");
    el("cross-time").textContent = mode.value === "observed" ? "Measured " + time(measurement && measurement.measured_at_utc) : "Valid " + time(forecast.target_at_utc) + " · generated " + time(forecast.generated_at_utc || station.forecast_generated_at_utc);
  }
  function chartMarkup(history, forecasts, stale) {
    const root = el("history-chart");
    root.replaceChildren();
    const observations = stale ? [] : ((history && history.points) || []);
    const validForecasts = stale ? [] : (forecasts || []).filter((item) => Number.isFinite(Number(item.predicted_water_level_m)) && Date.parse(item.target_at_utc) >= Date.now());
    const values = observations.map((point) => Number(point.water_level_m)).concat(validForecasts.map((item) => Number(item.predicted_water_level_m))).filter(Number.isFinite);
    const minX = Date.parse((history && history.requested_start_utc) || observations[0] && observations[0].measured_at_utc || new Date().toISOString());
    const historyEnd = Date.parse((history && history.requested_end_utc) || new Date().toISOString());
    const forecastEnd = validForecasts.reduce((max, item) => Math.max(max, Date.parse(item.target_at_utc)), historyEnd);
    const maxX = Math.max(historyEnd, forecastEnd, minX + 1);
    let low = values.length ? Math.min.apply(null, values) : 0;
    let high = values.length ? Math.max.apply(null, values) : 1;
    if (high - low < .05) { low -= .05; high += .05; }
    const left = 54, right = 870, top = 20, bottom = 270, width = right - left, height = bottom - top;
    for (let index = 0; index <= 4; index += 1) {
      const y = top + height * index / 4;
      root.append(svgNode("line", {x1: left, y1: y, x2: right, y2: y, class: "chart-gridline"}));
      const label = svgNode("text", {x: left - 8, y: y + 3, "text-anchor": "end", class: "chart-axis-text"});
      label.textContent = (high - (high - low) * index / 4).toFixed(2);
      root.append(label);
    }
    const xFor = (value) => left + (Date.parse(value) - minX) / Math.max(1, maxX - minX) * width;
    const yFor = (value) => bottom - (Number(value) - low) / Math.max(.0001, high - low) * height;
    const grouped = new Map();
    observations.forEach((point) => { const key = Number(point.segment || 0); if (!grouped.has(key)) grouped.set(key, []); grouped.get(key).push(point); });
    grouped.forEach((points) => {
      if (!points.length) return;
      const d = points.map((point, index) => (index ? "L" : "M") + xFor(point.measured_at_utc).toFixed(1) + " " + yFor(point.water_level_m).toFixed(1)).join(" ");
      root.append(svgNode("path", {d, class: "chart-line"}));
      points.forEach((point) => root.append(svgNode("circle", {cx: xFor(point.measured_at_utc), cy: yFor(point.water_level_m), r: 2.7, class: "chart-point"})));
    });
    if (observations.length && validForecasts.length) {
      const ordered = validForecasts.slice().sort((a, b) => Date.parse(a.target_at_utc) - Date.parse(b.target_at_utc));
      const path = [{measured_at_utc: observations[observations.length - 1].measured_at_utc, water_level_m: observations[observations.length - 1].water_level_m}].concat(ordered.map((item) => ({measured_at_utc: item.target_at_utc, water_level_m: item.predicted_water_level_m})));
      root.append(svgNode("path", {d: path.map((point, index) => (index ? "L" : "M") + xFor(point.measured_at_utc).toFixed(1) + " " + yFor(point.water_level_m).toFixed(1)).join(" "), class: "forecast-line"}));
      ordered.forEach((item) => root.append(svgNode("circle", {cx: xFor(item.target_at_utc), cy: yFor(item.predicted_water_level_m), r: 4, class: "forecast-point"})));
    }
    [[left, minX], [right, maxX]].forEach(([x, value]) => {
      const label = svgNode("text", {x, y: 294, "text-anchor": x === left ? "start" : "end", class: "chart-axis-text"});
      label.textContent = new Date(Number(value)).toLocaleString("en-GB", {timeZone: "UTC", month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false}) + " UTC";
      root.append(label);
    });
    root.setAttribute("aria-label", "Observed water levels and verified forecast on a UTC time axis");
  }
  function renderForecasts(station, stale) {
    const items = stale ? [] : ((station && station.forecast) || []);
    if (!station) { el("forecast-cards").innerHTML = '<div class="forecast-empty">Select a station · verified forecasts only.</div>'; return; }
    const cells = [15, 60, 360].map((minutes) => {
      const forecast = items.find((item) => Number(item.horizon_minutes) === minutes);
      const waiting = station.forecast_status === "WAITING_FOR_FORECAST_REFRESH" && station.forecast_refresh_expected_at_utc;
      const reason = stale ? "Hidden while connection is unavailable." : waiting
        ? "Refresh expected by " + time(station.forecast_refresh_expected_at_utc) + ". Previous forecast is not shown."
        : (station.forecast_reason || "No verified forecast for this station and horizon.");
      return forecast
        ? '<div class="forecast-cell"><span>' + esc(horizons[minutes]) + ' · verified point forecast</span><strong>' + Number(forecast.predicted_water_level_m).toFixed(3) + ' m</strong><small>Target ' + esc(time(forecast.target_at_utc)) + '<br>Generated ' + esc(time(forecast.generated_at_utc || station.forecast_generated_at_utc)) + '<br>Model ' + esc(forecast.model_version || station.model_version || "version unavailable") + '</small></div>'
        : '<div class="forecast-cell"><span>' + esc(horizons[minutes]) + '</span><strong>—</strong><small>' + esc(reason) + '</small></div>';
    }).join("");
    el("forecast-cards").innerHTML = cells;
  }
  function renderThresholdDetail(station) {
    const threshold = station.threshold_status || (ui.references && ui.references.thresholds) || {status: "BLOCKED_EFFECTIVE_DATE_UNKNOWN", reason: "Threshold source has not been verified."};
    const suffix = threshold.status === "VERIFIED" ? "Verified threshold source active." : (threshold.reason || "Threshold mapping, units, datum or effective date is unverified.");
    el("station-threshold").textContent = "Threshold status: " + statusText(threshold.status) + ". " + suffix;
  }
  function renderDetail(stale, errorText) {
    const payload = ui.detail;
    const station = payload && payload.station;
    if (!station) return;
    const measurement = station.latest_measurement || {};
    const meta = station.observation_metadata || {};
    const status = stale ? "STALE · LAST KNOWN" : statusText(station.status);
    const cls = stale ? "error" : statusClass(station.status);
    const forecastGenerated = stale ? "hidden while stale" : station.forecast_generated_at_utc ? time(station.forecast_generated_at_utc) : "not generated";
    const notes = [stale ? (errorText || "Connection lost. Last reading is shown as stale; forecasts are hidden.") : station.observation_reason, (meta.gaps || []).length ? "Metadata gaps: " + meta.gaps.join(" ") : ""].filter(Boolean);
    el("station-detail").innerHTML = '<article class="detail-card"><header class="detail-head"><div><p class="eyebrow">SELECTED MRC STATION</p><h2>' + esc(station.name || station.station_id) + '</h2><div class="detail-subtitle">' + esc(String(station.station_id)) + ' · ' + esc(station.country || "Country unavailable") + ' · ' + esc(station.river || "River unavailable") + '</div></div><span class="status-label ' + cls + '">' + esc(status) + '</span></header>'
      + (notes.length ? '<p class="station-note">' + esc(notes.join(" ")) + '</p>' : "")
      + '<div class="measurement-card"><div><div class="level-number">' + (measurement.water_level_m == null ? "—" : Number(measurement.water_level_m).toFixed(3)) + '<small>' + esc(meta.unit || "m") + '</small></div><div class="level-label">LATEST OBSERVED WATER LEVEL</div></div><div class="time-pair">MEASURED <b>' + esc(time(measurement.measured_at_utc)) + '</b><br>RECEIVED <b>' + esc(time(measurement.received_at_utc)) + '</b><br>AGE <b>' + (measurement.age_minutes == null ? "—" : esc(measurement.age_minutes) + " min") + '</b><br>DATUM <b>' + esc(meta.vertical_datum || station.vertical_datum || "Not verified") + '</b></div></div>'
      + '<section class="detail-section"><div class="detail-section-title"><div><p class="eyebrow">INTERACTIVE SECTION</p><h3>Water level profile</h3></div><label class="history-controls">Display<select id="waterline-mode"><option value="observed">Latest observation</option><option value="15">Forecast · 15 min</option><option value="60">Forecast · 1 hour</option><option value="360">Forecast · 6 hours</option></select></label></div><div class="cross-wrap"><svg id="station-cross-section" viewBox="0 0 760 300" role="img" aria-label="Illustrative water-level profile; not surveyed or to scale"><path class="bank-shape" d="M82 70 C105 104 133 128 170 164 C209 203 253 226 326 230 C402 232 445 204 493 163 C532 130 559 103 585 70 L585 252 L82 252 Z"></path><path id="water-body" class="water-body"></path><path class="bed-line" d="M82 70 C105 104 133 128 170 164 C209 203 253 226 326 230 C402 232 445 204 493 163 C532 130 559 103 585 70"></path><line id="waterline" class="waterline" x1="110" y1="142" x2="557" y2="142"></line><text id="waterline-label" class="waterline-label" x="570" y="137">—</text><text class="section-bank-label" x="94" y="56">LEFT BANK</text><text class="section-bank-label" x="516" y="56">RIGHT BANK</text><text class="section-axis-label" x="350" y="280">Illustrative profile · not to scale</text></svg><div class="cross-reading"><span id="cross-value-label">Selected level</span><strong id="cross-value">—</strong><small id="cross-time">No valid value selected</small></div></div><p class="illustrative-note"><b>Illustrative only.</b> Surveyed channel geometry and bank elevations are not verified; the drawn shape is not to scale.</p></section>'
      + '<section class="detail-section"><div class="detail-section-title"><div><p class="eyebrow">OBSERVATION HISTORY</p><h3>Water-level timeline</h3></div><span id="datum-note">' + esc(meta.unit || "m") + ' · ' + esc(meta.vertical_datum || station.vertical_datum || "datum unavailable") + '</span></div><div class="history-controls"><label for="history-range">Window<select id="history-range"><option value="24h">24 hours</option><option value="7d">7 days</option><option value="season">Season · up to 180 days</option><option value="custom">Custom dates</option></select></label><label id="history-start-label" class="custom-date" for="history-start" hidden>From<input id="history-start" type="date"></label><label id="history-end-label" class="custom-date" for="history-end" hidden>Through<input id="history-end" type="date"></label><button id="history-retry" class="button" type="button">Refresh history</button></div><div id="history-meta" class="history-meta">History loads after station selection.</div><div class="chart-wrap"><svg id="history-chart" viewBox="0 0 900 310" role="img" aria-label="Observed water level with verified forecast on a UTC time axis"></svg></div><div class="export-actions"><button id="export-csv" class="button" type="button">Export CSV</button><button id="export-png" class="button" type="button">Export chart PNG</button></div></section>'
      + '<section class="detail-section"><div class="detail-section-title"><div><p class="eyebrow">RESEARCH OUTPUT</p><h3>Forecast horizons</h3></div><span>NOT AN OFFICIAL WARNING<br>Generated ' + esc(forecastGenerated) + '</span></div><div id="forecast-cards" class="forecast-strip"></div></section>'
      + '<section class="detail-section"><div id="station-threshold" class="threshold-banner">Threshold status: unavailable.</div><div class="detail-subtitle">Source: MRC recent telemetry · Last source poll ' + esc(time(station.source_poll_at_utc)) + ' · HTTP ' + esc(station.source_poll_http_status || "not recorded") + '</div></section>'
      + (errorText && !stale ? '<div class="station-note">' + esc(errorText) + ' <button id="detail-retry" class="button" type="button">Retry station</button></div>' : "") + '</article>';
    const period = el("history-range");
    period.value = ui.period;
    el("history-start").value = ui.start;
    el("history-end").value = ui.end;
    updateCustomControls();
    const metaText = ui.historyError ? "History unavailable: " + ui.historyError + ". Use Retry history." : ui.history
      ? ui.history.status + " · " + (ui.history.coverage_percent || 0) + "% of requested window · " + (ui.history.point_count || 0) + " measurements · " + (ui.history.cadence_minutes || "unknown") + " min median cadence · " + (ui.history.gap_count || 0) + " gaps · longest " + (ui.history.longest_gap_minutes || 0) + " min · data " + time(ui.history.coverage_start_utc) + " to " + time(ui.history.coverage_end_utc) + " · archive/request limit " + (ui.history.archive_limit_days || 180) + " days" + (ui.history.reason ? " · " + ui.history.reason : "")
      : "History is unavailable for this station.";
    el("history-meta").textContent = metaText;
    drawCrossSection(station, stale);
    chartMarkup(ui.history, station.forecast, stale);
    renderForecasts(station, stale);
    renderThresholdDetail(station);
  }
  function updateCustomControls() {
    const historyCustom = ui.period === "custom";
    if (el("history-start-label")) el("history-start-label").hidden = !historyCustom;
    if (el("history-end-label")) el("history-end-label").hidden = !historyCustom;
    const compareCustom = el("compare-period").value === "custom";
    document.querySelectorAll(".range-controls .custom-date").forEach((label) => { label.hidden = !compareCustom; });
  }
  function updateThresholdStatus(station) {
    const status = station && station.threshold_status || (ui.references && ui.references.thresholds) || {};
    const root = el("threshold-status");
    root.innerHTML = '<strong>Threshold alerts ' + (status.status === "VERIFIED" ? "active" : "unavailable") + '</strong><span>' + esc(status.reason || "No effective threshold has been verified for this station. No exceedance signal is calculated.") + '</span>';
  }

  function compareSelectedIds() {
    return Array.from(el("compare-stations").selectedOptions).map((option) => option.value);
  }
  function comparisonPath(ids, period, start, end) {
    const params = new URLSearchParams({stations: ids.join(","), period});
    if (period === "custom") { params.set("start", start); params.set("end", end); }
    return "/v1/public/compare?" + params.toString();
  }
  async function loadComparison() {
    const ids = compareSelectedIds();
    if (!ids.length || ids.length > 6) {
      el("compare-summary").textContent = "Choose one to six stations.";
      el("compare-warning").hidden = false;
      el("compare-warning").textContent = "Choose at least one and no more than six stations.";
      return;
    }
    const period = el("compare-period").value;
    const start = el("compare-start").value;
    const end = el("compare-end").value;
    if (period === "custom" && (!start || !end || start > end)) {
      el("compare-warning").hidden = false;
      el("compare-warning").textContent = "Choose a valid custom start and end date.";
      return;
    }
    const sequence = ++ui.compareSequence;
    if (ui.compareController) ui.compareController.abort();
    ui.compareController = new AbortController();
    const controller = ui.compareController;
    el("compare-load").textContent = "Loading…";
    try {
      const data = await requestJson(comparisonPath(ids, period, start, end), controller);
      if (sequence !== ui.compareSequence) return;
      ui.comparison = data;
      el("compare-warning").hidden = false;
      el("compare-warning").textContent = data.warning + " Each station's own datum and unit are shown below.";
      el("compare-summary").textContent = data.stations.length + " stations · checked " + time(data.server_time_utc);
      renderComparison(data);
    } catch (error) {
      if (sequence !== ui.compareSequence || controller.signal.aborted) return;
      ui.comparison = null;
      el("compare-warning").hidden = false;
      el("compare-warning").textContent = "Comparison unavailable: " + String(error.message || "request failed") + ". Retry when the API is reachable.";
      el("compare-chart").replaceChildren();
      el("compare-table").innerHTML = "";
    } finally {
      if (sequence === ui.compareSequence) el("compare-load").textContent = "Load comparison";
    }
  }
  function renderComparison(data) {
    const chart = el("compare-chart");
    chart.replaceChildren();
    const series = data.stations || [];
    const allPoints = series.flatMap((item) => (item.history.points || []).map((point) => ({...point, station: item})));
    const forecastPoints = series.flatMap((item) => (item.forecast || []).filter((forecast) => Date.parse(forecast.target_at_utc) >= Date.now()).map((forecast) => ({...forecast, station: item})));
    const values = allPoints.map((point) => Number(point.water_level_m)).concat(forecastPoints.map((point) => Number(point.predicted_water_level_m))).filter(Number.isFinite);
    if (!allPoints.length) {
      const label = svgNode("text", {x: 450, y: 170, "text-anchor": "middle", class: "chart-axis-text"});
      label.textContent = "No measurements fall in the selected window"; chart.append(label);
    } else {
      let low = Math.min.apply(null, values), high = Math.max.apply(null, values);
      if (high - low < .05) { low -= .05; high += .05; }
      const minX = Math.min(...allPoints.map((point) => Date.parse(point.measured_at_utc)));
      const maxX = Math.max(...allPoints.map((point) => Date.parse(point.measured_at_utc)).concat(forecastPoints.map((point) => Date.parse(point.target_at_utc))));
      const left = 55, right = 880, top = 18, bottom = 285, width = right - left, height = bottom - top;
      for (let index = 0; index <= 4; index += 1) {
        const y = top + height * index / 4;
        chart.append(svgNode("line", {x1: left, y1: y, x2: right, y2: y, class: "chart-gridline"}));
        const label = svgNode("text", {x: left - 8, y: y + 3, "text-anchor": "end", class: "chart-axis-text"});
        label.textContent = (high - (high - low) * index / 4).toFixed(2); chart.append(label);
      }
      const x = (value) => left + (Date.parse(value) - minX) / Math.max(1, maxX - minX) * width;
      const y = (value) => bottom - (Number(value) - low) / Math.max(.0001, high - low) * height;
      series.forEach((item, index) => {
        const grouped = new Map();
        (item.history.points || []).forEach((point) => { const key = Number(point.segment || 0); if (!grouped.has(key)) grouped.set(key, []); grouped.get(key).push(point); });
        grouped.forEach((points) => {
          if (points.length < 1) return;
          chart.append(svgNode("path", {d: points.map((point, pointIndex) => (pointIndex ? "L" : "M") + x(point.measured_at_utc).toFixed(1) + " " + y(point.water_level_m).toFixed(1)).join(" "), fill: "none", stroke: colors[index % colors.length], "stroke-width": "2"}));
        });
        const forecasts = forecastPoints.filter((point) => point.station.station_id === item.station_id).sort((a, b) => Date.parse(a.target_at_utc) - Date.parse(b.target_at_utc));
        const observations = (item.history.points || []).slice().sort((a, b) => Date.parse(a.measured_at_utc) - Date.parse(b.measured_at_utc));
        if (forecasts.length && observations.length) {
          const timeline = [{at: observations[observations.length - 1].measured_at_utc, level: observations[observations.length - 1].water_level_m}].concat(forecasts.map((point) => ({at: point.target_at_utc, level: point.predicted_water_level_m})));
          chart.append(svgNode("path", {d: timeline.map((point, pointIndex) => (pointIndex ? "L" : "M") + x(point.at).toFixed(1) + " " + y(point.level).toFixed(1)).join(" "), class: "forecast-line", stroke: colors[index % colors.length]}));
        }
      });
    }
    el("compare-legend").innerHTML = series.map((item, index) => {
      const unitNote = item.unit_metadata_available === false ? "unit from reference; telemetry omits unit" : "unit " + (item.unit_metadata_available ? "provided" : "status unavailable");
      const datumNote = item.vertical_datum_status === "VERIFIED_SOURCE" ? item.vertical_datum : (item.vertical_datum || "datum unavailable") + " (not verified)";
      return '<span><i style="border-color:' + colors[index % colors.length] + '"></i>' + esc(item.station.name || item.station_id) + ' · ' + esc(item.unit || "unit unavailable") + ' (' + esc(unitNote) + ') · ' + esc(datumNote) + '</span>';
    }).join("");
    const rows = series.map((item) => {
      const station = item.station || {}, measurement = station.latest_measurement || {}, history = item.history || {};
      const forecast = item.forecast_status === "READY" ? "Eligible verified horizons: " + ((item.forecast || []).map((value) => horizons[Number(value.horizon_minutes)]).join(", ") || "none") : statusText(item.forecast_status);
      const unitEvidence = item.unit_metadata_available === false ? (item.unit_reference || "Telemetry omits unit; reference status shown.") : "Telemetry unit field " + (item.unit_metadata_available ? "present." : "not verified.");
      const datumEvidence = item.vertical_datum_status === "VERIFIED_SOURCE" ? "Verified source metadata." : "Not verified.";
      return '<tr><td>' + esc(station.name || item.station_id) + '<br><span class="muted">' + esc(item.station_id) + ' · ' + esc(station.river || "river unavailable") + '</span></td><td>' + (measurement.water_level_m == null ? "—" : Number(measurement.water_level_m).toFixed(3)) + ' ' + esc(item.unit || "") + '<br><span class="muted">' + esc(time(measurement.measured_at_utc)) + '<br>' + esc(unitEvidence) + '</span></td><td>' + esc(item.vertical_datum || "Not verified") + '<br><span class="muted">' + esc(datumEvidence) + '</span></td><td>' + esc(history.status) + ' · ' + esc(history.coverage_percent || 0) + '%<br><span class="muted">' + esc(history.reason || (history.gap_count || 0) + " gaps") + '</span></td><td>' + esc(forecast) + '</td></tr>';
    }).join("");
    el("compare-table").innerHTML = '<table><thead><tr><th>Station</th><th>Latest observed</th><th>Vertical datum</th><th>History coverage</th><th>Forecast</th></tr></thead><tbody>' + rows + '</tbody></table>';
    el("compare-export-csv").disabled = !series.length;
    el("compare-export-png").disabled = !series.length;
  }

  async function loadHealth() {
    const sequence = ++ui.healthSequence;
    if (ui.healthController) ui.healthController.abort();
    ui.healthController = new AbortController();
    const controller = ui.healthController;
    el("health-checked").textContent = "Checking MRC, collector and model status…";
    try {
      const data = await requestJson("/v1/public/health", controller);
      if (sequence !== ui.healthSequence) return;
      ui.health = data;
      el("health-checked").textContent = "Checked " + time(data.server_time_utc) + " · " + data.cadence_minutes + " min cadence";
      el("health-count").textContent = data.station_count + " stations";
      renderHealth(data);
      const threshold = data.thresholds || {};
      el("threshold-status").innerHTML = '<strong>Threshold alerts ' + (threshold.status === "VERIFIED" ? "active" : "unavailable") + '</strong><span>' + esc(threshold.reason || "No effective station thresholds have been verified. No exceedance signal is calculated.") + '</span>';
    } catch (error) {
      if (sequence !== ui.healthSequence || controller.signal.aborted) return;
      el("health-checked").textContent = "Health checks unavailable · " + String(error.message || "request failed");
      el("health-table").innerHTML = '<p class="muted pad">Retry to load source, collector, history and model status.</p>';
    }
  }
  function renderHealth(data) {
    const rows = (data.stations || []).map((station) => {
      const c = station.components || {};
      const cell = (name) => {
        const component = c[name] || {};
        const status = component.status || "UNKNOWN";
        return '<td><span class="health-state ' + esc(status.toLowerCase()) + '">' + esc(statusText(status)) + '</span>' + (name === "source" && component.last_poll_at_utc ? '<div class="table-reason">Last poll ' + esc(time(component.last_poll_at_utc)) + '</div>' : '') + '<div class="table-reason">' + esc(component.reason || "—") + '</div></td>';
      };
      return '<tr><td><b>' + esc(station.name || station.station_id) + '</b><br><span class="muted">' + esc(station.station_id) + ' · ' + esc(station.river || "river unavailable") + '</span><br><span class="muted">Checked ' + esc(time(station.last_checked_at_utc)) + '</span></td>' + cell("source") + cell("collector") + cell("history") + cell("forecast") + cell("model") + cell("thresholds") + '</tr>';
    }).join("");
    el("health-table").innerHTML = '<table class="health-table"><thead><tr><th>Station / last checked</th><th>MRC source</th><th>Collector</th><th>History</th><th>Forecast</th><th>Model</th><th>Thresholds</th></tr></thead><tbody>' + rows + '</tbody></table>';
  }

  function csvCell(value) { return '"' + String(value == null ? "" : value).replace(/"/g, '""') + '"'; }
  function download(name, body, type) {
    const url = URL.createObjectURL(new Blob([body], {type}));
    const anchor = document.createElement("a"); anchor.href = url; anchor.download = name; document.body.append(anchor); anchor.click(); anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  function detailCsvRows() {
    const station = ui.detail && ui.detail.station;
    if (!station) return [];
    const history = ui.history || {}, meta = station.observation_metadata || {};
    const common = [station.station_id, station.name, station.country, station.river, meta.unit || "m", meta.vertical_datum || station.vertical_datum || "", meta.unit_reference || "", meta.unit_present_in_telemetry === false ? "not in telemetry" : meta.unit_present_in_telemetry === true ? "provided in telemetry" : "not verified", meta.vertical_datum_status || "NOT_AVAILABLE"];
    const range = [history.requested_start_utc, history.requested_end_utc, history.status];
    const rows = (history.points || []).map((point) => ["OBSERVATION", ...common, point.measured_at_utc, "", "", point.water_level_m, "", "", point.received_at_utc, ...range]);
    (station.forecast || []).forEach((forecast) => rows.push(["FORECAST", ...common, "", forecast.target_at_utc, forecast.horizon_minutes, forecast.predicted_water_level_m, forecast.benchmark_status, forecast.model_version, forecast.generated_at_utc || station.forecast_generated_at_utc, ...range]));
    return rows;
  }
  function exportWindow(period, start, end) {
    return period === "custom" && start && end ? "custom-" + start + "-" + end : period;
  }
  function exportCsv(comparison) {
    const header = ["record_type", "station_id", "station_name", "country", "river", "unit", "vertical_datum", "unit_reference", "unit_metadata_status", "vertical_datum_status", "measured_at_utc", "target_at_utc", "horizon_minutes", "water_level", "forecast_status", "model_version", "received_or_generated_at_utc", "requested_window_start_utc", "requested_window_end_utc", "history_status"];
    let rows = [];
    let label = "station";
    let window = exportWindow(ui.period, ui.start, ui.end);
    if (comparison && ui.comparison) {
      label = ui.comparison.stations.map((item) => item.station_id).join("-");
      window = exportWindow(el("compare-period").value, el("compare-start").value, el("compare-end").value);
      ui.comparison.stations.forEach((item) => {
        const station = item.station || {}, meta = station.observation_metadata || {};
        const common = [item.station_id, station.name, station.country, station.river, item.unit || "", item.vertical_datum || "", item.unit_reference || "", item.unit_metadata_available === false ? "not in telemetry" : item.unit_metadata_available === true ? "provided in telemetry" : "not verified", item.vertical_datum_status || "NOT_AVAILABLE"];
        const range = [item.history.requested_start_utc, item.history.requested_end_utc, item.history.status];
        (item.history.points || []).forEach((point) => rows.push(["OBSERVATION", ...common, point.measured_at_utc, "", "", point.water_level_m, "", "", point.received_at_utc, ...range]));
        (item.forecast || []).forEach((forecast) => rows.push(["FORECAST", ...common, "", forecast.target_at_utc, forecast.horizon_minutes, forecast.predicted_water_level_m, forecast.benchmark_status, forecast.model_version, forecast.generated_at_utc || station.forecast_generated_at_utc, ...range]));
      });
    } else {
      const station = ui.detail && ui.detail.station;
      if (!station) { showToast("Select a station before exporting."); return; }
      label = String(station.station_id);
      rows = detailCsvRows();
    }
    if (!rows.length) { showToast("No observations or eligible forecasts are available in this selection."); return; }
    const lines = [header, ...rows].map((row) => row.map(csvCell).join(","));
    download("mekong-" + label + "-" + window + ".csv", "\uFEFF" + lines.join("\r\n"), "text/csv;charset=utf-8");
  }
  function exportPng(svgId, filename) {
    const source = el(svgId);
    if (!source || !source.querySelector("path,circle")) { showToast("Load chart data before exporting the PNG."); return; }
    const copy = source.cloneNode(true);
    copy.setAttribute("xmlns", SVG_NS);
    const box = source.viewBox.baseVal;
    const serializer = new XMLSerializer();
    const blob = new Blob([serializer.serializeToString(copy)], {type: "image/svg+xml;charset=utf-8"});
    const url = URL.createObjectURL(blob);
    const image = new Image();
    image.onload = () => {
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(900, Math.round(box.width * 2)); canvas.height = Math.max(500, Math.round(box.height * 2));
      const context = canvas.getContext("2d");
      context.fillStyle = "#ffffff"; context.fillRect(0, 0, canvas.width, canvas.height);
      context.drawImage(image, 0, 0, canvas.width, canvas.height);
      canvas.toBlob((png) => {
        if (png) download(filename, png, "image/png"); else showToast("The chart image could not be exported.");
        URL.revokeObjectURL(url);
      }, "image/png");
    };
    image.onerror = () => { URL.revokeObjectURL(url); showToast("The chart image could not be exported."); };
    image.src = url;
  }

  function wire() {
    el("retry-button").addEventListener("click", () => {
      if (!ui.polling && ["prompt", "denied", "unknown", "unsupported"].includes(ui.permissionState)) connectFromGesture();
      else refreshStations();
    });
    el("station-grid").addEventListener("click", (event) => {
      const button = event.target.closest("[data-station-id]");
      if (button) selectStation(button.getAttribute("data-station-id"));
    });
    el("station-search").addEventListener("input", (event) => { ui.filters.search = event.target.value; renderStations(); });
    el("country-filter").addEventListener("change", (event) => { ui.filters.country = event.target.value; renderStations(); });
    el("river-filter").addEventListener("change", (event) => { ui.filters.river = event.target.value; renderStations(); });
    el("status-filter").addEventListener("change", (event) => { ui.filters.status = event.target.value; renderStations(); });
    el("station-map").addEventListener("click", (event) => { const marker = event.target.closest("[data-station-id]"); if (marker) selectStation(marker.getAttribute("data-station-id")); });
    el("station-detail").addEventListener("change", (event) => {
      if (event.target.id === "waterline-mode") drawCrossSection(ui.detail && ui.detail.station, ui.globalOffline);
      if (event.target.id === "history-range") { ui.period = event.target.value; updateCustomControls(); if (ui.period === "custom") { const today = new Date().toISOString().slice(0, 10); el("history-end").value = today; el("history-start").value = new Date(Date.now() - 2 * 86400000).toISOString().slice(0, 10); ui.start = el("history-start").value; ui.end = el("history-end").value; } refreshHistory(); }
    });
    el("station-detail").addEventListener("change", (event) => {
      if (["history-start", "history-end"].includes(event.target.id)) { ui.start = el("history-start").value; ui.end = el("history-end").value; refreshHistory(); }
    });
    el("station-detail").addEventListener("click", (event) => {
      if (event.target.id === "detail-retry") selectStation(ui.selectedId);
      if (event.target.id === "history-retry") refreshHistory();
      if (event.target.id === "export-csv") exportCsv(false);
      if (event.target.id === "export-png") exportPng("history-chart", "mekong-" + ui.selectedId + "-" + exportWindow(ui.period, ui.start, ui.end) + ".png");
    });
    el("compare-period").addEventListener("change", updateCustomControls);
    el("compare-load").addEventListener("click", loadComparison);
    el("compare-export-csv").addEventListener("click", () => exportCsv(true));
    el("compare-export-png").addEventListener("click", () => exportPng("compare-chart", "mekong-comparison-" + compareSelectedIds().join("-") + "-" + exportWindow(el("compare-period").value, el("compare-start").value, el("compare-end").value) + ".png"));
    el("health-refresh").addEventListener("click", loadHealth);
    el("clear-alerts").addEventListener("click", () => { ui.alerts = []; ui.alertKeys.clear(); renderAlerts(); });
    document.querySelectorAll(".tab").forEach((button) => button.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((tab) => { tab.classList.remove("active"); tab.setAttribute("aria-selected", "false"); });
      document.querySelectorAll(".tab-panel").forEach((panel) => { panel.classList.remove("active"); panel.hidden = true; });
      button.classList.add("active"); button.setAttribute("aria-selected", "true");
      const panel = el("panel-" + button.dataset.panel); panel.hidden = false; panel.classList.add("active");
      if (button.dataset.panel === "health") loadHealth();
      if (button.dataset.panel === "compare" && !ui.comparison) {
        const current = Array.from(el("compare-stations").options).find((option) => option.value === ui.selectedId);
        if (current) current.selected = true;
      }
    }));
    window.addEventListener("offline", () => setOffline("Browser reports that this device is offline."));
    window.addEventListener("online", () => { if (ui.polling) refreshStations(); });
  }
  async function loadReferences() {
    try {
      ui.references = await requestJson("/v1/public/dashboard/references");
      updateThresholdStatus(ui.detail && ui.detail.station);
    } catch (_) {
      ui.references = {thresholds: {status: "BLOCKED_EFFECTIVE_DATE_UNKNOWN", reason: "Threshold metadata could not be verified from the public dashboard API."}};
      updateThresholdStatus(ui.detail && ui.detail.station);
    }
  }
  function initDates() {
    const today = new Date().toISOString().slice(0, 10);
    const previous = new Date(Date.now() - 2 * 86400000).toISOString().slice(0, 10);
    ui.end = today; ui.start = previous;
    if (el("compare-start")) el("compare-start").value = previous;
    if (el("compare-end")) el("compare-end").value = today;
  }
  function init() {
    wire(); initDates(); updateCustomControls(); renderAlerts();
    initNetworkPermission();
  }
  init();
})();
