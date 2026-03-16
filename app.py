import os
import json
import hashlib
import datetime as dt
import base64
from functools import wraps
from urllib.parse import urlencode

import pandas as pd
import requests
import jwt
from flask import Flask, request, jsonify, render_template, redirect
from dotenv import load_dotenv

load_dotenv()

# =========================
# Config
# =========================
APP_DIR = os.path.dirname(__file__)
TOKENS_FILE = os.path.join(APP_DIR, "tokens.json")
LICENSE_FILE = os.path.join(APP_DIR, "licenses.json")

JWT_SECRET = os.getenv("JWT_SECRET", "dev_jwt_change_me")
SECRET_KEY = os.getenv("SECRET_KEY", "dev_change_me")

AO_JV_SAVE_PATH = os.getenv("AO_JV_SAVE_PATH", "/api/journal-voucher/save.do")

OAUTH_AUTHORIZE_URL = "https://account.accurate.id/oauth/authorize"
OAUTH_TOKEN_URL = "https://account.accurate.id/oauth/token"
ACCOUNT_DB_LIST_URL = "https://account.accurate.id/api/db-list.do"
ACCOUNT_OPEN_DB_URL = "https://account.accurate.id/api/open-db.do"

# Debug store (optional)
LAST_DEBUG = {
    "time": None,
    "form_sample": None,
    "url": None,
    "headers": None,
    "response_status": None,
    "response": None,
    "summary": None,
}

app = Flask(__name__)
app.config["SECRET_KEY"] = SECRET_KEY


