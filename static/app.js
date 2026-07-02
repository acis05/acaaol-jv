let token = sessionStorage.getItem("app_token") || null;
let selectedFile = null;
let builtPayload = null;
let currentUser = sessionStorage.getItem("app_user") || "";
let currentLicense = JSON.parse(sessionStorage.getItem("app_license") || "null");
let lastFailureText = "";
let lastImportCompleted = false;
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

function setProcessStatus(kind, title, subtitle = "") {
  const el = $("processStatus");
  if (!el) return;

  el.classList.remove("idle", "working", "success", "error");
  el.classList.add(kind || "idle");

  el.innerHTML = `
    <span class="status-dot"></span>
    <div>
      <strong>${escapeHtml(title || "")}</strong>
      <small>${escapeHtml(subtitle || "")}</small>
    </div>
  `;
}

function setMetrics(total = 0, success = 0, failed = 0) {
  setText("metricTotal", total);
  setText("metricSuccess", success);
  setText("metricFailed", failed);
}


function formatLicenseDate(value) {
  if (!value) return "-";
  return String(value);
}

function saveLicenseInfo(info = {}) {
  currentLicense = {
    customer_name: info.customer_name || currentLicense?.customer_name || "-",
    email: info.email || currentLicense?.email || "-",
    expires: info.expires ?? currentLicense?.expires ?? null,
    max_databases: info.max_databases ?? currentLicense?.max_databases ?? 5,
    used_databases: info.used_databases ?? currentLicense?.used_databases ?? 0,
    allowed_databases: info.allowed_databases || currentLicense?.allowed_databases || []
  };
  sessionStorage.setItem("app_license", JSON.stringify(currentLicense));
  renderLicenseInfo();
}

function renderLicenseInfo() {
  const info = currentLicense || {};
  const customer = info.customer_name || "-";
  const email = info.email || currentUser || "-";
  const expires = formatLicenseDate(info.expires);
  const maxDb = info.max_databases || 5;
  const usedDb = info.used_databases ?? (Array.isArray(info.allowed_databases) ? info.allowed_databases.length : 0);

  setText("licenseOwner", `APLIKASI ACA-AOL INI TERDAFTAR ATAS NAMA ${customer}`);
  setText("licenseEmail", `Email: ${email}`);
  setText("licenseExpiry", `Masa berlaku: ${expires}`);
  setText("licenseDbQuota", `Kuota database: ${usedDb}/${maxDb}`);
}

