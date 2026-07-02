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
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@aca-aol.id").strip().lower()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")

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
                "email": "demo@aca-aol.id",
                "password_sha256": sha256("1234"),
                "active": True,
                "expires": None,
                "customer_name": "Demo User",
                "max_databases": 5,
                "allowed_databases": [],
            }
        ]
    with open(LICENSE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_licenses(data):
    with open(LICENSE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def normalize_license_record(lic: dict) -> dict:
    if lic is None:
        return {}

    if "max_databases" not in lic or lic.get("max_databases") in (None, ""):
        lic["max_databases"] = 5

    try:
        lic["max_databases"] = int(lic.get("max_databases") or 5)
    except Exception:
        lic["max_databases"] = 5

    if not isinstance(lic.get("allowed_databases"), list):
        lic["allowed_databases"] = []

    return lic


def normalize_allowed_databases(lic: dict):
    lic = normalize_license_record(lic or {})
    allowed = lic.setdefault("allowed_databases", [])
    normalized = []

    for item in allowed:
        if isinstance(item, dict):
            db_id = str(item.get("id") or "").strip()
            alias = str(item.get("alias") or "").strip()
            registered_at = str(item.get("registered_at") or "").strip()
        else:
            db_id = str(item or "").strip()
            alias = ""
            registered_at = ""

        if db_id and not any(str(x.get("id")) == db_id for x in normalized):
            row = {"id": db_id, "alias": alias}
            if registered_at:
                row["registered_at"] = registered_at
            normalized.append(row)

    lic["allowed_databases"] = normalized
    return normalized


def get_max_databases(lic: dict) -> int:
    try:
        max_db = int((lic or {}).get("max_databases", 5))
    except Exception:
        max_db = 5
    return max(max_db, 0)


def license_valid(email: str, password: str):
    licenses = load_licenses()
    email = (email or "").strip().lower()

    lic = next(
        (x for x in licenses if str(x.get("email", "")).strip().lower() == email),
        None
    )

    if not lic:
        return False, "Email tidak terdaftar", None

    if not lic.get("active"):
        return False, "Akun tidak aktif", None

    expires = lic.get("expires")
    if expires:
        try:
            exp_dt = dt.datetime.fromisoformat(expires + "T23:59:59")
            if dt.datetime.now() > exp_dt:
                return False, "Akun expired", None
        except Exception:
            return False, "Format expires di licenses.json salah", None

    if sha256(password) != lic.get("password_sha256"):
        return False, "Password salah", None

    lic = normalize_license_record(lic)
    return True, "OK", lic


def make_token(email: str) -> str:
    payload = {
        "email": email,
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
# Admin helpers
# =========================
def make_admin_token(email: str) -> str:
    payload = {
        "email": email,
        "role": "admin",
        "exp": dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=8),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def require_admin(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return jsonify({"ok": False, "message": "Unauthorized admin"}), 401
        token = auth[7:]
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
            if payload.get("role") != "admin":
                return jsonify({"ok": False, "message": "Invalid admin session"}), 401
        except Exception:
            return jsonify({"ok": False, "message": "Invalid admin session"}), 401
        return fn(*args, **kwargs)
    return wrapper


def admin_license_view(lic: dict) -> dict:
    lic = normalize_license_record(lic or {})
    allowed = normalize_allowed_databases(lic)
    max_db = get_max_databases(lic)
    return {
        "email": str(lic.get("email", "")).strip().lower(),
        "customer_name": lic.get("customer_name") or "-",
        "active": bool(lic.get("active")),
        "expires": lic.get("expires") or "",
        "notes": lic.get("notes") or "",
        "max_databases": max_db,
        "used_databases": len(allowed),
        "allowed_databases": allowed,
    }


def find_license_index(licenses, email):
    email = str(email or "").strip().lower()
    for i, lic in enumerate(licenses):
        if str(lic.get("email", "")).strip().lower() == email:
            return i
    return -1


def get_current_email_from_auth():
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None

    token = auth[7:]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        email = (payload.get("email") or "").strip().lower()
        return email or None
    except Exception:
        return None


def get_license_by_email(email: str):
    email = (email or "").strip().lower()
    if not email:
        return None

    licenses = load_licenses()
    for lic in licenses:
        if str(lic.get("email", "")).strip().lower() == email:
            return normalize_license_record(lic)
    return None


def license_public_info(lic: dict) -> dict:
    lic = normalize_license_record(lic or {})
    allowed = normalize_allowed_databases(lic)
    return {
        "customer_name": lic.get("customer_name") or "-",
        "email": lic.get("email") or "-",
        "expires": lic.get("expires"),
        "max_databases": get_max_databases(lic),
        "used_databases": len(allowed),
        "allowed_databases": allowed,
    }


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


def normalize_jv_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Support header Excel lama dan baru.
    Contoh: BRANCHID / BranchId / branchId akan dibaca sebagai branchId.
    """
    rename_map = {
        "TRANSDATE": "transDate",
        "NUMBER": "number",
        "DESCRIPTION": "description",
        "BRANCHID": "branchId",
        "BRANCHNAME": "branchName",
        "ID": "id",
        "TYPEAUTONUMBER": "typeAutoNumber",

        "ACCOUNTNO": "accountNo",
        "AMOUNT": "amount",
        "AMOUNTTYPE": "amountType",
        "MEMO": "memo",
        "SUBSIDIARYTYPE": "subsidiaryType",
        "CUSTOMERNO": "customerNo",
        "VENDORNO": "vendorNo",
        "EMPLOYEENO": "employeeNo",
        "PROJECTNO": "projectNo",
        "DEPARTMENTNAME": "departmentName",
        "RATE": "rate",
        "PRIMEAMOUNT": "primeAmount",
        "DETAILID": "id",
        "DETAILSTATUS": "_status",
        "_STATUS": "_status",

        "DATACLASSIFICATION1NAME": "dataClassification1Name",
        "DATACLASSIFICATION2NAME": "dataClassification2Name",
        "DATACLASSIFICATION3NAME": "dataClassification3Name",
        "DATACLASSIFICATION4NAME": "dataClassification4Name",
        "DATACLASSIFICATION5NAME": "dataClassification5Name",
        "DATACLASSIFICATION6NAME": "dataClassification6Name",
        "DATACLASSIFICATION7NAME": "dataClassification7Name",
        "DATACLASSIFICATION8NAME": "dataClassification8Name",
        "DATACLASSIFICATION9NAME": "dataClassification9Name",
        "DATACLASSIFICATION10NAME": "dataClassification10Name",
    }

    df = df.copy()
    df.rename(
        columns=lambda x: rename_map.get(str(x).strip().replace(" ", "").upper(), str(x).strip()),
        inplace=True,
    )
    return df


def build_payload_from_df(df: pd.DataFrame):
    df = normalize_jv_columns(df)

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
    email = (data.get("email") or "").strip().lower()
    password = (data.get("password") or "").strip()

    if not email or not password:
        return jsonify({"ok": False, "message": "Email & password wajib"}), 400

    ok, msg, lic = license_valid(email, password)
    if not ok:
        return jsonify({"ok": False, "message": msg}), 401

    token = make_token(email)

    info = license_public_info(lic)

    return jsonify({
        "ok": True,
        "token": token,
        "customer_name": info.get("customer_name"),
        "email": email,
        "expires": info.get("expires"),
        "max_databases": info.get("max_databases"),
        "used_databases": info.get("used_databases"),
        "allowed_databases": info.get("allowed_databases"),
    })

# =========================
# Routes: status
# =========================
@app.get("/api/ao-status")
@require_auth
def api_ao_status():
    tokens = load_tokens()

    email = get_current_email_from_auth()
    lic = get_license_by_email(email) if email else None
    license_info = license_public_info(lic) if lic else None

    return jsonify(
        {
            "ok": True,
            "has_token": bool((tokens.get("access_token") or "").strip()),
            "has_session": bool((tokens.get("host") or "").strip()) and bool((tokens.get("x_session_id") or "").strip()),
            "db_id": tokens.get("db_id"),
            "db_alias": tokens.get("db_alias"),
            "license": license_info,
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
@require_auth
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
@require_auth
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

    email = get_current_email_from_auth()
    if not email:
        return jsonify({"ok": False, "message": "Unauthorized"}), 401

    licenses = load_licenses()
    user_license = None
    for lic in licenses:
        if str(lic.get("email", "")).strip().lower() == email:
            user_license = normalize_license_record(lic)
            break

    if not user_license:
        return jsonify({"ok": False, "message": "User tidak ditemukan"}), 401

    tokens = refresh_access_token_if_needed()
    access_token = (tokens.get("access_token") or "").strip()
    if not access_token:
        return jsonify({"ok": False, "message": "Belum connect OAuth."}), 401
    if not db_id:
        return jsonify({"ok": False, "message": "db id kosong."}), 400

    allowed = user_license.setdefault("allowed_databases", [])
    max_db = int(user_license.get("max_databases") or 5)
    already_registered = any(str(x.get("id")) == db_id for x in allowed)

    if not already_registered and len(allowed) >= max_db:
        listed = [f"- {x.get('alias') or 'Database'} (ID: {x.get('id')})" for x in allowed]
        detail = "\n".join(listed) if listed else "- belum ada database terdaftar"
        return jsonify({
            "ok": False,
            "message": (
                f"Kuota database penuh. Lisensi {user_license.get('customer_name') or email} "
                f"maksimal {max_db} database.\n\n"
                f"Database yang sudah terdaftar:\n{detail}\n\n"
                "Hubungi ACIS untuk upgrade atau reset database."
            ),
            "license": license_public_info(user_license),
        }), 403

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

    registered_now = False
    if not already_registered:
        allowed.append({
            "id": db_id,
            "alias": db_alias or j.get("alias") or f"Database {db_id}",
            "registered_at": dt.datetime.now().isoformat(),
        })
        save_licenses(licenses)
        registered_now = True

    return jsonify({
        "ok": True,
        "response": j,
        "registered_now": registered_now,
        "message": (
            f"Database berhasil didaftarkan ({len(allowed)}/{max_db})."
            if registered_now else
            f"Database aktif. Kuota database {len(allowed)}/{max_db}."
        ),
        "license": license_public_info(user_license),
    })



# =========================
# Routes: Admin License Panel
# =========================
@app.get("/admin")
def admin_page():
    return render_template("admin.html")


@app.post("/api/admin/login")
def api_admin_login():
    data = request.get_json(silent=True) or {}
    email = str(data.get("email") or "").strip().lower()
    password = str(data.get("password") or "").strip()

    if email != ADMIN_EMAIL or password != ADMIN_PASSWORD:
        return jsonify({"ok": False, "message": "Email/password admin salah"}), 401

    return jsonify({"ok": True, "token": make_admin_token(email), "email": email})


@app.get("/api/admin/licenses")
@require_admin
def api_admin_list_licenses():
    licenses = load_licenses()
    changed = False
    for lic in licenses:
        before = json.dumps(lic, sort_keys=True, ensure_ascii=False)
        normalize_license_record(lic)
        normalize_allowed_databases(lic)
        after = json.dumps(lic, sort_keys=True, ensure_ascii=False)
        changed = changed or before != after
    if changed:
        save_licenses(licenses)
    return jsonify({"ok": True, "data": [admin_license_view(x) for x in licenses]})


@app.post("/api/admin/licenses")
@require_admin
def api_admin_create_license():
    data = request.get_json(silent=True) or {}
    email = str(data.get("email") or "").strip().lower()
    password = str(data.get("password") or "").strip()
    customer_name = str(data.get("customer_name") or "").strip()
    expires = str(data.get("expires") or "").strip()
    notes = str(data.get("notes") or "").strip()
    active = bool(data.get("active", True))

    try:
        max_databases = int(data.get("max_databases") or 5)
    except Exception:
        max_databases = 5

    if not email:
        return jsonify({"ok": False, "message": "Email wajib diisi"}), 400
    if not password:
        return jsonify({"ok": False, "message": "Password wajib diisi"}), 400
    if not customer_name:
        return jsonify({"ok": False, "message": "Nama PT/customer wajib diisi"}), 400
    if expires:
        try:
            dt.datetime.fromisoformat(expires + "T00:00:00")
        except Exception:
            return jsonify({"ok": False, "message": "Format expired harus YYYY-MM-DD"}), 400

    licenses = load_licenses()
    if find_license_index(licenses, email) >= 0:
        return jsonify({"ok": False, "message": "Email sudah terdaftar"}), 400

    lic = {
        "email": email,
        "password_sha256": sha256(password),
        "active": active,
        "expires": expires or None,
        "customer_name": customer_name,
        "notes": notes,
        "max_databases": max_databases,
        "allowed_databases": [],
    }
    licenses.append(lic)
    save_licenses(licenses)
    return jsonify({"ok": True, "message": "Customer berhasil dibuat", "license": admin_license_view(lic)})


@app.put("/api/admin/licenses/<path:email>")
@require_admin
def api_admin_update_license(email):
    target_email = str(email or "").strip().lower()
    data = request.get_json(silent=True) or {}
    licenses = load_licenses()
    idx = find_license_index(licenses, target_email)
    if idx < 0:
        return jsonify({"ok": False, "message": "Customer tidak ditemukan"}), 404

    lic = licenses[idx]
    if "customer_name" in data:
        val = str(data.get("customer_name") or "").strip()
        if val:
            lic["customer_name"] = val
    if "expires" in data:
        expires = str(data.get("expires") or "").strip()
        if expires:
            try:
                dt.datetime.fromisoformat(expires + "T00:00:00")
            except Exception:
                return jsonify({"ok": False, "message": "Format expired harus YYYY-MM-DD"}), 400
            lic["expires"] = expires
        else:
            lic["expires"] = None
    if "notes" in data:
        lic["notes"] = str(data.get("notes") or "").strip()
    if "active" in data:
        lic["active"] = bool(data.get("active"))
    if "max_databases" in data:
        try:
            lic["max_databases"] = int(data.get("max_databases") or 5)
        except Exception:
            lic["max_databases"] = 5
    if str(data.get("password") or "").strip():
        lic["password_sha256"] = sha256(str(data.get("password")).strip())

    normalize_license_record(lic)
    normalize_allowed_databases(lic)
    save_licenses(licenses)
    return jsonify({"ok": True, "message": "Customer berhasil diupdate", "license": admin_license_view(lic)})


@app.post("/api/admin/licenses/<path:email>/reset-databases")
@require_admin
def api_admin_reset_databases(email):
    target_email = str(email or "").strip().lower()
    licenses = load_licenses()
    idx = find_license_index(licenses, target_email)
    if idx < 0:
        return jsonify({"ok": False, "message": "Customer tidak ditemukan"}), 404
    licenses[idx]["allowed_databases"] = []
    save_licenses(licenses)
    return jsonify({"ok": True, "message": "Database terdaftar berhasil direset", "license": admin_license_view(licenses[idx])})


@app.post("/api/admin/licenses/<path:email>/toggle-active")
@require_admin
def api_admin_toggle_active(email):
    target_email = str(email or "").strip().lower()
    licenses = load_licenses()
    idx = find_license_index(licenses, target_email)
    if idx < 0:
        return jsonify({"ok": False, "message": "Customer tidak ditemukan"}), 404
    licenses[idx]["active"] = not bool(licenses[idx].get("active"))
    save_licenses(licenses)
    return jsonify({"ok": True, "message": "Status customer berhasil diubah", "license": admin_license_view(licenses[idx])})


# =========================
# Template download
# =========================
@app.get("/api/template")
def api_template():
    # Template default Journal Voucher lengkap sesuai parameter API Accurate.
    # Header dibuat camelCase agar langsung cocok dengan app.py, namun app.py juga menerima versi UPPERCASE.
    columns = [
        "transDate",
        "number",
        "description",
        "branchId",
        "branchName",
        "typeAutoNumber",

        "accountNo",
        "amount",
        "amountType",
        "memo",
        "subsidiaryType",
        "customerNo",
        "vendorNo",
        "employeeNo",
        "projectNo",
        "departmentName",
        "rate",
        "primeAmount",
        "detailId",
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

    rows = [
        {
            "transDate": "31/03/2026",
            "number": "JV-001",
            "description": "Jurnal Umum Cabang",
            "branchId": "1",
            "branchName": "Cabang Jakarta",
            "typeAutoNumber": "",
            "accountNo": "1100",
            "amount": "100000",
            "amountType": "DEBIT",
            "memo": "Kas masuk",
            "subsidiaryType": "",
            "customerNo": "",
            "vendorNo": "",
            "employeeNo": "",
            "projectNo": "PRJ-01",
            "departmentName": "FIN",
            "rate": "",
            "primeAmount": "",
        },
        {
            "transDate": "31/03/2026",
            "number": "JV-001",
            "description": "Jurnal Umum Cabang",
            "branchId": "1",
            "branchName": "Cabang Jakarta",
            "typeAutoNumber": "",
            "accountNo": "2100",
            "amount": "100000",
            "amountType": "CREDIT",
            "memo": "Kas masuk",
            "subsidiaryType": "",
            "customerNo": "",
            "vendorNo": "",
            "employeeNo": "",
            "projectNo": "PRJ-01",
            "departmentName": "FIN",
            "rate": "",
            "primeAmount": "",
        },
    ]

    def csv_escape(value):
        s = str(value if value is not None else "")
        if any(ch in s for ch in [",", '"', "\n"]):
            return '"' + s.replace('"', '""') + '"'
        return s

    csv_lines = [",".join(columns)]
    for row in rows:
        csv_lines.append(",".join(csv_escape(row.get(col, "")) for col in columns))

    csv = "\n".join(csv_lines)

    return app.response_class(
        csv,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=template-journal-voucher.csv"},
    )


if __name__ == "__main__":
    port = int(os.getenv("PORT", "3000"))
    app.run(host="0.0.0.0", port=port, debug=False)