let token = null;
let rows = [];
let payload = null;

const $ = (id) => document.getElementById(id);
const log = (msg) => { $("log").textContent += msg + "\n"; $("log").scrollTop = 1e9; };
const setSummary = (s) => { $("summary").textContent = s || ""; };

function normalizeHeader(h) {
  return String(h || "").trim();
}

function parseExcel(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("Gagal baca file"));
    reader.onload = (e) => {
      const data = new Uint8Array(e.target.result);
      const wb = XLSX.read(data, { type: "array" });
      const ws = wb.Sheets[wb.SheetNames[0]];
      const json = XLSX.utils.sheet_to_json(ws, { defval: "" });
      resolve(json);
    };
    reader.readAsArrayBuffer(file);
  });
}

function renderTable(data) {
  const table = $("table");
  table.innerHTML = "";
  if (!data || data.length === 0) return;

  const headers = Object.keys(data[0]);
  const thead = document.createElement("thead");
  const trh = document.createElement("tr");
  headers.forEach(h => {
    const th = document.createElement("th");
    th.textContent = h;
    trh.appendChild(th);
  });
  thead.appendChild(trh);

  const tbody = document.createElement("tbody");
  data.slice(0, 200).forEach(r => {
    const tr = document.createElement("tr");
    headers.forEach(h => {
      const td = document.createElement("td");
      td.textContent = r[h];
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });

  table.appendChild(thead);
  table.appendChild(tbody);
}

function parseDateDDMMYYYY(s) {
  const str = String(s || "").trim();
  const m = str.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
  if (!m) return null;
  const dd = Number(m[1]), mm = Number(m[2]), yyyy = Number(m[3]);
  if (!dd || !mm || !yyyy) return null;
  return `${String(dd).padStart(2,"0")}/${String(mm).padStart(2,"0")}/${yyyy}`;
}

function autoVoucherNo(baseDate, idx) {
  const d = baseDate.replaceAll("/", "");
  return `JV-${d}-${String(idx).padStart(3,"0")}`;
}

function buildPayloadFromRows(rows) {
  // required columns
  const required = ["transDate", "accountNo", "amount", "amountType"];
  for (const r of required) {
    if (!Object.prototype.hasOwnProperty.call(rows[0], r)) {
      throw new Error(`Kolom wajib tidak ada: ${r}`);
    }
  }

  // Normalize and validate each row
  const normalized = rows.map((r, i) => {
    const transDate = parseDateDDMMYYYY(r.transDate);
    if (!transDate) throw new Error(`Row ${i+2}: transDate harus DD/MM/YYYY`);

    const accountNo = String(r.accountNo || "").trim();
    if (!accountNo) throw new Error(`Row ${i+2}: accountNo kosong`);

    const amount = Number(String(r.amount).replaceAll(",", "").trim());
    if (!Number.isFinite(amount)) throw new Error(`Row ${i+2}: amount bukan angka`);

    const amountType = String(r.amountType || "").trim().toUpperCase();
    if (!["DEBIT","CREDIT"].includes(amountType)) {
      throw new Error(`Row ${i+2}: amountType harus DEBIT/CREDIT`);
    }

    let number = String(r.number || "").trim();
    return { ...r, transDate, accountNo, amount, amountType, number };
  });

  // group by voucher number
  // if number empty, generate based on first date and running index per file
  let autoIndex = 1;
  const grouped = new Map();

  for (const r of normalized) {
    if (!r.number) {
      r.number = autoVoucherNo(r.transDate, autoIndex++);
    }
    const key = r.number;

    if (!grouped.has(key)) grouped.set(key, []);
    grouped.get(key).push(r);
  }

  const data = [];
  for (const [number, groupRows] of grouped.entries()) {
    const head = groupRows[0];

    const tx = {
      transDate: head.transDate,
      number,
    };

    if (head.description) tx.description = String(head.description);
    if (head.branchId) tx.branchId = Number(head.branchId);
    if (head.branchName) tx.branchName = String(head.branchName);

    tx.detailJournalVoucher = groupRows.map((r) => {
      const d = {
        accountNo: String(r.accountNo).trim(),
        amount: r.amount,
        amountType: String(r.amountType).trim().toUpperCase()
      };

      // optional passthrough fields if present and not empty
      const optionalFields = [
        "memo","customerNo","vendorNo","employeeNo","subsidiaryType",
        "projectNo","departmentName","rate","primeAmount","id","_status",
        "dataClassification1Name","dataClassification2Name","dataClassification3Name",
        "dataClassification4Name","dataClassification5Name","dataClassification6Name",
        "dataClassification7Name","dataClassification8Name","dataClassification9Name",
        "dataClassification10Name"
      ];
      for (const f of optionalFields) {
        if (r[f] !== undefined && String(r[f]).trim() !== "") {
          d[f] = (f === "rate" || f === "primeAmount") ? Number(r[f]) : r[f];
        }
      }

      if (d.subsidiaryType) d.subsidiaryType = String(d.subsidiaryType).toUpperCase();
      return d;
    });

    data.push(tx);
  }

  return { data };
}

async function api(path, body, useAuth=true) {
  const headers = { "Content-Type": "application/json" };
  if (useAuth && token) headers["Authorization"] = `Bearer ${token}`;
  const r = await fetch(path, { method: "POST", headers, body: JSON.stringify(body) });
  const t = await r.text();
  let j; try { j = JSON.parse(t); } catch { j = { raw: t }; }
  if (!r.ok) throw new Error(j?.message || `HTTP ${r.status}`);
  return j;
}

// Theme toggle
$("themeToggle").onclick = () => {
  const cur = document.documentElement.getAttribute("data-theme");
  document.documentElement.setAttribute("data-theme", cur === "clear" ? "" : "clear");
};

// Login
$("btnLogin").onclick = async () => {
  $("loginStatus").textContent = "";
  $("log").textContent = "";
  try {
    const code = $("code").value.trim();
    const pin = $("pin").value.trim();
    const res = await api("/api/login", { code, pin }, false);
    token = res.token;
    $("loginStatus").textContent = "Login OK";
    log("Login berhasil.");
  } catch (e) {
    $("loginStatus").textContent = `Login gagal: ${e.message}`;
    log(`Login gagal: ${e.message}`);
  }
};

// Upload
$("file").addEventListener("change", async (e) => {
  payload = null;
  $("btnImport").disabled = true;
  try {
    const f = e.target.files?.[0];
    if (!f) return;
    rows = await parseExcel(f);

    // Normalize headers: SheetJS keeps keys as headers already
    // Just show preview
    renderTable(rows);
    setSummary(`Rows terbaca: ${rows.length} (preview max 200 rows).`);
    log(`File dibaca: ${f.name}. Rows: ${rows.length}`);
  } catch (err) {
    log(`Error baca excel: ${err.message}`);
  }
});

// Build payload
$("btnBuild").onclick = () => {
  try {
    if (!rows || rows.length === 0) throw new Error("Upload file dulu");
    payload = buildPayloadFromRows(rows);
    const countTx = payload.data.length;
    const countLines = payload.data.reduce((a,x)=>a + (x.detailJournalVoucher?.length||0), 0);
    setSummary(`Siap import: ${countTx} transaksi, ${countLines} baris detail.`);
    log(`Payload built: transaksi=${countTx}, detail=${countLines}`);
    $("btnImport").disabled = false;
  } catch (e) {
    log(`Build gagal: ${e.message}`);
    $("btnImport").disabled = true;
  }
};

// Import
$("btnImport").onclick = async () => {
  try {
    if (!token) throw new Error("Login dulu");
    if (!payload) throw new Error("Klik Build Payload dulu");

    const authOverride = {
      bearerToken: $("bearerToken").value.trim(),
      xSessionId: $("xSessionId").value.trim()
    };

    log("Mengirim ke Accurate...");
    const res = await api("/api/import/journal-voucher", { ...payload, authOverride }, true);
    log("SUKSES. Response:");
    log(JSON.stringify(res, null, 2));
  } catch (e) {
    log(`IMPORT GAGAL: ${e.message}`);
  }
};

// Template CSV
$("btnTemplate").onclick = () => {
  const csv = [
    "transDate,number,description,accountNo,amount,amountType,memo,subsidiaryType,customerNo,vendorNo,employeeNo,projectNo,departmentName",
    "31/03/2016,JV-001,Test JV,1100,100000,DEBIT,Catatan,,,,,PRJ-01,FIN",
    "31/03/2016,JV-001,Test JV,2100,100000,CREDIT,Catatan,,,,,PRJ-01,FIN"
  ].join("\n");

  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "template-journal-voucher.csv";
  a.click();
  URL.revokeObjectURL(url);
};

// Reset file manual
const btnResetFile = document.getElementById("btnResetFile");
if (btnResetFile) {
  btnResetFile.onclick = () => {
    selectedFile = null;
    builtPayload = null;
    document.getElementById("file").value = "";
    setSummary("");
    log("File di-reset. Silakan pilih file baru.");
    updateUI();
  };
}

// Logout Accurate
const btnLogoutAO = document.getElementById("btnLogoutAO");
if (btnLogoutAO) {
  btnLogoutAO.onclick = async () => {
    try {
      await fetch("/api/ao-logout", { method: "POST" });
      token = token; // login app tetap
      selectedFile = null;
      builtPayload = null;
      log("Logout Accurate berhasil.");
      alert("Logout Accurate berhasil. Silakan Connect lagi untuk akun lain.");
      location.reload();
    } catch (e) {
      alert("Logout gagal: " + e.message);
    }
  };
}