# =========================
# Utils: token file
# =========================
def save_tokens(data: dict):
    with open(TOKENS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_tokens():
    if not os.path.exists(TOKENS_FILE):
        return {}
    try:
        with open(TOKENS_FILE, "r", encoding="utf-8") as f:
            txt = f.read().strip()
            if not txt:
                return {}
            return json.loads(txt)
    except Exception:
        # kalau file rusak / kosong, anggap belum ada token
        return {}


# =========================
# Utils: license & auth
# =========================
def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_licenses():
    if not os.path.exists(LICENSE_FILE):
        # default demo
        return [
            {
                "code": "DEMO-001",
                "pin_sha256": sha256("1234"),
                "active": True,
                "expires": None,
            }
        ]
    with open(LICENSE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def license_valid(code: str, pin: str):
    licenses = load_licenses()
    lic = next((x for x in licenses if x.get("code") == code), None)

    if not lic:
        return False, "Kode tidak valid", None

    if not lic.get("active"):
        return False, "Lisensi tidak aktif", None

    expires = lic.get("expires")
    if expires:
        try:
            exp_dt = dt.datetime.fromisoformat(expires + "T23:59:59")
            if dt.datetime.now() > exp_dt:
                return False, "Lisensi expired", None
        except Exception:
            return False, "Format expires di licenses.json salah", None

    if sha256(pin) != lic.get("pin_sha256"):
        return False, "PIN salah", None

    return True, "OK", lic


def make_token(code: str) -> str:
    payload = {
        "code": code,
        # python 3.14 warning utcnow → kita pakai timezone aware
        "exp": dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=12),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def require_auth(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return jsonify({"ok": False, "message": "Unauthorized"}), 401
        token = auth[7:]
        try:
            jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        except Exception:
            return jsonify({"ok": False, "message": "Invalid session"}), 401
        return fn(*args, **kwargs)

    return wrapper


# =========================
# OAuth helpers
# =========================
def refresh_access_token_if_needed():
    tokens = load_tokens()
    access_token = (tokens.get("access_token") or "").strip()
    refresh_token = (tokens.get("refresh_token") or "").strip()
    expires_at = (tokens.get("expires_at") or "").strip()  # ISO string

    if not access_token:
        return tokens

    # kalau belum ada expires_at, anggap valid
    if not expires_at:
        return tokens

    try:
        exp = dt.datetime.fromisoformat(expires_at)
        if dt.datetime.now() < exp - dt.timedelta(minutes=2):
            return tokens
    except Exception:
        return tokens

    if not refresh_token:
        return tokens

    client_id = (os.getenv("AO_CLIENT_ID") or "").strip()
    client_secret = (os.getenv("AO_CLIENT_SECRET") or "").strip()
    if not client_id or not client_secret:
        return tokens

    basic = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("utf-8")
    headers = {"Authorization": f"Basic {basic}"}
    data = {"grant_type": "refresh_token", "refresh_token": refresh_token}

    r = requests.post(OAUTH_TOKEN_URL, headers=headers, data=data, timeout=60)
    if not r.ok:
        return tokens

    j = r.json()
    expires_in = int(j.get("expires_in") or 3600)
    new_exp = dt.datetime.now() + dt.timedelta(seconds=expires_in)

    tokens.update(
        {
            "access_token": j.get("access_token"),
            "refresh_token": j.get("refresh_token") or refresh_token,
            "expires_at": new_exp.isoformat(),
            "updated_at": dt.datetime.now().isoformat(),
        }
    )
    save_tokens(tokens)
    return tokens


# =========================
# Excel → payload
# =========================
def parse_date_ddmmyyyy(val):
    if val is None:
        return None

    if isinstance(val, (dt.datetime, dt.date)):
        d = val.date() if isinstance(val, dt.datetime) else val
        return d.strftime("%d/%m/%Y")

    if isinstance(val, (int, float)) and str(val).strip() != "":
        try:
            base = dt.datetime(1899, 12, 30)
            d = base + dt.timedelta(days=float(val))
            return d.strftime("%d/%m/%Y")
        except Exception:
            pass

    s = str(val).strip()
    if not s:
        return None

    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y", "%m/%d/%Y"):
        try:
            d = dt.datetime.strptime(s, fmt)
            return d.strftime("%d/%m/%Y")
        except Exception:
            continue

    try:
        d = pd.to_datetime(s, dayfirst=True, errors="raise")
        return d.strftime("%d/%m/%Y")
    except Exception:
        return None


def build_payload_from_df(df: pd.DataFrame):
    required = ["transDate", "accountNo", "amount", "amountType"]
    for col in required:
        if col not in df.columns:
            raise ValueError(f"Kolom wajib tidak ada: {col}")

    df = df.fillna("")

    normalized_rows = []
    for idx, row in df.iterrows():
        line_no = idx + 2

        trans_date = parse_date_ddmmyyyy(row["transDate"])
        if not trans_date:
            raise ValueError(f"Row {line_no}: transDate harus DD/MM/YYYY atau tanggal valid")

        account_no = str(row["accountNo"]).strip()
        if not account_no:
            raise ValueError(f"Row {line_no}: accountNo kosong")

        try:
            amount = float(str(row["amount"]).replace(",", "").strip())
        except Exception:
            raise ValueError(f"Row {line_no}: amount bukan angka")

        amount_type = str(row["amountType"]).strip().upper()
        if amount_type not in ("DEBIT", "CREDIT"):
            raise ValueError(f"Row {line_no}: amountType harus DEBIT/CREDIT")

        number = str(row.get("number", "")).strip()
        description = str(row.get("description", "")).strip()

        normalized_rows.append(
            {
                **row.to_dict(),
                "transDate": trans_date,
                "accountNo": account_no,
                "amount": amount,
                "amountType": amount_type,
                "number": number,
                "description": description,
            }
        )

    # group by number (autogen kalau kosong)
    auto_i = 1

    def auto_jv_no(date_str, i):
        d = date_str.replace("/", "")
        return f"JV-{d}-{i:03d}"

    grouped = {}
    for r in normalized_rows:
        if not r["number"]:
            r["number"] = auto_jv_no(r["transDate"], auto_i)
            auto_i += 1
        grouped.setdefault(r["number"], []).append(r)

    optional_header_tx = ["description", "branchId", "branchName", "id", "typeAutoNumber"]
    optional_detail = [
        "memo",
        "customerNo",
        "vendorNo",
        "employeeNo",
        "subsidiaryType",
        "projectNo",
        "departmentName",
        "rate",
        "primeAmount",
        "id",
        "_status",
        "dataClassification1Name",
        "dataClassification2Name",
        "dataClassification3Name",
        "dataClassification4Name",
        "dataClassification5Name",
        "dataClassification6Name",
        "dataClassification7Name",
        "dataClassification8Name",
        "dataClassification9Name",
        "dataClassification10Name",
    ]

    data = []
    for number, lines in grouped.items():
        head = lines[0]
        tx = {
            "transDate": head["transDate"],
            "number": number,
            "detailJournalVoucher": [],
        }

        for f in optional_header_tx:
            if f in head and str(head.get(f, "")).strip() != "":
                val = head.get(f)
                if f in ("branchId", "id", "typeAutoNumber"):
                    try:
                        val = int(float(val))
                    except Exception:
                        pass
                tx[f] = val

        for r in lines:
            det = {
                "accountNo": r["accountNo"],
                "amount": r["amount"],
                "amountType": r["amountType"],
            }
            for f in optional_detail:
                if f in r and str(r.get(f, "")).strip() != "":
                    val = r.get(f)
                    if f in ("rate", "primeAmount"):
                        try:
                            val = float(str(val).replace(",", "").strip())
                        except Exception:
                            pass
                    if f == "subsidiaryType":
                        val = str(val).strip().upper()
                    det[f] = val
            tx["detailJournalVoucher"].append(det)

        data.append(tx)

    return {"data": data}


# =========================
# Payload → Form params (INI KUNCI)
# =========================
def payload_to_form_params(payload: dict) -> dict:
    """
    Convert:
      {"data":[{"transDate":"04/03/2026","number":"JV-001","detailJournalVoucher":[{...},{...}]}]}
    into:
      data[0].transDate=04/03/2026
      data[0].number=JV-001
      data[0].detailJournalVoucher[0].accountNo=1100
      ...
    """
    form = {}
    data = payload.get("data") or []
    for i, tx in enumerate(data):
        # header
        for k, v in tx.items():
            if k == "detailJournalVoucher":
                continue
            if v is None or str(v).strip() == "":
                continue
            form[f"data[{i}].{k}"] = str(v)

        # details
        details = tx.get("detailJournalVoucher") or []
        for j, det in enumerate(details):
            for dk, dv in det.items():
                if dv is None or str(dv).strip() == "":
                    continue
                form[f"data[{i}].detailJournalVoucher[{j}].{dk}"] = str(dv)

    return form


# =========================
# Routes: UI
# =========================
@app.get("/")
def home():
    return render_template("index.html")


# =========================
# Routes: login/license
# =========================
@app.post("/api/login")
def api_login():
    data = request.get_json(silent=True) or {}
    code = (data.get("code") or "").strip()
    pin = (data.get("pin") or "").strip()

    if not code or not pin:
        return jsonify({"ok": False, "message": "Code & PIN wajib"}), 400

    ok, msg, lic = license_valid(code, pin)
    if not ok:
        return jsonify({"ok": False, "message": msg}), 401

    token = make_token(code)

    return jsonify({
        "ok": True,
        "token": token,
        "customer_name": lic.get("customer_name")
    })

# =========================
# Routes: status
# =========================
@app.get("/api/ao-status")
def api_ao_status():
    tokens = load_tokens()
    return jsonify(
        {
            "ok": True,
            "has_token": bool((tokens.get("access_token") or "").strip()),
            "has_session": bool((tokens.get("host") or "").strip()) and bool((tokens.get("x_session_id") or "").strip()),
            "db_id": tokens.get("db_id"),
            "db_alias": tokens.get("db_alias"),
        }
    )


@app.get("/api/debug-last")
def api_debug_last():
    return jsonify({"ok": True, **LAST_DEBUG})


# =========================
# Routes: build payload
# =========================
@app.post("/api/build-payload")
@require_auth
def api_build_payload():
    if "file" not in request.files:
        return jsonify({"ok": False, "message": "File tidak ditemukan"}), 400

    f = request.files["file"]
    if not f.filename.lower().endswith((".xlsx", ".xls")):
        return jsonify({"ok": False, "message": "File harus Excel (.xlsx/.xls)"}), 400

    try:
        df = pd.read_excel(f)
        built = build_payload_from_df(df)

        tx_count = len(built.get("data", []))
        line_count = sum(len(x.get("detailJournalVoucher", [])) for x in built.get("data", []))

        return jsonify(
            {
                "ok": True,
                "payload": built,
                "summary": {"transactions": tx_count, "lines": line_count},
            }
        )
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 400

def tx_to_form_params(tx: dict) -> dict:
    """
    Convert 1 transaksi JV (tanpa wrapper 'data') ke form params yang dimau save.do
    """
    out = {}

    # header minimal
    for k in ["transDate", "number", "description", "branchId", "branchName", "typeAutoNumber", "id"]:
        v = tx.get(k)
        if v not in (None, ""):
            out[k] = v

    details = tx.get("detailJournalVoucher") or []
    for i, det in enumerate(details):
        for k, v in det.items():
            if v in (None, ""):
                continue
            out[f"detailJournalVoucher[{i}].{k}"] = v

    # semua value jadikan string
    return {k: str(v) for k, v in out.items()}

@app.post("/api/ao-logout")
def api_ao_logout():
    if os.path.exists(TOKENS_FILE):
        os.remove(TOKENS_FILE)
    return jsonify({"ok": True})

# =========================
# Routes: import JV (FIXED)
# =========================
@app.post("/api/import-journal-voucher")
@require_auth
def api_import_jv():
    body = request.get_json(silent=True) or {}
    payload = body.get("payload")

    if not payload or "data" not in payload:
        return jsonify({"ok": False, "message": "payload kosong"}), 400

    tokens = refresh_access_token_if_needed()
    access_token = (tokens.get("access_token") or "").strip()
    host = (tokens.get("host") or "").strip()
    x_session = (tokens.get("x_session_id") or "").strip()

    if not access_token or not host or not x_session:
        return jsonify({
            "ok": False,
            "message": "OAuth belum lengkap. Connect + pilih DB dulu."
        }), 400

    url = f"{host}/accurate{AO_JV_SAVE_PATH}"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "X-Session-ID": x_session,
        "Accept": "application/json",
    }

    results = []
    success_count = 0
    failed_count = 0

    try:
        for idx, tx in enumerate(payload.get("data", []), start=1):
            tx_number = tx.get("number") or f"TX-{idx}"
            tx_date = tx.get("transDate") or "-"
            tx_errors = []
            resp_json = None
            tx_ok = False

            try:
                form_params = tx_to_form_params(tx)

                r = requests.post(
                    url,
                    headers=headers,
                    data=form_params,
                    timeout=60
                )

                try:
                    resp_json = r.json()
                except Exception:
                    resp_json = {"raw": r.text}

                # sukses jika HTTP OK dan Accurate s=true
                if r.ok and isinstance(resp_json, dict) and resp_json.get("s") is True:
                    tx_ok = True
                    success_count += 1
                else:
                    failed_count += 1

                    if isinstance(resp_json, dict):
                        if isinstance(resp_json.get("d"), list):
                            tx_errors = [str(x) for x in resp_json.get("d", [])]
                        elif resp_json.get("d"):
                            tx_errors = [str(resp_json.get("d"))]
                        elif resp_json.get("message"):
                            tx_errors = [str(resp_json.get("message"))]
                        else:
                            tx_errors = ["Transaksi ditolak Accurate."]
                    else:
                        tx_errors = ["Response Accurate tidak dikenali."]

            except Exception as ex:
                failed_count += 1
                tx_errors = [str(ex)]

            results.append({
                "index": idx,
                "number": tx_number,
                "transDate": tx_date,
                "ok": tx_ok,
                "errors": tx_errors,
                "raw_response": resp_json
            })

        summary = {
            "total": len(results),
            "success": success_count,
            "failed": failed_count
        }

        # simpan debug terakhir
        LAST_DEBUG["time"] = dt.datetime.now().isoformat()
        LAST_DEBUG["url"] = url
        LAST_DEBUG["headers"] = {
            "Authorization": "Bearer ***",
            "X-Session-ID": x_session
        }
        LAST_DEBUG["response"] = results
        LAST_DEBUG["summary"] = summary

        # semua sukses
        if failed_count == 0:
            return jsonify({
                "ok": True,
                "message": "Import berhasil",
                "summary": summary,
                "results": results
            }), 200

        # ada yang gagal
        return jsonify({
            "ok": False,
            "message": "Import selesai",
            "summary": summary,
            "results": results
        }), 400

    except Exception as e:
        return jsonify({
            "ok": False,
            "message": str(e)
        }), 500

# =========================
# Routes: OAuth
# =========================
@app.get("/oauth/start")
def oauth_start():
    client_id = (os.getenv("AO_CLIENT_ID") or "").strip()
    redirect_uri = (os.getenv("AO_REDIRECT_URI") or "").strip()
    scope = (os.getenv("AO_SCOPE") or "").strip()

    if not client_id or not redirect_uri or not scope:
        return (
            jsonify(
                {
                    "ok": False,
                    "message": "OAuth env belum lengkap. Isi AO_CLIENT_ID, AO_REDIRECT_URI, AO_SCOPE di .env",
                }
            ),
            500,
        )

    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": scope,
    }

    url = OAUTH_AUTHORIZE_URL + "?" + urlencode(params)
    return redirect(url, code=302)


@app.get("/oauth/callback")
def oauth_callback():
    code = (request.args.get("code") or "").strip()
    if not code:
        return "Tidak ada parameter code. OAuth ditolak / gagal.", 400

    client_id = (os.getenv("AO_CLIENT_ID") or "").strip()
    client_secret = (os.getenv("AO_CLIENT_SECRET") or "").strip()
    redirect_uri = (os.getenv("AO_REDIRECT_URI") or "").strip()
    if not client_id or not client_secret or not redirect_uri:
        return "OAuth env belum lengkap. Isi AO_CLIENT_ID/AO_CLIENT_SECRET/AO_REDIRECT_URI di .env", 500

    basic = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("utf-8")
    headers = {"Authorization": f"Basic {basic}"}
    data = {"code": code, "grant_type": "authorization_code", "redirect_uri": redirect_uri}

    r = requests.post(OAUTH_TOKEN_URL, headers=headers, data=data, timeout=60)
    try:
        j = r.json()
    except Exception:
        j = {"raw": r.text}

    if not r.ok:
        return jsonify({"ok": False, "message": "Gagal tukar code ke token", "response": j}), r.status_code

    expires_in = int(j.get("expires_in") or 3600)
    exp = dt.datetime.now() + dt.timedelta(seconds=expires_in)

    tokens = load_tokens()
    tokens.update(
        {
            "access_token": j.get("access_token"),
            "refresh_token": j.get("refresh_token"),
            "scope": j.get("scope"),
            "token_type": j.get("token_type"),
            "expires_at": exp.isoformat(),
            "updated_at": dt.datetime.now().isoformat(),
        }
    )
    save_tokens(tokens)

    return """
    <script>
      window.location.href = "/";
    </script>
    """


# =========================
# Routes: db list & open db
# =========================
@app.get("/api/db-list")
def api_db_list():
    tokens = refresh_access_token_if_needed()
    access_token = (tokens.get("access_token") or "").strip()
    if not access_token:
        return jsonify({"ok": False, "message": "Belum connect OAuth. Klik Connect Accurate dulu."}), 401

    headers = {"Authorization": f"Bearer {access_token}"}
    r = requests.get(ACCOUNT_DB_LIST_URL, headers=headers, timeout=60)

    try:
        j = r.json()
    except Exception:
        j = {"raw": r.text}

    if not r.ok:
        return jsonify({"ok": False, "message": "db-list gagal", "status": r.status_code, "response": j}), r.status_code

    return jsonify({"ok": True, "response": j})


@app.post("/api/open-db")
def api_open_db():
    body = request.get_json(silent=True) or {}
    db_id = str(body.get("id") or "").strip()
    db_alias = str(body.get("alias") or "").strip()

    tokens = refresh_access_token_if_needed()
    access_token = (tokens.get("access_token") or "").strip()
    if not access_token:
        return jsonify({"ok": False, "message": "Belum connect OAuth."}), 401
    if not db_id:
        return jsonify({"ok": False, "message": "db id kosong."}), 400

    headers = {"Authorization": f"Bearer {access_token}"}
    r = requests.get(ACCOUNT_OPEN_DB_URL, headers=headers, params={"id": db_id}, timeout=60)

    try:
        j = r.json()
    except Exception:
        j = {"raw": r.text}

    if not r.ok:
        return jsonify({"ok": False, "message": "open-db gagal", "status": r.status_code, "response": j}), r.status_code

    # simpan host + session
    tokens.update(
        {
            "db_id": db_id,
            "db_alias": db_alias or tokens.get("db_alias"),
            "host": j.get("host"),
            "x_session_id": j.get("session"),
            "updated_at": dt.datetime.now().isoformat(),
        }
    )
    save_tokens(tokens)

    return jsonify({"ok": True, "response": j})


# =========================
# Template download
# =========================
@app.get("/api/template")
def api_template():
    csv = "\n".join(
        [
            "transDate,number,description,accountNo,amount,amountType,memo,subsidiaryType,customerNo,vendorNo,employeeNo,projectNo,departmentName",
            "31/03/2016,JV-001,Test JV,1100,100000,DEBIT,Catatan,,,,,PRJ-01,FIN",
            "31/03/2016,JV-001,Test JV,2100,100000,CREDIT,Catatan,,,,,PRJ-01,FIN",
        ]
    )
    return app.response_class(
        csv,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=template-journal-voucher.csv"},
    )


if __name__ == "__main__":
    app.run(debug=True, port=3000)