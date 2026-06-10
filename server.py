import io
import math
import os
import re
import time
import hmac
import hashlib
import secrets
from typing import Annotated, Any

import numpy as np
import cv2
from fastapi import Cookie, Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from collections import deque
import base64
import json
import threading
from fastapi import Request
from datetime import datetime
import sqlite3
from collections import defaultdict

from fastapi import Query
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.concurrency import run_in_threadpool

# Ultralytics YOLOv8 (PyTorch). This is the simplest server-side YOLO path for demos.
# Install: pip install -r requirements.txt
from ultralytics import YOLO


APP_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(APP_DIR, "static")

app = FastAPI(title="Parking Eye Demo (web + server-side YOLO)")


class _NoCacheStaticMiddleware(BaseHTTPMiddleware):
  """Dev: always return fresh HTML/JS/CSS (no 304) so cabinet updates apply."""

  _STATIC_SUFFIX = (".html", ".js", ".css")

  async def dispatch(self, request: Request, call_next):
    path = request.url.path
    no_cache = path == "/" or path.endswith(self._STATIC_SUFFIX)
    if no_cache:
      headers = [
        (n, v)
        for n, v in request.scope.get("headers", [])
        if n.lower() not in (b"if-none-match", b"if-modified-since")
      ]
      request.scope["headers"] = headers
    response = await call_next(request)
    if no_cache:
      response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
      response.headers["Pragma"] = "no-cache"
      if "etag" in response.headers:
        del response.headers["etag"]
      if "last-modified" in response.headers:
        del response.headers["last-modified"]
    return response


app.add_middleware(_NoCacheStaticMiddleware)


class _ApiLogMiddleware(BaseHTTPMiddleware):
  """Print API hits to console (helps debug pay/bookings)."""

  async def dispatch(self, request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/"):
      print(f"[PE] {request.method} {path}", flush=True)
    return await call_next(request)


app.add_middleware(_ApiLogMiddleware)


@app.exception_handler(HTTPException)
async def _api_http_exception(request: Request, exc: HTTPException) -> JSONResponse:
  """JSON errors for /api/* (e.g. login_required instead of plain detail)."""
  if str(request.url.path).startswith("/api/"):
    detail = exc.detail
    reason = detail if isinstance(detail, str) else str(detail)
    return JSONResponse({"ok": False, "reason": reason}, status_code=exc.status_code)
  return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


# Models:
# - SLOT model: segmentation model that outlines parking slots (preferably trained on slot masks).
# - CAR model: detection model for vehicles, used for occupancy via overlap.
#
# Back-compat:
# - PARKING_EYE_MODEL still works as SLOT model path.
SLOT_MODEL_PATH = os.environ.get("PARKING_EYE_SLOT_MODEL", os.environ.get("PARKING_EYE_MODEL", "yolov8n-seg.pt"))
CAR_MODEL_PATH = os.environ.get("PARKING_EYE_CAR_MODEL", "yolov8n.pt")
CONF_THRES = float(os.environ.get("PARKING_EYE_CONF", "0.25"))
AUTO_CROP_MODE = os.environ.get("PARKING_EYE_AUTO_CROP", "auto").lower()

# Auto-slots mode: model returns segmented parking slots with occupancy
# We expect classes: slot_free / slot_occupied
SLOT_FREE = {"slot_free", "free", "not_occupied", "not occupied"}
SLOT_OCC = {"slot_occupied", "occupied"}

_slot_model: YOLO | None = None
_car_model: YOLO | None = None

# --- Shared state (latest frame + slots) for "client view" ---
_state_lock = threading.Lock()
_last_frame_jpeg: bytes | None = None
_last_slots: list[dict[str, Any]] = []
_last_ts: float | None = None
_last_dt_ms: int | None = None
_event_id: int = 0

# Rolling stats (last N detections)
_stats_lock = threading.Lock()
_stats_window = deque(maxlen=120)  # ~24s at 5 fps; enough for smoothing

# Simple auth (stage4)
OPERATOR_KEY = os.environ.get("PARKING_EYE_OPERATOR_KEY", "").strip()
CLIENT_KEY = os.environ.get("PARKING_EYE_CLIENT_KEY", "").strip()

# naive rate limit (per IP per endpoint)
_rl_lock = threading.Lock()
_rl_hits: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=200))

# --- User cabinet + bookings (sessions via HttpOnly cookie) ---
SESSION_COOKIE = "pe_session"
SESSION_SECONDS = max(3600, int(float(os.environ.get("PARKING_EYE_SESSION_DAYS", "14"))) * 86400)
REGISTRATION_ENABLED = os.environ.get("PARKING_EYE_REGISTRATION", "1").strip().lower() not in ("0", "false", "no")
_USERNAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,31}$")
_EMAIL_RE = re.compile(r"^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,24}$")
_FAMILY_INVITE_RE = re.compile(r"^[A-Z0-9]{6,12}$")


def _normalize_username(username: str) -> str | None:
  u = str(username or "").strip().lower()
  if "@" in u:
    if 3 <= len(u) <= 64 and _EMAIL_RE.match(u):
      return u
    return None
  if _USERNAME_RE.match(u):
    return u
  return u


def _normalize_family_invite(code: str) -> str | None:
  c = str(code or "").strip().upper().replace("-", "")
  if not c or not _FAMILY_INVITE_RE.match(c):
    return None
  return c


def _new_family_invite_code() -> str:
  return secrets.token_hex(4).upper()


def _user_family_row(con: sqlite3.Connection, user_id: int) -> dict[str, Any] | None:
  row = con.execute(
    """
    SELECT u.family_id AS family_id, u.family_role AS family_role,
           f.name AS family_name, f.invite_code AS invite_code, f.owner_user_id AS owner_user_id
    FROM users u
    LEFT JOIN family_accounts f ON f.id = u.family_id
    WHERE u.id = ?
    """,
    (int(user_id),),
  ).fetchone()
  if not row or row["family_id"] is None:
    return None
  return dict(row)


def _family_public(con: sqlite3.Connection, user_id: int) -> dict[str, Any] | None:
  fr = _user_family_row(con, user_id)
  if not fr:
    return None
  fid = int(fr["family_id"])
  members = con.execute(
    """
    SELECT id, username, display_name, family_role, active
    FROM users WHERE family_id = ?
    ORDER BY CASE family_role WHEN 'owner' THEN 0 ELSE 1 END, id ASC
    """,
    (fid,),
  ).fetchall()
  is_owner = int(fr.get("owner_user_id") or 0) == int(user_id) or str(fr.get("family_role") or "") == "owner"
  return {
    "id": fid,
    "name": str(fr.get("family_name") or "Семейный аккаунт"),
    "invite_code": str(fr["invite_code"]) if is_owner else None,
    "is_owner": is_owner,
    "members": [
      {
        "id": int(m["id"]),
        "username": str(m["username"]),
        "display_name": str(m["display_name"]),
        "family_role": str(m["family_role"] or "member"),
        "active": bool(int(m["active"] or 0)),
      }
      for m in members
    ],
  }


def _create_family_account(con: sqlite3.Connection, owner_user_id: int, name: str) -> int:
  ts = time.time()
  for _ in range(12):
    code = _new_family_invite_code()
    try:
      cur = con.execute(
        """
        INSERT INTO family_accounts (name, invite_code, owner_user_id, created_ts)
        VALUES (?, ?, ?, ?)
        """,
        (name[:80] or "Семейный аккаунт", code, int(owner_user_id), ts),
      )
      return int(cur.lastrowid)
    except sqlite3.IntegrityError:
      continue
  raise RuntimeError("family_invite_collision")


def _ensure_user_has_family(con: sqlite3.Connection, user_id: int, display_name: str) -> int:
  row = con.execute("SELECT family_id FROM users WHERE id = ?", (int(user_id),)).fetchone()
  if row and row["family_id"] is not None:
    return int(row["family_id"])
  fid = _create_family_account(con, int(user_id), f"Семья {display_name[:40]}")
  con.execute(
    "UPDATE users SET family_id = ?, family_role = 'owner' WHERE id = ?",
    (fid, int(user_id)),
  )
  return fid


def _booking_access_sql(family_id: int | None, uid: int, alias: str = "b") -> tuple[str, list[Any]]:
  if family_id is not None:
    return f"{alias}.family_id = ?", [int(family_id)]
  return f"{alias}.user_id = ?", [int(uid)]


def _validate_password(password: str) -> bool:
  p = str(password or "")
  return 8 <= len(p) <= 128


def _user_public(row: dict[str, Any], family: dict[str, Any] | None = None) -> dict[str, Any]:
  out: dict[str, Any] = {
    "id": int(row["id"]),
    "username": str(row["username"]),
    "display_name": str(row["display_name"]),
    "role": str(row["role"]),
  }
  if family:
    out["family"] = family
  return out


def _issue_session_response(user_id: int, username: str, display_name: str, role: str) -> JSONResponse:
  raw_token = secrets.token_urlsafe(32)
  th = _session_digest(raw_token)
  now = time.time()
  family: dict[str, Any] | None = None
  with _db_lock:
    con = _db()
    try:
      con.execute(
        "INSERT INTO sessions (token_hash, user_id, created_ts, expires_ts) VALUES (?, ?, ?, ?)",
        (th, int(user_id), now, now + float(SESSION_SECONDS)),
      )
      family = _family_public(con, int(user_id))
      con.commit()
    finally:
      con.close()
  out = JSONResponse(
    {
      "ok": True,
      "user": _user_public(
        {
          "id": int(user_id),
          "username": str(username),
          "display_name": str(display_name),
          "role": str(role),
        },
        family,
      ),
    }
  )
  secure_cookie = os.environ.get("PARKING_EYE_COOKIE_SECURE", "").strip().lower() in ("1", "true", "yes")
  out.set_cookie(
    SESSION_COOKIE,
    raw_token,
    httponly=True,
    max_age=int(SESSION_SECONDS),
    samesite="lax",
    path="/",
    secure=secure_cookie,
  )
  return out


def _hash_password_plain(password: str) -> str:
  salt = os.urandom(16)
  dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
  return base64.b64encode(salt + dk).decode("ascii")


def _verify_password_plain(password: str, stored: str) -> bool:
  try:
    raw = base64.b64decode(stored.encode("ascii"))
  except Exception:
    return False
  if len(raw) < 32:
    return False
  salt, want = raw[:16], raw[16:]
  got = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
  return hmac.compare_digest(want, got)


def _session_digest(token: str) -> str:
  return hashlib.sha256(token.strip().encode("utf-8")).hexdigest()


def _auth_row_from_cookie(pe_session: str | None) -> dict[str, Any] | None:
  if not pe_session:
    return None
  t = pe_session.strip()
  if len(t) < 16:
    return None
  th = _session_digest(t)
  now = time.time()
  with _db_lock:
    con = _db()
    try:
      row = con.execute(
        """
        SELECT u.id AS id, u.username AS username, u.display_name AS display_name, u.role AS role, u.active AS active,
               u.family_id AS family_id, u.family_role AS family_role
        FROM sessions s
        JOIN users u ON u.id = s.user_id
        WHERE s.token_hash = ? AND s.expires_ts > ?
        """,
        (th, now),
      ).fetchone()
    finally:
      con.close()
  if not row or not int(row["active"] or 0):
    return None
  return dict(row)


def require_login(pe_session: str | None = Cookie(default=None)) -> dict[str, Any]:
  u = _auth_row_from_cookie(pe_session)
  if not u:
    raise HTTPException(status_code=401, detail="login_required")
  return u


def require_admin(user: Annotated[dict[str, Any], Depends(require_login)]) -> dict[str, Any]:
  if str(user.get("role") or "").lower() != "admin":
    raise HTTPException(status_code=403, detail="admin_only")
  return user


def _client_ip(req: Request) -> str:
  xff = req.headers.get("x-forwarded-for")
  if xff:
    return xff.split(",")[0].strip()
  c = getattr(req, "client", None)
  return str(getattr(c, "host", "unknown"))


def _rate_limit(req: Request, key: str, limit: int, window_s: float) -> bool:
  now = time.time()
  ip = _client_ip(req)
  k = f"{ip}:{key}"
  with _rl_lock:
    dq = _rl_hits[k]
    while dq and (now - dq[0]) > window_s:
      dq.popleft()
    if len(dq) >= limit:
      return False
    dq.append(now)
    return True


def _require_key(req: Request, expected: str) -> bool:
  if not expected:
    return True
  provided = (req.headers.get("x-api-key") or req.query_params.get("key") or "").strip()
  return provided == expected

# Slot tracking (stage3): stable ids + debounce
_track_lock = threading.Lock()
_tracks: dict[str, dict[str, Any]] = {}
_next_slot_id = 1

# Runtime config (editable via /api/config)
_cfg_lock = threading.Lock()
_cfg: dict[str, Any] = {
  "conf": CONF_THRES,
  "auto_crop": AUTO_CROP_MODE,  # "auto"|"off"
  "source_fps": int(os.environ.get("PARKING_EYE_SOURCE_FPS", "5")),
  "client_poll_ms": int(os.environ.get("PARKING_EYE_CLIENT_POLL_MS", "1500")),
  "use_car_occupancy": True,
  "car_conf": float(os.environ.get("PARKING_EYE_CAR_CONF", "0.25")),
  "car_overlap": float(os.environ.get("PARKING_EYE_CAR_OVERLAP", "0.12")),
  "car_classes": ["car", "truck", "bus", "motorcycle"],
}

# Snapshots
SNAP_DIR = os.path.join(APP_DIR, "snapshots")
os.makedirs(SNAP_DIR, exist_ok=True)
_snap_lock = threading.Lock()
_snap_index: deque[dict[str, Any]] = deque(maxlen=200)

# SQLite storage (MVP); override with PARKING_EYE_DB for tests
DB_PATH = os.environ.get("PARKING_EYE_DB", os.path.join(APP_DIR, "parking.db"))
_db_lock = threading.RLock()


def _db() -> sqlite3.Connection:
  # One connection per call; guarded by _db_lock (RLock — nested _kv_get inside transactions).
  con = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=15.0)
  con.row_factory = sqlite3.Row
  try:
    con.execute("PRAGMA journal_mode=WAL")
  except sqlite3.Error:
    pass
  return con


