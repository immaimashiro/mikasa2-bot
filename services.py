# services.py
# -*- coding: utf-8 -*-

import os, io, time, random, string, asyncio
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


CAT_EMOJIS = ["🐱", "🐾", "😺", "😸", "😼", "🐈"]

def catify(text: str, chance: float = 0.20) -> str:
    if random.random() < chance:
        return f"{text} {random.choice(CAT_EMOJIS)}"
    return text

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
    return " ".join(w.capitalize() for w in s.split(" "))

def normalize_code(code: str) -> str:
    code = (code or "").strip().upper().replace(" ", "")
    return code.replace("O", "0")

def gen_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    a = "".join(random.choice(alphabet) for _ in range(4))
    b = "".join(random.choice(alphabet) for _ in range(4))
    return f"SUB-{a}-{b}"

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def extract_tag(text: str, prefix: str) -> Optional[str]:
    if not text:
        return None
    toks = text.lower().split()
    for tok in toks:
        if tok.startswith(prefix.lower()):
            return tok.split(":", 1)[1].strip() if ":" in tok else None
    return None

def parse_iso_dt(s: str, tz: ZoneInfo) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.astimezone(tz)
    except Exception:
        return None

# --------------------------
# Google Sheets service
# --------------------------

@dataclass
class CachedWS:
    expires_at: float
    ws: Any

class SheetsService:
    def __init__(self, *, sheet_id: str, creds_json_path: str, scopes: List[str], ttl_seconds: int = 60):
        self.sheet_id = sheet_id
        self.creds_json_path = creds_json_path
        self.scopes = scopes
        self.ttl_seconds = ttl_seconds

        self._gc = None
        self._sh = None
        self._ws_cache: Dict[str, CachedWS] = {}

    def _make_client_sync(self):
        creds = Credentials.from_service_account_file(self.creds_json_path, scopes=self.scopes)
        return gspread.authorize(creds)

    async def _retry_429(self, fn, *args, **kwargs):
        delay = 1.0
        for _ in range(6):
            try:
                return await asyncio.to_thread(fn, *args, **kwargs)
            except APIError as e:
                if "429" in str(e) or "Quota exceeded" in str(e):
                    await asyncio.sleep(delay)
                    delay *= 2
                    continue
                raise
        return await asyncio.to_thread(fn, *args, **kwargs)

    async def _ensure_open(self):
        if self._gc is None:
            self._gc = await asyncio.to_thread(self._make_client_sync)
        if self._sh is None:
            self._sh = await self._retry_429(self._gc.open_by_key, self.sheet_id)

    async def ws(self, title: str):
        now = time.time()
        cached = self._ws_cache.get(title)
        if cached and now < cached.expires_at:
            return cached.ws

        await self._ensure_open()
        w = await self._retry_429(self._sh.worksheet, title)
        self._ws_cache[title] = CachedWS(expires_at=now + self.ttl_seconds, ws=w)
        return w

    async def headers(self, title: str) -> List[str]:
        w = await self.ws(title)
        row = await asyncio.to_thread(w.row_values, 1)
        return [h.strip() for h in row]

    async def append_by_headers(self, title: str, data: Dict[str, Any]):
        w = await self.ws(title)
        hdr = await self.headers(title)
        row = [""] * len(hdr)
        for k, v in data.items():
            if k in hdr:
                row[hdr.index(k)] = v
        await asyncio.to_thread(w.append_row, row, value_input_option="RAW")

    async def update_cell_by_header(self, title: str, row_i: int, header_name: str, value: Any):
        w = await self.ws(title)
        hdr = await self.headers(title)
        if header_name not in hdr:
            raise RuntimeError(f"Colonne `{header_name}` introuvable dans {title}")
        col = hdr.index(header_name) + 1
        await asyncio.to_thread(w.update_cell, row_i, col, value)

    async def batch_update(self, title: str, updates: List[Dict[str, Any]]):
        w = await self.ws(title)
        await asyncio.to_thread(w.batch_update, updates)

    async def all_records(self, title: str) -> List[Dict[str, Any]]:
        w = await self.ws(title)
        return await asyncio.to_thread(w.get_all_records)

    async def all_values(self, title: str) -> List[List[str]]:
        w = await self.ws(title)
        return await asyncio.to_thread(w.get_all_values)

    async def delete_rows(self, title: str, idx: int):
        w = await self.ws(title)
        await asyncio.to_thread(w.delete_rows, idx)

# --------------------------
# S3 service
# --------------------------

class S3Service:
    def __init__(self):
        self.bucket = (os.getenv("AWS_S3_BUCKET_NAME") or "").strip()
        self.endpoint_url = (os.getenv("AWS_ENDPOINT_URL") or "").strip()
        self.region = (os.getenv("AWS_DEFAULT_REGION") or "auto").strip()
        self.key_id = (os.getenv("AWS_ACCESS_KEY_ID") or "").strip()
        self.secret = (os.getenv("AWS_SECRET_ACCESS_KEY") or "").strip()

    def client(self):
        return boto3.client(
            "s3",
            endpoint_url=self.endpoint_url if self.endpoint_url else None,
            aws_access_key_id=self.key_id or None,
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

    def signed_url(self, key: str, expires_seconds: int = 3600) -> Optional[str]:
        if not key or not self.bucket:
            return None
        if not self.object_exists(key):
            return None
        s3 = self.client()
        return s3.generate_presigned_url(
            ClientMethod="get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=int(expires_seconds),
        )

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

        base = (self.endpoint_url or "").rstrip("/")
        return f"{base}/{self.bucket}/{object_key}"

# --------------------------
# VIP card generator
# --------------------------

def generate_vip_card_image(
    template_path: str,
    font_path: str,
    code_vip: str,
    full_name: str,
    dob: str,
    phone: str,
    bleeter: str
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
