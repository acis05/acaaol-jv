import express from "express";
import helmet from "helmet";
import fetch from "node-fetch";
import dotenv from "dotenv";
import fs from "fs";
import crypto from "crypto";
import jwt from "jsonwebtoken";
import path from "path";
import { fileURLToPath } from "url";

dotenv.config();

const app = express();
app.use(helmet());
app.use(express.json({ limit: "10mb" }));

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

app.use(express.static(path.join(__dirname, "public")));

function sha256(str) {
  return crypto.createHash("sha256").update(str, "utf8").digest("hex");
}

function loadLicenses() {
  const p = process.env.LICENSE_FILE || "./licenses.json";
  return JSON.parse(fs.readFileSync(p, "utf8"));
}

function isExpired(expires) {
  if (!expires) return false;
  const d = new Date(expires + "T23:59:59");
  return Number.isFinite(d.getTime()) ? (Date.now() > d.getTime()) : false;
}

function authMiddleware(req, res, next) {
  const auth = req.headers.authorization || "";
  const token = auth.startsWith("Bearer ") ? auth.slice(7) : null;
  if (!token) return res.status(401).json({ ok: false, message: "Unauthorized" });
  try {
    req.user = jwt.verify(token, process.env.JWT_SECRET || "dev");
    return next();
  } catch {
    return res.status(401).json({ ok: false, message: "Invalid session" });
  }
}

app.post("/api/login", (req, res) => {
  const { code, pin } = req.body || {};
  if (!code || !pin) return res.status(400).json({ ok: false, message: "Code & PIN wajib" });

  const licenses = loadLicenses();
  const lic = licenses.find(x => x.code === code);

  if (!lic || !lic.active) return res.status(401).json({ ok: false, message: "Kode tidak valid" });
  if (isExpired(lic.expires)) return res.status(401).json({ ok: false, message: "Lisensi expired" });

  const pinHash = sha256(pin);
  if (pinHash !== lic.pin_sha256) return res.status(401).json({ ok: false, message: "PIN salah" });

  const token = jwt.sign(
    { code },
    process.env.JWT_SECRET || "dev",
    { expiresIn: "12h" }
  );

  res.json({ ok: true, token });
});

/**
 * Body: { data: [ { transDate, number?, description?, branchId?, branchName?, detailJournalVoucher:[...] } ] }
 */
app.post("/api/import/journal-voucher", authMiddleware, async (req, res) => {
  const { data, authOverride } = req.body || {};
  if (!Array.isArray(data) || data.length === 0) {
    return res.status(400).json({ ok: false, message: "Payload data kosong" });
  }

  const baseUrl = (process.env.AO_BASE_URL || "").replace(/\/$/, "");
  const savePath = process.env.AO_JV_SAVE_PATH || "/api/journal-voucher/save.do";
  if (!baseUrl) return res.status(500).json({ ok: false, message: "AO_BASE_URL belum di-set" });

  // Auth fleksibel: env default, bisa override dari UI (opsional)
  const bearer = (authOverride?.bearerToken || process.env.AO_BEARER_TOKEN || "").trim();
  const xSession = (authOverride?.xSessionId || process.env.AO_X_SESSION_ID || "").trim();

  const headers = { "Content-Type": "application/json" };
  if (bearer) headers["Authorization"] = `Bearer ${bearer}`;
  if (xSession) headers["X-Session-ID"] = xSession;

  // Kirim langsung 1 request (data[n] array)
  const url = `${baseUrl}${savePath}`;
  try {
    const r = await fetch(url, {
      method: "POST",
      headers,
      body: JSON.stringify({ data })
    });

    const text = await r.text();
    let json;
    try { json = JSON.parse(text); } catch { json = { raw: text }; }

    if (!r.ok) {
      return res.status(r.status).json({ ok: false, message: "Accurate API error", response: json });
    }
    return res.json({ ok: true, response: json });
  } catch (err) {
    return res.status(500).json({ ok: false, message: err?.message || "Server error" });
  }
});

app.get("/api/health", (_req, res) => res.json({ ok: true }));

app.listen(process.env.PORT || 3000, () => {
  console.log(`Running http://localhost:${process.env.PORT || 3000}`);
  console.log("Tip: set AO_BASE_URL + auth di .env");
});