def _db_init() -> None:
  with _db_lock:
    con = _db()
    try:
      cur = con.cursor()
      cur.execute(
        """
        CREATE TABLE IF NOT EXISTS observations (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          ts REAL NOT NULL,
          dt_ms INTEGER,
          total INTEGER,
          free INTEGER,
          occupied INTEGER,
          slots_json TEXT NOT NULL
        )
        """
      )
      cur.execute(
        """
        CREATE TABLE IF NOT EXISTS snapshots (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          ts REAL NOT NULL,
          event_id INTEGER,
          name TEXT NOT NULL,
          jpg_path TEXT NOT NULL,
          json_path TEXT NOT NULL,
          total INTEGER,
          free INTEGER,
          occupied INTEGER
        )
        """
      )
      cur.execute(
        """
        CREATE TABLE IF NOT EXISTS kv (
          k TEXT PRIMARY KEY,
          v TEXT NOT NULL
        )
        """
      )
      cur.execute(
        """
        CREATE TABLE IF NOT EXISTS vehicles (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          created_ts REAL NOT NULL,
          plate TEXT,
          kind TEXT,
          size TEXT,
          is_ev INTEGER,
          is_disabled INTEGER,
          notes TEXT
        )
        """
      )
      cur.execute(
        """
        CREATE TABLE IF NOT EXISTS visits (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          ts REAL NOT NULL,
          vehicle_id INTEGER,
          source TEXT,
          meta_json TEXT,
          FOREIGN KEY(vehicle_id) REFERENCES vehicles(id)
        )
        """
      )
      cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          username TEXT UNIQUE NOT NULL,
          password_hash TEXT NOT NULL,
          display_name TEXT NOT NULL,
          role TEXT NOT NULL DEFAULT 'user',
          active INTEGER NOT NULL DEFAULT 1,
          created_ts REAL NOT NULL
        )
        """
      )
      cur.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          token_hash TEXT UNIQUE NOT NULL,
          user_id INTEGER NOT NULL,
          created_ts REAL NOT NULL,
          expires_ts REAL NOT NULL,
          FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
      )
      cur.execute(
        """
        CREATE TABLE IF NOT EXISTS bookings (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id INTEGER NOT NULL,
          slot_id TEXT NOT NULL,
          start_ts REAL NOT NULL,
          end_ts REAL NOT NULL,
          status TEXT NOT NULL DEFAULT 'active',
          note TEXT,
          created_ts REAL NOT NULL,
          FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
      )
      cur.execute("CREATE INDEX IF NOT EXISTS idx_bookings_slot_active ON bookings(slot_id, status, start_ts, end_ts)")
      cur.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)")
      con.commit()
    finally:
      con.close()


