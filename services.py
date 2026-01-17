# services.py
# -*- coding: utf-8 -*-

import os
import io
import time
import random
import string
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any, Dict, List, Optional, Tuple

import gspread
from gspread.exceptions import APIError
from google.oauth2.service_account import Credentials

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from PIL import Image, ImageDraw, ImageFont


# ----------------------------
# Config / helpers
# ----------------------------
PARIS_TZ = ZoneInfo(os.getenv("PARIS_TZ", "Europe/Paris"))

CAT_EMOJIS = ["🐱", "🐾", "😺", "😸", "😼", "🐈"]

def catify(text: str, chance: float = 0.20) -> str:
    if random.random() < chance:
        return f"{text} {random.choice(CAT_EMOJIS)}"
    return text

def now_fr() -> datetime:
    return datetime.now(tz=PARIS_TZ)

def fmt_fr(dt: datetime) -> str:
    return dt.astimezone(PARIS_TZ).strftime("%d/%m %H:%M")

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def normalize_name(name: str) -> str:
    if not name:
        return ""
    s = str(name).lower().strip().replace("_", " ")
    while "  " in s:
        s = s.replace("  ", " ")
    return s

def display_name(name: str) -> str:
    if not name:
        return ""
    s = str(name).replace("_", " ").strip()
    while "  " in s:
        s = s.replace("  ", " ")
    return " ".join(w.capitalize() for w in s.split(" ") if w)

def normalize_code(code: str) -> str:
    code = (code or "").strip().upper().replace(" ", "")
    return code.replace("O", "0")

def gen_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    a = "".join(random.choice(alphabet) for _ in range(4))
    b = "".join(random.choice(alphabet) for _ in range(4))
    return f"SUB-{a}-{b}"

def parse_iso_dt(s: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.astimezone(PARIS_TZ)
    except Exception:
        return None

def extract_tag(text: str, prefix: str) -> Optional[str]:
    if not text:
        return None
    toks = text.lower().split()
    for tok in toks:
        if tok.startswith(prefix.lower()):
            return tok.split(":", 1)[1].strip() if ":" in tok else None
    return None

def last_friday_17(now: datetime) -> datetime:
    target_weekday = 4  # Friday
    candidate = now.astimezone(PARIS_TZ).replace(hour=17, minute=0, second=0, microsecond=0)
    days_back = (candidate.weekday() - target_weekday) % 7
    candidate = candidate - timedelta(days=days_back)
    if now < candidate:
        candidate -= timedelta(days=7)
    return candidate

def parse_dt_fr_env(name: str) -> Optional[datetime]:
    s = (os.getenv(name) or "").strip()
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=PARIS_TZ)
    except Exception:
        return None

def challenge_week_window(now: Optional[datetime] = None) -> Tuple[datetime, datetime]:
    now = now or now_fr()
    now = now.astimezone(PARIS_TZ)
    bootstrap_end = parse_dt_fr_env("CHALLENGE_BOOTSTRAP_END")
    if bootstrap_end and now < bootstrap_end:
        start = last_friday_17(now)
        end = bootstrap_end
        return start, end
    start = last_friday_17(now)
    end = start + timedelta(days=7)
    return start, end


# ----------------------------
# Google Sheets service
# ----------------------------
def _is_quota_429(e: Exception) -> bool:
    return isinstance(e, APIError) and ("429" in str(e) or "Quota exceeded" in str(e))

@dataclass
class CacheItem:
    exp: float
    value: Any

class SheetsService:
    """
    - Cache worksheet (TTL)
    - Cache headers (TTL)
    - Retry 429
    - Header-safe append/update
    """
    def __init__(self, sheet_id: str, creds_path: str = "credentials.json"):
        self.sheet_id = sheet_id
        self.creds_path = creds_path
        self.scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive.file",
        ]
        self._gc: Optional[gspread.Client] = None
        self._sh = None

        self._ws_cache: Dict[str, CacheItem] = {}
        self._hdr_cache: Dict[str, CacheItem] = {}

        self.ws_ttl = 60
        self.hdr_ttl = 180

    def _retry(self, fn, *args, **kwargs):
        delay = 1.0
        for _ in range(6):
            try:
                return fn(*args, **kwargs)
            except Exception as e:
                if _is_quota_429(e):
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise
        return fn(*args, **kwargs)

    def client(self) -> gspread.Client:
        if self._gc is None:
            creds = Credentials.from_service_account_file(self.creds_path, scopes=self.scopes)
            self._gc = gspread.authorize(creds)
        return self._gc

    def sheet(self):
        if self._sh is None:
            gc = self.client()
            self._sh = self._retry(gc.open_by_key, self.sheet_id)
        return self._sh

    def ws(self, title: str):
        now = time.time()
        cached = self._ws_cache.get(title)
        if cached and now < cached.exp:
            return cached.value

        sh = self.sheet()
        w = self._retry(sh.worksheet, title)
        self._ws_cache[title] = CacheItem(exp=now + self.ws_ttl, value=w)
        return w

    def headers(self, title: str) -> List[str]:
        now = time.time()
        cached = self._hdr_cache.get(title)
        if cached and now < cached.exp:
            return cached.value

        w = self.ws(title)
        hdr = [h.strip() for h in self._retry(w.row_values, 1)]
        self._hdr_cache[title] = CacheItem(exp=now + self.hdr_ttl, value=hdr)
        return hdr

    def append_by_headers(self, title: str, data: Dict[str, Any]):
        w = self.ws(title)
        hdr = self.headers(title)
        row = [""] * len(hdr)
        for k, v in data.items():
            if k in hdr:
                row[hdr.index(k)] = v
        self._retry(w.append_row, row, value_input_option="RAW")

    def update_cell_by_header(self, title: str, row_i: int, header: str, value: Any):
        w = self.ws(title)
        hdr = self.headers(title)
        if header not in hdr:
            raise RuntimeError(f"Colonne `{header}` introuvable dans {title}")
        col = hdr.index(header) + 1
        self._retry(w.update_cell, row_i, col, value)

    def batch_update(self, title: str, updates: List[Dict[str, Any]]):
        """
        updates = [{"range": "D2", "values": [[123]]}, ...]
        """
        w = self.ws(title)
        self._retry(w.batch_update, updates)

    def get_all_records(self, title: str) -> List[Dict[str, Any]]:
        w = self.ws(title)
        return self._retry(w.get_all_records)

    def get_all_values(self, title: str) -> List[List[str]]:
        w = self.ws(title)
        return self._retry(w.get_all_values)

    def delete_row(self, title: str, row_i: int):
        w = self.ws(title)
        self._retry(w.delete_rows, row_i)