function updateChips() {
  const chipLogin = $("chipLogin");
  const chipOAuth = $("chipOAuth");
  const chipDb = $("chipDb");
  const chipFile = $("chipFile");

  if (chipLogin) {
    chipLogin.classList.toggle("ok", !!token);
    chipLogin.textContent = token ? "Login OK" : "Belum Login";
  }

  if (chipOAuth) {
    chipOAuth.classList.toggle("ok", !!ao.has_token);
    chipOAuth.textContent = ao.has_token ? "Accurate OK" : "Belum Connect";
  }

  if (chipDb) {
    chipDb.classList.toggle("ok", !!ao.has_session);
    chipDb.textContent = ao.has_session ? "DB Aktif" : "DB Belum Dipilih";
  }

  if (chipFile) {
    chipFile.classList.toggle("ok", !!selectedFile);
    chipFile.textContent = selectedFile ? "Excel Siap" : "Excel Belum Ada";
  }
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

function buildFailureText(results = []) {
  const failItems = results.filter(x => !x.ok);
  if (failItems.length === 0) return "";

  const lines = [];
  lines.push("CATATAN GAGAL IMPORT JOURNAL VOUCHER");
  lines.push("====================================");
  lines.push("");

  failItems.forEach((x, i) => {
    lines.push(`${i + 1}. ${x.number || "-"} | ${x.transDate || "-"}`);
    const errors = Array.isArray(x.errors) && x.errors.length ? x.errors : ["Transaksi gagal diproses."];
    errors.forEach(err => lines.push(`   - ${err}`));
    lines.push("");
  });

  return lines.join("\n");
}

function renderImportResult(summary = {}, results = []) {
  const total = summary.total || results.length || 0;
  const success = summary.success || results.filter(x => x.ok).length || 0;
  const failed = summary.failed || results.filter(x => !x.ok).length || 0;
  const failItems = results.filter(x => !x.ok);

  setMetrics(total, success, failed);

  if (failed === 0) {
    hideFailurePad();
    return `
      <div class="friendly-result success-result">
        <strong>Semua transaksi berhasil diimport.</strong>
        <span>Total ${total} transaksi sudah masuk ke Accurate.</span>
      </div>
    `;
  }

  return `
    <div class="friendly-result error-result">
      <strong>${failed} transaksi gagal diimport.</strong>
      <span>${success} transaksi berhasil. Catatan gagal sudah dibuat di bawah.</span>
    </div>
    <div class="failure-list">
      ${failItems.map(x => `
        <div class="failure-row">
          <div>
            <strong>${escapeHtml(x.number || "-")}</strong>
            <small>${escapeHtml(x.transDate || "-")}</small>
          </div>
          <span>${escapeHtml((x.errors || ["Gagal"])[0])}</span>
        </div>
      `).join("")}
    </div>
  `;
}

function showFailurePad(text) {
  lastFailureText = text || "";
  const pad = $("failurePad");
  const notes = $("failureNotes");
  if (!pad || !notes) return;

  if (!lastFailureText) {
    hideFailurePad();
    return;
  }

  notes.value = lastFailureText;
  pad.classList.remove("hidden");
}

function hideFailurePad() {
  lastFailureText = "";
  const pad = $("failurePad");
  const notes = $("failureNotes");
  if (notes) notes.value = "";
  if (pad) pad.classList.add("hidden");
}

const notifyClose = $("notifyClose");
if (notifyClose) {
  notifyClose.onclick = () => clearNotify();
}

if ($("btnCopyFailures")) {
  $("btnCopyFailures").onclick = async () => {
    try {
      if (!lastFailureText) return;
      await navigator.clipboard.writeText(lastFailureText);
      showNotify("success", "Catatan berhasil dicopy", renderSimpleMessage(["Catatan gagal sudah disalin ke clipboard."]));
    } catch {
      showNotify("info", "Copy manual", renderSimpleMessage(["Silakan blok teks catatan gagal lalu copy manual."]));
    }
  };
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

function updateViewByLogin() {
  const loggedIn = isLoggedIn();

  if ($("loginView")) {
    $("loginView").classList.toggle("hidden", loggedIn);
  }

  if ($("appView")) {
    $("appView").classList.toggle("hidden", !loggedIn);
  }

  if ($("userBadge")) {
    $("userBadge").textContent = currentUser || "Login aktif";
  }

  renderLicenseInfo();
}

function updateUI() {
  updateViewByLogin();

  const loggedIn = isLoggedIn();
  const fileReady = isFileReady();
  const payloadReady = isPayloadReady();
  const dbReady = isDbReady();
  const oauthReady = !!ao.has_token;

  if ($("btnBuild")) $("btnBuild").disabled = !fileReady;
  if ($("btnImport")) $("btnImport").disabled = !(loggedIn && dbReady && payloadReady);
  if ($("btnLoadDb")) $("btnLoadDb").disabled = !oauthReady;

  if ($("btnUseDb")) {
    const sel = $("dbSelect");
    const hasSelectedDb = !!(sel && sel.value && String(sel.value).trim() !== "");
    $("btnUseDb").disabled = !(oauthReady && hasSelectedDb);
  }

  const status = [];
  status.push(loggedIn ? "Login OK" : "Belum login");
  status.push(oauthReady ? "OAuth OK" : "Belum Connect");
  status.push(dbReady ? `DB Aktif${ao.db_alias ? ": " + ao.db_alias : ""}` : "DB belum dipilih");
  setText("aoStatus", status.join(" · "));

  updateChips();

  if (!lastImportCompleted) {
    if (!fileReady && !payloadReady) {
      setProcessStatus("idle", "Menunggu file Excel", "Pilih file Excel terlebih dahulu.");
    } else if (fileReady && !payloadReady) {
      setProcessStatus("idle", "File sudah dipilih", "Klik Cek File untuk membaca transaksi.");
    }
  }
}

function resetExcelState() {
  lastImportCompleted = false;
  selectedFile = null;
  builtPayload = null;
  if ($("file")) $("file").value = "";
  setText("fileName", "Belum ada file dipilih");
  setSummary("");
  setMetrics(0, 0, 0);
  hideFailurePad();
  clearNotify();
  updateUI();
}

// ======================
// HTTP helpers
// ======================
async function getJson(url, auth = false) {
  const headers = {};
  if (auth && token) headers["Authorization"] = `Bearer ${token}`;

  const r = await fetch(url, { headers });
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
    const st = await getJson("/api/ao-status", true);
    ao = {
      has_token: !!st.has_token,
      has_session: !!st.has_session,
      db_id: st.db_id || null,
      db_alias: st.db_alias || null
    };
    if (st.license) saveLicenseInfo(st.license);
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
      const email = $("email")?.value?.trim() || "";
      const password = $("password")?.value?.trim() || "";

      const res = await postJson("/api/login", { email, password }, false);
      token = res.token;
      currentUser = res.email || email || res.customer_name || "Login aktif";
      sessionStorage.setItem("app_token", token);
      sessionStorage.setItem("app_user", currentUser);
      saveLicenseInfo(res);

      if ($("customerInfo")) {
        $("customerInfo").textContent = `APLIKASI ACA-AOL INI TERDAFTAR ATAS NAMA ${res.customer_name || "-"}`;
      }

      setText("loginStatus", "");
      log("Login berhasil.");
      updateUI();

      await fetchAoStatus();
    } catch (e) {
      token = null;
      currentUser = "";
      sessionStorage.removeItem("app_token");
      sessionStorage.removeItem("app_user");
      sessionStorage.removeItem("app_license");
      currentLicense = null;
      setText("loginStatus", "Login gagal: " + e.message);

      if ($("customerInfo")) {
        $("customerInfo").textContent = "";
      }

      showNotify("error", "Login gagal", renderSimpleMessage([e.message]));
      updateUI();
    }
  };
}