def _seed_demo_users() -> None:
  """One-time demo accounts when DB has no users."""
  demo = [
    ("admin", _hash_password_plain("admin123"), "Администратор", "admin"),
    ("ivan", _hash_password_plain("user123"), "Иван Петров", "user"),
    ("maria", _hash_password_plain("user123"), "Мария Сидорова", "user"),
    ("oleg", _hash_password_plain("user123"), "Олег Кузнецов", "user"),
  ]
  ts = time.time()
  with _db_lock:
    con = _db()
    try:
      n = int(con.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"])
      if n > 0:
        return
      for username, pw_hash, disp, role in demo:
        con.execute(
          "INSERT INTO users (username, password_hash, display_name, role, active, created_ts) VALUES (?,?,?,?,?,?)",
          (username.lower(), pw_hash, disp, role, 1, ts),
        )
      con.commit()
    finally:
      con.close()


def _db_migrate() -> None:
  """Additive schema for MVP features."""
  with _db_lock:
    con = _db()
    try:
      cur = con.cursor()
      cur.execute(
        """
        CREATE TABLE IF NOT EXISTS slot_overrides (
          slot_id TEXT PRIMARY KEY,
          status TEXT NOT NULL DEFAULT 'available',
          note TEXT,
          updated_ts REAL NOT NULL
        )
        """
      )
      cur.execute(
        """
        CREATE TABLE IF NOT EXISTS payments (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id INTEGER NOT NULL,
          booking_id INTEGER,
          amount_rub REAL NOT NULL,
          status TEXT NOT NULL DEFAULT 'paid',
          receipt_id TEXT,
          created_ts REAL NOT NULL,
          FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
      )
      for stmt in (
        "ALTER TABLE bookings ADD COLUMN plate TEXT",
        "ALTER TABLE users ADD COLUMN block_reason TEXT",
      ):
        try:
          cur.execute(stmt)
        except sqlite3.OperationalError:
          pass
      cur.execute(
        "INSERT OR IGNORE INTO kv (k, v) VALUES ('tariff_hour_rub', '120')"
      )
      cur.execute(
        "INSERT OR IGNORE INTO kv (k, v) VALUES ('tariff_currency', 'RUB')"
      )
      cur.execute(
        "INSERT OR IGNORE INTO kv (k, v) VALUES ('loyalty_points_per_paid_hour', '50')"
      )
      cur.execute(
        "INSERT OR IGNORE INTO kv (k, v) VALUES ('loyalty_points_per_free_hour', '500')"
      )
      cur.execute(
        """
        CREATE TABLE IF NOT EXISTS family_accounts (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL,
          invite_code TEXT UNIQUE NOT NULL,
          owner_user_id INTEGER NOT NULL,
          created_ts REAL NOT NULL,
          FOREIGN KEY(owner_user_id) REFERENCES users(id)
        )
        """
      )
      for stmt in (
        "ALTER TABLE users ADD COLUMN family_id INTEGER",
        "ALTER TABLE users ADD COLUMN family_role TEXT",
        "ALTER TABLE bookings ADD COLUMN family_id INTEGER",
        "ALTER TABLE payments ADD COLUMN family_id INTEGER",
        "ALTER TABLE family_accounts ADD COLUMN points_balance INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE payments ADD COLUMN points_earned INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE payments ADD COLUMN paid_with_points INTEGER NOT NULL DEFAULT 0",
      ):
        try:
          cur.execute(stmt)
        except sqlite3.OperationalError:
          pass
      cur.execute(
        """
        CREATE TABLE IF NOT EXISTS support_messages (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id INTEGER NOT NULL,
          from_role TEXT NOT NULL,
          body TEXT NOT NULL,
          created_ts REAL NOT NULL,
          read_by_user INTEGER NOT NULL DEFAULT 0,
          read_by_admin INTEGER NOT NULL DEFAULT 0,
          FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
      )
      cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_support_user_ts ON support_messages(user_id, created_ts)"
      )
      cur.execute(
        """
        CREATE TABLE IF NOT EXISTS loyalty_ledger (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          family_id INTEGER NOT NULL,
          user_id INTEGER NOT NULL,
          delta INTEGER NOT NULL,
          balance_after INTEGER NOT NULL,
          reason TEXT NOT NULL,
          booking_id INTEGER,
          payment_id INTEGER,
          created_ts REAL NOT NULL,
          FOREIGN KEY(family_id) REFERENCES family_accounts(id),
          FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
      )
      users_no_family = cur.execute(
        "SELECT id, display_name FROM users WHERE family_id IS NULL"
      ).fetchall()
      for u in users_no_family:
        uid = int(u["id"])
        disp = str(u["display_name"] or "User")
        fid = _create_family_account(con, uid, f"Семья {disp[:40]}")
        cur.execute(
          "UPDATE users SET family_id = ?, family_role = 'owner' WHERE id = ?",
          (fid, uid),
        )
      cur.execute(
        """
        UPDATE bookings SET family_id = (
          SELECT family_id FROM users WHERE users.id = bookings.user_id
        ) WHERE family_id IS NULL
        """
      )
      cur.execute(
        """
        UPDATE payments SET family_id = (
          SELECT family_id FROM users WHERE users.id = payments.user_id
        ) WHERE family_id IS NULL
        """
      )
      con.commit()
    finally:
      con.close()


_db_init()
_db_migrate()
_seed_demo_users()

DEFAULT_TARIFF_HOUR_RUB = 120.0


def _kv_get(key: str, default: str = "") -> str:
  with _db_lock:
    con = _db()
    try:
      row = con.execute("SELECT v FROM kv WHERE k = ?", (key,)).fetchone()
    finally:
      con.close()
  return str(row["v"]) if row else default


def _tariff_hour_rub() -> float:
  try:
    return max(1.0, float(_kv_get("tariff_hour_rub", "120")))
  except Exception:
    return DEFAULT_TARIFF_HOUR_RUB


def _calc_price_rub(hours: float) -> float:
  return round(max(0.25, float(hours)) * _tariff_hour_rub(), 2)


def _loyalty_points_per_paid_hour() -> int:
  try:
    return max(1, int(float(_kv_get("loyalty_points_per_paid_hour", "50"))))
  except Exception:
    return 50


def _loyalty_points_per_free_hour() -> int:
  try:
    return max(1, int(float(_kv_get("loyalty_points_per_free_hour", "500"))))
  except Exception:
    return 500


def _loyalty_earn_points(hours: float) -> int:
  return int(max(0.25, float(hours)) * _loyalty_points_per_paid_hour())


def _loyalty_redeem_cost(hours: float) -> int:
  return int(math.ceil(max(0.25, float(hours)) * _loyalty_points_per_free_hour()))


def _family_points_balance(con: sqlite3.Connection, family_id: int) -> int:
  row = con.execute(
    "SELECT COALESCE(points_balance, 0) AS b FROM family_accounts WHERE id = ?",
    (int(family_id),),
  ).fetchone()
  return int(row["b"] or 0) if row else 0


def _loyalty_apply_delta(
  con: sqlite3.Connection,
  family_id: int,
  user_id: int,
  delta: int,
  reason: str,
  *,
  booking_id: int | None = None,
  payment_id: int | None = None,
) -> tuple[bool, int, str | None]:
  """Returns (ok, new_balance, error_reason)."""
  delta_i = int(delta)
  if delta_i == 0:
    return True, _family_points_balance(con, family_id), None
  fid = int(family_id)
  cur_bal = _family_points_balance(con, fid)
  new_bal = cur_bal + delta_i
  if new_bal < 0:
    return False, cur_bal, "insufficient_points"
  con.execute(
    "UPDATE family_accounts SET points_balance = ? WHERE id = ?",
    (new_bal, fid),
  )
  con.execute(
    """
    INSERT INTO loyalty_ledger (family_id, user_id, delta, balance_after, reason, booking_id, payment_id, created_ts)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """,
    (fid, int(user_id), delta_i, new_bal, str(reason)[:64], booking_id, payment_id, time.time()),
  )
  return True, new_bal, None


def _loyalty_status(con: sqlite3.Connection, family_id: int, hours: float = 1.0) -> dict[str, Any]:
  bal = _family_points_balance(con, int(family_id))
  redeem_cost = _loyalty_redeem_cost(hours)
  per_free = _loyalty_points_per_free_hour()
  return {
    "balance": bal,
    "points_per_paid_hour": _loyalty_points_per_paid_hour(),
    "points_per_free_hour": per_free,
    "redeem_cost_points": redeem_cost,
    "can_redeem_hours": bal // per_free if per_free else 0,
    "can_redeem": bal >= redeem_cost,
    "earn_on_pay_points": _loyalty_earn_points(hours),
  }


def _traffic_from_counts(free: int, total: int) -> dict[str, Any]:
  if total <= 0:
    return {"level": "unknown", "free": 0, "total": 0, "occupied": 0, "pct_free": 0.0}
  free_i = max(0, int(free))
  total_i = max(0, int(total))
  occ = max(0, total_i - free_i)
  pct = free_i / total_i if total_i else 0.0
  if pct > 0.3:
    level = "green"
  elif pct > 0.1:
    level = "yellow"
  else:
    level = "red"
  return {
    "level": level,
    "free": free_i,
    "total": total_i,
    "occupied": occ,
    "pct_free": round(pct, 4),
  }


def _slot_override_map() -> dict[str, dict[str, Any]]:
  with _db_lock:
    con = _db()
    try:
      rows = con.execute(
        "SELECT slot_id, status, note, updated_ts FROM slot_overrides"
      ).fetchall()
    finally:
      con.close()
  return {str(r["slot_id"]): dict(r) for r in rows}


def _slot_bookable(slot_id: str) -> tuple[bool, str | None]:
  ov = _slot_override_map().get(slot_id)
  if not ov:
    return True, None
  st = str(ov.get("status") or "available").lower()
  if st in ("available", "free", ""):
    return True, None
  return False, st


def _normalize_plate(plate: str) -> str:
  t = str(plate or "").upper().strip()
  for ch in (" ", "-", ".", "_", "\t"):
    t = t.replace(ch, "")
  return t[:32]

def _centroid_norm(points: list[list[float]]) -> tuple[float, float]:
  if not points:
    return 0.0, 0.0
  xs = [p[0] for p in points]
  ys = [p[1] for p in points]
  return float(sum(xs) / len(xs)), float(sum(ys) / len(ys))


def get_slot_model() -> YOLO:
  global _slot_model
  if _slot_model is None:
    _slot_model = YOLO(SLOT_MODEL_PATH)
  return _slot_model


def get_car_model() -> YOLO:
  global _car_model
  if _car_model is None:
    _car_model = YOLO(CAR_MODEL_PATH)
  return _car_model


def _preload_yolo_models() -> None:
  """Load YOLO in background so /api/me/* is not blocked for minutes on first detect."""

  def _run() -> None:
    try:
      get_slot_model()
    except Exception as exc:
      print(f"[Parking Eye] slot model preload failed: {exc}")
    try:
      get_car_model()
    except Exception as exc:
      print(f"[Parking Eye] car model preload failed: {exc}")

  threading.Thread(target=_run, daemon=True).start()


@app.on_event("startup")
def _on_app_startup() -> None:
  _preload_yolo_models()


def _assign_occupancy_by_cars(
  slots: list[dict[str, Any]],
  car_boxes: list[tuple[float, float, float, float]],
  overlap_thresh: float,
) -> list[dict[str, Any]]:
  """
  Determine slot_occupied if any car overlaps the slot polygon enough.
  Uses fast raster overlap on a small grid:
    overlap = area(slot_polygon ∩ car_bbox) / area(slot_polygon)

  This is more stable than bbox∩bbox for slanted/rotated slots, while still fast.
  """
  grid_w = 320
  grid_h = 180

  def clamp01(v: float) -> float:
    return 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)

  def to_px_x(x: float) -> int:
    return int(round(clamp01(float(x)) * (grid_w - 1)))

  def to_px_y(y: float) -> int:
    return int(round(clamp01(float(y)) * (grid_h - 1)))

  def rect_px(b: tuple[float, float, float, float]) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = b
    px1 = to_px_x(min(x1, x2))
    px2 = to_px_x(max(x1, x2))
    py1 = to_px_y(min(y1, y2))
    py2 = to_px_y(max(y1, y2))
    # convert to slicing-exclusive high bound
    return px1, py1, min(grid_w, px2 + 1), min(grid_h, py2 + 1)

  for s in slots:
    pts = s.get("points")
    if not isinstance(pts, list) or len(pts) < 3:
      continue
    poly = []
    for p in pts:
      if not isinstance(p, list) or len(p) != 2:
        continue
      poly.append([to_px_x(float(p[0])), to_px_y(float(p[1]))])
    if len(poly) < 3:
      continue
    mask = np.zeros((grid_h, grid_w), dtype=np.uint8)
    cv2.fillPoly(mask, [np.array(poly, dtype=np.int32)], 1)
    sa = int(mask.sum())
    if sa <= 0:
      continue
    occ = False
    best = 0.0
    for cb in car_boxes:
      x1, y1, x2, y2 = rect_px(cb)
      if x2 <= x1 or y2 <= y1:
        continue
      inter = int(mask[y1:y2, x1:x2].sum())
      r = float(inter / sa)
      if r > best:
        best = r
      if r >= overlap_thresh:
        occ = True
        break
    s["occ_overlap"] = float(best)
    s["label"] = "slot_occupied" if occ else "slot_free"
  return slots


def _get_cfg() -> dict[str, Any]:
  with _cfg_lock:
    return dict(_cfg)


def _set_cfg(patch: dict[str, Any]) -> dict[str, Any]:
  with _cfg_lock:
    if "conf" in patch:
      v = float(patch["conf"])
      _cfg["conf"] = max(0.01, min(0.99, v))
    if "auto_crop" in patch:
      v = str(patch["auto_crop"]).lower().strip()
      if v in ("auto", "off"):
        _cfg["auto_crop"] = v
    if "source_fps" in patch:
      v = int(patch["source_fps"])
      _cfg["source_fps"] = max(1, min(15, v))
    if "client_poll_ms" in patch:
      v = int(patch["client_poll_ms"])
      _cfg["client_poll_ms"] = max(250, min(10_000, v))
    if "use_car_occupancy" in patch:
      _cfg["use_car_occupancy"] = bool(patch["use_car_occupancy"])
    if "car_conf" in patch:
      v = float(patch["car_conf"])
      _cfg["car_conf"] = max(0.01, min(0.99, v))
    if "car_overlap" in patch:
      v = float(patch["car_overlap"])
      _cfg["car_overlap"] = max(0.01, min(0.90, v))
    if "car_classes" in patch:
      v = patch["car_classes"]
      if isinstance(v, list):
        _cfg["car_classes"] = [str(x).lower().strip() for x in v if str(x).strip()][:16]
    return dict(_cfg)


def maybe_crop_focus_region(np_img: np.ndarray) -> tuple[np.ndarray, tuple[int, int, int, int]]:
  """
  Crop out large black borders when the phone camera is pointed at a bright screen.

  Returns:
    cropped_image, (x0, y0, crop_w, crop_h)
  """
  h, w = np_img.shape[:2]
  if _get_cfg().get("auto_crop") == "off":
    return np_img, (0, 0, w, h)

  gray = cv2.cvtColor(np_img, cv2.COLOR_RGB2GRAY)

  # Identify likely "content" pixels. This works well for bright screen content while
  # leaving normal full-frame parking images almost unchanged.
  mask = gray > 20
  ys, xs = np.where(mask)
  if len(xs) == 0 or len(ys) == 0:
    return np_img, (0, 0, w, h)

  x0 = int(xs.min())
  x1 = int(xs.max()) + 1
  y0 = int(ys.min())
  y1 = int(ys.max()) + 1

  crop_w = x1 - x0
  crop_h = y1 - y0

  # If the detected content is too tiny, keep the original frame.
  if crop_w < int(w * 0.35) or crop_h < int(h * 0.35):
    return np_img, (0, 0, w, h)

  # Expand a bit so we don't cut off useful edges.
  pad_x = max(8, int(crop_w * 0.03))
  pad_y = max(8, int(crop_h * 0.03))
  x0 = max(0, x0 - pad_x)
  y0 = max(0, y0 - pad_y)
  x1 = min(w, x1 + pad_x)
  y1 = min(h, y1 + pad_y)

  cropped = np_img[y0:y1, x0:x1]
  return cropped, (x0, y0, x1 - x0, y1 - y0)


@app.get("/api/health")
def health() -> dict[str, Any]:
  cfg = _get_cfg()
  return {
    "ok": True,
    "model": SLOT_MODEL_PATH,
    "car_model": CAR_MODEL_PATH,
    "mode": "slots_seg",
    "config": cfg,
    "auth": {"operator": bool(OPERATOR_KEY), "client": bool(CLIENT_KEY)},
  }


@app.get("/api/config")
def get_config(req: Request) -> JSONResponse:
  if not _require_key(req, OPERATOR_KEY):
    return JSONResponse({"ok": False, "reason": "unauthorized"}, status_code=401)
  return JSONResponse({"ok": True, "config": _get_cfg()})


@app.post("/api/config")
async def post_config(req: Request) -> JSONResponse:
  if not _require_key(req, OPERATOR_KEY):
    return JSONResponse({"ok": False, "reason": "unauthorized"}, status_code=401)
  try:
    data = await req.json()
    if not isinstance(data, dict):
      raise ValueError("body must be json object")
  except Exception:
    return JSONResponse({"ok": False, "reason": "invalid_json"}, status_code=400)
  cfg = _set_cfg(data)
  return JSONResponse({"ok": True, "config": cfg})


def _count_slots(slots: list[dict[str, Any]]) -> dict[str, int]:
  total = 0
  occ = 0
  for s in slots:
    if not s or not isinstance(s, dict):
      continue
    label = str(s.get("label", "")).lower()
    if label not in ("slot_free", "slot_occupied"):
      continue
    total += 1
    if label == "slot_occupied":
      occ += 1
  return {"total": total, "occupied": occ, "free": max(0, total - occ)}


def _update_latest(frame_jpeg: bytes, slots: list[dict[str, Any]], ts: float, dt_ms: int) -> int:
  global _last_frame_jpeg, _last_slots, _last_ts, _last_dt_ms, _event_id
  with _state_lock:
    _last_frame_jpeg = frame_jpeg
    _last_slots = slots
    _last_ts = ts
    _last_dt_ms = dt_ms
    _event_id += 1
    eid = _event_id
  counts = _count_slots(slots)
  with _stats_lock:
    _stats_window.append({"ts": ts, "dt_ms": dt_ms, **counts})

  # Persist observation off the hot path (detect thread must not block pay/bookings on _db_lock).
  def _persist_obs() -> None:
    try:
      with _db_lock:
        con = _db()
        try:
          con.execute(
            "INSERT INTO observations (ts, dt_ms, total, free, occupied, slots_json) VALUES (?,?,?,?,?,?)",
            (ts, dt_ms, counts["total"], counts["free"], counts["occupied"], json.dumps(slots, ensure_ascii=False)),
          )
          con.commit()
        finally:
          con.close()
    except Exception:
      pass

  threading.Thread(target=_persist_obs, daemon=True).start()
  return eid


@app.post("/api/ingest")
async def ingest(req: Request, file: UploadFile = File(...)) -> JSONResponse:
  if not _require_key(req, OPERATOR_KEY):
    return JSONResponse({"ok": False, "reason": "unauthorized"}, status_code=401)
  # Alias to detect() for plan's ingest/read split.
  return await detect(file)


@app.post("/api/vehicle/checkin")
async def vehicle_checkin(req: Request) -> JSONResponse:
  """
  Store vehicle parameters (from client) and create a visit session.
  Body example:
    { plate, kind:'car|suv|truck', size:'compact|normal|large', is_ev:bool, is_disabled:bool, notes }
  """
  if not _require_key(req, CLIENT_KEY):
    return JSONResponse({"ok": False, "reason": "unauthorized"}, status_code=401)
  try:
    data = await req.json()
    if not isinstance(data, dict):
      raise ValueError()
  except Exception:
    return JSONResponse({"ok": False, "reason": "invalid_json"}, status_code=400)

  plate = str(data.get("plate") or "").strip()[:32] or None
  kind = str(data.get("kind") or "car").strip()[:16]
  size = str(data.get("size") or "normal").strip()[:16]
  is_ev = 1 if bool(data.get("is_ev")) else 0
  is_disabled = 1 if bool(data.get("is_disabled")) else 0
  notes = str(data.get("notes") or "").strip()[:200] or None
  ts = time.time()

  with _db_lock:
    con = _db()
    try:
      cur = con.cursor()
      cur.execute(
        "INSERT INTO vehicles (created_ts, plate, kind, size, is_ev, is_disabled, notes) VALUES (?,?,?,?,?,?,?)",
        (ts, plate, kind, size, is_ev, is_disabled, notes),
      )
      vehicle_id = int(cur.lastrowid)
      cur.execute(
        "INSERT INTO visits (ts, vehicle_id, source, meta_json) VALUES (?,?,?,?)",
        (ts, vehicle_id, "client", json.dumps({"ip": _client_ip(req)}, ensure_ascii=False)),
      )
      visit_id = int(cur.lastrowid)
      con.commit()
    finally:
      con.close()

  return JSONResponse({"ok": True, "visit_id": visit_id, "vehicle_id": vehicle_id})


@app.get("/api/parking/state")
def parking_state(req: Request) -> JSONResponse:
  if not _require_key(req, CLIENT_KEY):
    return JSONResponse({"ok": False, "reason": "unauthorized"}, status_code=401)
  # Read-only endpoint for client/operator.
  with _state_lock:
    if _last_ts is None:
      return JSONResponse({"ok": False, "reason": "no_data_yet"}, status_code=404)
    payload = {
      "ok": True,
      "ts": _last_ts,
      "dt_ms": _last_dt_ms,
      "event_id": _event_id,
      "slots": _last_slots,
      "counts": _count_slots(_last_slots),
    }
  return JSONResponse(payload)


def _majority_label(history: deque[str]) -> str:
  c = {"slot_free": 0, "slot_occupied": 0}
  for h in history:
    if h in c:
      c[h] += 1
  return "slot_occupied" if c["slot_occupied"] > c["slot_free"] else "slot_free"


def _track_and_debounce(slots: list[dict[str, Any]]) -> list[dict[str, Any]]:
  """
  Assign stable ids by centroid proximity and debounce labels via majority vote.
  Mutates slot dicts by adding: id, centroid, label_raw, label.
  """
  global _next_slot_id
  # Extract detections with centroid
  dets: list[tuple[int, float, float]] = []  # (idx, cx, cy)
  for i, s in enumerate(slots):
    pts = s.get("points")
    if isinstance(pts, list) and len(pts) >= 3:
      cx, cy = _centroid_norm(pts)
      dets.append((i, cx, cy))

  with _track_lock:
    # Build list of existing tracks
    existing = []
    for tid, t in _tracks.items():
      existing.append((tid, float(t.get("cx", 0.0)), float(t.get("cy", 0.0))))

    used_tracks: set[str] = set()

    def dist2(ax: float, ay: float, bx: float, by: float) -> float:
      dx = ax - bx
      dy = ay - by
      return dx * dx + dy * dy

    # Greedy matching by nearest distance
    matches: dict[int, str] = {}
    for i, cx, cy in dets:
      best_tid = None
      best_d = 1e9
      for tid, tx, ty in existing:
        if tid in used_tracks:
          continue
        d = dist2(cx, cy, tx, ty)
        if d < best_d:
          best_d = d
          best_tid = tid
      # Threshold in normalized space (~0.02 is fairly strict)
      if best_tid is not None and best_d < (0.02 * 0.02):
        matches[i] = best_tid
        used_tracks.add(best_tid)

    # Assign ids / update tracks
    now = time.time()
    for i, cx, cy in dets:
      s = slots[i]
      raw_label = str(s.get("label", "")).lower()
      if raw_label not in ("slot_free", "slot_occupied"):
        raw_label = "slot_occupied"

      tid = matches.get(i)
      if tid is None:
        tid = f"slot_{_next_slot_id}"
        _next_slot_id += 1
        _tracks[tid] = {"cx": cx, "cy": cy, "history": deque(maxlen=5), "last_seen": now}

      t = _tracks.get(tid)
      if t is None:
        t = {"cx": cx, "cy": cy, "history": deque(maxlen=5), "last_seen": now}
        _tracks[tid] = t

      t["cx"] = cx
      t["cy"] = cy
      t["last_seen"] = now
      hist: deque[str] = t["history"]
      hist.append(raw_label)
      debounced = _majority_label(hist)

      s["id"] = tid
      s["centroid"] = [cx, cy]
      s["label_raw"] = raw_label
      s["label"] = debounced

    # Garbage collect old tracks
    to_del = []
    for tid, t in _tracks.items():
      if now - float(t.get("last_seen", now)) > 10.0:
        to_del.append(tid)
    for tid in to_del:
      _tracks.pop(tid, None)

  return slots


@app.get("/api/latest")
def latest(req: Request) -> JSONResponse:
  if not _require_key(req, CLIENT_KEY):
    return JSONResponse({"ok": False, "reason": "unauthorized"}, status_code=401)
  if not _rate_limit(req, "latest", limit=60, window_s=10.0):
    return JSONResponse({"ok": False, "reason": "rate_limited"}, status_code=429)
  """
  Latest frame + slots (for client mode).
  Returns base64 JPEG to keep it simple for demos.
  """
  with _state_lock:
    if _last_frame_jpeg is None or _last_ts is None:
      return JSONResponse({"ok": False, "reason": "no_data_yet"}, status_code=404)
    jpeg_b64 = base64.b64encode(_last_frame_jpeg).decode("ascii")
    payload = {
      "ok": True,
      "ts": _last_ts,
      "dt_ms": _last_dt_ms,
      "event_id": _event_id,
      "image_jpeg_base64": jpeg_b64,
      "slots": _last_slots,
      "counts": _count_slots(_last_slots),
    }
  return JSONResponse(payload)


@app.get("/api/latest.jpg")
def latest_jpg(req: Request) -> Response:
  if not _require_key(req, CLIENT_KEY):
    return Response(status_code=401)
  if not _rate_limit(req, "latestjpg", limit=120, window_s=10.0):
    return Response(status_code=429)
  with _state_lock:
    if _last_frame_jpeg is None:
      return Response(status_code=404)
    data = _last_frame_jpeg
  return Response(content=data, media_type="image/jpeg")


@app.get("/api/stats")
def stats(req: Request) -> JSONResponse:
  if not _require_key(req, OPERATOR_KEY):
    return JSONResponse({"ok": False, "reason": "unauthorized"}, status_code=401)
  with _stats_lock:
    rows = list(_stats_window)
  if not rows:
    return JSONResponse({"ok": False, "reason": "no_data_yet"}, status_code=404)
  # Simple aggregates
  avg_dt = int(sum(r["dt_ms"] for r in rows) / max(1, len(rows)))
  avg_free = float(sum(r["free"] for r in rows) / max(1, len(rows)))
  last = rows[-1]
  return JSONResponse(
    {
      "ok": True,
      "window": len(rows),
      "avg_dt_ms": avg_dt,
      "avg_free": avg_free,
      "last": last,
    }
  )


@app.post("/api/snapshot")
def snapshot(req: Request) -> JSONResponse:
  if not _require_key(req, OPERATOR_KEY):
    return JSONResponse({"ok": False, "reason": "unauthorized"}, status_code=401)
  with _state_lock:
    if _last_frame_jpeg is None or _last_ts is None:
      return JSONResponse({"ok": False, "reason": "no_data_yet"}, status_code=404)
    frame = _last_frame_jpeg
    slots = list(_last_slots)
    ts = float(_last_ts)
    dt = _last_dt_ms
    eid = _event_id

  stamp = datetime.fromtimestamp(ts).strftime("%Y%m%d_%H%M%S")
  name = f"snap_{stamp}_{eid}"
  jpg_name = f"{name}.jpg"
  json_name = f"{name}.json"
  jpg_path = os.path.join(SNAP_DIR, jpg_name)
  json_path = os.path.join(SNAP_DIR, json_name)

  with open(jpg_path, "wb") as f:
    f.write(frame)
  with open(json_path, "w", encoding="utf-8") as f:
    json.dump({"ts": ts, "dt_ms": dt, "event_id": eid, "slots": slots, "counts": _count_slots(slots)}, f, ensure_ascii=False)

  item = {
    "name": name,
    "ts": ts,
    "event_id": eid,
    "jpg": f"/snapshots/{jpg_name}",
    "json": f"/snapshots/{json_name}",
    "counts": _count_slots(slots),
  }
  with _snap_lock:
    _snap_index.appendleft(item)

  # Persist snapshot metadata
  try:
    counts = item["counts"]
    with _db_lock:
      con = _db()
      try:
        con.execute(
          "INSERT INTO snapshots (ts, event_id, name, jpg_path, json_path, total, free, occupied) VALUES (?,?,?,?,?,?,?,?)",
          (ts, eid, name, jpg_name, json_name, counts["total"], counts["free"], counts["occupied"]),
        )
        con.commit()
      finally:
        con.close()
  except Exception:
    pass
  return JSONResponse({"ok": True, "snapshot": item})


@app.get("/api/snapshots")
def snapshots(req: Request) -> JSONResponse:
  if not _require_key(req, OPERATOR_KEY):
    return JSONResponse({"ok": False, "reason": "unauthorized"}, status_code=401)
  with _snap_lock:
    items = list(_snap_index)
  return JSONResponse({"ok": True, "snapshots": items})


@app.get("/api/stream")
def stream(req: Request) -> StreamingResponse:
  if not _require_key(req, CLIENT_KEY):
    return StreamingResponse(iter(["event: error\ndata: unauthorized\n\n"]), media_type="text/event-stream")
  """
  Server-Sent Events stream of occupancy + event_id.
  Clients can use this to refresh /api/latest.jpg + /api/latest occasionally.
  """

  def gen():
    last_sent = 0
    while True:
      with _state_lock:
        eid = _event_id
        ts = _last_ts
        slots = _last_slots
        dt = _last_dt_ms
      if eid != 0 and eid != last_sent and ts is not None:
        last_sent = eid
        data = {
          "event_id": eid,
          "ts": ts,
          "dt_ms": dt,
          "counts": _count_slots(slots),
        }
        yield f"id: {eid}\n"
        yield "event: update\n"
        yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
      time.sleep(0.5)

  return StreamingResponse(gen(), media_type="text/event-stream")

def _detect_from_raw(raw: bytes) -> dict[str, Any]:
  """CPU-heavy YOLO path — run via run_in_threadpool so /api/me/* stays responsive."""
  t0 = time.perf_counter()
  img = Image.open(io.BytesIO(raw)).convert("RGB")
  np_img = np.array(img)  # HWC RGB
  infer_img, (crop_x, crop_y, crop_w, crop_h) = maybe_crop_focus_region(np_img)

  slot_model = get_slot_model()
  car_model = get_car_model()

  cfg = _get_cfg()
  # Run segmentation model; we'll return polygons.
  results = slot_model.predict(infer_img, imgsz=960, conf=float(cfg.get("conf", CONF_THRES)), verbose=False)
  r = results[0]

  slots: list[dict[str, Any]] = []
  names = getattr(r, "names", {}) or {}

  # Ultralytics segmentation outputs:
  # - r.masks.xy: list of Nx2 arrays in pixel coords
  # - r.boxes.cls/conf: per instance
  if getattr(r, "masks", None) is not None and getattr(r.masks, "xy", None) is not None:
    H, W = np_img.shape[0], np_img.shape[1]
    polys = r.masks.xy
    cls = r.boxes.cls.cpu().numpy().astype(int) if r.boxes is not None else []
    conf = r.boxes.conf.cpu().numpy() if r.boxes is not None else []

    for i, poly in enumerate(polys):
      if poly is None or len(poly) < 3:
        continue
      c = int(cls[i]) if i < len(cls) else -1
      cf = float(conf[i]) if i < len(conf) else 0.0
      label = str(names.get(c, c)).lower()

      # For slot geometry we accept both slot_free/slot_occupied labels.
      if label in SLOT_FREE:
        out_label = "slot_free"
      elif label in SLOT_OCC:
        out_label = "slot_occupied"
      else:
        # If custom model has different naming, treat all masks as potential slots.
        out_label = "slot_free"

      # Convert pixel polygon -> normalized 0..1 top-left origin
      pts = []
      for x, y in poly:
        px = float((x + crop_x) / W)
        py = float((y + crop_y) / H)
        pts.append([px, py])
      slots.append({"label": out_label, "conf": cf, "points": pts})

  # Vehicle detection + tracking (ByteTrack) for occupancy assignment
  cars: list[dict[str, Any]] = []
  car_boxes_norm: list[tuple[float, float, float, float]] = []
  if bool(cfg.get("use_car_occupancy", True)):
    try:
      car_res = car_model.track(
        infer_img,
        imgsz=960,
        conf=float(cfg.get("car_conf", 0.25)),
        persist=True,
        tracker="bytetrack.yaml",
        verbose=False,
      )
      cr = car_res[0]
      names = getattr(cr, "names", {}) or {}
      allow = set(str(x).lower() for x in (cfg.get("car_classes") or []))
      if cr.boxes is not None:
        xyxy = cr.boxes.xyxy.cpu().numpy()
        ccls = cr.boxes.cls.cpu().numpy().astype(int)
        cconf = cr.boxes.conf.cpu().numpy()
        tids = cr.boxes.id.cpu().numpy().astype(int) if getattr(cr.boxes, "id", None) is not None else None
        for i in range(len(xyxy)):
          lab = str(names.get(int(ccls[i]), ccls[i])).lower()
          if allow and lab not in allow:
            continue
          x1, y1, x2, y2 = [float(v) for v in xyxy[i]]
          # Convert from infer_img pixels -> normalized in original frame
          bx1 = float((x1 + crop_x) / W)
          by1 = float((y1 + crop_y) / H)
          bx2 = float((x2 + crop_x) / W)
          by2 = float((y2 + crop_y) / H)
          box = (bx1, by1, bx2, by2)
          car_boxes_norm.append(box)
          cars.append(
            {
              "label": lab,
              "conf": float(cconf[i]),
              "box": [bx1, by1, bx2, by2],
              "track_id": int(tids[i]) if tids is not None else None,
            }
          )
    except Exception:
      # Don't fail whole request if tracking breaks
      pass

  if car_boxes_norm:
    slots = _assign_occupancy_by_cars(slots, car_boxes_norm, float(cfg.get("car_overlap", 0.12)))

  # stage3: stable ids + debounce
  slots = _track_and_debounce(slots)

  dt_ms = int((time.perf_counter() - t0) * 1000)
  ts = time.time()
  _update_latest(raw, slots, ts, dt_ms)
  return {"slots": slots, "cars": cars, "dt_ms": dt_ms, "ts": ts}


@app.post("/api/detect")
async def detect(file: UploadFile = File(...)) -> JSONResponse:
  """
  Accepts an image frame (jpg/png) and returns segmented parking slots.

  Returns segmented parking slots as polygons in normalized coords (0..1), origin top-left:
  { slots: [ {label, conf, points:[[x,y],...]} ] }
  """
  raw = await file.read()
  try:
    payload = await run_in_threadpool(_detect_from_raw, raw)
  except Exception as exc:
    return JSONResponse({"ok": False, "reason": "detect_failed", "detail": str(exc)}, status_code=500)
  return JSONResponse(payload)


@app.get("/api/auth/session")
def auth_session(pe_session: str | None = Cookie(default=None)) -> dict[str, Any]:
  u = _auth_row_from_cookie(pe_session)
  if not u:
    return {"ok": True, "user": None}
  uid = int(u["id"])
  with _db_lock:
    con = _db()
    try:
      family = _family_public(con, uid)
    finally:
      con.close()
  return {"ok": True, "user": _user_public(u, family)}


@app.post("/api/auth/register")
async def auth_register(req: Request) -> JSONResponse:
  if not REGISTRATION_ENABLED:
    return JSONResponse({"ok": False, "reason": "registration_disabled"}, status_code=403)
  if not _rate_limit(req, "auth_register", 8, 600.0):
    return JSONResponse({"ok": False, "reason": "rate_limited"}, status_code=429)
  try:
    body = await req.json()
    if not isinstance(body, dict):
      raise ValueError("bad")
  except Exception:
    return JSONResponse({"ok": False, "reason": "invalid_json"}, status_code=400)
  username = _normalize_username(str(body.get("username") or ""))
  password = str(body.get("password") or "")
  display_name = str(body.get("display_name") or "").strip()
  family_invite_raw = str(
    body.get("family_invite") or body.get("invite_code") or body.get("family_code") or ""
  ).strip()
  if not username:
    return JSONResponse({"ok": False, "reason": "invalid_username"}, status_code=400)
  if not _validate_password(password):
    return JSONResponse({"ok": False, "reason": "weak_password"}, status_code=400)
  if not display_name:
    display_name = username.split("@")[0].replace(".", " ").replace("_", " ").title()
  if len(display_name) > 80:
    return JSONResponse({"ok": False, "reason": "invalid_display_name"}, status_code=400)
  invite_code = _normalize_family_invite(family_invite_raw) if family_invite_raw else None
  if family_invite_raw and not invite_code:
    return JSONResponse({"ok": False, "reason": "invalid_family_invite"}, status_code=400)
  pw_hash = _hash_password_plain(password)
  ts = time.time()
  with _db_lock:
    con = _db()
    try:
      exists = con.execute("SELECT 1 FROM users WHERE username = ? COLLATE NOCASE", (username,)).fetchone()
      if exists:
        return JSONResponse({"ok": False, "reason": "username_taken"}, status_code=409)
      cur = con.execute(
        """
        INSERT INTO users (username, password_hash, display_name, role, active, created_ts, family_id, family_role)
        VALUES (?,?,?,?,?,?,?,?)
        """,
        (username, pw_hash, display_name, "user", 1, ts, None, None),
      )
      user_id = int(cur.lastrowid)
      if invite_code:
        fam = con.execute(
          "SELECT id FROM family_accounts WHERE invite_code = ?",
          (invite_code,),
        ).fetchone()
        if not fam:
          return JSONResponse({"ok": False, "reason": "family_invite_not_found"}, status_code=404)
        con.execute(
          "UPDATE users SET family_id = ?, family_role = 'member' WHERE id = ?",
          (int(fam["id"]), user_id),
        )
      else:
        fid = _create_family_account(con, user_id, f"Семья {display_name[:40]}")
        con.execute(
          "UPDATE users SET family_id = ?, family_role = 'owner' WHERE id = ?",
          (fid, user_id),
        )
      con.commit()
    finally:
      con.close()
  return _issue_session_response(user_id, username, display_name, "user")


@app.post("/api/auth/login")
async def auth_login(req: Request) -> JSONResponse:
  if not _rate_limit(req, "auth_login", 20, 300.0):
    return JSONResponse({"ok": False, "reason": "rate_limited"}, status_code=429)
  try:
    body = await req.json()
    if not isinstance(body, dict):
      raise ValueError("bad")
  except Exception:
    return JSONResponse({"ok": False, "reason": "invalid_json"}, status_code=400)
  username = _normalize_username(str(body.get("username") or ""))
  password = str(body.get("password") or "")
  if not username or not password:
    return JSONResponse({"ok": False, "reason": "bad_credentials"}, status_code=401)
  with _db_lock:
    con = _db()
    try:
      row = con.execute(
        "SELECT id, password_hash, display_name, role, active, block_reason FROM users WHERE username = ? COLLATE NOCASE",
        (username,),
      ).fetchone()
    finally:
      con.close()
  if not row:
    return JSONResponse({"ok": False, "reason": "bad_credentials"}, status_code=401)
  if not int(row["active"] or 0):
    br = ""
    try:
      br = str(row["block_reason"] or "").strip()
    except Exception:
      pass
    return JSONResponse(
      {"ok": False, "reason": "blocked", "block_reason": br or None},
      status_code=403,
    )
  if not _verify_password_plain(password, str(row["password_hash"])):
    return JSONResponse({"ok": False, "reason": "bad_credentials"}, status_code=401)
  return _issue_session_response(int(row["id"]), username, str(row["display_name"]), str(row["role"]))


@app.post("/api/auth/logout")
def auth_logout(pe_session: str | None = Cookie(default=None)) -> JSONResponse:
  if pe_session:
    with _db_lock:
      con = _db()
      try:
        con.execute("DELETE FROM sessions WHERE token_hash = ?", (_session_digest(pe_session),))
        con.commit()
      finally:
        con.close()
  r = JSONResponse({"ok": True})
  r.delete_cookie(SESSION_COOKIE, path="/")
  return r


@app.get("/api/auth/me")
def auth_me(user: Annotated[dict[str, Any], Depends(require_login)]) -> dict[str, Any]:
  uid = int(user["id"])
  with _db_lock:
    con = _db()
    try:
      family = _family_public(con, uid)
    finally:
      con.close()
  return {"ok": True, "user": _user_public(user, family)}


@app.get("/api/me/loyalty")
def me_loyalty(user: Annotated[dict[str, Any], Depends(require_login)]) -> JSONResponse:
  uid = int(user["id"])
  fid = _user_family_id(user)
  with _db_lock:
    con = _db()
    try:
      if fid is None:
        fid = _ensure_user_has_family(con, uid, str(user.get("display_name") or "User"))
      status = _loyalty_status(con, int(fid), 1.0)
    finally:
      con.close()
  return JSONResponse({"ok": True, "loyalty": status})


@app.get("/api/me/family")
def me_family(user: Annotated[dict[str, Any], Depends(require_login)]) -> dict[str, Any]:
  uid = int(user["id"])
  with _db_lock:
    con = _db()
    try:
      family = _family_public(con, uid)
    finally:
      con.close()
  if not family:
    return JSONResponse({"ok": False, "reason": "no_family"}, status_code=404)
  return {"ok": True, "family": family}


@app.post("/api/me/family/invite")
def me_family_invite_refresh(user: Annotated[dict[str, Any], Depends(require_login)]) -> JSONResponse:
  uid = int(user["id"])
  with _db_lock:
    con = _db()
    try:
      fr = _user_family_row(con, uid)
      if not fr:
        return JSONResponse({"ok": False, "reason": "no_family"}, status_code=404)
      is_owner = int(fr.get("owner_user_id") or 0) == uid or str(fr.get("family_role") or "") == "owner"
      if not is_owner:
        return JSONResponse({"ok": False, "reason": "family_owner_required"}, status_code=403)
      fid = int(fr["family_id"])
      for _ in range(12):
        code = _new_family_invite_code()
        try:
          con.execute("UPDATE family_accounts SET invite_code = ? WHERE id = ?", (code, fid))
          con.commit()
          return JSONResponse({"ok": True, "invite_code": code})
        except sqlite3.IntegrityError:
          continue
    finally:
      con.close()
  return JSONResponse({"ok": False, "reason": "invite_collision"}, status_code=500)


@app.post("/api/auth/change-password")
async def auth_change_password(
  user: Annotated[dict[str, Any], Depends(require_login)], req: Request
) -> JSONResponse:
  try:
    body = await req.json()
    if not isinstance(body, dict):
      raise ValueError()
  except Exception:
    return JSONResponse({"ok": False, "reason": "invalid_json"}, status_code=400)
  current = str(body.get("current_password") or "")
  new_pw = str(body.get("new_password") or "")
  if not current or not _validate_password(new_pw):
    return JSONResponse({"ok": False, "reason": "weak_password"}, status_code=400)
  uid = int(user["id"])
  with _db_lock:
    con = _db()
    try:
      row = con.execute("SELECT password_hash FROM users WHERE id = ?", (uid,)).fetchone()
      if not row or not _verify_password_plain(current, str(row["password_hash"])):
        return JSONResponse({"ok": False, "reason": "bad_credentials"}, status_code=401)
      con.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (_hash_password_plain(new_pw), uid),
      )
      con.commit()
    finally:
      con.close()
  return JSONResponse({"ok": True})


def _user_family_id(user: dict[str, Any]) -> int | None:
  fid = user.get("family_id")
  return int(fid) if fid is not None else None


@app.get("/api/me/overview")
def me_overview(user: Annotated[dict[str, Any], Depends(require_login)]) -> dict[str, Any]:
  uid = int(user["id"])
  fid = _user_family_id(user)
  now = time.time()
  scope_sql, scope_args = _booking_access_sql(fid, uid, "b")
  with _db_lock:
    con = _db()
    try:
      active_n = int(
        con.execute(
          f"SELECT COUNT(*) AS c FROM bookings b WHERE {scope_sql} AND b.status = 'active' AND b.end_ts > ?",
          (*scope_args, now),
        ).fetchone()["c"]
      )
      next_row = con.execute(
        f"""
        SELECT b.id, b.slot_id, b.start_ts, b.end_ts, b.status
        FROM bookings b
        WHERE {scope_sql} AND b.status = 'active' AND b.end_ts > ?
        ORDER BY b.end_ts ASC LIMIT 1
        """,
        (*scope_args, now),
      ).fetchone()
    finally:
      con.close()
  next_booking = dict(next_row) if next_row else None
  parking: dict[str, Any] = {"total": 0, "free": 0, "occupied": 0, "ts": None, "live": False}
  with _state_lock:
    if _last_slots:
      c = _count_slots(list(_last_slots))
      parking = {
        "total": int(c["total"]),
        "free": int(c["free"]),
        "occupied": int(c["occupied"]),
        "ts": float(_last_ts) if _last_ts is not None else None,
        "live": True,
      }
      parking["traffic"] = _traffic_from_counts(int(c["free"]), int(c["total"]))
  loyalty: dict[str, Any] | None = None
  if fid is not None:
    with _db_lock:
      con = _db()
      try:
        loyalty = _loyalty_status(con, int(fid), 1.0)
      finally:
        con.close()
  return {
    "ok": True,
    "bookings_active": active_n,
    "next_booking": next_booking,
    "parking": parking,
    "tariff_hour_rub": _tariff_hour_rub(),
    "loyalty": loyalty,
  }


@app.get("/api/me/bookings")
def me_bookings_list(user: Annotated[dict[str, Any], Depends(require_login)]) -> dict[str, Any]:
  uid = int(user["id"])
  fid = _user_family_id(user)
  scope_sql, scope_args = _booking_access_sql(fid, uid, "b")
  with _db_lock:
    con = _db()
    try:
      rows = con.execute(
        f"""
        SELECT b.id, b.slot_id, b.start_ts, b.end_ts, b.status, b.note, b.created_ts, b.plate, b.user_id,
               u.display_name AS booked_by_name, u.username AS booked_by_username,
               (SELECT COUNT(*) FROM payments p WHERE p.booking_id = b.id) AS paid_n,
               (SELECT COALESCE(SUM(p.amount_rub), 0) FROM payments p WHERE p.booking_id = b.id) AS paid_sum,
               (SELECT p.receipt_id FROM payments p WHERE p.booking_id = b.id
                ORDER BY p.created_ts DESC LIMIT 1) AS last_receipt_id,
               (SELECT COALESCE(MAX(p.paid_with_points), 0) FROM payments p WHERE p.booking_id = b.id) AS paid_with_points
        FROM bookings b
        LEFT JOIN users u ON u.id = b.user_id
        WHERE {scope_sql}
        ORDER BY b.created_ts DESC
        """,
        tuple(scope_args),
      ).fetchall()
    finally:
      con.close()
  now = time.time()
  enriched = []
  for r in rows:
    d = dict(r)
    d["remaining_s"] = max(0.0, float(d["end_ts"]) - now) if str(d["status"]) == "active" else 0.0
    hours = max(0.25, (float(d["end_ts"]) - float(d["start_ts"])) / 3600.0)
    d["price_estimate_rub"] = _calc_price_rub(hours)
    d["paid_n"] = int(d.get("paid_n") or 0)
    paid_sum = d.get("paid_sum")
    d["paid_sum"] = float(paid_sum) if paid_sum is not None else 0.0
    enriched.append(d)
  return {"ok": True, "bookings": enriched}


@app.post("/api/me/bookings")
async def me_bookings_create(user: Annotated[dict[str, Any], Depends(require_login)], req: Request) -> JSONResponse:
  try:
    body = await req.json()
    if not isinstance(body, dict):
      raise ValueError()
  except Exception:
    return JSONResponse({"ok": False, "reason": "invalid_json"}, status_code=400)
  slot_id = str(body.get("slot_id") or "").strip()[:64]
  if not slot_id:
    return JSONResponse({"ok": False, "reason": "slot_id_required"}, status_code=400)
  bookable, ov_st = _slot_bookable(slot_id)
  if not bookable:
    return JSONResponse(
      {"ok": False, "reason": "slot_unavailable", "override_status": ov_st},
      status_code=409,
    )
  try:
    hours = float(body.get("hours") if body.get("hours") is not None else 3)
  except Exception:
    hours = 3.0
  hours = max(0.25, min(72.0, hours))
  note = str(body.get("note") or "").strip()[:200] or None
  plate = str(body.get("plate") or "").strip()[:24] or None
  redeem_points = bool(body.get("redeem_points"))
  price_rub = _calc_price_rub(hours)
  now = time.time()
  end_ts = now + hours * 3600.0
  uid = int(user["id"])
  fid = _user_family_id(user)
  with _db_lock:
    con = _db()
    try:
      if fid is None:
        fid = _ensure_user_has_family(con, uid, str(user.get("display_name") or "User"))
      fid_i = int(fid)
      if redeem_points:
        cost = _loyalty_redeem_cost(hours)
        if _family_points_balance(con, fid_i) < cost:
          return JSONResponse(
            {
              "ok": False,
              "reason": "insufficient_points",
              "balance": _family_points_balance(con, fid_i),
              "redeem_cost_points": cost,
            },
            status_code=409,
          )
      clash = con.execute(
        """
        SELECT id FROM bookings
        WHERE slot_id = ? AND status = 'active' AND start_ts < ? AND end_ts > ?
        LIMIT 1
        """,
        (slot_id, end_ts, now),
      ).fetchone()
      if clash:
        return JSONResponse({"ok": False, "reason": "slot_busy"}, status_code=409)
      cur = con.cursor()
      cur.execute(
        """
        INSERT INTO bookings (user_id, family_id, slot_id, start_ts, end_ts, status, note, created_ts, plate)
        VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?)
        """,
        (uid, int(fid), slot_id, now, end_ts, note, now, plate),
      )
      bid = int(cur.lastrowid)
      paid_with_points = False
      points_spent = 0
      if redeem_points:
        cost = _loyalty_redeem_cost(hours)
        ok_pts, _, pts_err = _loyalty_apply_delta(
          con, fid_i, uid, -cost, "redeem_booking", booking_id=bid
        )
        if not ok_pts:
          con.execute("UPDATE bookings SET status = 'cancelled' WHERE id = ?", (bid,))
          con.commit()
          return JSONResponse({"ok": False, "reason": pts_err or "insufficient_points"}, status_code=409)
        receipt_id = f"PE-PTS-{int(now)}-{bid}"
        con.execute(
          """
          INSERT INTO payments (user_id, family_id, booking_id, amount_rub, status, receipt_id, created_ts, points_earned, paid_with_points)
          VALUES (?, ?, ?, 0, 'paid', ?, ?, 0, 1)
          """,
          (uid, fid_i, bid, receipt_id, now),
        )
        paid_with_points = True
        points_spent = cost
      con.commit()
    finally:
      con.close()
  out: dict[str, Any] = {
    "ok": True,
    "booking_id": bid,
    "price_rub": 0 if redeem_points else price_rub,
    "end_ts": end_ts,
    "hours": hours,
    "paid_with_points": paid_with_points,
  }
  if redeem_points:
    out["points_spent"] = points_spent
    out["message"] = f"Место забронировано за {points_spent} баллов."
  return JSONResponse(out)


@app.delete("/api/me/bookings/{booking_id}")
def me_booking_cancel(booking_id: int, user: Annotated[dict[str, Any], Depends(require_login)]) -> JSONResponse:
  uid = int(user["id"])
  fid = _user_family_id(user)
  scope_sql, scope_args = _booking_access_sql(fid, uid, "b")
  with _db_lock:
    con = _db()
    try:
      row = con.execute(
        f"SELECT b.id, b.status FROM bookings b WHERE b.id = ? AND {scope_sql}",
        (booking_id, *scope_args),
      ).fetchone()
      if not row:
        return JSONResponse({"ok": False, "reason": "not_found"}, status_code=404)
      if str(row["status"]) != "active":
        return JSONResponse({"ok": False, "reason": "not_active"}, status_code=400)
      con.execute("UPDATE bookings SET status = 'cancelled' WHERE id = ?", (booking_id,))
      con.commit()
    finally:
      con.close()
  return JSONResponse({"ok": True})


@app.get("/api/admin/users")
def admin_users_list(_admin: Annotated[dict[str, Any], Depends(require_admin)]) -> dict[str, Any]:
  with _db_lock:
    con = _db()
    try:
      rows = con.execute(
        "SELECT id, username, display_name, role, active, block_reason, created_ts FROM users ORDER BY id ASC"
      ).fetchall()
    finally:
      con.close()
  return {"ok": True, "users": [dict(r) for r in rows]}


@app.patch("/api/admin/users/{user_id}")
async def admin_user_patch(
  user_id: int,
  admin: Annotated[dict[str, Any], Depends(require_admin)],
  req: Request,
) -> JSONResponse:
  if user_id == int(admin["id"]):
    pass
  try:
    patch = await req.json()
    if not isinstance(patch, dict):
      raise ValueError()
  except Exception:
    return JSONResponse({"ok": False, "reason": "invalid_json"}, status_code=400)
  if user_id == int(admin["id"]) and patch.get("active") is False:
    return JSONResponse({"ok": False, "reason": "cannot_deactivate_self"}, status_code=400)
  updates: list[str] = []
  vals: list[Any] = []
  if "display_name" in patch:
    dn = str(patch.get("display_name") or "").strip()[:80]
    if not dn:
      return JSONResponse({"ok": False, "reason": "invalid_display_name"}, status_code=400)
    updates.append("display_name = ?")
    vals.append(dn)
  if "active" in patch:
    updates.append("active = ?")
    vals.append(1 if bool(patch["active"]) else 0)
  if "block_reason" in patch:
    br = str(patch.get("block_reason") or "").strip()[:300] or None
    updates.append("block_reason = ?")
    vals.append(br)
  if not updates:
    return JSONResponse({"ok": False, "reason": "no_fields"}, status_code=400)
  vals.append(user_id)
  with _db_lock:
    con = _db()
    try:
      n = int(con.execute("SELECT COUNT(*) AS c FROM users WHERE id = ?", (user_id,)).fetchone()["c"])
      if not n:
        return JSONResponse({"ok": False, "reason": "not_found"}, status_code=404)
      sql = f"UPDATE users SET {', '.join(updates)} WHERE id = ?"
      con.execute(sql, vals)
      con.commit()
    finally:
      con.close()
  return JSONResponse({"ok": True})


@app.post("/api/admin/users")
async def admin_user_create(admin: Annotated[dict[str, Any], Depends(require_admin)], req: Request) -> JSONResponse:
  try:
    body = await req.json()
    if not isinstance(body, dict):
      raise ValueError()
  except Exception:
    return JSONResponse({"ok": False, "reason": "invalid_json"}, status_code=400)
  username = _normalize_username(str(body.get("username") or ""))
  password = str(body.get("password") or "")
  display_name = str(body.get("display_name") or "").strip()[:80]
  role = str(body.get("role") or "user").lower().strip()
  if role not in ("user", "admin"):
    role = "user"
  if not username or len(password) < 4:
    return JSONResponse({"ok": False, "reason": "weak_credentials"}, status_code=400)
  if not display_name:
    return JSONResponse({"ok": False, "reason": "display_name_required"}, status_code=400)
  ts = time.time()
  ph = _hash_password_plain(password)
  with _db_lock:
    con = _db()
    try:
      try:
        cur = con.cursor()
        cur.execute(
          """
          INSERT INTO users (username, password_hash, display_name, role, active, created_ts, family_id, family_role)
          VALUES (?, ?, ?, ?, 1, ?, NULL, NULL)
          """,
          (username, ph, display_name, role, ts),
        )
        uid = int(cur.lastrowid)
        _ensure_user_has_family(con, uid, display_name)
        con.commit()
      except sqlite3.IntegrityError:
        return JSONResponse({"ok": False, "reason": "username_taken"}, status_code=409)
    finally:
      con.close()
  return JSONResponse({"ok": True, "user_id": uid})


@app.get("/api/admin/bookings")
def admin_bookings_list(_admin: Annotated[dict[str, Any], Depends(require_admin)]) -> dict[str, Any]:
  with _db_lock:
    con = _db()
    try:
      rows = con.execute(
        """
        SELECT b.id AS id, b.slot_id AS slot_id, b.start_ts AS start_ts, b.end_ts AS end_ts,
               b.status AS status, b.note AS note, b.plate AS plate, b.created_ts AS created_ts,
               u.id AS user_id, u.username AS username, u.display_name AS display_name
        FROM bookings b
        JOIN users u ON u.id = b.user_id
        ORDER BY b.created_ts DESC
        LIMIT 500
        """
      ).fetchall()
    finally:
      con.close()
  return {"ok": True, "bookings": [dict(r) for r in rows]}


@app.get("/api/admin/find-by-plate")
def admin_find_by_plate(
  _admin: Annotated[dict[str, Any], Depends(require_admin)],
  plate: str = Query("", max_length=32),
) -> JSONResponse:
  q = _normalize_plate(plate)
  if len(q) < 2:
    return JSONResponse({"ok": False, "reason": "plate_too_short"}, status_code=400)
  now = time.time()
  with _db_lock:
    con = _db()
    try:
      rows = con.execute(
        """
        SELECT b.id AS id, b.slot_id AS slot_id, b.start_ts AS start_ts, b.end_ts AS end_ts,
               b.status AS status, b.plate AS plate, b.note AS note,
               u.id AS user_id, u.username AS username, u.display_name AS display_name
        FROM bookings b
        JOIN users u ON u.id = b.user_id
        WHERE b.status = 'active' AND b.end_ts > ? AND b.plate IS NOT NULL AND TRIM(b.plate) != ''
        ORDER BY b.end_ts DESC
        LIMIT 200
        """,
        (now,),
      ).fetchall()
    finally:
      con.close()
  live_by_slot: dict[str, dict[str, Any]] = {}
  try:
    for s in _parking_slots_map_payload().get("slots") or []:
      sid = str(s.get("id") or "")
      if sid:
        live_by_slot[sid] = s
  except Exception:
    pass
  matches: list[dict[str, Any]] = []
  for r in rows:
    d = dict(r)
    p_norm = _normalize_plate(str(d.get("plate") or ""))
    if not p_norm:
      continue
    if q not in p_norm and p_norm != q:
      continue
    sid = str(d.get("slot_id") or "")
    live = live_by_slot.get(sid) or {}
    matches.append(
      {
        "booking_id": int(d["id"]),
        "slot_id": sid,
        "plate": str(d.get("plate") or "").strip(),
        "start_ts": float(d.get("start_ts") or 0),
        "end_ts": float(d.get("end_ts") or 0),
        "status": str(d.get("status") or ""),
        "note": d.get("note"),
        "user_id": int(d.get("user_id") or 0),
        "username": str(d.get("username") or ""),
        "display_name": str(d.get("display_name") or ""),
        "remaining_s": max(0.0, float(d.get("end_ts") or 0) - now),
        "live_state": live.get("state"),
        "live_detected": live.get("detected"),
      }
    )
  return JSONResponse({"ok": True, "query": plate.strip(), "matches": matches})


def _peek_last_slots_safe() -> list[dict[str, Any]]:
  with _state_lock:
    return [dict(id=s.get("id"), label=s.get("label")) for s in (_last_slots or [])][:50]


@app.get("/api/admin/summary")
def admin_summary(_admin: Annotated[dict[str, Any], Depends(require_admin)]) -> dict[str, Any]:
  now = time.time()
  with _db_lock:
    con = _db()
    try:
      users_n = int(con.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"])
      active_bookings = con.execute(
        "SELECT COUNT(*) AS c FROM bookings WHERE status='active' AND end_ts > ?",
        (now,),
      ).fetchone()
      ab = int(active_bookings["c"])
      by_slot = con.execute(
        """
        SELECT slot_id AS slot_id, COUNT(*) AS n
        FROM bookings WHERE status='active' AND end_ts > ?
        GROUP BY slot_id ORDER BY n DESC LIMIT 40
        """,
        (now,),
      ).fetchall()
    finally:
      con.close()
  return {
    "ok": True,
    "users_total": users_n,
    "bookings_active_now": ab,
    "active_by_slot": [dict(r) for r in by_slot],
    "detected_slots_hint": _peek_last_slots_safe(),
  }


@app.get("/api/admin/slots-hint")
def admin_slots_hint(_admin: Annotated[dict[str, Any], Depends(require_admin)]) -> dict[str, Any]:
  return {"ok": True, "slots": _peek_last_slots_safe()}


def _active_booked_slots(now: float | None = None) -> set[str]:
  t = float(now if now is not None else time.time())
  with _db_lock:
    con = _db()
    try:
      rows = con.execute(
        "SELECT DISTINCT slot_id FROM bookings WHERE status='active' AND end_ts > ?",
        (t,),
      ).fetchall()
    finally:
      con.close()
  return {str(r["slot_id"]) for r in rows}


def _parking_slots_map_payload() -> dict[str, Any]:
  with _state_lock:
    raw = [dict(s) for s in (_last_slots or [])]
    ts = float(_last_ts) if _last_ts is not None else None
  overrides = _slot_override_map()
  booked = _active_booked_slots()
  items: list[dict[str, Any]] = []
  for s in raw:
    sid = str(s.get("id") or "").strip()
    if not sid:
      continue
    label = str(s.get("label") or "").lower()
    detected = "occupied" if label == "slot_occupied" else "free" if label == "slot_free" else "unknown"
    ov = overrides.get(sid) or {}
    ov_st = str(ov.get("status") or "available").lower()
    is_booked = sid in booked
    if ov_st not in ("available", "free", ""):
      state = ov_st
    elif is_booked:
      state = "booked"
    else:
      state = detected
    items.append(
      {
        "id": sid,
        "label": s.get("label"),
        "detected": detected,
        "state": state,
        "override": ov_st if ov else None,
        "override_note": ov.get("note") if ov else None,
        "bookable": ov_st in ("available", "free", "") and not is_booked and detected != "occupied",
      }
    )
  counts = _count_slots(raw)
  traffic = _traffic_from_counts(counts["free"], counts["total"])
  return {"ok": True, "ts": ts, "slots": items, "counts": counts, "traffic": traffic}


@app.get("/api/parking/traffic")
def parking_traffic(_user: Annotated[dict[str, Any], Depends(require_login)]) -> dict[str, Any]:
  with _state_lock:
    slots = list(_last_slots or [])
    ts = float(_last_ts) if _last_ts is not None else None
  if slots:
    c = _count_slots(slots)
    traffic = _traffic_from_counts(c["free"], c["total"])
    return {"ok": True, "live": True, "ts": ts, **traffic, "counts": c}
  return {"ok": True, "live": False, "ts": None, **_traffic_from_counts(0, 0), "counts": {"total": 0, "free": 0, "occupied": 0}}


@app.get("/api/parking/slots-map")
def parking_slots_map(_user: Annotated[dict[str, Any], Depends(require_login)]) -> dict[str, Any]:
  return _parking_slots_map_payload()


@app.get("/api/tariff")
def tariff_info(_user: Annotated[dict[str, Any], Depends(require_login)]) -> dict[str, Any]:
  return {
    "ok": True,
    "hour_rub": _tariff_hour_rub(),
    "currency": _kv_get("tariff_currency", "RUB"),
  }


@app.post("/api/tariff/calc")
async def tariff_calc(
  _user: Annotated[dict[str, Any], Depends(require_login)], req: Request
) -> JSONResponse:
  try:
    body = await req.json()
    if not isinstance(body, dict):
      raise ValueError()
  except Exception:
    return JSONResponse({"ok": False, "reason": "invalid_json"}, status_code=400)
  try:
    hours = float(body.get("hours") if body.get("hours") is not None else 1)
  except Exception:
    hours = 1.0
  hours = max(0.25, min(72.0, hours))
  price = _calc_price_rub(hours)
  return JSONResponse(
    {
      "ok": True,
      "hours": hours,
      "hour_rub": _tariff_hour_rub(),
      "price_rub": price,
      "currency": _kv_get("tariff_currency", "RUB"),
    }
  )


@app.patch("/api/me/bookings/{booking_id}")
async def me_booking_patch(
  booking_id: int,
  user: Annotated[dict[str, Any], Depends(require_login)],
  req: Request,
) -> JSONResponse:
  try:
    body = await req.json()
    if not isinstance(body, dict):
      raise ValueError()
  except Exception:
    return JSONResponse({"ok": False, "reason": "invalid_json"}, status_code=400)
  try:
    extend_hours = float(body.get("extend_hours") or 0)
  except Exception:
    extend_hours = 0.0
  if extend_hours <= 0:
    return JSONResponse({"ok": False, "reason": "extend_hours_required"}, status_code=400)
  extend_hours = max(0.25, min(48.0, extend_hours))
  uid = int(user["id"])
  fid = _user_family_id(user)
  scope_sql, scope_args = _booking_access_sql(fid, uid, "b")
  now = time.time()
  extra_price = _calc_price_rub(extend_hours)
  with _db_lock:
    con = _db()
    try:
      row = con.execute(
        f"SELECT b.id, b.slot_id, b.end_ts, b.status FROM bookings b WHERE b.id = ? AND {scope_sql}",
        (booking_id, *scope_args),
      ).fetchone()
      if not row:
        return JSONResponse({"ok": False, "reason": "not_found"}, status_code=404)
      if str(row["status"]) != "active":
        return JSONResponse({"ok": False, "reason": "not_active"}, status_code=400)
      base_end = float(row["end_ts"])
      if base_end <= now:
        new_end = now + extend_hours * 3600.0
      else:
        new_end = base_end + extend_hours * 3600.0
      clash = con.execute(
        """
        SELECT id FROM bookings
        WHERE slot_id = ? AND status = 'active' AND id != ? AND start_ts < ? AND end_ts > ?
        LIMIT 1
        """,
        (str(row["slot_id"]), booking_id, new_end, float(row["end_ts"])),
      ).fetchone()
      if clash:
        return JSONResponse({"ok": False, "reason": "slot_busy"}, status_code=409)
      con.execute("UPDATE bookings SET end_ts = ? WHERE id = ?", (new_end, booking_id))
      con.commit()
    finally:
      con.close()
  return JSONResponse(
    {"ok": True, "end_ts": new_end, "extend_hours": extend_hours, "extra_price_rub": extra_price}
  )


def _booking_payment_quote_row(
  con: sqlite3.Connection, booking_id: int, uid: int, family_id: int | None = None
) -> tuple[dict[str, Any] | None, str | None]:
  scope_sql, scope_args = _booking_access_sql(family_id, uid, "b")
  row = con.execute(
    f"""
    SELECT id, slot_id, start_ts, end_ts, status,
           (SELECT COUNT(*) FROM payments p WHERE p.booking_id = b.id) AS paid_n,
           (SELECT p.receipt_id FROM payments p WHERE p.booking_id = b.id
            ORDER BY p.created_ts DESC LIMIT 1) AS last_receipt_id
    FROM bookings b
    WHERE b.id = ? AND {scope_sql}
    """,
    (booking_id, *scope_args),
  ).fetchone()
  if not row:
    return None, "not_found"
  if str(row["status"]) != "active":
    return None, "not_active"
  hours = max(0.25, (float(row["end_ts"]) - float(row["start_ts"])) / 3600.0)
  amount = _calc_price_rub(hours)
  paid_n = int(row["paid_n"] or 0)
  out: dict[str, Any] = {
    "booking_id": int(row["id"]),
    "slot_id": str(row["slot_id"]),
    "hours": round(hours, 2),
    "amount_rub": amount,
    "hour_rub": _tariff_hour_rub(),
    "currency": _kv_get("tariff_currency", "RUB"),
    "already_paid": paid_n > 0,
    "paid_n": paid_n,
    "last_receipt_id": row["last_receipt_id"],
  }
  if family_id is not None:
    out["loyalty"] = _loyalty_status(con, int(family_id), hours)
  return out, None


@app.get("/api/me/bookings/{booking_id}/payment-quote")
def me_booking_payment_quote(
  booking_id: int, user: Annotated[dict[str, Any], Depends(require_login)]
) -> JSONResponse:
  uid = int(user["id"])
  fid = _user_family_id(user)
  print(f"[PE] payment-quote booking_id={booking_id} user_id={uid}", flush=True)
  with _db_lock:
    con = _db()
    try:
      quote, err = _booking_payment_quote_row(con, booking_id, uid, fid)
    finally:
      con.close()
  if err == "not_found":
    return JSONResponse({"ok": False, "reason": "not_found"}, status_code=404)
  if err == "not_active":
    return JSONResponse({"ok": False, "reason": "not_active"}, status_code=400)
  return JSONResponse({"ok": True, **quote})


@app.post("/api/me/bookings/{booking_id}/pay")
async def me_booking_pay(
  booking_id: int,
  user: Annotated[dict[str, Any], Depends(require_login)],
  req: Request,
) -> JSONResponse:
  """Mock payment — рубли или списание баллов лояльности."""
  uid = int(user["id"])
  fid = _user_family_id(user)
  redeem_points = False
  try:
    body = await req.json()
    if isinstance(body, dict):
      redeem_points = bool(body.get("redeem_points"))
  except Exception:
    pass
  print(f"[PE] pay booking_id={booking_id} user_id={uid} redeem={redeem_points}", flush=True)
  now = time.time()
  try:
    with _db_lock:
      con = _db()
      try:
        quote, err = _booking_payment_quote_row(con, booking_id, uid, fid)
        if err == "not_found":
          return JSONResponse({"ok": False, "reason": "not_found"}, status_code=404)
        if err == "not_active":
          return JSONResponse({"ok": False, "reason": "not_active"}, status_code=400)
        assert quote is not None
        if quote["already_paid"]:
          return JSONResponse(
            {
              "ok": False,
              "reason": "already_paid",
              "amount_rub": quote["amount_rub"],
              "receipt_id": quote["last_receipt_id"],
            },
            status_code=409,
          )
        hours = float(quote["hours"])
        if fid is None:
          fid = _ensure_user_has_family(con, uid, str(user.get("display_name") or "User"))
        fid_i = int(fid)
        cur = con.cursor()
        if redeem_points:
          cost = _loyalty_redeem_cost(hours)
          ok_pts, new_bal, pts_err = _loyalty_apply_delta(
            con, fid_i, uid, -cost, "redeem_booking", booking_id=booking_id
          )
          if not ok_pts:
            return JSONResponse(
              {
                "ok": False,
                "reason": pts_err or "insufficient_points",
                "balance": _family_points_balance(con, fid_i),
                "redeem_cost_points": cost,
              },
              status_code=409,
            )
          receipt_id = f"PE-PTS-{int(now)}-{booking_id}"
          cur.execute(
            """
            INSERT INTO payments (user_id, family_id, booking_id, amount_rub, status, receipt_id, created_ts, points_earned, paid_with_points)
            VALUES (?, ?, ?, 0, 'paid', ?, ?, 0, 1)
            """,
            (uid, fid_i, booking_id, receipt_id, now),
          )
          pid = int(cur.lastrowid)
          con.commit()
          loyalty = _loyalty_status(con, fid_i, hours)
          return JSONResponse(
            {
              "ok": True,
              "payment_id": pid,
              "amount_rub": 0,
              "receipt_id": receipt_id,
              "paid_with_points": True,
              "points_spent": cost,
              "loyalty": loyalty,
              "demo": True,
              "message": f"Бронь оплачена баллами (−{cost} баллов).",
            }
          )
        amount = float(quote["amount_rub"])
        earned = _loyalty_earn_points(hours)
        receipt_id = f"PE-{int(now)}-{booking_id}"
        cur.execute(
          """
          INSERT INTO payments (user_id, family_id, booking_id, amount_rub, status, receipt_id, created_ts, points_earned, paid_with_points)
          VALUES (?, ?, ?, ?, 'paid', ?, ?, ?, 0)
          """,
          (uid, fid_i, booking_id, amount, receipt_id, now, earned),
        )
        pid = int(cur.lastrowid)
        if earned > 0:
          ok_pts, new_bal, pts_err = _loyalty_apply_delta(
            con, fid_i, uid, earned, "paid_parking", booking_id=booking_id, payment_id=pid
          )
          if not ok_pts:
            return JSONResponse({"ok": False, "reason": pts_err or "points_error"}, status_code=500)
        con.commit()
        loyalty = _loyalty_status(con, fid_i, hours)
      finally:
        con.close()
  except sqlite3.Error:
    return JSONResponse({"ok": False, "reason": "payment_db_error"}, status_code=500)
  return JSONResponse(
    {
      "ok": True,
      "payment_id": pid,
      "amount_rub": amount,
      "receipt_id": receipt_id,
      "points_earned": earned,
      "loyalty": loyalty,
      "demo": True,
      "message": f"Демо-оплата сохранена. Начислено {earned} баллов.",
    }
  )


@app.get("/api/me/sessions")
def me_sessions(user: Annotated[dict[str, Any], Depends(require_login)]) -> dict[str, Any]:
  uid = int(user["id"])
  fid = _user_family_id(user)
  b_scope, b_args = _booking_access_sql(fid, uid, "b")
  p_scope = "family_id = ?" if fid is not None else "user_id = ?"
  p_args: list[Any] = [int(fid)] if fid is not None else [uid]
  with _db_lock:
    con = _db()
    try:
      bookings = con.execute(
        f"""
        SELECT b.id, b.slot_id, b.start_ts, b.end_ts, b.status, b.plate, b.created_ts, b.user_id,
               u.display_name AS booked_by_name,
               (SELECT COUNT(*) FROM payments p WHERE p.booking_id = b.id) AS paid_n,
               (SELECT SUM(amount_rub) FROM payments p WHERE p.booking_id = b.id) AS paid_sum
        FROM bookings b
        LEFT JOIN users u ON u.id = b.user_id
        WHERE {b_scope}
        ORDER BY b.created_ts DESC
        LIMIT 100
        """,
        tuple(b_args),
      ).fetchall()
      payments = con.execute(
        f"""
        SELECT id, booking_id, amount_rub, status, receipt_id, created_ts, user_id
        FROM payments WHERE {p_scope}
        ORDER BY created_ts DESC LIMIT 100
        """,
        tuple(p_args),
      ).fetchall()
    finally:
      con.close()
  sessions_out: list[dict[str, Any]] = []
  for r in bookings:
    d = dict(r)
    paid_sum = d.get("paid_sum")
    d["paid_sum"] = float(paid_sum) if paid_sum is not None else 0.0
    sessions_out.append(d)
  return {
    "ok": True,
    "sessions": sessions_out,
    "payments": [dict(r) for r in payments],
  }


def _pdf_unicode_font() -> tuple[str, str]:
  """Windows system TTF with Cyrillic for PDF receipts."""
  fonts_dir = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
  for fname in ("arial.ttf", "Arial.ttf", "segoeui.ttf", "calibri.ttf"):
    path = os.path.join(fonts_dir, fname)
    if os.path.isfile(path):
      return "PeFont", path
  return "", ""


def _fmt_receipt_dt(ts: float) -> str:
  try:
    return datetime.fromtimestamp(float(ts)).strftime("%d.%m.%Y %H:%M")
  except Exception:
    return str(ts)


def _fetch_receipt_row(
  con: sqlite3.Connection, receipt_id: str, uid: int, family_id: int | None = None
) -> dict[str, Any] | None:
  p_scope = "p.family_id = ?" if family_id is not None else "p.user_id = ?"
  p_arg = int(family_id) if family_id is not None else int(uid)
  row = con.execute(
    f"""
    SELECT p.receipt_id, p.amount_rub, p.created_ts, p.booking_id, p.status AS pay_status,
           b.slot_id, b.plate, b.start_ts, b.end_ts, b.status AS booking_status,
           u.display_name, u.username
    FROM payments p
    LEFT JOIN bookings b ON b.id = p.booking_id
    LEFT JOIN users u ON u.id = p.user_id
    WHERE p.receipt_id = ? AND {p_scope}
    """,
    (receipt_id, p_arg),
  ).fetchone()
  return dict(row) if row else None


def _receipt_context(row: dict[str, Any]) -> dict[str, Any]:
  plate = str(row.get("plate") or "").strip() or "—"
  slot = str(row.get("slot_id") or "—")
  name = str(row.get("display_name") or row.get("username") or "—")
  amount = float(row.get("amount_rub") or 0)
  created = float(row.get("created_ts") or 0)
  start = row.get("start_ts")
  end = row.get("end_ts")
  period = "—"
  if start is not None and end is not None:
    period = f"{_fmt_receipt_dt(float(start))} — {_fmt_receipt_dt(float(end))}"
  return {
    "receipt_id": str(row["receipt_id"]),
    "amount_rub": amount,
    "amount_fmt": f"{amount:,.0f}".replace(",", " ") + " ₽",
    "booking_id": row.get("booking_id"),
    "slot_id": slot,
    "plate": plate,
    "period": period,
    "customer": name,
    "paid_at": _fmt_receipt_dt(created),
    "pay_status": str(row.get("pay_status") or "paid"),
    "booking_status": str(row.get("booking_status") or ""),
    "demo": True,
  }


def _html_esc(s: Any) -> str:
  return (
    str(s)
    .replace("&", "&amp;")
    .replace("<", "&lt;")
    .replace(">", "&gt;")
    .replace('"', "&quot;")
  )


def _build_receipt_html(ctx: dict[str, Any]) -> str:
  rid = ctx["receipt_id"]
  e = _html_esc
  return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Чек {e(rid)}</title>
  <style>
    @page {{ margin: 14mm; }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0; min-height: 100vh; display: flex; align-items: center; justify-content: center;
      font-family: "Segoe UI", system-ui, sans-serif;
      background: linear-gradient(145deg, #0a0a10, #12121c);
      color: #f4f4f8; padding: 24px;
    }}
    .receipt {{
      width: min(420px, 100%); background: #16161f; border: 1px solid rgba(255,255,255,.1);
      border-radius: 16px; overflow: hidden; box-shadow: 0 24px 64px rgba(0,0,0,.45);
    }}
    .head {{ background: linear-gradient(135deg, #20d56b, #14a853); color: #061008; padding: 20px 22px; }}
    .brand {{ font-size: 22px; font-weight: 800; }}
    .sub {{ font-size: 13px; opacity: .85; margin-top: 4px; }}
    .body {{ padding: 22px; }}
    .rid {{ font-size: 12px; color: rgba(255,255,255,.55); margin-bottom: 16px; word-break: break-all; }}
    .amount {{ font-size: 36px; font-weight: 800; color: #20d56b; margin: 0 0 20px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
    td {{ padding: 10px 0; border-bottom: 1px solid rgba(255,255,255,.06); }}
    td:first-child {{ color: rgba(255,255,255,.5); width: 42%; }}
    .foot {{ padding: 16px 22px; font-size: 11px; color: rgba(255,255,255,.45); border-top: 1px solid rgba(255,255,255,.06); }}
    .badge {{ display: inline-block; margin-top: 12px; padding: 4px 10px; border-radius: 8px;
      background: rgba(32,213,107,.15); color: #20d56b; font-size: 11px; font-weight: 700; }}
    .actions {{ display: flex; gap: 10px; padding: 0 22px 20px; }}
    .btn {{ flex: 1; padding: 10px; border-radius: 10px; border: none; font-weight: 700; cursor: pointer; }}
    .btn-primary {{ background: #20d56b; color: #061008; }}
    .btn-ghost {{ background: rgba(255,255,255,.08); color: #f4f4f8; }}
    @media print {{ body {{ background: #fff; }} .actions {{ display: none !important; }} }}
  </style>
</head>
<body>
  <div class="receipt">
    <div class="head"><div class="brand">Parking Eye</div><div class="sub">Квитанция об оплате (демо)</div></div>
    <div class="body">
      <div class="rid">№ {e(rid)}</div>
      <div class="amount">{e(ctx["amount_fmt"])}</div>
      <table>
        <tr><td>Дата оплаты</td><td>{e(ctx["paid_at"])}</td></tr>
        <tr><td>Клиент</td><td>{e(ctx["customer"])}</td></tr>
        <tr><td>Место</td><td>{e(ctx["slot_id"])}</td></tr>
        <tr><td>Госномер</td><td>{e(ctx["plate"])}</td></tr>
        <tr><td>Период</td><td>{e(ctx["period"])}</td></tr>
        <tr><td>Бронь №</td><td>{e(ctx["booking_id"])}</td></tr>
      </table>
      <span class="badge">Оплачено · демо без банка</span>
    </div>
    <div class="actions">
      <button type="button" class="btn btn-primary" onclick="window.print()">Сохранить как PDF</button>
      <button type="button" class="btn btn-ghost" onclick="window.close()">Закрыть</button>
    </div>
    <div class="foot">Демонстрационный чек Parking Eye. Списание с карты не выполнялось.</div>
  </div>
</body>
</html>"""


def _build_receipt_pdf(ctx: dict[str, Any]) -> bytes:
  from fpdf import FPDF

  pdf = FPDF(orientation="P", unit="mm", format="A4")
  pdf.set_auto_page_break(auto=True, margin=18)
  pdf.add_page()
  font_name, font_path = _pdf_unicode_font()
  if font_path:
    pdf.add_font(font_name, "", font_path)
    body_font = font_name
  else:
    body_font = "Helvetica"

  pdf.set_fill_color(32, 213, 107)
  pdf.rect(0, 0, 210, 32, style="F")
  pdf.set_text_color(6, 16, 8)
  pdf.set_font(body_font, size=20)
  pdf.set_xy(18, 11)
  pdf.cell(0, 10, "Parking Eye")
  pdf.set_font(body_font, size=11)
  pdf.set_xy(18, 22)
  pdf.cell(0, 6, "Квитанция об оплате (демо)")

  pdf.set_text_color(30, 30, 40)
  y = 42.0
  pdf.set_xy(18, y)
  pdf.set_font(body_font, size=10)
  pdf.set_text_color(120, 120, 130)
  pdf.cell(0, 6, f"№ {ctx['receipt_id']}")
  y += 10
  pdf.set_xy(18, y)
  pdf.set_font(body_font, size=26)
  pdf.set_text_color(13, 159, 79)
  pdf.cell(0, 12, ctx["amount_fmt"])
  y += 18

  rows = [
    ("Дата оплаты", ctx["paid_at"]),
    ("Клиент", ctx["customer"]),
    ("Место", ctx["slot_id"]),
    ("Госномер", ctx["plate"]),
    ("Период", ctx["period"]),
    ("Бронь №", str(ctx["booking_id"])),
  ]
  pdf.set_font(body_font, size=11)
  for label, val in rows:
    pdf.set_xy(18, y)
    pdf.set_text_color(120, 120, 130)
    pdf.cell(45, 7, label)
    pdf.set_text_color(30, 30, 40)
    pdf.set_xy(63, y)
    pdf.multi_cell(125, 7, str(val))
    y = pdf.get_y() + 3

  y += 4
  pdf.set_fill_color(230, 248, 238)
  pdf.rect(18, y, 174, 10, style="F")
  pdf.set_xy(22, y + 2.5)
  pdf.set_font(body_font, size=10)
  pdf.set_text_color(13, 120, 60)
  pdf.cell(0, 6, "Оплачено · демонстрация без банка")

  pdf.set_xy(18, 270)
  pdf.set_font(body_font, size=8)
  pdf.set_text_color(150, 150, 160)
  pdf.multi_cell(174, 4, "Демонстрационный чек Parking Eye. Списание с карты не выполнялось.")

  out = pdf.output()
  if isinstance(out, bytearray):
    return bytes(out)
  if isinstance(out, bytes):
    return out
  return str(out).encode("latin-1")


def _receipt_response_data(receipt_id: str, uid: int, family_id: int | None = None) -> dict[str, Any] | None:
  rid = str(receipt_id or "").strip()[:64]
  if not rid:
    return None
  with _db_lock:
    con = _db()
    try:
      row = _fetch_receipt_row(con, rid, uid, family_id)
    finally:
      con.close()
  if not row:
    return None
  return _receipt_context(row)


@app.get("/api/me/receipt/{receipt_id}.pdf")
def me_receipt_pdf(
  receipt_id: str,
  user: Annotated[dict[str, Any], Depends(require_login)],
) -> Response:
  ctx = _receipt_response_data(receipt_id, int(user["id"]), _user_family_id(user))
  if not ctx:
    return Response(status_code=404)
  try:
    body = _build_receipt_pdf(ctx)
  except Exception:
    return Response(status_code=500)
  if isinstance(body, bytearray):
    body = bytes(body)
  rid = ctx["receipt_id"]
  return Response(
    content=body,
    media_type="application/pdf",
    headers={"Content-Disposition": f'attachment; filename="{rid}.pdf"'},
  )


@app.get("/api/me/receipt/{receipt_id}.html")
def me_receipt_html(
  receipt_id: str,
  user: Annotated[dict[str, Any], Depends(require_login)],
) -> Response:
  ctx = _receipt_response_data(receipt_id, int(user["id"]), _user_family_id(user))
  if not ctx:
    return Response(status_code=404)
  return Response(content=_build_receipt_html(ctx), media_type="text/html; charset=utf-8")


@app.get("/api/me/receipt/{receipt_id}.csv")
def me_receipt_csv(
  receipt_id: str,
  user: Annotated[dict[str, Any], Depends(require_login)],
) -> Response:
  ctx = _receipt_response_data(receipt_id, int(user["id"]), _user_family_id(user))
  if not ctx:
    return Response(status_code=404)
  rid = ctx["receipt_id"]
  lines = [
    "receipt_id,amount_rub,booking_id,slot_id,plate,paid_at",
    f"{rid},{ctx['amount_rub']},{ctx['booking_id']},{ctx['slot_id']},{ctx['plate']},{ctx['paid_at']}",
  ]
  return Response(
    content="\n".join(lines),
    media_type="text/csv",
    headers={"Content-Disposition": f'attachment; filename="{rid}.csv"'},
  )



@app.get("/api/admin/slot-overrides")
def admin_slot_overrides_list(_admin: Annotated[dict[str, Any], Depends(require_admin)]) -> dict[str, Any]:
  return {"ok": True, "overrides": list(_slot_override_map().values())}


@app.put("/api/admin/slot-overrides/{slot_id}")
async def admin_slot_override_put(
  slot_id: str,
  _admin: Annotated[dict[str, Any], Depends(require_admin)],
  req: Request,
) -> JSONResponse:
  sid = str(slot_id or "").strip()[:64]
  if not sid:
    return JSONResponse({"ok": False, "reason": "slot_id_required"}, status_code=400)
  try:
    body = await req.json()
    if not isinstance(body, dict):
      raise ValueError()
  except Exception:
    return JSONResponse({"ok": False, "reason": "invalid_json"}, status_code=400)
  status = str(body.get("status") or "available").lower().strip()[:32]
  if status not in ("available", "repair", "reserved", "closed"):
    return JSONResponse({"ok": False, "reason": "invalid_status"}, status_code=400)
  note = str(body.get("note") or "").strip()[:200] or None
  ts = time.time()
  with _db_lock:
    con = _db()
    try:
      con.execute(
        """
        INSERT INTO slot_overrides (slot_id, status, note, updated_ts)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(slot_id) DO UPDATE SET status=excluded.status, note=excluded.note, updated_ts=excluded.updated_ts
        """,
        (sid, status, note, ts),
      )
      if status == "available":
        con.execute("DELETE FROM slot_overrides WHERE slot_id = ?", (sid,))
      con.commit()
    finally:
      con.close()
  return JSONResponse({"ok": True, "slot_id": sid, "status": status})


@app.patch("/api/admin/bookings/{booking_id}")
async def admin_booking_patch(
  booking_id: int,
  _admin: Annotated[dict[str, Any], Depends(require_admin)],
  req: Request,
) -> JSONResponse:
  try:
    body = await req.json()
    if not isinstance(body, dict):
      raise ValueError()
  except Exception:
    return JSONResponse({"ok": False, "reason": "invalid_json"}, status_code=400)
  updates: list[str] = []
  vals: list[Any] = []
  if "slot_id" in body:
    sid = str(body.get("slot_id") or "").strip()[:64]
    if not sid:
      return JSONResponse({"ok": False, "reason": "slot_id_required"}, status_code=400)
    updates.append("slot_id = ?")
    vals.append(sid)
  extend_hours = body.get("extend_hours")
  with _db_lock:
    con = _db()
    try:
      row = con.execute("SELECT id, end_ts, status, slot_id FROM bookings WHERE id = ?", (booking_id,)).fetchone()
      if not row:
        return JSONResponse({"ok": False, "reason": "not_found"}, status_code=404)
      if extend_hours is not None:
        try:
          eh = max(0.25, min(48.0, float(extend_hours)))
        except Exception:
          return JSONResponse({"ok": False, "reason": "invalid_extend"}, status_code=400)
        new_end = float(row["end_ts"]) + eh * 3600.0
        updates.append("end_ts = ?")
        vals.append(new_end)
      if not updates:
        return JSONResponse({"ok": False, "reason": "no_fields"}, status_code=400)
      vals.append(booking_id)
      con.execute(f"UPDATE bookings SET {', '.join(updates)} WHERE id = ?", vals)
      con.commit()
    finally:
      con.close()
  return JSONResponse({"ok": True})


@app.get("/api/admin/analytics/occupancy")
def admin_analytics_occupancy(
  _admin: Annotated[dict[str, Any], Depends(require_admin)],
  days: int = 7,
) -> dict[str, Any]:
  days = max(1, min(30, int(days)))
  since = time.time() - days * 86400.0
  with _db_lock:
    con = _db()
    try:
      rows = con.execute(
        """
        SELECT CAST(ts / 3600 AS INTEGER) * 3600 AS bucket,
               AVG(occupied * 1.0 / NULLIF(total, 0)) AS load_ratio,
               AVG(free) AS avg_free,
               COUNT(*) AS n
        FROM observations
        WHERE ts >= ? AND total > 0
        GROUP BY bucket
        ORDER BY bucket ASC
        """,
        (since,),
      ).fetchall()
      daily = con.execute(
        """
        SELECT CAST(ts / 86400 AS INTEGER) * 86400 AS day,
               AVG(occupied) AS avg_occupied,
               AVG(free) AS avg_free,
               MAX(occupied) AS peak_occupied
        FROM observations
        WHERE ts >= ?
        GROUP BY day
        ORDER BY day ASC
        """,
        (since,),
      ).fetchall()
    finally:
      con.close()
  return {
    "ok": True,
    "days": days,
    "hourly": [dict(r) for r in rows],
    "daily": [dict(r) for r in daily],
  }


@app.get("/api/admin/finance/summary")
def admin_finance_summary(
  _admin: Annotated[dict[str, Any], Depends(require_admin)],
  days: int = 30,
) -> dict[str, Any]:
  days = max(1, min(365, int(days)))
  since = time.time() - days * 86400.0
  with _db_lock:
    con = _db()
    try:
      total_row = con.execute(
        "SELECT COALESCE(SUM(amount_rub), 0) AS s, COUNT(*) AS n FROM payments WHERE created_ts >= ?",
        (since,),
      ).fetchone()
      by_day = con.execute(
        """
        SELECT CAST(created_ts / 86400 AS INTEGER) * 86400 AS day,
               SUM(amount_rub) AS revenue,
               COUNT(*) AS payments
        FROM payments
        WHERE created_ts >= ?
        GROUP BY day
        ORDER BY day ASC
        """,
        (since,),
      ).fetchall()
    finally:
      con.close()
  return {
    "ok": True,
    "days": days,
    "revenue_rub": float(total_row["s"] or 0),
    "payments_count": int(total_row["n"] or 0),
    "tariff_hour_rub": _tariff_hour_rub(),
    "by_day": [dict(r) for r in by_day],
  }


_SUPPORT_BODY_MAX = 2000


def _support_row_dict(r: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
  d = dict(r)
  return {
    "id": int(d["id"]),
    "user_id": int(d["user_id"]),
    "from_role": str(d["from_role"]),
    "body": str(d["body"]),
    "created_ts": float(d["created_ts"]),
  }


@app.get("/api/me/support/messages")
def me_support_messages(
  user: Annotated[dict[str, Any], Depends(require_login)],
  since_id: int = 0,
) -> dict[str, Any]:
  uid = int(user["id"])
  sid = max(0, int(since_id))
  with _db_lock:
    con = _db()
    try:
      con.execute(
        """
        UPDATE support_messages
        SET read_by_user = 1
        WHERE user_id = ? AND from_role = 'admin' AND read_by_user = 0
        """,
        (uid,),
      )
      if sid == 0:
        rows = con.execute(
          """
          SELECT id, user_id, from_role, body, created_ts
          FROM support_messages
          WHERE user_id = ?
          ORDER BY created_ts ASC
          LIMIT 500
          """,
          (uid,),
        ).fetchall()
      else:
        rows = con.execute(
          """
          SELECT id, user_id, from_role, body, created_ts
          FROM support_messages
          WHERE user_id = ? AND id > ?
          ORDER BY created_ts ASC
          LIMIT 500
          """,
          (uid, sid),
        ).fetchall()
      messages = [_support_row_dict(r) for r in rows]
      con.commit()
    finally:
      con.close()
  return {"ok": True, "messages": messages}


@app.post("/api/me/support/messages")
async def me_support_post(
  user: Annotated[dict[str, Any], Depends(require_login)],
  req: Request,
) -> JSONResponse:
  if str(user.get("role") or "").lower() == "admin":
    return JSONResponse({"ok": False, "reason": "use_admin_panel"}, status_code=400)
  try:
    body = await req.json()
    if not isinstance(body, dict):
      raise ValueError()
  except Exception:
    return JSONResponse({"ok": False, "reason": "invalid_json"}, status_code=400)
  text = str(body.get("body") or "").strip()
  if not text:
    return JSONResponse({"ok": False, "reason": "empty_body"}, status_code=400)
  if len(text) > _SUPPORT_BODY_MAX:
    return JSONResponse({"ok": False, "reason": "body_too_long"}, status_code=400)
  uid = int(user["id"])
  ts = time.time()
  with _db_lock:
    con = _db()
    try:
      cur = con.cursor()
      cur.execute(
        """
        INSERT INTO support_messages (user_id, from_role, body, created_ts, read_by_user, read_by_admin)
        VALUES (?, 'user', ?, ?, 1, 0)
        """,
        (uid, text, ts),
      )
      mid = int(cur.lastrowid)
      con.commit()
    finally:
      con.close()
  return JSONResponse({"ok": True, "message": _support_row_dict({"id": mid, "user_id": uid, "from_role": "user", "body": text, "created_ts": ts})})


@app.get("/api/admin/support/threads")
def admin_support_threads(_admin: Annotated[dict[str, Any], Depends(require_admin)]) -> dict[str, Any]:
  with _db_lock:
    con = _db()
    try:
      rows = con.execute(
        """
        SELECT u.id AS user_id, u.username AS username, u.display_name AS display_name,
               MAX(m.created_ts) AS last_ts,
               (SELECT body FROM support_messages m2
                WHERE m2.user_id = u.id ORDER BY m2.created_ts DESC LIMIT 1) AS last_body,
               (SELECT COUNT(*) FROM support_messages m3
                WHERE m3.user_id = u.id AND m3.from_role = 'user' AND m3.read_by_admin = 0) AS unread
        FROM users u
        INNER JOIN support_messages m ON m.user_id = u.id
        WHERE u.role != 'admin'
        GROUP BY u.id
        ORDER BY last_ts DESC
        LIMIT 200
        """
      ).fetchall()
    finally:
      con.close()
  threads = [
    {
      "user_id": int(r["user_id"]),
      "username": str(r["username"]),
      "display_name": str(r["display_name"]),
      "last_ts": float(r["last_ts"] or 0),
      "last_body": str(r["last_body"] or "")[:120],
      "unread": int(r["unread"] or 0),
    }
    for r in rows
  ]
  return {"ok": True, "threads": threads}


@app.get("/api/admin/support/threads/{user_id}/messages")
def admin_support_thread_messages(
  user_id: int,
  _admin: Annotated[dict[str, Any], Depends(require_admin)],
  since_id: int = 0,
) -> dict[str, Any]:
  uid = int(user_id)
  sid = max(0, int(since_id))
  with _db_lock:
    con = _db()
    try:
      u = con.execute(
        "SELECT id, username, display_name FROM users WHERE id = ? AND role != 'admin'",
        (uid,),
      ).fetchone()
      if not u:
        return JSONResponse({"ok": False, "reason": "user_not_found"}, status_code=404)
      con.execute(
        """
        UPDATE support_messages
        SET read_by_admin = 1
        WHERE user_id = ? AND from_role = 'user' AND read_by_admin = 0
        """,
        (uid,),
      )
      if sid == 0:
        rows = con.execute(
          """
          SELECT id, user_id, from_role, body, created_ts
          FROM support_messages WHERE user_id = ?
          ORDER BY created_ts ASC LIMIT 500
          """,
          (uid,),
        ).fetchall()
      else:
        rows = con.execute(
          """
          SELECT id, user_id, from_role, body, created_ts
          FROM support_messages WHERE user_id = ? AND id > ?
          ORDER BY created_ts ASC LIMIT 500
          """,
          (uid, sid),
        ).fetchall()
      con.commit()
    finally:
      con.close()
  return {
    "ok": True,
    "user": {"id": uid, "username": str(u["username"]), "display_name": str(u["display_name"])},
    "messages": [_support_row_dict(r) for r in rows],
  }


@app.post("/api/admin/support/threads/{user_id}/messages")
async def admin_support_thread_post(
  user_id: int,
  _admin: Annotated[dict[str, Any], Depends(require_admin)],
  req: Request,
) -> JSONResponse:
  uid = int(user_id)
  try:
    body = await req.json()
    if not isinstance(body, dict):
      raise ValueError()
  except Exception:
    return JSONResponse({"ok": False, "reason": "invalid_json"}, status_code=400)
  text = str(body.get("body") or "").strip()
  if not text:
    return JSONResponse({"ok": False, "reason": "empty_body"}, status_code=400)
  if len(text) > _SUPPORT_BODY_MAX:
    return JSONResponse({"ok": False, "reason": "body_too_long"}, status_code=400)
  ts = time.time()
  with _db_lock:
    con = _db()
    try:
      u = con.execute("SELECT id FROM users WHERE id = ? AND role != 'admin'", (uid,)).fetchone()
      if not u:
        return JSONResponse({"ok": False, "reason": "user_not_found"}, status_code=404)
      cur = con.cursor()
      cur.execute(
        """
        INSERT INTO support_messages (user_id, from_role, body, created_ts, read_by_user, read_by_admin)
        VALUES (?, 'admin', ?, ?, 0, 1)
        """,
        (uid, text, ts),
      )
      mid = int(cur.lastrowid)
      con.commit()
    finally:
      con.close()
  return JSONResponse(
    {
      "ok": True,
      "message": _support_row_dict(
        {"id": mid, "user_id": uid, "from_role": "admin", "body": text, "created_ts": ts}
      ),
    }
  )


# NOTE: Mount static AFTER API routes. Mounting at "/" first would swallow "/api/*"
# and cause 404/405 for API endpoints.
app.mount("/snapshots", StaticFiles(directory=SNAP_DIR), name="snapshots")
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