# ----------------------------
# S3 service
# ----------------------------
class S3Service:
    def __init__(self):
        self.bucket = (os.getenv("AWS_S3_BUCKET_NAME") or "").strip()
        self.endpoint = (os.getenv("AWS_ENDPOINT_URL") or "").strip()
        self.region = (os.getenv("AWS_DEFAULT_REGION") or "auto").strip()
        self.key = (os.getenv("AWS_ACCESS_KEY_ID") or "").strip()
        self.secret = (os.getenv("AWS_SECRET_ACCESS_KEY") or "").strip()

    def enabled(self) -> bool:
        return bool(self.bucket and self.endpoint)

    def client(self):
        return boto3.client(
            "s3",
            endpoint_url=self.endpoint if self.endpoint else None,
            aws_access_key_id=self.key or None,
            aws_secret_access_key=self.secret or None,
            region_name=self.region or "auto",
            config=Config(signature_version="s3v4"),
        )

    def object_exists(self, key: str) -> bool:
        if not self.bucket:
            return False
        try:
            self.client().head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError:
            return False

    def upload_png(self, png_bytes: bytes, object_key: str) -> str:
        if not self.bucket:
            raise RuntimeError("AWS_S3_BUCKET_NAME manquant")
        s3 = self.client()
        extra = {"ContentType": "image/png"}
        extra_try_acl = dict(extra)
        extra_try_acl["ACL"] = "public-read"

        try:
            s3.put_object(Bucket=self.bucket, Key=object_key, Body=png_bytes, **extra_try_acl)
        except ClientError:
            s3.put_object(Bucket=self.bucket, Key=object_key, Body=png_bytes, **extra)

        base = (self.endpoint or "").rstrip("/")
        return f"{base}/{self.bucket}/{object_key}"

    def signed_url(self, object_key: str, expires_seconds: int = 3600) -> Optional[str]:
        if not object_key or not self.bucket:
            return None
        if not self.object_exists(object_key):
            return None
        s3 = self.client()
        return s3.generate_presigned_url(
            ClientMethod="get_object",
            Params={"Bucket": self.bucket, "Key": object_key},
            ExpiresIn=int(expires_seconds),
        )


# ----------------------------
# VIP card image
# ----------------------------
def generate_vip_card_image(
    template_path: str,
    font_path: str,
    code_vip: str,
    full_name: str,
    dob: str,
    phone: str,
    bleeter: str,
) -> bytes:
    img = Image.open(template_path).convert("RGBA")
    draw = ImageDraw.Draw(img)

    title_font = ImageFont.truetype(font_path, 56)
    font_name  = ImageFont.truetype(font_path, 56)
    font_line  = ImageFont.truetype(font_path, 38)
    font_id    = ImageFont.truetype(font_path, 46)

    white  = (245, 245, 245, 255)
    red    = (220, 30, 30, 255)
    shadow = (0, 0, 0, 160)

    def shadow_text(x, y, text, font, fill):
        draw.text((x+2, y+2), text, font=font, fill=shadow)
        draw.text((x, y), text, font=font, fill=fill)

    w, h = img.size
    vip_txt = "VIP"
    winter_txt = " WINTER EDITION"
    vip_w = draw.textlength(vip_txt, font=title_font)
    winter_w = draw.textlength(winter_txt, font=title_font)
    total_w = vip_w + winter_w
    x0 = int((w - total_w) / 2)
    y0 = 35
    shadow_text(x0, y0, vip_txt, title_font, red)
    shadow_text(x0 + vip_w, y0, winter_txt, title_font, white)

    full_name = display_name(full_name).upper()
    dob = (dob or "").strip()
    phone = (phone or "").strip()
    bleeter = (bleeter or "").strip()
    if bleeter and not bleeter.startswith("@"):
        bleeter = "@" + bleeter

    x = 70
    y = 140
    gap = 70

    shadow_text(x, y, full_name, font_name, white)
    shadow_text(x, y + gap*1, f"DN : {dob}", font_line, white)
    shadow_text(x, y + gap*2, f"TELEPHONE : {phone}", font_line, white)
    shadow_text(x, y + gap*3, f"BLEETER : {bleeter if bleeter else 'NON RENSEIGNE'}", font_line, white)

    card_text = f"CARD ID : {code_vip}"
    tw = draw.textlength(card_text, font=font_id)
    shadow_text(int((w - tw)/2), h - 95, card_text, font_id, red)

    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()