if ($("btnAppLogout")) {
  $("btnAppLogout").onclick = () => {
    token = null;
    currentUser = "";
    selectedFile = null;
    builtPayload = null;
    sessionStorage.removeItem("app_token");
    sessionStorage.removeItem("app_user");
    sessionStorage.removeItem("app_license");
    currentLicense = null;
    setMetrics(0, 0, 0);
    hideFailurePad();
    clearNotify();
    clearLog();
    setSummary("");
    updateUI();
  };
}

// ======================
// Login enter key
// ======================
["email", "password"].forEach((id) => {
  const el = $(id);
  if (el) {
    el.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && $("btnLogin")) {
        $("btnLogin").click();
      }
    });
  }
});

// ======================
// File picker
// ======================
if ($("file")) {
  $("file").addEventListener("change", (e) => {
    lastImportCompleted = false;
    clearNotify();
    hideFailurePad();

    selectedFile = e.target.files?.[0] || null;
    builtPayload = null;
    setMetrics(0, 0, 0);

    if (selectedFile) {
      setText("fileName", selectedFile.name);
      setProcessStatus("idle", "File sudah dipilih", "Klik Cek File untuk membaca transaksi.");
    } else {
      setText("fileName", "Belum ada file dipilih");
      setProcessStatus("idle", "Menunggu file Excel", "Pilih file Excel terlebih dahulu.");
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
  };
}

// ======================
// Load DB
// ======================
if ($("btnLoadDb")) {
  $("btnLoadDb").onclick = async () => {
    try {
      clearNotify();
      setProcessStatus("working", "Memuat database", "Mengambil daftar database dari Accurate...");

      const res = await getJson("/api/db-list", true);
      const arr = res?.response?.d || [];

      const sel = $("dbSelect");
      if (sel) {
        sel.innerHTML = "";

        const firstOpt = document.createElement("option");
        firstOpt.value = "";
        firstOpt.textContent = "-- pilih database --";
        sel.appendChild(firstOpt);

        arr.forEach((db) => {
          const opt = document.createElement("option");
          opt.value = db.id;
          opt.textContent = `${db.alias || "DB"} (ID: ${db.id})`;
          opt.dataset.alias = db.alias || "";
          sel.appendChild(opt);
        });
      }

      updateUI();

      if (arr.length === 0) {
        showNotify("info", "Database kosong", renderSimpleMessage(["Tidak ada database yang muncul di akun ini."]));
      } else {
        showNotify("info", "Database berhasil dimuat", renderSimpleMessage([`Total database: ${arr.length}`]));
      }
    } catch (e) {
      showNotify("error", "Load Database gagal", renderSimpleMessage([e.message]));
    } finally {
      updateUI();
    }
  };
}

// ======================
// DB select change
// ======================
if ($("dbSelect")) {
  $("dbSelect").addEventListener("change", () => {
    updateUI();
  });
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

      const res = await postJson("/api/open-db", { id, alias }, true);
      if (res.license) saveLicenseInfo(res.license);
      await fetchAoStatus();

      showNotify("success", "Database aktif", renderSimpleMessage([res.message || `Database siap digunakan: ${alias || id}`]));
      setProcessStatus("idle", "Database sudah aktif", "Lanjut upload file Excel.");
      log(JSON.stringify(res, null, 2));
    } catch (e) {
      showNotify("error", "Open Database gagal", renderSimpleMessage([e.message]));
    } finally {
      updateUI();
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
      await fetch("/api/ao-logout", {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {}
      });

      ao = {
        has_token: false,
        has_session: false,
        db_id: null,
        db_alias: null
      };
      builtPayload = null;
      setSummary("");
      setMetrics(0, 0, 0);
      hideFailurePad();
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
      lastImportCompleted = false;
      clearNotify();
      hideFailurePad();

      if (!token) throw new Error("Login dulu");
      if (!selectedFile) throw new Error("Pilih file Excel dulu");

      const fd = new FormData();
      fd.append("file", selectedFile);

      setProcessStatus("working", "Mengecek file Excel", "Mohon tunggu, sistem sedang membaca transaksi...");
      const res = await postForm("/api/build-payload", fd);

      builtPayload = res.payload;
      const tx = res.summary.transactions || 0;
      const lines = res.summary.lines || 0;

      setMetrics(tx, 0, 0);
      setSummary(`File siap diimport: ${tx} transaksi, ${lines} baris detail.`);
      setProcessStatus("success", "File siap diimport", `${tx} transaksi dan ${lines} baris detail terdeteksi.`);

      showNotify(
        "success",
        "File siap diimport",
        renderSimpleMessage([
          `Jumlah transaksi: ${tx}`,
          `Jumlah detail: ${lines}`,
          "Silakan klik Import ke Accurate."
        ])
      );

      updateUI();
    } catch (e) {
      builtPayload = null;
      setMetrics(0, 0, 0);
      setProcessStatus("error", "Cek file gagal", e.message);
      showNotify("error", "Cek File gagal", renderSimpleMessage([e.message]));
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
      hideFailurePad();

      if (!token) throw new Error("Login dulu");
      if (!ao.has_session) throw new Error("Pilih DB dulu");
      if (!builtPayload) throw new Error("Cek file dulu");

      setProcessStatus("working", "Mengimport ke Accurate", "Mohon tunggu, transaksi sedang dikirim...");
      const res = await postJson("/api/import-journal-voucher", { payload: builtPayload }, true);

      const summary = res.summary || {};
      const results = res.results || [];
      const failed = summary.failed || 0;

      setProcessStatus(
        failed > 0 ? "error" : "success",
        failed > 0 ? "Import selesai dengan catatan" : "Import berhasil",
        failed > 0 ? `${failed} transaksi gagal. Lihat catatan gagal.` : "Semua transaksi berhasil masuk ke Accurate."
      );

      showNotify(
        failed > 0 ? "error" : "success",
        failed > 0 ? "Import selesai dengan beberapa kegagalan" : "Import berhasil",
        renderImportResult(summary, results)
      );

      const failureText = buildFailureText(results);
      if (failureText) showFailurePad(failureText);

      if (failed === 0) {
        // Jangan panggil resetExcelState() di sini, karena reset akan menghapus
        // angka sukses/gagal dan mengembalikan status menjadi "Menunggu file Excel".
        // Kita hanya kosongkan payload supaya user tidak sengaja import ulang file yang sama,
        // tetapi hasil import sukses tetap ditampilkan di layar.
        lastImportCompleted = true;
        selectedFile = null;
        builtPayload = null;
        if ($("file")) $("file").value = "";
        setText("fileName", "Belum ada file dipilih");
        setProcessStatus("success", "Import berhasil", "Semua transaksi berhasil masuk ke Accurate.");
      }
    } catch (e) {
      const data = e.data || {};
      const summary = data.summary || {};
      const results = data.results || [];

      if (results.length > 0) {
        const failureText = buildFailureText(results);
        setProcessStatus("error", "Import selesai dengan catatan", `${summary.failed || 0} transaksi gagal.`);
        showNotify(
          "error",
          "Import selesai dengan beberapa kegagalan",
          renderImportResult(summary, results)
        );
        if (failureText) showFailurePad(failureText);
      } else if (data.response?.d) {
        setProcessStatus("error", "Import gagal", "Ada pesan dari Accurate yang perlu diperiksa.");
        showNotify("error", "Import gagal", renderSimpleMessage(data.response.d));
      } else {
        setProcessStatus("error", "Import gagal", e.message);
        showNotify("error", "Import gagal", renderSimpleMessage([e.message]));
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
  currentUser = sessionStorage.getItem("app_user") || "";
  currentLicense = JSON.parse(sessionStorage.getItem("app_license") || "null");
  renderLicenseInfo();
  updateUI();

  if (token) {
    await fetchAoStatus();
  }
});
