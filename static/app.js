let token = sessionStorage.getItem("app_token") || null;
let selectedFile = null;
let builtPayload = null;
let ao = {
  has_token: false,
  has_session: false,
  db_id: null,
  db_alias: null
};

const $ = (id) => document.getElementById(id);

// ======================
// Basic helpers
// ======================
function log(msg) {
  const el = $("log");
  if (!el) return;
  el.textContent += msg + "\n";
  el.scrollTop = el.scrollHeight;
}

function clearLog() {
  const el = $("log");
  if (el) el.textContent = "";
}

function setText(id, value = "") {
  const el = $(id);
  if (el) el.textContent = value;
}

function setSummary(text) {
  setText("summary", text || "");
}

function escapeHtml(text) {
  return String(text ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

// ======================
// Notify helpers
// ======================
function clearNotify() {
  const box = $("notifyBox");
  const titleEl = $("notifyTitle");
  const bodyEl = $("notifyBody");
  if (!box || !titleEl || !bodyEl) return;

  box.classList.add("hidden");
  box.classList.remove("success", "error", "info");
  titleEl.textContent = "";
  bodyEl.innerHTML = "";
}

function showNotify(type, title, html = "") {
  const box = $("notifyBox");
  const titleEl = $("notifyTitle");
  const bodyEl = $("notifyBody");
  if (!box || !titleEl || !bodyEl) return;

  box.classList.remove("hidden", "success", "error", "info");
  box.classList.add(type || "info");

  titleEl.textContent = title || "";
  bodyEl.innerHTML = html || "";
}

function renderSimpleMessage(lines = []) {
  const arr = Array.isArray(lines) ? lines : [lines];
  return `
    <ul class="notify-list">
      ${arr.filter(Boolean).map(x => `<li>${escapeHtml(x)}</li>`).join("")}
    </ul>
  `;
}

function renderImportSummary(summary = {}, results = []) {
  const okItems = results.filter(x => x.ok);
  const failItems = results.filter(x => !x.ok);

  const okHtml = okItems.length
    ? `
      <div class="notify-section">
        <div class="notify-section-title">Berhasil</div>
        ${okItems.map(x => `
          <div class="notify-item ok">
            <div class="notify-meta">✔ ${escapeHtml(x.number || "-")} • ${escapeHtml(x.transDate || "-")}</div>
          </div>
        `).join("")}
      </div>
    `
    : "";

  const failHtml = failItems.length
    ? `
      <div class="notify-section">
        <div class="notify-section-title">Gagal</div>
        ${failItems.map(x => `
          <div class="notify-item fail">
            <div class="notify-meta">✘ ${escapeHtml(x.number || "-")} • ${escapeHtml(x.transDate || "-")}</div>
            <ul class="notify-errors">
              ${(x.errors || []).map(err => `<li>${escapeHtml(err)}</li>`).join("")}
            </ul>
          </div>
        `).join("")}
      </div>
    `
    : "";

  return `
    <div class="import-summary">
      <div class="sum-item">
        <span>Total</span>
        <strong>${summary.total || 0}</strong>
      </div>
      <div class="sum-item ok">
        <span>Berhasil</span>
        <strong>${summary.success || 0}</strong>
      </div>
      <div class="sum-item fail">
        <span>Gagal</span>
        <strong>${summary.failed || 0}</strong>
      </div>
    </div>
    ${okHtml}
    ${failHtml}
  `;
}

const notifyClose = $("notifyClose");
if (notifyClose) {
  notifyClose.onclick = () => clearNotify();
}

// ======================
// State helpers
// ======================
function isLoggedIn() {
  return !!token;
}

function isFileReady() {
  return !!selectedFile;
}

function isPayloadReady() {
  return !!builtPayload;
}

function isDbReady() {
  return !!ao.has_session;
}

function updateUI() {
  const loggedIn = isLoggedIn();
  const fileReady = isFileReady();
  const payloadReady = isPayloadReady();
  const dbReady = isDbReady();
  const oauthReady = !!ao.has_token;

  if ($("btnBuild")) $("btnBuild").disabled = !fileReady;
  if ($("btnImport")) $("btnImport").disabled = !(loggedIn && dbReady && payloadReady);
  if ($("btnLoadDb")) $("btnLoadDb").disabled = !oauthReady;

  if ($("btnUseDb")) {
    const hasOptions = $("dbSelect") && $("dbSelect").options.length > 0;
    $("btnUseDb").disabled = !(oauthReady && hasOptions);
  }

  const status = [];
  status.push(loggedIn ? "Login OK" : "Belum login");
  status.push(oauthReady ? "OAuth OK" : "Belum Connect");
  status.push(dbReady ? `DB Aktif${ao.db_alias ? ": " + ao.db_alias : ""}` : "DB belum dipilih");
  setText("aoStatus", status.join(" · "));
}

function resetExcelState() {
  selectedFile = null;
  builtPayload = null;
  if ($("file")) $("file").value = "";
  setSummary("");
  clearNotify();
  updateUI();
}

// ======================
// HTTP helpers
// ======================
async function getJson(url) {
  const r = await fetch(url);
  const t = await r.text();
  let j;
  try { j = JSON.parse(t); } catch { j = { raw: t }; }

  if (!r.ok) {
    const err = new Error(j?.message || `HTTP ${r.status}`);
    err.data = j;
    err.status = r.status;
    throw err;
  }
  return j;
}

async function postJson(url, body, auth = true) {
  const headers = { "Content-Type": "application/json" };
  if (auth && token) headers["Authorization"] = `Bearer ${token}`;

  const r = await fetch(url, {
    method: "POST",
    headers,
    body: JSON.stringify(body || {})
  });

  const t = await r.text();
  let j;
  try { j = JSON.parse(t); } catch { j = { raw: t }; }

  if (!r.ok) {
    const err = new Error(j?.message || `HTTP ${r.status}`);
    err.data = j;
    err.status = r.status;
    throw err;
  }
  return j;
}

async function postForm(url, formData) {
  const headers = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const r = await fetch(url, {
    method: "POST",
    headers,
    body: formData
  });

  const t = await r.text();
  let j;
  try { j = JSON.parse(t); } catch { j = { raw: t }; }

  if (!r.ok) {
    const err = new Error(j?.message || `HTTP ${r.status}`);
    err.data = j;
    err.status = r.status;
    throw err;
  }
  return j;
}

async function fetchAoStatus() {
  try {
    const st = await getJson("/api/ao-status");
    ao = {
      has_token: !!st.has_token,
      has_session: !!st.has_session,
      db_id: st.db_id || null,
      db_alias: st.db_alias || null
    };
  } catch {
    ao = {
      has_token: false,
      has_session: false,
      db_id: null,
      db_alias: null
    };
  }
  updateUI();
}

// ======================
// Theme
// ======================
if ($("themeToggle")) {
  $("themeToggle").onclick = () => {
    const cur = document.documentElement.getAttribute("data-theme");
    document.documentElement.setAttribute("data-theme", cur === "clear" ? "" : "clear");
  };
}

// ======================
// Login
// ======================
if ($("btnLogin")) {
  $("btnLogin").onclick = async () => {
    setText("loginStatus", "");
    clearLog();
    clearNotify();

    try {
      const code = $("code")?.value?.trim() || "";
      const pin = $("pin")?.value?.trim() || "";

      const res = await postJson("/api/login", { code, pin }, false);
      token = res.token;
      sessionStorage.setItem("app_token", token);

      if ($("customerInfo")) {
        $("customerInfo").textContent = "Customer: " + (res.customer_name || "-");
      }

      setText("loginStatus", "Login OK");
      log("Login berhasil.");

      await fetchAoStatus();
    } catch (e) {
      token = null;
      sessionStorage.removeItem("app_token");
      setText("loginStatus", "Login gagal: " + e.message);

      if ($("customerInfo")) {
        $("customerInfo").textContent = "";
      }

      log("Login gagal: " + e.message);
      showNotify("error", "Login gagal", renderSimpleMessage([e.message]));
      updateUI();
    }
  };
}

// ======================
// File picker
// ======================
if ($("file")) {
  $("file").addEventListener("change", (e) => {
    clearNotify();

    selectedFile = e.target.files?.[0] || null;
    builtPayload = null;

    if (selectedFile) {
      log(`File dipilih: ${selectedFile.name}`);
    } else {
      log("Tidak ada file dipilih.");
    }

    updateUI();
  });
}

// ======================
// Reset file
// ======================
if ($("btnResetFile")) {
  $("btnResetFile").onclick = () => {
    resetExcelState();
    log("File di-reset.");
  };
}

// ======================
// Load DB
// ======================
if ($("btnLoadDb")) {
  $("btnLoadDb").onclick = async () => {
    try {
      clearNotify();
      log("Load DB list...");
      const res = await getJson("/api/db-list");
      const arr = res?.response?.d || [];

      const sel = $("dbSelect");
      if (sel) {
        sel.innerHTML = "";
        arr.forEach((db) => {
          const opt = document.createElement("option");
          opt.value = db.id;
          opt.textContent = `${db.alias || "DB"} (ID: ${db.id})`;
          opt.dataset.alias = db.alias || "";
          sel.appendChild(opt);
        });
      }

      log(`DB list loaded: ${arr.length} database.`);
      updateUI();

      if (arr.length === 0) {
        showNotify("info", "Database kosong", renderSimpleMessage(["Tidak ada database yang muncul di akun ini."]));
      } else {
        showNotify("info", "Database berhasil dimuat", renderSimpleMessage([`Total database: ${arr.length}`]));
      }
    } catch (e) {
      log("DB list gagal: " + e.message);
      showNotify("error", "Load DB gagal", renderSimpleMessage([e.message]));
    }
  };
}

// ======================
// Use DB
// ======================
if ($("btnUseDb")) {
  $("btnUseDb").onclick = async () => {
    try {
      clearNotify();

      const sel = $("dbSelect");
      const id = sel?.value;
      const alias = sel?.selectedOptions?.[0]?.dataset?.alias || sel?.selectedOptions?.[0]?.textContent || "";

      if (!id) throw new Error("Pilih database dulu");

      log("Open DB...");
      const res = await postJson("/api/open-db", { id, alias }, false);

      log("Open DB OK.");
      log(JSON.stringify(res, null, 2));

      await fetchAoStatus();
      showNotify("success", "Database aktif", renderSimpleMessage([alias || id]));
    } catch (e) {
      log("Open DB gagal: " + e.message);
      showNotify("error", "Open DB gagal", renderSimpleMessage([e.message]));
    }
  };
}

// ======================
// Logout Accurate
// ======================
if ($("btnLogoutAO")) {
  $("btnLogoutAO").onclick = async () => {
    try {
      clearNotify();
      await fetch("/api/ao-logout", { method: "POST" });

      ao = {
        has_token: false,
        has_session: false,
        db_id: null,
        db_alias: null
      };
      builtPayload = null;
      setSummary("");
      log("Logout Accurate berhasil.");
      updateUI();

      showNotify("success", "Logout Accurate berhasil", renderSimpleMessage(["Silakan Connect lagi untuk akun lain."]));
    } catch (e) {
      showNotify("error", "Logout gagal", renderSimpleMessage([e.message]));
    }
  };
}

// ======================
// Build
// ======================
if ($("btnBuild")) {
  $("btnBuild").onclick = async () => {
    try {
      clearNotify();

      if (!token) throw new Error("Login dulu");
      if (!selectedFile) throw new Error("Pilih file Excel dulu");

      const fd = new FormData();
      fd.append("file", selectedFile);

      log("Build payload dari Excel...");
      const res = await postForm("/api/build-payload", fd);

      builtPayload = res.payload;
      setSummary(`Siap import: ${res.summary.transactions} transaksi, ${res.summary.lines} baris detail.`);
      log("Build OK.");

      showNotify(
        "info",
        "Build berhasil",
        renderSimpleMessage([
          `Jumlah transaksi: ${res.summary.transactions}`,
          `Jumlah detail: ${res.summary.lines}`,
          "Payload siap di-import ke Accurate."
        ])
      );

      updateUI();
    } catch (e) {
      builtPayload = null;
      log("Build gagal: " + e.message);
      showNotify("error", "Build Payload gagal", renderSimpleMessage([e.message]));
      updateUI();
    }
  };
}

// ======================
// Import
// ======================
if ($("btnImport")) {
  $("btnImport").onclick = async () => {
    try {
      clearNotify();

      if (!token) throw new Error("Login dulu");
      if (!ao.has_session) throw new Error("Pilih DB dulu");
      if (!builtPayload) throw new Error("Build payload dulu");

      log("Mengirim ke Accurate...");
      const res = await postJson("/api/import-journal-voucher", { payload: builtPayload }, true);

      const summary = res.summary || {};
      const results = res.results || [];
      const hasFailed = (summary.failed || 0) > 0;

      log("IMPORT SELESAI");
      log(JSON.stringify(res, null, 2));

      showNotify(
        hasFailed ? "error" : "success",
        hasFailed ? "Import selesai dengan beberapa kegagalan" : "Import berhasil",
        renderImportSummary(summary, results)
      );

      if (!hasFailed) {
        resetExcelState();
        log("Semua transaksi berhasil. Silakan pilih file baru untuk import berikutnya.");
      }
    } catch (e) {
      log("IMPORT ERROR: " + e.message);

      // paling penting: baca detail dari backend error response
      const data = e.data || {};
      const summary = data.summary || {};
      const results = data.results || [];

      if (results.length > 0) {
        showNotify(
          "error",
          "Import selesai dengan beberapa kegagalan",
          renderImportSummary(summary, results)
        );
      } else if (data.response?.d) {
        showNotify(
          "error",
          "Import gagal",
          renderSimpleMessage(data.response.d)
        );
      } else {
        showNotify(
          "error",
          "Import gagal",
          renderSimpleMessage([e.message])
        );
      }
    } finally {
      updateUI();
    }
  };
}

// ======================
// Init
// ======================
window.addEventListener("load", async () => {
  token = sessionStorage.getItem("app_token") || null;
  updateUI();
  await fetchAoStatus();
});