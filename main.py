# mikasa_bot_refactor.py
# -*- coding: utf-8 -*-

import os
import io
import re
import random
import string
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Optional, Tuple, Dict, Any, List

import gspread
from google.oauth2.service_account import Credentials

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from PIL import Image, ImageDraw, ImageFont

import discord
from discord.ext import commands
from discord import app_commands

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger



import time
from gspread.exceptions import APIError

# ============================================================
# 0) ENV + CREDENTIALS (Railway)
# ============================================================
GOOGLE_CREDS_ENV = os.getenv("GOOGLE_CREDS", "").strip()
if GOOGLE_CREDS_ENV:
    with open("credentials.json", "w", encoding="utf-8") as f:
        f.write(GOOGLE_CREDS_ENV)
TZ_FR = ZoneInfo("Europe/Paris")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
SHEET_ID = os.getenv("SHEET_ID", "").strip()
SHEET_NAME = os.getenv("SHEET_NAME", "SubUrban_VIP").strip()

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN manquant (Railway -> Variables).")
if not SHEET_ID:
    raise RuntimeError("SHEET_ID manquant (Railway -> Variables).")
    
W1_START = datetime(2026, 1, 2, 17, 0, tzinfo=TZ_FR)   # 02/01/26 17:00 FR
W2_START = datetime(2026, 1, 16, 17, 0, tzinfo=TZ_FR)  # 16/01/26 17:00 FR (fin S1 / début S2)

# ============================================================
# 1) CONFIG GÉNÉRALE
# ============================================================
GUILD_ID = int(os.getenv("GUILD_ID", "990985463898734602"))  # ton serveur test
PARIS_TZ = ZoneInfo(os.getenv("PARIS_TZ", "Europe/Paris"))

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ✅ GROUPS (UNE SEULE FOIS)
vip_group = app_commands.Group(name="vip", description="Commandes VIP", guild_ids=[GUILD_ID])
defi_group = app_commands.Group(name="defi", description="Commandes défis (HG)", guild_ids=[GUILD_ID])
cave_group = app_commands.Group(name="cave", description="Cave de Mikasa (HG)", guild_ids=[GUILD_ID])

bot.tree.add_command(vip_group)
bot.tree.add_command(defi_group)
bot.tree.add_command(cave_group)

async def reply_ephemeral(interaction: discord.Interaction, content: str):
    try:
        if interaction.response.is_done():
            await interaction.followup.send(content, ephemeral=True)
        else:
            await interaction.response.send_message(content, ephemeral=True)
    except Exception:
        pass

import traceback

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    # unwrap CommandInvokeError -> vraie exception dans .original
    original = getattr(error, "original", error)

    # log console Railway
    print("=== SLASH ERROR ===")
    traceback.print_exception(type(original), original, original.__traceback__)

    # réponse user (ephemeral)
    msg = f"❌ Erreur slash: `{type(original).__name__}`"
    detail = str(original)
    if detail:
        msg += f"\n`{detail[:1500]}`"  # évite overflow discord

    try:
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except Exception:
        pass


# IDs rôles / channels
EMPLOYEE_ROLE_ID = int(os.getenv("EMPLOYEE_ROLE_ID", "1413872714032222298"))
HG_ROLE_ID = int(os.getenv("HG_ROLE_ID", "1455950271615209492"))

STAFF_CHANNEL_ID = int(os.getenv("STAFF_CHANNEL_ID", "0"))     # salon staff
ANNOUNCE_CHANNEL_ID = int(os.getenv("ANNOUNCE_CHANNEL_ID", "0"))  # salon annonce (défis / level-up)

# Bucket S3 Railway compatible
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "").strip()
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "").strip()
AWS_DEFAULT_REGION = os.getenv("AWS_DEFAULT_REGION", "auto").strip()
AWS_ENDPOINT_URL = os.getenv("AWS_ENDPOINT_URL", "").strip()
AWS_S3_BUCKET_NAME = os.getenv("AWS_S3_BUCKET_NAME", "").strip()

# Assets carte VIP
VIP_TEMPLATE_PATH = os.getenv("VIP_TEMPLATE_PATH", "template.png")
VIP_FONT_PATH = os.getenv("VIP_FONT_PATH", "PaybAck.ttf")
TEMPLATE_PATH = "template.png"
FONT_PATH = "PaybAck.ttf"

# Google scopes
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]

# Employés : actions autorisées hors HG
EMPLOYEE_ALLOWED_ACTIONS = {"ACHAT", "RECYCLAGE"}

# Scheduler annonces hebdo
scheduler = AsyncIOScheduler(timezone=PARIS_TZ)

# Défis hebdo
WEEKLY_CHALLENGES: Dict[int, List[str]] = {
    1: ["Photo devant le SubUrban", "Photo avec un autre client SubUrban", "Photo Bleeter (spot tenue)", "Photo lieu emblématique (Vespucci Beach)"],
    2: ["Photo mur tagué / street art", "Photo outfit rue fréquentée", "Photo devant vitrine SubUrban", "Photo place publique (Legion Square)"],
    3: ["Photo de nuit dans les rues", "Photo sous néons", "Photo rooftop", "Photo ambiance nocturne"],
    4: ["Photo prise par un ami (pose)", "Photo en mouvement", "Photo devant SubUrban (pose stylée)", "Photo duo/groupe coordonné"],
    5: ["Photo au Mont Chiliad", "Photo skyline", "Photo toit très élevé", "Photo observatoire (Griffith)"],
    6: ["Photo en voiture + outfit", "Photo devant garage custom", "Photo station-service", "Photo véhicule de luxe"],
    7: ["Photo plage tenue estivale", "Photo chill terrasse/café", "Photo sunset", "Photo nature/parc"],
    8: ["Photo avec vendeur SubUrban", "Photo essayage tenue (cabine)", "Photo miroir", "Photo devant enseigne SubUrban"],
    9: ["Photo pièce favorite", "Photo lookbook", "Photo minimaliste", "Photo monochrome"],
    10: ["Photo musée/galerie", "Photo artistique (silhouette/ombre)", "Photo bâtiment architectural", "Photo lieu original"],
    11: ["Photo club/salle concert", "Photo ambiance musique", "Photo clip-friendly", "Photo backstage"],
    12: [
        "Freestyle - choisir 4 défis parmi la liste :",
        "Outfit préféré de la saison",
        "Photo posée avec un ami",
        "Photo stylé avec un véhicule",
        "Photo devant le SubUrban",
        "Photo rooftop",
        "Photo sur une plage",
        "Photo devant un lieu emblématique",
        "Photo artistique",
        "Photo urbex",
        "Photo sportive",
        "Photo premium / luxe",
    ],
}


# ============================================================
# 2) OUTILS TEXTE / TIME / ROLES
# ============================================================
CAT_EMOJIS = ["🐱", "🐾", "😺", "😸", "😼", "🐈"]

def catify(text: str, chance: float = 0.20) -> str:
    if random.random() < chance:
        return f"{text} {random.choice(CAT_EMOJIS)}"
    return text

def now_fr() -> datetime:
    return datetime.now(tz=PARIS_TZ)

def fmt_fr(dt: datetime) -> str:
    return dt.astimezone(PARIS_TZ).strftime("%d/%m %H:%M")

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

def has_role(member: discord.Member, role_id: int) -> bool:
    return any(r.id == role_id for r in getattr(member, "roles", []))

def is_employee(member: discord.Member) -> bool:
    return has_role(member, EMPLOYEE_ROLE_ID)

def is_hg(member: discord.Member) -> bool:
    return has_role(member, HG_ROLE_ID)
    
def staff_member(interaction: discord.Interaction) -> Optional[discord.Member]:
    if interaction.guild and isinstance(interaction.user, discord.Member):
        return interaction.user
    return None

def is_staff_slash(interaction: discord.Interaction) -> bool:
    m = staff_member(interaction)
    return bool(m and (is_employee(m) or is_hg(m)))

def is_hg_slash(interaction: discord.Interaction) -> bool:
    m = staff_member(interaction)
    return bool(m and is_hg(m))

def staff_check():
    async def predicate(interaction: discord.Interaction) -> bool:
        if not is_staff_slash(interaction):
            raise app_commands.CheckFailure("Réservé staff.")
        return True
    return app_commands.check(predicate)

def hg_check():
    async def predicate(interaction: discord.Interaction) -> bool:
        if not is_hg_slash(interaction):
            raise app_commands.CheckFailure("Réservé HG.")
        return True
    return app_commands.check(predicate)

def staff_channel_only(channel: discord.abc.GuildChannel) -> bool:
    return (STAFF_CHANNEL_ID == 0) or (getattr(channel, "id", 0) == STAFF_CHANNEL_ID)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]

_gc = None
_sh = None
_ws_cache = {}

def _retry_429(fn, *args, **kwargs):
    delay = 1.0
    for _ in range(6):
        try:
            return fn(*args, **kwargs)
        except APIError as e:
            if "429" in str(e):
                time.sleep(delay)
                delay *= 2
                continue
            raise
    return fn(*args, **kwargs)

def get_gspread_client():
    global _gc
    if _gc is None:
        creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
        _gc = gspread.authorize(creds)
    return _gc

def get_sheet():
    global _sh
    if _sh is None:
        gc = get_gspread_client()
        _sh = _retry_429(gc.open_by_key, SHEET_ID)
    return _sh

def ws(title: str):
    if title in _ws_cache:
        return _ws_cache[title]
    sh = get_sheet()
    w = _retry_429(sh.worksheet, title)
    _ws_cache[title] = w
    return w

# ============================================================
# 3) GOOGLE SHEETS INIT + WORKSHEETS
# ============================================================
creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
gc = gspread.authorize(creds)
_ws_cache: dict[str, tuple[float, Any]] = {}  # title -> (expires_at, worksheet)
_WS_TTL_SECONDS = 60  # cache 1 minute (réduit les reads)

def _is_quota_error(e: Exception) -> bool:
    # gspread APIError: [429] Quota exceeded...
    return isinstance(e, APIError) and ("429" in str(e) or "Quota exceeded" in str(e))

def safe_ws(title: str):
    """
    Retourne la worksheet si OK, sinon None si quota/indispo.
    Cache TTL pour limiter les reads.
    """
    now = time.time()
    cached = _ws_cache.get(title)
    if cached:
        exp, w = cached
        if now < exp:
            return w

    try:
        # ⚠️ IMPORTANT: n'ouvre pas au top-level, seulement ici
        sh = gc.open_by_key(SHEET_ID)
        w = sh.worksheet(title)
        _ws_cache[title] = (now + _WS_TTL_SECONDS, w)
        return w
    except Exception as e:
        if _is_quota_error(e):
            return None
        # autre erreur => remonte (utile pour debug)
        raise
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ============================================================
# 4) DATA ACCESS HELPERS (SAFE HEADERS)
# ============================================================
def get_vip_week_index(now: datetime | None = None) -> int:
    """
    Retourne:
    0 si pas commencé
    1 si dans la fenêtre S1 (14 jours)
    2..12 ensuite par tranches de 7 jours
    """
    now = now or now_fr()

    if now < W1_START:
        return 0
    if now < W2_START:
        return 1

    weeks_after = int((now - W2_START) // timedelta(days=7))
    wk = 2 + weeks_after
    return min(12, wk)


def get_week_window(week: int | None = None, now: datetime | None = None) -> tuple[datetime, datetime, int]:
    """
    Retourne (start, end, week_index)
    - Si week=None: calcule la semaine actuelle
    - end = borne de fin exclusive (pratique pour comparaisons)
    """
    now = now or now_fr()

    wk = week if week is not None else get_vip_week_index(now)

    if wk <= 0:
        # fenêtre vide (pas lancé)
        return (W1_START, W1_START, 0)

    if wk == 1:
        start = W1_START
        end = W2_START
        return (start, end, 1)

    start = W2_START + timedelta(days=7 * (wk - 2))
    end = start + timedelta(days=7)
    return (start, end, wk)

def safe_ws(title: str):
    try:
        return ws(title)
    except Exception as e:
        return None

def get_current_week_window(now: datetime | None = None) -> tuple[datetime | None, datetime | None, int]:
    """Retourne (start, end, week) pour maintenant."""
    now = now or now_fr()
    wk = get_vip_week_index(now)
    if wk == 0:
        return None, None, 0
    start, end = get_week_window_by_week(wk)
    return start, end, wk

def code_exists(code: str) -> bool:
    _, r = find_vip_row_by_code(code)
    return r is not None

def mikasa_ban_block_reaction() -> str:
    return random.choice([
        "😾 **Mikasa hérisse les poils.** Ce nom est déjà sur sa liste noire.",
        "🐾 *Tsssk…* **La cave a déjà une place réservée pour ce nom.**",
        "🕯️ **Mikasa pose une patte sur le registre.** Refus immédiat.",
        "😼 **Mikasa ne discute pas avec la cave.**",
        "😾 *Hssss…* **Impossible.**",
    ])

def headers_of(ws) -> List[str]:
    return [h.strip() for h in ws.row_values(1)]

def update_cell_by_header(ws, row_i: int, header_name: str, value: Any):
    hdr = headers_of(ws)
    if header_name not in hdr:
        raise RuntimeError(f"Colonne `{header_name}` introuvable dans {ws.title}")
    col = hdr.index(header_name) + 1
    ws.update_cell(row_i, col, value)

def append_row_by_headers(ws, data: Dict[str, Any]):
    hdr = headers_of(ws)
    row = [""] * len(hdr)
    for k, v in data.items():
        if k in hdr:
            row[hdr.index(k)] = v
    ws.append_row(row, value_input_option="RAW")

async def reply_ephemeral(interaction: discord.Interaction, content: str, embed: discord.Embed | None = None):
    if interaction.response.is_done():
        await interaction.followup.send(content=content, embed=embed, ephemeral=True)
    else:
        await interaction.response.send_message(content=content, embed=embed, ephemeral=True)

# ============================================================
# 5) NIVEAUX
# ============================================================
def get_levels() -> List[Tuple[int, int, str]]:
    rows = ws_niveaux.get_all_records()
    levels: List[Tuple[int, int, str]] = []
    for r in rows:
        try:
            lvl = int(r["niveau"])
            pts = int(r["points_min"])
            av = str(r.get("avantages", "")).strip()
            levels.append((lvl, pts, av))
        except Exception:
            continue
    if not levels:
        return [(1, 0, "")]
    levels.sort(key=lambda x: x[1])
    return levels

def calc_level(points: int) -> int:
    lvl = 1
    for n, pmin, _ in get_levels():
        if points >= pmin:
            lvl = n
    return lvl

def get_level_info(lvl: int) -> Tuple[int, str]:
    for n, pmin, av in get_levels():
        if n == lvl:
            return pmin, av
    return 0, ""

def get_next_level(lvl: int):
    levels = get_levels()
    for i, (n, pmin, av) in enumerate(levels):
        if n == lvl:
            if i + 1 < len(levels):
                return levels[i + 1]
            return None
    for n, pmin, av in levels:
        if n > lvl:
            return (n, pmin, av)
    return None

def split_avantages(raw: str) -> List[str]:
    raw = (raw or "").strip()
    if not raw:
        return []
    return [p.strip() for p in raw.split("|") if p.strip()]

def get_all_unlocked_advantages(current_level: int) -> str:
    all_adv = []
    for lvl in range(1, current_level + 1):
        _, raw = get_level_info(lvl)
        all_adv.extend(split_avantages(raw))
    if not all_adv:
        return "✅ (Aucun avantage débloqué pour le moment)"
    seen = set()
    uniq = []
    for a in all_adv:
        if a not in seen:
            seen.add(a)
            uniq.append(a)
    return "\n".join([f"✅ {a}" for a in uniq])

def progress_bar(current: int, target: int, width: int = 14) -> str:
    if target <= 0:
        return "█" * width
    ratio = max(0.0, min(1.0, current / target))
    filled = int(round(ratio * width))
    return "█" * filled + "░" * (width - filled)


# ============================================================
# 6) VIP QUERIES
# ============================================================
def get_all_vips() -> List[Dict[str, Any]]:
    return ws_vip.get_all_records()

def find_vip_row_by_code(code_vip: str) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
    code = normalize_code(code_vip)
    rows = ws_vip.get_all_records()
    for idx, r in enumerate(rows, start=2):
        if normalize_code(str(r.get("code_vip", ""))) == code:
            return idx, r
    return None, None

def find_vip_row_by_discord_id(discord_id: int) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
    rows = ws_vip.get_all_records()
    for idx, r in enumerate(rows, start=2):
        if str(r.get("discord_id", "")).strip() == str(discord_id):
            return idx, r
    return None, None

def find_vip_row_by_pseudo(pseudo: str) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
    target = normalize_name(pseudo)
    rows = ws_vip.get_all_records()
    for idx, r in enumerate(rows, start=2):
        if normalize_name(str(r.get("pseudo", ""))) == target:
            return idx, r
    return None, None

def find_vip_row_by_code_or_pseudo(term: str) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
    if not term:
        return None, None
    t = term.strip()
    if t.upper().startswith("SUB-"):
        return find_vip_row_by_code(t)
    # sinon pseudo
    return find_vip_row_by_pseudo(t)

def get_rank_among_active(code_vip: str) -> Tuple[int, int]:
    code = normalize_code(code_vip)
    rows = ws_vip.get_all_records()
    active = []
    for r in rows:
        status = str(r.get("status", "ACTIVE")).strip().upper()
        if status != "ACTIVE":
            continue
        c = normalize_code(str(r.get("code_vip", "")))
        try:
            pts = int(r.get("points", 0))
        except Exception:
            pts = 0
        active.append((pts, c))
    active.sort(key=lambda x: x[0], reverse=True)
    total = len(active)
    rank = 0
    for i, (_, c) in enumerate(active, start=1):
        if c == code:
            rank = i
            break
    return rank, total

def log_rows_for_vip(code_vip: str) -> List[Dict[str, Any]]:
    code = normalize_code(code_vip)
    out = []
    for r in ws_log.get_all_records():
        c = normalize_code(str(r.get("code_vip", "")))
        if c == code:
            out.append(r)
    return out

def parse_iso_dt(s: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.astimezone(PARIS_TZ)
    except Exception:
        return None

def get_last_actions(code_vip: str, n: int = 3):
    items = []
    for r in log_rows_for_vip(code_vip):
        t = str(r.get("timestamp", "")).strip()
        dt = parse_iso_dt(t)
        if not dt:
            continue
        a = str(r.get("action_key", r.get("action", ""))).strip().upper()
        try:
            qty = int(r.get("quantite", r.get("qty", 1)))
        except Exception:
            qty = 1
        try:
            pts_add = int(r.get("delta_points", r.get("delta", 0)))
        except Exception:
            pts_add = 0
        reason = str(r.get("raison", r.get("reason", "")) or "").strip()
        items.append((dt, a, qty, pts_add, reason))
    items.sort(key=lambda x: x[0], reverse=True)
    return items[:n]


# ============================================================
# 7) ACTIONS + LIMITES
# ============================================================
def get_actions_map() -> Dict[str, Dict[str, Any]]:
    rows = ws_actions.get_all_records()
    m: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        key = str(r.get("action_key", "")).strip().upper()
        if not key:
            continue
        try:
            pu = int(r.get("points_unite", 0))
        except Exception:
            pu = 0
        m[key] = {
            "description": str(r.get("description", "")).strip(),
            "points_unite": pu,
            "limite": str(r.get("limite", "")).strip(),
            "regles": str(r.get("regles", "")).strip(),
        }
    return m

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
    candidate = now.replace(hour=17, minute=0, second=0, microsecond=0)
    days_back = (candidate.weekday() - target_weekday) % 7
    candidate = candidate - timedelta(days=days_back)
    if now < candidate:
        candidate -= timedelta(days=7)
    return candidate

def parse_bootstrap_end() -> Optional[datetime]:
    s = (os.getenv("CHALLENGE_BOOTSTRAP_END") or "").strip()
    if not s:
        return None
    try:
        dt = datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=PARIS_TZ)
        return dt
    except Exception:
        return None

def challenge_week_window(now: Optional[datetime] = None) -> Tuple[datetime, datetime]:
    now = now or now_fr()
    if now.tzinfo is None:
        now = now.replace(tzinfo=PARIS_TZ)

    bootstrap_end = parse_bootstrap_end()
    if bootstrap_end and now < bootstrap_end:
        start = last_friday_17(now)
        end = bootstrap_end
        return start, end

    start = last_friday_17(now)
    end = start + timedelta(days=7)
    return start, end

def count_usage(code_vip: str, action_key: str, start_dt: datetime, end_dt: datetime, tag_prefix: Optional[str] = None, tag_value: Optional[str] = None) -> int:
    action = (action_key or "").strip().upper()
    rows = log_rows_for_vip(code_vip)
    total = 0
    for r in rows:
        dt = parse_iso_dt(str(r.get("timestamp", "")).strip())
        if not dt:
            continue
        if not (start_dt <= dt < end_dt):
            continue
        a = str(r.get("action_key", "")).strip().upper()
        if a != action:
            continue
        raison = str(r.get("raison", "") or "").strip()
        if tag_prefix and tag_value:
            got = extract_tag(raison, tag_prefix)
            if not got or got.lower() != tag_value.lower():
                continue
        try:
            q = int(r.get("quantite", 1))
        except Exception:
            q = 1
        total += q
    return total

def check_action_limit(code_vip: str, action_key: str, qty: int, reason: str, author_is_hg: bool) -> Tuple[bool, str, bool]:
    actions = get_actions_map()
    row = actions.get((action_key or "").strip().upper())
    if not row:
        return False, "Action inconnue dans l’onglet ACTIONS.", False

    lim_raw = str(row.get("limite", "")).strip().lower()

    if ("illimit" in lim_raw) or (lim_raw == ""):
        return True, "", False

    start, end = challenge_week_window()

    ev = extract_tag(reason or "", "event:")
    poche = extract_tag(reason or "", "poche:")

    # 1 / semaine, 4 / semaine...
    if "semaine" in lim_raw and "/" in lim_raw:
        try:
            max_per_week = int(lim_raw.split("/")[0].strip())
        except Exception:
            max_per_week = 1

        used = count_usage(code_vip, action_key, start, end)
        if used + qty <= max_per_week:
            return True, "", False

        if author_is_hg:
            return False, f"Limite hebdo atteinte (**{used}/{max_per_week}**). HG peut forcer.", True
        return False, f"😾 Limite hebdo atteinte (**{used}/{max_per_week}**).", False

    if "par event" in lim_raw:
        if not ev:
            return False, "😾 Ajoute `event:NomEvent` dans la raison (ou utilise `!vip_event`).", False
        used = count_usage(
            code_vip, action_key,
            start_dt=datetime.min.replace(tzinfo=PARIS_TZ),
            end_dt=datetime.max.replace(tzinfo=PARIS_TZ),
            tag_prefix="event:", tag_value=ev
        )
        if used + qty <= 1:
            return True, "", False
        if author_is_hg:
            return False, f"Déjà validé pour **event:{ev}**. HG peut forcer.", True
        return False, f"😾 Déjà validé pour **event:{ev}**.", False

    if "par poche" in lim_raw:
        if not poche:
            return False, "😾 Ajoute `poche:XXX` dans la raison.", False
        used = count_usage(
            code_vip, action_key,
            start_dt=datetime.min.replace(tzinfo=PARIS_TZ),
            end_dt=datetime.max.replace(tzinfo=PARIS_TZ),
            tag_prefix="poche:", tag_value=poche
        )
        if used + qty <= 1:
            return True, "", False
        if author_is_hg:
            return False, f"Déjà validé pour **poche:{poche}**. HG peut forcer.", True
        return False, f"😾 Déjà validé pour **poche:{poche}**.", False

    if "a valider" in lim_raw:
        return True, "", False

    if "selon" in lim_raw:
        if author_is_hg:
            return True, "", False
        return False, "😾 Cette action nécessite validation HG (SELON RÈGLES).", False

    return True, "", False


def add_points_by_action(code_vip: str, action_key: str, qty: int, staff_id: int, reason: str, author_is_hg: bool = False):
    action_key = (action_key or "").strip().upper()
    code = normalize_code(code_vip)

    if not author_is_hg and action_key not in EMPLOYEE_ALLOWED_ACTIONS:
        return False, "😾 Action réservée aux HG. Employés: ACHAT, RECYCLAGE."

    ok_lim, msg_lim, needs_confirm = check_action_limit(code, action_key, qty, reason or "", author_is_hg)
    if not ok_lim:
        if needs_confirm:
            return False, msg_lim + " Tape `!vipforce CODE ACTION QTE ...` (HG) pour forcer."
        return False, msg_lim

    if qty <= 0:
        return False, "La quantité doit être > 0."

    row_i, vip = find_vip_row_by_code(code)
    if not row_i or not vip:
        return False, "Code VIP introuvable."

    status = str(vip.get("status", "ACTIVE")).strip().upper()
    if status != "ACTIVE":
        return False, "VIP désactivé."

    actions = get_actions_map()
    if action_key not in actions:
        return False, f"Action inconnue: {action_key}. Utilise `!vipactions`."

    pu = int(actions[action_key]["points_unite"])
    delta = pu * qty

    old_points = int(vip.get("points", 0))
    new_points = old_points + delta
    old_level = calc_level(old_points)
    new_level = calc_level(new_points)

    ws_vip.batch_update([
        {"range": f"D{row_i}", "values": [[new_points]]},
        {"range": f"E{row_i}", "values": [[new_level]]},
    ])

    # LOG (headers d’après ta capture)
    ws_log.append_row([
        now_iso(),              # timestamp
        str(staff_id),          # staff_id
        code,                   # code_vip
        action_key,             # action_key
        qty,                    # quantite
        pu,                     # points_unite
        delta,                  # delta_points
        reason or "",           # raison
    ])

    return True, (delta, new_points, old_level, new_level)


# ============================================================
# 8) CARTES VIP (S3 SIGNED URL + PNG)
# ============================================================
def get_s3_client():
    return boto3.client(
        "s3",
        endpoint_url=AWS_ENDPOINT_URL if AWS_ENDPOINT_URL else None,
        aws_access_key_id=AWS_ACCESS_KEY_ID or None,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY or None,
        region_name=AWS_DEFAULT_REGION or "auto",
        config=Config(signature_version="s3v4"),
    )

def object_exists_in_bucket(key: str) -> bool:
    if not AWS_S3_BUCKET_NAME:
        return False
    try:
        s3 = get_s3_client()
        s3.head_object(Bucket=AWS_S3_BUCKET_NAME, Key=key)
        return True
    except ClientError:
        return False

def generate_signed_url(key: str, expires_seconds: int = 3600) -> Optional[str]:
    if not key or not AWS_S3_BUCKET_NAME:
        return None
    if not object_exists_in_bucket(key):
        return None
    s3 = get_s3_client()
    return s3.generate_presigned_url(
        ClientMethod="get_object",
        Params={"Bucket": AWS_S3_BUCKET_NAME, "Key": key},
        ExpiresIn=int(expires_seconds),
    )

def upload_png_to_bucket(png_bytes: bytes, object_key: str) -> str:
    if not AWS_S3_BUCKET_NAME:
        raise RuntimeError("AWS_S3_BUCKET_NAME manquant")

    s3 = get_s3_client()
    extra = {"ContentType": "image/png"}
    extra_try_acl = dict(extra)
    extra_try_acl["ACL"] = "public-read"

    try:
        s3.put_object(Bucket=AWS_S3_BUCKET_NAME, Key=object_key, Body=png_bytes, **extra_try_acl)
    except ClientError:
        s3.put_object(Bucket=AWS_S3_BUCKET_NAME, Key=object_key, Body=png_bytes, **extra)

    base = (AWS_ENDPOINT_URL or "").rstrip("/")
    return f"{base}/{AWS_S3_BUCKET_NAME}/{object_key}"

def generate_vip_card_image(code_vip: str, full_name: str, dob: str, phone: str, bleeter: str) -> bytes:
    img = Image.open(VIP_TEMPLATE_PATH).convert("RGBA")
    draw = ImageDraw.Draw(img)

    title_font = ImageFont.truetype(VIP_FONT_PATH, 56)
    font_name  = ImageFont.truetype(VIP_FONT_PATH, 56)
    font_line  = ImageFont.truetype(VIP_FONT_PATH, 38)
    font_id    = ImageFont.truetype(VIP_FONT_PATH, 46)

    white  = (245, 245, 245, 255)
    red    = (220, 30, 30, 255)
    shadow = (0, 0, 0, 160)

    def shadow_text(x, y, text, font, fill):
        draw.text((x+2, y+2), text, font=font, fill=shadow)
        draw.text((x, y), text, font=font, fill=fill)

    # Titre VIP WINTER EDITION (centré)
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


# ============================================================
# 9) DEFIS (SHEET DEFIS d’après ta capture)
# ============================================================
def week_key_for(k: int) -> str:
    return f"W{k:02d}"

def week_label_for(k: int) -> str:
    return f"Semaine {k}/12"

# Début “challenge week” : basé sur fenêtre vendredi 17h -> vendredi suivant 17h
def current_challenge_week_number(now: Optional[datetime] = None) -> int:
    now = now or now_fr()
    start = last_friday_17(now)
    # Semaine 1 = bootstrap jusqu’à CHALLENGE_BOOTSTRAP_END si présent
    bootstrap_end = parse_bootstrap_end()
    if bootstrap_end and now < bootstrap_end:
        return 1
    # Sinon on boucle 1..12 en partant de la première semaine “normale”
    # Simple: on compte les semaines depuis un point de référence (bootstrap_end si existe, sinon start).
    ref = bootstrap_end or start
    weeks_since = int((start - ref).total_seconds() // (7 * 24 * 3600))
    wk = ((weeks_since) % 12) + 1
    return wk

def defis_done_count(row: Dict[str, Any]) -> int:
    return sum(1 for k in ["d1", "d2", "d3", "d4"] if str(row.get(k, "")).strip() != "")

def get_defis_row(code_vip: str, wk_key: str) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
    rows = ws_defis.get_all_records()
    code = normalize_code(code_vip)
    for idx, r in enumerate(rows, start=2):
        if normalize_code(str(r.get("code_vip", ""))) == code and str(r.get("week_key", "")).strip() == wk_key:
            return idx, r
    return None, None

def ensure_defis_row(code_vip: str, wk_key: str, wk_label: str) -> Tuple[int, Dict[str, Any]]:
    row_i, row = get_defis_row(code_vip, wk_key)
    if row_i and row:
        return row_i, row
    # headers DEFIS: week_key, code_vip, d1..d4, completed_at, completed_by, d_notes, week_label
    ws_defis.append_row([wk_key, normalize_code(code_vip), "", "", "", "", "", "", "", wk_label])
    row_i2, row2 = get_defis_row(code_vip, wk_key)
    if not row_i2 or not row2:
        raise RuntimeError("Impossible de créer/récupérer la ligne DEFIS.")
    return row_i2, row2

def get_week_tasks_for_view(wk: int) -> List[str]:
    tasks = WEEKLY_CHALLENGES.get(wk, [])
    if wk == 12:
        if not tasks:
            return ["(Aucun défi configuré)"] * 12
        if len(tasks) == 1:
            return [tasks[0]] * 12
        return tasks[:12]
    tasks = tasks[:4]
    while len(tasks) < 4:
        tasks.append("(Défi non configuré)")
    return tasks

# ============================================================
# PATCH: SLASH TIMEOUT SAFETY + ERROR HANDLER
# ============================================================
async def defer_ephemeral(interaction: discord.Interaction):
    """Ack rapide pour éviter 'application did not respond'."""
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    # Affiche une erreur lisible en privé au lieu de "did not respond"
    msg = f"❌ Erreur slash: `{type(error).__name__}`"
    # Optionnel: détails
    # msg += f"\n`{error}`"
    try:
        await reply_ephemeral(interaction, msg)
    except Exception:
        try:
            await interaction.followup.send(msg, ephemeral=True)
        except Exception:
            pass

# ============================================================
# 10) DISCORD BOT + PRIVACY (slash ephemeral + fallback DM)
# ============================================================
# ============================================================
# /vip GROUP (slash)
# ============================================================

def is_hg(member: discord.Member) -> bool:
    return any(r.id == HG_ROLE_ID for r in member.roles)

@bot.tree.command(name="vipactions", description="Liste des actions et points (staff).", guild=discord.Object(id=GUILD_ID))
async def slash_vipactions(interaction: discord.Interaction):
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return await reply_ephemeral(interaction, "❌ Utilisable en serveur.")
    if not is_employee(interaction.user) and not is_hg(interaction.user):
        return await reply_ephemeral(interaction, "⛔ Réservé staff.")

    actions = get_actions_map()
    is_hg_user = is_hg(interaction.user)

    lines = []
    for k in sorted(actions.keys()):
        if (not is_hg_user) and (k not in EMPLOYEE_ALLOWED_ACTIONS):
            continue
        pu = actions[k]["points_unite"]
        lim = actions[k]["limite"]
        lines.append(f"• **{k}**: {pu} pts/unité" + (f" _(limite: {lim})_" if lim else ""))

    if not lines:
        return await reply_ephemeral(interaction, "😾 Aucune action accessible.")
    return await reply_ephemeral(interaction, "📋 **Actions disponibles:**\n" + "\n".join(lines[:40]))

@vip_group.command(name="actions", description="Liste des actions et points (staff).")
@staff_check()
async def vip_actions_slash(interaction: discord.Interaction):
    await defer_ephemeral(interaction)

    ws_vip = safe_ws("VIP")
    ws_actions = safe_ws("ACTIONS")
    ws_log = safe_ws("LOG")

    if not ws_vip or not ws_actions or not ws_log:
        return await interaction.followup.send(
            "😾 Google Sheets indisponible (quota). Réessaie dans 1-2 min.",
            ephemeral=True
        )
        
    actions = get_actions_map()
    m = staff_member(interaction)
    is_hg_user = bool(m and is_hg(m))

    lines = []
    for k in sorted(actions.keys()):
        if (not is_hg_user) and (k not in EMPLOYEE_ALLOWED_ACTIONS):
            continue
        pu = actions[k]["points_unite"]
        lim = actions[k]["limite"]
        lines.append(f"• **{k}**: {pu} pts/unité" + (f" _(limite: {lim})_" if lim else ""))

    if not lines:
        return await interaction.followup.send("😾 Aucune action accessible.", ephemeral=True)

    await interaction.followup.send("📋 **Actions disponibles :**\n" + "\n".join(lines[:40]), ephemeral=True)

@vip_group.command(name="add", description="Ajouter une action/points à un VIP (staff).")
@app_commands.describe(code_vip="SUB-XXXX-XXXX", action_key="Action (ACHAT, RECYCLAGE...)", quantite="Quantité", raison="Optionnel")
async def vip_add(interaction: discord.Interaction, code_vip: str, action_key: str, quantite: int, raison: str = ""):
    await defer_ephemeral(interaction)

    ws_vip = safe_ws("VIP")
    ws_actions = safe_ws("ACTIONS")
    ws_log = safe_ws("LOG")

    if not ws_vip or not ws_actions or not ws_log:
        return await interaction.followup.send(
            "😾 Google Sheets indisponible (quota). Réessaie dans 1-2 min.",
            ephemeral=True
        )
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return await reply_ephemeral(interaction, "❌ Utilisable en serveur.")
    if not (is_employee(interaction.user) or is_hg(interaction.user)):
        return await reply_ephemeral(interaction, "⛔ Réservé staff.")
    if quantite <= 0:
        return await reply_ephemeral(interaction, "❌ La quantité doit être > 0.")

    if not is_hg(interaction.user) and action_key.upper() not in EMPLOYEE_ALLOWED_ACTIONS:
        return await reply_ephemeral(interaction, "😾 Action réservée HG.\n✅ Employés: ACHAT, RECYCLAGE.")

    ok, res = add_points_by_action(code_vip, action_key, quantite, interaction.user.id, raison, author_is_hg=is_hg(interaction.user))
    if not ok:
        return await reply_ephemeral(interaction, f"❌ {res}")

    delta, new_points, old_level, new_level = res
    msg = f"✅ `{normalize_code(code_vip)}` → **{action_key.upper()}** x{quantite} = **+{delta} pts**\n➡️ Total: **{new_points}** | Niveau: **{new_level}**"
    await reply_ephemeral(interaction, msg)

    if new_level > old_level:
        await announce_level_up_async(normalize_code(code_vip), "VIP", old_level, new_level)
        
@staff_check()
@app_commands.describe(code_vip="Code VIP SUB-XXXX-XXXX", action_key="Action", quantite="Quantité", raison="Optionnel")
async def vip_add_slash(interaction: discord.Interaction, code_vip: str, action_key: str, quantite: int, raison: str = ""):
    await defer_ephemeral(interaction)

    m = staff_member(interaction)
    author_is_hg = bool(m and is_hg(m))

    if quantite <= 0:
        return await interaction.followup.send("❌ Quantité doit être > 0.", ephemeral=True)

    # employé limité
    if (not author_is_hg) and action_key.upper() not in EMPLOYEE_ALLOWED_ACTIONS:
        return await interaction.followup.send("😾 Action réservée HG.\n✅ Employés: ACHAT, RECYCLAGE.", ephemeral=True)

    ok, res = add_points_by_action(code_vip, action_key, quantite, interaction.user.id, raison, author_is_hg=author_is_hg)
    if not ok:
        return await interaction.followup.send(f"❌ {res}", ephemeral=True)

    delta, new_points, old_level, new_level = res
    msg = f"✅ `{normalize_code(code_vip)}` → **{action_key.upper()}** x{quantite} = **+{delta} pts**\n➡️ Total: **{new_points}** | Niveau: **{new_level}**"
    await interaction.followup.send(msg, ephemeral=True)

    if new_level > old_level:
        # annonce publique
        row_i, vip = find_vip_row_by_code(code_vip)
        pseudo = vip.get("pseudo", "VIP") if vip else "VIP"
        await announce_level_up_async(normalize_code(code_vip), pseudo, old_level, new_level)

@vip_group.command(name="create", description="Créer un profil VIP (staff).")
@staff_check()
@app_commands.describe(
    pseudo="Nom/Pseudo RP (obligatoire)",
    membre="Optionnel: lier directement à un membre Discord",
    bleeter="Optionnel",
    dob="Optionnel: JJ/MM/AAAA",
    phone="Optionnel",
    note="Optionnel: note interne (log)"
)
async def vip_create_slash(
    interaction: discord.Interaction,
    pseudo: str,
    membre: Optional[discord.Member] = None,
    bleeter: str = "",
    dob: str = "",
    phone: str = "",
    note: str = ""
):
    await defer_ephemeral(interaction)

    # ✅ AJOUT ICI (et seulement ici)
    w = safe_ws("VIP")
    w_ban = safe_ws("VIP_BAN_CREATE")
    w_log = safe_ws("LOG")

    if not w or not w_ban or not w_log:
        return await interaction.followup.send(
            "😾 Google Sheets indisponible (quota). Réessaie dans 1–2 minutes.",
            ephemeral=True
        )

    # --- ensuite TON code existant ---
    pseudo_clean = display_name((pseudo or "").strip())
    if not pseudo_clean:
        return await interaction.followup.send("❌ Pseudo vide.", ephemeral=True)

    # BAN CHECK (VIP_BAN_CREATE)
    banned, ban_reason = check_banned_for_create(
        pseudo=pseudo_clean,
        discord_id=str(membre.id) if membre else ""
    )

    if banned:
        log_create_blocked(interaction.user.id, pseudo_clean, str(membre.id) if membre else "", ban_reason or "Match VIP_BAN_CREATE")
        return await interaction.followup.send(mikasa_ban_block_reaction(), ephemeral=True)

    # déjà lié ?
    if membre:
        existing_row, _ = find_vip_row_by_discord_id(membre.id)
        if existing_row:
            return await interaction.followup.send("😾 Ce membre a déjà un VIP lié.", ephemeral=True)

    # code unique
    code = gen_code()
    while True:
        r, _ = find_vip_row_by_code(code)
        if not r:
            break
        code = gen_code()

    points = 0
    niveau = calc_level(points)
    created_at = now_iso()

    # INSERT VIP (safe headers)
    append_row_by_headers(ws_vip, {
        "code_vip": code,
        "discord_id": str(membre.id) if membre else "",
        "pseudo": pseudo_clean,
        "points": points,
        "niveau": niveau,
        "created_at": created_at,
        "created_by": str(interaction.user.id),
        "status": "ACTIVE",
        "bleeter": (bleeter or "").strip(),
        "dob": (dob or "").strip(),
        "phone": (phone or "").strip(),
        # card_* restent vides
    })

    # LOG
    append_row_by_headers(ws_log, {
        "timestamp": created_at,
        "staff_id": str(interaction.user.id),
        "code_vip": code,
        "action_key": "CREATE",
        "quantite": 1,
        "points_unite": 0,
        "delta_points": 0,
        "raison": f"Création VIP pour {pseudo_clean}" + (f" | note:{note}" if note else "")
    })

    msg = f"✅ Profil créé : **{pseudo_clean}**\n🎴 Code: `{code}`"
    if membre:
        msg += f"\n🔗 Lié à: {membre.mention}"
    await interaction.followup.send(msg, ephemeral=True)

@vip_group.command(name="help", description="Aide interactive VIP/Staff.")
@app_commands.describe(section="vip | staff | defi | tout")
async def vip_help_slash(interaction: discord.Interaction, section: str = "tout"):
    await defer_ephemeral(interaction)

    ws_vip = safe_ws("VIP")
    ws_actions = safe_ws("ACTIONS")
    ws_log = safe_ws("LOG")

    if not ws_vip or not ws_actions or not ws_log:
        return await interaction.followup.send(
            "😾 Google Sheets indisponible (quota). Réessaie dans 1-2 min.",
            ephemeral=True
        )
    is_staff = is_staff_slash(interaction)
    section = (section or "tout").lower().strip()

    def mention(path: str) -> str:
        # path ex: "vip add" ou "vip help"
        parts = path.split()
        cmd = bot.tree.get_command(parts[0])
        if not cmd:
            return f"`/{path}`"
        if len(parts) == 1:
            return cmd.mention
        sub = cmd.get_command(parts[1]) if hasattr(cmd, "get_command") else None
        return sub.mention if sub else f"`/{path}`"

    vip_lines = [
        f"{mention('niveau')} — Voir tes points/niveau (privé)",
        f"{mention('defistatus')} — Voir tes défis (privé)",
    ]
    staff_lines = [
        f"{mention('vip create')} — Créer un profil VIP",
        f"{mention('vip add')} — Ajouter des points via action",
        f"{mention('vip actions')} — Liste actions & points",
    ]
    defi_lines = [
        f"`!defi` — (HG) panel défis (tu peux le migrer plus tard en slash view)",
        f"`!defiweek` — (HG) annonce hebdo",
    ]

    embed = discord.Embed(
        title="📌 Aide SubUrban VIP",
        description="Clique sur une commande pour l’ouvrir.",
    )
    embed.set_footer(text="Astuce: les commandes staff répondent en privé (ephemeral).")

    if section in ("tout", "vip"):
        embed.add_field(name="🧍 VIP", value="\n".join(vip_lines), inline=False)

    if section in ("tout", "defi"):
        embed.add_field(name="🎯 Défis", value="\n".join(defi_lines), inline=False)

    if section in ("tout", "staff"):
        embed.add_field(name="🛠️ Staff", value="\n".join(staff_lines) if is_staff else "⛔ Visible uniquement au staff.", inline=False)

    await interaction.followup.send(embed=embed, ephemeral=True)


@vip_group.command(name="force", description="Forcer une action (HG).")
@app_commands.describe(code_vip="SUB-XXXX-XXXX", action_key="Action", quantite="Quantité", raison="Optionnel")
async def vip_force(interaction: discord.Interaction, code_vip: str, action_key: str, quantite: int, raison: str = "HG_FORCE"):
    await defer_ephemeral(interaction)

    ws_vip = safe_ws("VIP")
    ws_actions = safe_ws("ACTIONS")
    ws_log = safe_ws("LOG")

    if not ws_vip or not ws_actions or not ws_log:
        return await interaction.followup.send(
            "😾 Google Sheets indisponible (quota). Réessaie dans 1-2 min.",
            ephemeral=True
        )
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return await reply_ephemeral(interaction, "❌ Utilisable en serveur.")
    if not is_hg(interaction.user):
        return await reply_ephemeral(interaction, "⛔ Réservé HG.")

    ok, res = add_points_by_action(code_vip, action_key, quantite, interaction.user.id, raison, author_is_hg=True)
    if not ok:
        return await reply_ephemeral(interaction, f"❌ {res}")

    delta, new_points, old_level, new_level = res
    await reply_ephemeral(interaction, f"✅ Forcé (HG): **{action_key.upper()}** x{quantite} = **+{delta} pts**\n➡️ Total: **{new_points}** | Niveau: **{new_level}**")

@vip_group.command(name="edit", description="Modifier dob/phone/bleeter (staff).")
@app_commands.describe(code_vip="SUB-XXXX-XXXX", champ="dob|phone|bleeter", valeur="Nouvelle valeur")
async def vip_edit(interaction: discord.Interaction, code_vip: str, champ: str, valeur: str):
    await defer_ephemeral(interaction)

    ws_vip = safe_ws("VIP")
    ws_actions = safe_ws("ACTIONS")
    ws_log = safe_ws("LOG")

    if not ws_vip or not ws_actions or not ws_log:
        return await interaction.followup.send(
            "😾 Google Sheets indisponible (quota). Réessaie dans 1-2 min.",
            ephemeral=True
        )
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return await reply_ephemeral(interaction, "❌ Utilisable en serveur.")
    if not (is_employee(interaction.user) or is_hg(interaction.user)):
        return await reply_ephemeral(interaction, "⛔ Réservé staff.")

    champ = champ.lower().strip()
    if champ not in {"dob", "phone", "bleeter"}:
        return await reply_ephemeral(interaction, "❌ champ doit être: dob, phone, bleeter")

    row_i, vip = find_vip_row_by_code(code_vip)
    if not row_i or not vip:
        return await reply_ephemeral(interaction, "❌ Code VIP introuvable.")

    update_cell_by_header(ws_vip, row_i, champ, valeur.strip())
    await reply_ephemeral(interaction, f"✅ `{champ}` mis à jour pour **{display_name(vip.get('pseudo','VIP'))}** → `{valeur.strip()}`")

@vip_group.command(name="card_generate", description="Générer la carte VIP (staff).")
@app_commands.describe(code_vip="SUB-XXXX-XXXX")
async def vip_card_generate(interaction: discord.Interaction, code_vip: str):
    await defer_ephemeral(interaction)

    ws_vip = safe_ws("VIP")
    ws_actions = safe_ws("ACTIONS")
    ws_log = safe_ws("LOG")

    if not ws_vip or not ws_actions or not ws_log:
        return await interaction.followup.send(
            "😾 Google Sheets indisponible (quota). Réessaie dans 1-2 min.",
            ephemeral=True
        )
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return await reply_ephemeral(interaction, "❌ Utilisable en serveur.")
    if not (is_employee(interaction.user) or is_hg(interaction.user)):
        return await reply_ephemeral(interaction, "⛔ Réservé staff.")

    row_i, vip = find_vip_row_by_code(code_vip)
    if not row_i or not vip:
        return await reply_ephemeral(interaction, "❌ Code VIP introuvable.")

    full_name = str(vip.get("pseudo", "")).strip()
    dob = str(vip.get("dob", "")).strip()
    phone = str(vip.get("phone", "")).strip()
    bleeter = str(vip.get("bleeter", "")).strip()

    if not dob or not phone:
        return await reply_ephemeral(interaction, "😾 Impossible: il manque **DN** ou **Téléphone**.")

    await reply_ephemeral(interaction, "🖨️ Mikasa imprime… *prrrt prrrt* 🐾")

    png = generate_vip_card_image(normalize_code(code_vip), full_name, dob, phone, bleeter)
    object_key = f"vip_cards/{normalize_code(code_vip)}.png"
    url = upload_png_to_bucket(png, object_key)

    update_cell_by_header(ws_vip, row_i, "card_url", url)
    update_cell_by_header(ws_vip, row_i, "card_generated_at", now_iso())
    update_cell_by_header(ws_vip, row_i, "card_generated_by", str(interaction.user.id))

    file = discord.File(io.BytesIO(png), filename=f"VIP_{normalize_code(code_vip)}.png")
    if interaction.response.is_done():
        await interaction.followup.send(content=f"✅ Carte VIP générée pour **{display_name(full_name)}**\n🔗 {url}", file=file, ephemeral=True)
    else:
        await interaction.response.send_message(content=f"✅ Carte VIP générée pour **{display_name(full_name)}**\n🔗 {url}", file=file, ephemeral=True)

@vip_group.command(name="card_show", description="Afficher une carte VIP (staff).")
@app_commands.describe(query="SUB-XXXX-XXXX ou pseudo")
async def vip_card_show(interaction: discord.Interaction, query: str):
    await defer_ephemeral(interaction)

    ws_vip = safe_ws("VIP")
    ws_actions = safe_ws("ACTIONS")
    ws_log = safe_ws("LOG")

    if not ws_vip or not ws_actions or not ws_log:
        return await interaction.followup.send(
            "😾 Google Sheets indisponible (quota). Réessaie dans 1-2 min.",
            ephemeral=True
        )
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return await reply_ephemeral(interaction, "❌ Utilisable en serveur.")
    if not (is_employee(interaction.user) or is_hg(interaction.user)):
        return await reply_ephemeral(interaction, "⛔ Réservé staff.")

    row_i, vip = find_vip_row_by_code_or_pseudo(query.strip())
    if not row_i or not vip:
        return await reply_ephemeral(interaction, f"❌ Aucun VIP trouvé pour **{query}**.")

    code_vip = normalize_code(str(vip.get("code_vip", "")))
    pseudo = display_name(vip.get("pseudo", query))
    status = str(vip.get("status", "ACTIVE")).strip().upper()
    badge = "🟢" if status == "ACTIVE" else "🔴"

    object_key = f"vip_cards/{code_vip}.png"
    signed = generate_signed_url(object_key, expires_seconds=3600)
    if not signed:
        return await reply_ephemeral(interaction, "😾 Carte introuvable. Génère-la avec `/vip card_generate`.")

    embed = discord.Embed(
        title=f"{badge} Carte VIP de {pseudo}",
        description=f"🎴 Code: `{code_vip}`\n⏳ Lien temporaire (1h): {signed}",
    )
    embed.set_image(url=signed)
    embed.set_footer(text="Mikasa entrouvre la cachette… prrr 🐾")

    await reply_ephemeral(interaction, "", embed=embed)

@vip_group.command(name="event", description="Ajouter une action taggée event: (staff).")
@app_commands.describe(code_vip="SUB-XXXX-XXXX", action_key="Action", quantite="Quantité", event_name="Nom event (ex: LOOKBOOK_JAN)")
async def vip_event(interaction: discord.Interaction, code_vip: str, action_key: str, quantite: int, event_name: str):
    await defer_ephemeral(interaction)

    ws_vip = safe_ws("VIP")
    ws_actions = safe_ws("ACTIONS")
    ws_log = safe_ws("LOG")

    if not ws_vip or not ws_actions or not ws_log:
        return await interaction.followup.send(
            "😾 Google Sheets indisponible (quota). Réessaie dans 1-2 min.",
            ephemeral=True
        )
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return await reply_ephemeral(interaction, "❌ Utilisable en serveur.")
    if not (is_employee(interaction.user) or is_hg(interaction.user)):
        return await reply_ephemeral(interaction, "⛔ Réservé staff.")
    if quantite <= 0:
        return await reply_ephemeral(interaction, "❌ Quantité > 0 obligatoire.")

    reason = f"event:{event_name.replace(' ', '_')}"
    ok, res = add_points_by_action(code_vip, action_key, quantite, interaction.user.id, reason, author_is_hg=is_hg(interaction.user))
    if not ok:
        return await reply_ephemeral(interaction, f"❌ {res}")

    delta, new_points, old_level, new_level = res
    await reply_ephemeral(interaction, f"✅ `{normalize_code(code_vip)}` → **{action_key.upper()}** x{quantite} (**{reason}**) = **+{delta} pts**\n➡️ Total: **{new_points}** | Niveau: **{new_level}**")

@defi_group.command(name="panel", description="Ouvrir le panneau de validation des défis (HG).")
@app_commands.describe(code_vip="SUB-XXXX-XXXX")
async def defi_panel(interaction: discord.Interaction, code_vip: str):
    await defer_ephemeral(interaction)  # ✅ EN PREMIER

    # quota safe (si tu utilises safe_ws)
    w = safe_ws("DEFIS")
    if not w:
        return await interaction.followup.send("😾 Google Sheets indisponible (quota). Réessaie dans 1-2 min.", ephemeral=True)

    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return await reply_ephemeral(interaction, "❌ Utilisable en serveur.")
    if not is_hg(interaction.user):
        return await reply_ephemeral(interaction, "😾 Seuls les HG peuvent valider les défis.")

    code = normalize_code(code_vip)
    wk = current_challenge_week_number()
    wk_key = week_key_for(wk)
    wk_label = week_label_for(wk)

    row_vip_i, vip = find_vip_row_by_code(code)
    if not row_vip_i or not vip:
        return await reply_ephemeral(interaction, "❌ Code VIP introuvable.")

    pseudo = display_name(vip.get("pseudo", "Quelqu’un"))
    row_i, row = ensure_defis_row(code, wk_key, wk_label)

    if wk == 12:
        choices = get_week_tasks_for_view(12)
        view = DefiWeek12View(
            author=interaction.user,
            code=code,
            wk=wk,
            wk_key=wk_key,
            wk_label=wk_label,
            row_i=row_i,
            row=row,
            choices=choices,
            vip_pseudo=pseudo
        )
        emb = view._build_embed()
        await interaction.response.send_message(embed=emb, view=view, ephemeral=True)
        return

    tasks = get_week_tasks_for_view(wk)
    view = DefiValidateView(
        author=interaction.user,
        code=code,
        wk=wk,
        wk_key=wk_key,
        wk_label=wk_label,
        row_i=row_i,
        row=row,
        tasks=tasks,
        vip_pseudo=pseudo
    )
    emb = view._build_embed()
    await interaction.response.send_message(embed=emb, view=view, ephemeral=True)

@defi_group.command(name="top", description="Classement défis semaine en cours (staff).")
@app_commands.describe(limit="3 à 25")
async def defi_top(interaction: discord.Interaction, limit: int = 10):
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return await reply_ephemeral(interaction, "❌ Utilisable en serveur.")
    if not (is_employee(interaction.user) or is_hg(interaction.user)):
        return await reply_ephemeral(interaction, "⛔ Réservé staff.")

    limit = max(3, min(25, int(limit)))

    wk = current_challenge_week_number()
    wk_key = week_key_for(wk)
    wk_label = week_label_for(wk)

    rows = ws_defis.get_all_records()
    pack = []
    for r in rows:
        if str(r.get("week_key", "")).strip() != wk_key:
            continue
        code = str(r.get("code_vip", "")).strip().upper()
        if not code:
            continue
        done = defis_done_count(r)
        completed_at = str(r.get("completed_at", "")).strip()
        _, vip = find_vip_row_by_code(code)
        pseudo = display_name(vip.get("pseudo", code)) if vip else code
        pack.append((done, completed_at, pseudo, code))

    if not pack:
        return await reply_ephemeral(interaction, "📭 Aucun défi enregistré pour cette semaine.")

    pack.sort(key=lambda x: (-x[0], x[1] or "9999", x[2].lower()))
    pack = pack[:limit]

    lines = []
    for i, (done, comp, pseudo, code) in enumerate(pack, start=1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "🏁"
        lines.append(f"{medal} **#{i}** {pseudo} — **{done}/4** (`{code}`)")

    await reply_ephemeral(interaction, f"🏆 **Classement Défis** — {wk_label}\n" + "\n".join(lines))

@defi_group.command(name="week_announce", description="Poster l'annonce de la semaine (HG).")
async def defi_week_announce(interaction: discord.Interaction):
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return await reply_ephemeral(interaction, "❌ Utilisable en serveur.")
    if not is_hg(interaction.user):
        return await reply_ephemeral(interaction, "⛔ Réservé HG.")
    await post_weekly_challenges_announcement()
    await reply_ephemeral(interaction, "✅ Annonce postée. 🐾")

#@cave_group.command(name="list", description="Voir la cave Mikasa (HG).")
#async def cave_list(interaction: discord.Interaction):
 #   if not interaction.guild or not isinstance(interaction.user, discord.Member):
 #       return await reply_ephemeral(interaction, "❌ Utilisable en serveur.")
 #   if not is_hg(interaction.user):
 #       return await reply_ephemeral(interaction, "⛔ Réservé HG.")

 #   rows = ws_ban_create.get_all_records()
  #  if not rows:
  #      return await reply_ephemeral(interaction, "🐱 La cave est vide…")

#    lines = []
 #   for r in rows:
 #       pseudo_ref_raw = str(r.get("pseudo_ref", "")).strip()
 #       if not pseudo_ref_raw:
#            continue
#        aliases_raw = r.get("aliases", "")
#        aliases_list_norm = split_aliases(aliases_raw)
#       aliases_display = ", ".join(display_name(a) for a in aliases_list_norm) if aliases_list_norm else ""
#        pseudo_display = display_name(pseudo_ref_raw)
#        lines.append(f"🔒 **{pseudo_display}**" + (f" _(alias: {aliases_display})_" if aliases_display else ""))

 #   await reply_ephemeral(interaction, "🕯️ **La cave de Mikasa**\n" + "\n".join(lines[:40]))


async def send_private(ctx: commands.Context, content: str = "", embed: Optional[discord.Embed] = None):
    """
    - Si slash (interaction): répond en ephemeral
    - Si message "!" : envoie en DM (privé)
    """
    if ctx.interaction:
        if embed:
            await ctx.interaction.response.send_message(content=content or None, embed=embed, ephemeral=True)
        else:
            await ctx.interaction.response.send_message(content=content, ephemeral=True)
        return

    # message command fallback => DM
    try:
        if embed:
            await ctx.author.send(content=content or None, embed=embed)
        else:
            await ctx.author.send(content=content)
        await ctx.reply(catify("📩 Je t’ai répondu en DM (privé). 🐾"), mention_author=False)
    except Exception:
        await ctx.reply(catify("😾 Impossible de t’envoyer un DM. Active tes MP serveur."), mention_author=False)


def action_icon(a: str) -> str:
    a = (a or "").upper()
    if "ACHAT" in a: return "🛍️"
    if "RECYCL" in a: return "♻️"
    if "EVENT" in a: return "🎫"
    if "CREATE" in a: return "🆕"
    return "🧾"


async def announce_level_up_async(code_vip: str, pseudo: str, old_level: int, new_level: int):
    if not ANNOUNCE_CHANNEL_ID:
        return
    ch = bot.get_channel(int(ANNOUNCE_CHANNEL_ID))
    if not ch:
        return

    pseudo_disp = display_name(pseudo)
    _, raw_av = get_level_info(new_level)
    unlocked = split_avantages(raw_av)
    unlocked_lines = "\n".join([f"✅ {a}" for a in unlocked]) if unlocked else "✅ (Avantages non listés)"

    msg = (
        f"🎊 **LEVEL UP VIP**\n"
        f"👤 **{pseudo_disp}** vient de passer **Niveau {new_level}** !\n\n"
        f"🎁 **Débloque :**\n{unlocked_lines}\n\n"
        f"😼 Mikasa tamponne le registre. *clac* 🐾"
    )
    await ch.send(catify(msg, chance=0.12))


#bot.tree.get_command("vip").get_command("add")
# ============================================================
# 11) SLASH COMMANDS SYNC (GUILD)
# ============================================================
@bot.event
async def on_ready():
    print(f"Mikasa connectée en tant que {bot.user}")

    # sync slash commands sur ton guild test
    try:
        guild = discord.Object(id=GUILD_ID)
        bot.tree.copy_global_to(guild=guild)
        await bot.tree.sync(guild=guild)
        print(f"Slash commands sync sur GUILD_ID={GUILD_ID}")
    except Exception as e:
        print("Sync slash failed:", e)

    # scheduler défi hebdo (vendredi 17:00)
    if not getattr(bot, "_mikasa_scheduler_started", False):
        bot._mikasa_scheduler_started = True
        trigger = CronTrigger(day_of_week="fri", hour=17, minute=0, timezone=PARIS_TZ)
        scheduler.add_job(lambda: bot.loop.create_task(post_weekly_challenges_announcement()), trigger)
        scheduler.start()
        print("Scheduler: annonces hebdo activées (vendredi 17:00).")


@bot.event
async def on_command_error(ctx, error):
    import traceback
    traceback.print_exception(type(error), error, error.__traceback__)

    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.CheckFailure):
        await ctx.reply(catify("⛔ Pas les permissions pour cette commande."), mention_author=False)
        return
    await ctx.reply(catify(f"❌ Erreur: `{type(error).__name__}`"), mention_author=False)


# ============================================================
# 12) COMMANDES CLIENT (PRIVÉES)
# ============================================================
@commands.hybrid_command(name="niveau", description="Voir ton niveau VIP (privé).")
async def niveau(ctx: commands.Context, *, target: Optional[str] = None):
    """
    /niveau -> privé (ephemeral)
    !niveau -> DM privé
    /niveau target (staff only) -> privé
    """
    # CAS 1: sans target = soi-même
    if not target:
        row_i, vip = find_vip_row_by_discord_id(ctx.author.id)
        if not row_i or not vip:
            await send_private(ctx, catify("Tu n'as pas de VIP lié. Va voir un employé SubUrban pour la création."))
            return
    else:
        # target = pseudo ou code -> staff only
        if not (is_employee(ctx.author) or is_hg(ctx.author)):
            await send_private(ctx, catify("⛔ Réservé au staff pour consulter un autre VIP."))
            return
        row_i, vip = find_vip_row_by_code_or_pseudo(target)
        if not row_i or not vip:
            await send_private(ctx, catify(f"❌ Aucun VIP trouvé pour **{display_name(target)}**."))
            return

    points = int(vip.get("points", 0))
    lvl = int(vip.get("niveau", 1))
    created_at = str(vip.get("created_at", "—"))
    pseudo_vip = display_name(vip.get("pseudo", ctx.author.display_name))
    bleeter = str(vip.get("bleeter", "")).strip()
    date_simple = created_at[:10] if len(created_at) >= 10 else created_at

    bleeter_line = f"🛰️ Bleeter : **@{bleeter}**" if bleeter else "🛰️ Bleeter : _non enregistré_"
    unlocked_lines = get_all_unlocked_advantages(lvl)

    code_cur = str(vip.get("code_vip", "")).strip().upper()
    rank, total = get_rank_among_active(code_cur)
    rank_line = f"🏁 Rang: **#{rank}** sur **{total}** VIP actifs" if rank else "🏁 Rang: _non classé_"

    last = get_last_actions(code_cur, n=3)
    if last:
        last_block = "\n".join([f"• {action_icon(a)} **{a}** x{q} → **+{pts_add}** pts" for _dt, a, q, pts_add, _rsn in last])
    else:
        last_block = "_Aucune action récente._"

    nxt = get_next_level(lvl)
    if nxt:
        next_lvl, next_min, next_av = nxt
        missing = max(0, int(next_min) - points)

        cur_min, _ = get_level_info(lvl)
        span = max(1, int(next_min) - int(cur_min))
        into = max(0, points - int(cur_min))
        bar = progress_bar(into, span, width=14)
        pct = int((into / span) * 100) if span > 0 else 100
        pct = max(0, min(100, pct))

        preview = split_avantages(next_av)
        preview_lines = "\n".join([f"🔒 {x}" for x in preview[:2]]) if preview else "🔒 (à venir)"

        next_block = (
            f"⬆️ Prochain: **Niveau {next_lvl}** à **{next_min}** points\n"
            f"📈 Progression: `{bar}` **{pct}%**  (+{missing} pts)\n"
            f"{preview_lines}"
        )
    else:
        next_block = "🏁 **Niveau max atteint**. Respect. 😼"

    msg = (
        f"🎖️ **VIP SubUrban**\n"
        f"👤 **{pseudo_vip}**\n"
        f"{bleeter_line}\n"
        f"📊 Niveau **{lvl}** | **{points}** points\n"
        f"📅 VIP depuis : `{date_simple}`\n"
        f"{rank_line}\n\n"
        f"🧾 **Dernières actions**\n"
        f"{last_block}\n\n"
        f"🎁 **Avantages débloqués**\n"
        f"{unlocked_lines}\n\n"
        f"{next_block}"
    )

    await send_private(ctx, catify(msg, chance=0.18))

bot.add_command(niveau)


@commands.hybrid_command(name="defistatus", description="Voir tes défis de la semaine (privé).")
async def defistatus(ctx: commands.Context, code_vip: Optional[str] = None):
    """
    /defistatus -> privé (ephemeral)
    !defistatus -> DM
    """
    # 1) déterminer code
    if code_vip:
        if not (is_employee(ctx.author) or is_hg(ctx.author)):
            await send_private(ctx, catify("⛔ Réservé staff (employés/HG) pour consulter un autre VIP."))
            return
        code = normalize_code(code_vip)
    else:
        row_i, vip = find_vip_row_by_discord_id(ctx.author.id)
        if not row_i or not vip:
            await send_private(ctx, catify("❌ Aucun VIP lié à ton Discord."))
            return
        code = normalize_code(str(vip.get("code_vip", "")))

    wk = current_challenge_week_number()
    wk_key = week_key_for(wk)
    wk_label = week_label_for(wk)

    row_i, row = ensure_defis_row(code, wk_key, wk_label)

    tasks = WEEKLY_CHALLENGES.get(wk, [])
    done = 0
    lines = []

    if wk == 12:
        done = defis_done_count(row)
        lines.append("🎭 **Semaine 12 (Freestyle)**")
        lines.append(f"➡️ Progression: **{done}/4**")
    else:
        for i in range(1, 5):
            stamp = str(row.get(f"d{i}", "")).strip()
            ok = bool(stamp)
            if ok:
                done += 1
            label = tasks[i-1] if len(tasks) >= i else f"Défi {i}"
            icon = "✅" if ok else "❌"
            lines.append(f"{icon} **{label}**")
        lines.append(f"\n➡️ Progression: **{done}/4**")

    await send_private(ctx, catify(f"📸 **Défis de la semaine ({wk_label})**\n" + "\n".join(lines), chance=0.12))

bot.add_command(defistatus)


# ============================================================
# 13) COMMANDES STAFF (prefix "!" comme chez toi)
# ============================================================
def employee_only():
    async def predicate(ctx: commands.Context):
        return bool(ctx.guild) and is_employee(ctx.author)
    return commands.check(predicate)

def hg_only():
    async def predicate(ctx: commands.Context):
        return bool(ctx.guild) and is_hg(ctx.author)
    return commands.check(predicate)


@bot.command(name="vipactions")
@employee_only()
async def vipactions(ctx):
    if not staff_channel_only(ctx.channel):
        await ctx.reply(catify("😾 Commande utilisable uniquement dans le salon staff."), mention_author=False)
        return

    actions = get_actions_map()
    is_hg_user = is_hg(ctx.author)

    lines = []
    for k in sorted(actions.keys()):
        if not is_hg_user and k not in EMPLOYEE_ALLOWED_ACTIONS:
            continue
        pu = actions[k]["points_unite"]
        lim = actions[k]["limite"]
        if lim:
            lines.append(f"• **{k}**: {pu} pts/unité _(limite: {lim})_")
        else:
            lines.append(f"• **{k}**: {pu} pts/unité")

    if not lines:
        await ctx.reply(catify("😾 Aucune action accessible avec ton grade."), mention_author=False)
        return

    await ctx.reply(catify("📋 **Actions disponibles:**\n" + "\n".join(lines[:40]), chance=0.12), mention_author=False)


@bot.command(name="vip")
@employee_only()
async def vip(ctx, *, raw: str):
    """
    !vip CODE ACTION QTE [raison...]
    Employés: ACHAT/RECYCLAGE uniquement
    HG: tout
    """
    if not staff_channel_only(ctx.channel):
        await ctx.reply(catify("😾 Commande utilisable uniquement dans le salon staff."), mention_author=False)
        return

    raw = (raw or "").strip()
    parts = raw.split()
    if len(parts) < 3:
        await ctx.reply(catify("❌ Utilisation: `!vip CODE ACTION QTE [raison...]`"), mention_author=False)
        return

    code_vip = parts[0]
    action_key = parts[1].strip().upper()
    qty_str = parts[2]
    raison = " ".join(parts[3:]).strip() if len(parts) > 3 else ""

    if not is_hg(ctx.author) and action_key not in EMPLOYEE_ALLOWED_ACTIONS:
        await ctx.reply(catify("😾 Action réservée aux **HG**.\n✅ Employés: **ACHAT**, **RECYCLAGE**."), mention_author=False)
        return

    try:
        qty = int(qty_str)
    except ValueError:
        await ctx.reply(catify("❌ La quantité doit être un nombre."), mention_author=False)
        return

    code_norm = normalize_code(code_vip)
    row_i, vip_row = find_vip_row_by_code(code_norm)
    if not row_i or not vip_row:
        await ctx.reply(catify("❌ Code VIP introuvable."), mention_author=False)
        return

    pseudo = str(vip_row.get("pseudo", "Quelqu’un"))
    author_is_hg = is_hg(ctx.author)

    ok, res = add_points_by_action(code_norm, action_key, qty, ctx.author.id, raison, author_is_hg=author_is_hg)
    if not ok:
        await ctx.reply(catify(f"❌ {res}"), mention_author=False)
        return

    delta, new_points, old_level, new_level = res
    await ctx.reply(
        catify(f"✅ **{display_name(pseudo)}** → **{action_key}** x{qty} = **+{delta} pts**\n➡️ Total: **{new_points}** | Niveau: **{new_level}**", chance=0.18),
        mention_author=False
    )

    if new_level > old_level:
        await announce_level_up_async(code_norm, pseudo, old_level, new_level)


@bot.command(name="vipforce")
@hg_only()
async def vipforce(ctx, code_vip: str, action_key: str, qty: int, *, reason: str = ""):
    if not staff_channel_only(ctx.channel):
        await ctx.reply(catify("😾 Uniquement dans le salon staff."), mention_author=False)
        return
    reason = (reason or "").strip() or "HG_FORCE"
    ok, res = add_points_by_action(code_vip, action_key, qty, ctx.author.id, reason, author_is_hg=True)
    if not ok:
        await ctx.reply(catify(f"❌ {res}"), mention_author=False)
        return
    await ctx.reply(catify(f"✅ Forcé (HG). {res}", chance=0.18), mention_author=False)


@bot.command(name="vipsetdob")
@employee_only()
async def vipsetdob(ctx, code_vip: str = "", dob: str = ""):
    if not staff_channel_only(ctx.channel):
        await ctx.reply(catify("😾 Modifs VIP uniquement dans le salon staff."), mention_author=False)
        return
    if not code_vip or not dob:
        await ctx.reply(catify("❌ Utilisation: `!vipsetdob SUB-XXXX-XXXX 27/12/2004`"), mention_author=False)
        return

    row_i, vip = find_vip_row_by_code(code_vip)
    if not row_i or not vip:
        await ctx.reply(catify("❌ Code VIP introuvable."), mention_author=False)
        return

    update_cell_by_header(ws_vip, row_i, "dob", dob)
    await ctx.reply(catify(f"✅ DN enregistrée pour **{display_name(vip.get('pseudo','VIP'))}** : `{dob}` 🐾", chance=0.18), mention_author=False)


@bot.command(name="vipsetphone")
@employee_only()
async def vipsetphone(ctx, code_vip: str = "", phone: str = ""):
    if not staff_channel_only(ctx.channel):
        await ctx.reply(catify("😾 Modifs VIP uniquement dans le salon staff."), mention_author=False)
        return
    if not code_vip or not phone:
        await ctx.reply(catify("❌ Utilisation: `!vipsetphone SUB-XXXX-XXXX 0612345678`"), mention_author=False)
        return

    row_i, vip = find_vip_row_by_code(code_vip)
    if not row_i or not vip:
        await ctx.reply(catify("❌ Code VIP introuvable."), mention_author=False)
        return

    update_cell_by_header(ws_vip, row_i, "phone", phone)
    await ctx.reply(catify(f"✅ Téléphone enregistré pour **{display_name(vip.get('pseudo','VIP'))}** : `{phone}` 😺", chance=0.18), mention_author=False)


@bot.command(name="vipbleeter")
@employee_only()
async def vipbleeter(ctx, term: str = None, bleeter_pseudo: str = None):
    if not staff_channel_only(ctx.channel):
        await ctx.reply(catify("😾 Modifs VIP uniquement dans le salon staff."), mention_author=False)
        return
    if not term or not bleeter_pseudo:
        await ctx.reply(catify("❌ Utilisation: `!vipbleeter CODE|PSEUDO pseudo_bleeter`"), mention_author=False)
        return

    row_i, vip = find_vip_row_by_code_or_pseudo(term)
    if not row_i or not vip:
        await ctx.reply(catify("❌ VIP introuvable (code ou pseudo incorrect)."), mention_author=False)
        return

    update_cell_by_header(ws_vip, row_i, "bleeter", bleeter_pseudo.strip())
    ws_log.append_row([now_iso(), str(ctx.author.id), normalize_code(vip.get("code_vip","")), "SET_BLEETER", 1, 0, 0, f"Bleeter set to @{bleeter_pseudo.strip()}"])
    await ctx.reply(catify(f"✅ Bleeter de **{display_name(vip.get('pseudo','VIP'))}** mis à jour : **@{bleeter_pseudo.strip()}** 🛰️", chance=0.25), mention_author=False)


@bot.command(name="vipcard")
@employee_only()
async def vipcard(ctx, code_vip: str = ""):
    if not staff_channel_only(ctx.channel):
        await ctx.reply(catify("😾 Les cartes VIP se font uniquement dans le salon staff."), mention_author=False)
        return
    if not code_vip:
        await ctx.reply(catify("❌ Utilisation: `!vipcard SUB-XXXX-XXXX`"), mention_author=False)
        return

    row_i, vip = find_vip_row_by_code(code_vip)
    if not row_i or not vip:
        await ctx.reply(catify("❌ Code VIP introuvable."), mention_author=False)
        return

    full_name = str(vip.get("pseudo", "")).strip()
    dob = str(vip.get("dob", "")).strip()
    phone = str(vip.get("phone", "")).strip()
    bleeter = str(vip.get("bleeter", "")).strip()

    if not dob or not phone:
        await ctx.reply(catify("😾 Impossible: il manque **DN** ou **Téléphone**."), mention_author=False)
        return

    await ctx.reply(catify("🖨️ Mikasa imprime… *prrrt prrrt* 🐾", chance=0.25), mention_author=False)

    png = generate_vip_card_image(normalize_code(code_vip), full_name, dob, phone, bleeter)
    object_key = f"vip_cards/{normalize_code(code_vip)}.png"
    url = upload_png_to_bucket(png, object_key)

    update_cell_by_header(ws_vip, row_i, "card_url", url)
    update_cell_by_header(ws_vip, row_i, "card_generated_at", now_iso())
    update_cell_by_header(ws_vip, row_i, "card_generated_by", str(ctx.author.id))

    file = discord.File(io.BytesIO(png), filename=f"VIP_{normalize_code(code_vip)}.png")
    await ctx.reply(content=catify(f"✅ Carte VIP générée pour **{display_name(full_name)}**\n🔗 {url}", chance=0.18), file=file, mention_author=False)


@bot.command(name="vipcardshow")
@employee_only()
async def vipcardshow(ctx, *, query: str = ""):
    if not staff_channel_only(ctx.channel):
        await ctx.reply(catify("😾 Les cartes VIP se consultent uniquement dans le salon staff."), mention_author=False)
        return
    q = (query or "").strip()
    if not q:
        await ctx.reply(catify("❌ Utilisation: `!vipcardshow SUB-XXXX-XXXX` ou `!vipcardshow PSEUDO`"), mention_author=False)
        return

    row_i, vip = find_vip_row_by_code_or_pseudo(q)
    if not row_i or not vip:
        await ctx.reply(catify(f"❌ Aucun VIP trouvé pour **{q}**."), mention_author=False)
        return

    code_vip = normalize_code(str(vip.get("code_vip", "")))
    pseudo = display_name(vip.get("pseudo", q))
    status = str(vip.get("status", "ACTIVE")).strip().upper()
    badge = "🟢" if status == "ACTIVE" else "🔴"

    object_key = f"vip_cards/{code_vip}.png"
    signed = generate_signed_url(object_key, expires_seconds=3600)
    if not signed:
        await ctx.reply(catify("😾 Carte introuvable. Génère-la avec `!vipcard CODE`."), mention_author=False)
        return

    embed = discord.Embed(
        title=f"{badge} Carte VIP de {pseudo}",
        description=f"🎴 Code: `{code_vip}`\n⏳ Lien temporaire (1h): {signed}",
    )
    embed.set_image(url=signed)
    embed.set_footer(text="Mikasa entrouvre la cachette… prrr 🐾")
    await ctx.reply(embed=embed, mention_author=False)

# ============================================================
# /cave GROUP (HG)
# ============================================================
@cave_group.command(name="list", description="Lister la cave (HG).")
@hg_check()
async def cave_list_slash(interaction: discord.Interaction):
    await defer_ephemeral(interaction)
    rows = ws_ban_create.get_all_records()
    if not rows:
        return await interaction.followup.send("🐱 La cave est vide…", ephemeral=True)

    lines = []
    for r in rows:
        pseudo_ref = str(r.get("pseudo_ref", "")).strip()
        if not pseudo_ref:
            continue
        aliases_norm = split_aliases(r.get("aliases", ""))
        aliases_display = ", ".join(display_name(a) for a in aliases_norm) if aliases_norm else ""
        lines.append(f"🔒 **{display_name(pseudo_ref)}**" + (f" _(alias: {aliases_display})_" if aliases_display else ""))

    await interaction.followup.send("🕯️ **La cave de Mikasa**\n" + "\n".join(lines[:50]), ephemeral=True)

@cave_group.command(name="add", description="Ajouter un nom dans la cave (HG).")
@hg_check()
@app_commands.describe(pseudo="Nom principal", aliases="Optionnel: alias séparés par , ; |", discord_id="Optionnel")
async def cave_add_slash(interaction: discord.Interaction, pseudo: str, aliases: str = "", discord_id: str = ""):
    await defer_ephemeral(interaction)

    pseudo_ref_raw = (pseudo or "").strip()
    if not pseudo_ref_raw:
        return await interaction.followup.send("❌ Il me faut au moins un pseudo.", ephemeral=True)

    pseudo_norm = normalize_name(pseudo_ref_raw)
    aliases_list_norm = split_aliases(aliases)

    # doublon ?
    rows = ws_ban_create.get_all_records()
    for r in rows:
        existing_pseudo = normalize_name(r.get("pseudo_ref", ""))
        existing_aliases = split_aliases(r.get("aliases", ""))
        if pseudo_norm == existing_pseudo or pseudo_norm in existing_aliases:
            return await interaction.followup.send(catify("😾 Ce nom est déjà dans la cave."), ephemeral=True)

    ws_ban_create.append_row([
        pseudo_ref_raw,
        ", ".join(aliases_list_norm),
        (discord_id or "").strip(),
        "BAN_CREATE",
        str(interaction.user.id),
        now_iso(),
        ""
    ])

    await interaction.followup.send(
        catify(f"🔒 **{display_name(pseudo_ref_raw)}** est enfermé dans la cave de Mikasa.", chance=0.4),
        ephemeral=True
    )

@cave_group.command(name="remove", description="Retirer un nom de la cave (HG).")
@hg_check()
@app_commands.describe(term="Pseudo_ref ou un de ses alias")
async def cave_remove_slash(interaction: discord.Interaction, term: str):
    await defer_ephemeral(interaction)

    term_norm = normalize_name(term)
    values = ws_ban_create.get_all_values()
    if not values or len(values) < 2:
        return await interaction.followup.send(catify("🐾 Rien à libérer… la cave est vide."), ephemeral=True)

    header = [h.strip() for h in values[0]]
    data = values[1:]

    if "pseudo_ref" not in header:
        return await interaction.followup.send("❌ Colonne `pseudo_ref` introuvable.", ephemeral=True)

    col_pseudo = header.index("pseudo_ref")
    col_aliases = header.index("aliases") if "aliases" in header else None

    for idx, row in enumerate(data, start=2):
        pseudo_ref_raw = row[col_pseudo] if col_pseudo < len(row) else ""
        pseudo_ref_norm = normalize_name(pseudo_ref_raw)

        aliases_norm = []
        if col_aliases is not None and col_aliases < len(row):
            aliases_norm = split_aliases(row[col_aliases])

        if term_norm == pseudo_ref_norm or (aliases_norm and term_norm in aliases_norm):
            ws_ban_create.delete_rows(idx)
            return await interaction.followup.send(
                catify(f"🔓 **{display_name(pseudo_ref_raw)}** est retiré de la cave.", chance=0.45),
                ephemeral=True
            )

    await interaction.followup.send(catify("😾 Mikasa ne trouve aucun nom correspondant dans la cave."), ephemeral=True)
    
@cave_group.command(name="info", description="Afficher un dossier cave (HG).")
@hg_check()
@app_commands.describe(term="Pseudo_ref ou alias")
async def cave_info_slash(interaction: discord.Interaction, term: str):
    await defer_ephemeral(interaction)

    term_norm = normalize_name(term)
    rows = ws_ban_create.get_all_records()

    for r in rows:
        pseudo_ref_raw = str(r.get("pseudo_ref", "")).strip()
        pseudo_ref_norm = normalize_name(pseudo_ref_raw)
        aliases_norm = split_aliases(r.get("aliases", ""))

        if term_norm == pseudo_ref_norm or (aliases_norm and term_norm in aliases_norm):
            reason = str(r.get("reason", "—")).strip() or "—"
            added_by = str(r.get("added_by", "—")).strip() or "—"
            added_at = str(r.get("added_at", "—")).strip() or "—"
            notes = str(r.get("notes", "—")).strip() or "—"
            discord_id = str(r.get("discord_id", "—")).strip() or "—"

            aliases_display = ", ".join(display_name(a) for a in aliases_norm) if aliases_norm else "—"
            staff_mention = f"<@{added_by}>" if added_by.isdigit() else added_by

            msg = (
                f"🕯️ **Dossier cave Mikasa**\n"
                f"🔒 Nom: **{display_name(pseudo_ref_raw)}**\n"
                f"🏷️ Alias: {aliases_display}\n"
                f"📌 Reason: `{reason}`\n"
                f"👤 Ajouté par: {staff_mention}\n"
                f"📅 Ajouté le: `{added_at}`\n"
                f"🪪 discord_id: `{discord_id}`\n"
                f"📝 Notes: {notes}"
            )
            return await interaction.followup.send(catify(msg, chance=0.25), ephemeral=True)

    await interaction.followup.send(catify("😾 Aucun dossier trouvé dans la cave pour ce terme."), ephemeral=True)

vip_cmd = bot.tree.get_command("vip")
add_cmd = vip_cmd.get_command("add") if vip_cmd else None
txt = add_cmd.mention if add_cmd else "`/vip add`"

# ============================================================
# 14) DEFIS ANNOUNCE
# ============================================================
async def post_weekly_challenges_announcement():
    if not ANNOUNCE_CHANNEL_ID:
        return
    ch = bot.get_channel(int(ANNOUNCE_CHANNEL_ID))
    if not ch:
        return

    wk = current_challenge_week_number()
    start, end = challenge_week_window()

    tasks = WEEKLY_CHALLENGES.get(wk, [])
    title = f"📸 Défis VIP SubUrban #DEFISUBURBAN | Semaine {wk}/12"

    lines = []
    if wk == 12:
        lines.append("🎭 **SEMAINE FINALE – FREESTYLE**")
        lines.append("Choisissez **4 défis** parmi :")
        for t in tasks:
            lines.append(f"• {t}")
    else:
        lines.append("Voici les **4 défis** à valider cette semaine :")
        for i, t in enumerate(tasks[:4], start=1):
            lines.append(f"**{i}.** {t}")

    lines.append("")
    lines.append(f"🗓️ Période: **{fmt_fr(start)} → {fmt_fr(end)}** (heure FR)")
    lines.append("✅ Validation des défis: **HG uniquement**")
    lines.append("😼 Mikasa annonce la chasse aux photos. prrr 🐾")

    await ch.send("**" + title + "**\n" + "\n".join(lines))


@bot.command(name="defiweek")
@hg_only()
async def defiweek(ctx):
    await post_weekly_challenges_announcement()
    await ctx.reply(catify("✅ Annonce postée. 🐾", chance=0.15), mention_author=False)


# ============================================================
# 15) STUBS / EMPLACEMENTS POUR LES COMMANDES STAFF EN PLUS
# ============================================================

def yn_emoji(flag: bool) -> str:
    return "✔️" if flag else "❌"

def col_letter_for_defi(n: int) -> str:
    # DEFIS sheet: C..F = d1..d4
    return chr(ord("C") + (n - 1))

def get_week_tasks_for_view(wk: int) -> list[str]:
    """
    Semaines 1..11: 4 tâches
    Semaine 12: on renvoie 12 tâches "choix" (liste)
    """
    tasks = WEEKLY_CHALLENGES.get(wk, [])
    if wk == 12:
        # on attend une liste de 12 propositions
        if not tasks:
            return ["(Aucun défi configuré)"] * 12
        # si quelqu’un a mis 1 seule grosse ligne, on la garde mais ça fera 1 item:
        if len(tasks) == 1:
            # fallback: 12 copies (pas idéal mais évite crash)
            return [tasks[0]] * 12
        return tasks[:12]

    # semaines 1..11
    tasks = tasks[:4]
    while len(tasks) < 4:
        tasks.append("(Défi non configuré)")
    return tasks


# 1) Commandes création/link

def create_vip_for_member(member: discord.Member, staff_id: int):
    """
    Crée un VIP lié à un membre Discord.
    Retourne (True, code_vip) si OK
    ou (False, message_erreur) si refus
    """

    # 1) Vérifier si le membre a déjà un VIP lié
    existing = ws_vip.get_all_records()
    for r in existing:
        if str(r.get("discord_id", "")).strip() == str(member.id):
            return False, "😾 Ce membre possède déjà un accès VIP."

    # 2) Check BAN pré-création (pseudo/alias/discord_id)
    banned, ban_reason = check_banned_for_create(
        pseudo=member.display_name,
        discord_id=str(member.id),
    )
    if banned:
        # Log staff interne (invisible publiquement)
        log_create_blocked(
            staff_id=staff_id,
            pseudo_attempted=member.display_name,
            discord_id=str(member.id),
            reason=ban_reason or "Match VIP_BAN_CREATE"
        )

        rp_messages = [
            "😾 **Mikasa hérisse les poils.** Ce nom ne lui inspire pas confiance… Le carnet VIP reste fermé.",
            "🐾 **Mikasa renifle l’air, puis referme le registre VIP.** Quelque chose cloche.",
            "😼 **Mikasa s’assoit sur le carnet VIP.** Impossible de l’ouvrir pour ce nom.",
            "🐱 **Les oreilles de Mikasa se plaquent en arrière.** Elle refuse d’écrire ce nom.",
            "😾 **Un léger feulement retentit.** Mikasa décide de ne pas aller plus loin.",
        ]
        return False, mikasa_ban_block_reaction()

    # 3) Générer un code VIP unique
    code = gen_code()
    while code_exists(code):
        code = gen_code()

    # 4) Valeurs initiales
    points = 0
    niveau = calc_level(points)
    created_at = now_iso()
    pseudo = member.display_name

    # 5) Écrire dans l’onglet VIP
    ws_vip.append_row([
        code,            # code_vip
        str(member.id),  # discord_id
        pseudo,          # pseudo
        points,          # points
        niveau,          # niveau
        created_at,      # created_at
        str(staff_id),   # created_by
        "ACTIVE",        # status
        ""               # bleeter (vide par défaut)
    ])

    # 6) Log de création
    ws_log.append_row([
        created_at,
        str(staff_id),
        code,
        "CREATE",
        1,
        0,
        0,
        f"Création VIP (lié Discord) pour {pseudo} ({member.id})"
    ])

    return True, code

def create_vip_manual(pseudo: str, staff_id: int, note: str = ""):
    """
    Crée un VIP manuel (non lié Discord).
    Retourne (True, code_vip) si OK
    ou (False, message_erreur) si refus
    """

    # 0) Normalisation pseudo (underscore -> espaces + belles majuscules)
    pseudo_clean = display_name((pseudo or "").strip())
    if not pseudo_clean:
        return False, "❌ Pseudo vide. Utilise: `!vipcreate PSEUDO` ou `!vipcreatenote PSEUDO | NOTE`"

    # 1) Check BAN pré-création (par pseudo / alias)
    banned, ban_reason = check_banned_for_create(pseudo=pseudo_clean, discord_id="")
    if banned:
        # Log staff interne (invisible publiquement)
        log_create_blocked(
            staff_id=staff_id,
            pseudo_attempted=pseudo_clean,
            discord_id="",
            reason=ban_reason or "Match VIP_BAN_CREATE"
        )

        return False, mikasa_ban_block_reaction()

    # 2) Générer un code VIP unique
    code = gen_code()
    while code_exists(code):
        code = gen_code()

    # 3) Valeurs initiales
    points = 0
    niveau = calc_level(points)
    created_at = now_iso()

    # 4) Écrire la ligne VIP
    # Actuellement : code_vip, discord_id, pseudo, points, niveau, created_at, created_by, status, bleeter
    # On ajoute dob/phone/card_url plus tard, test et ensuite on met des "" ici aussi.
    ws_vip.append_row([
        code,            # code_vip
        "",              # discord_id (vide)
        pseudo_clean,    # pseudo
        points,          # points
        niveau,          # niveau
        created_at,      # created_at
        str(staff_id),   # created_by
        "ACTIVE",        # status
        "",              # bleeter (vide par défaut)
        "",              # date de naissance
        "",              # téléphone
        "",              # card_url
        "",              # card_generated_at
        ""               # card_generated_by
    ])

    # 5) Log de création
    reason = f"Création VIP (manuel) pour {pseudo_clean}"
    if note and str(note).strip():
        reason += f" | Note: {str(note).strip()}"

    ws_log.append_row([
        created_at,
        str(staff_id),
        code,
        "CREATE_MANUAL",
        1,
        0,
        0,
        reason
    ])

    return True, code

def check_banned_for_create(pseudo: str = "", discord_id: str = ""):
    """
    Retourne (True, reason) si la création doit être bloquée.
    Match possible:
    - pseudo == pseudo_ref
    - pseudo dans aliases
    - discord_id == discord_id banni
    """
    p = normalize_name(pseudo)
    did = str(discord_id or "").strip()

    for b in load_ban_create_list():
        if did and b["discord_id"] and did == b["discord_id"]:
            return True, b["reason"] or "Raison interne"
        if p and b["pseudo_ref"] and p == b["pseudo_ref"]:
            return True, b["reason"] or "Raison interne"
        if p and b["aliases"] and p in b["aliases"]:
            return True, b["reason"] or "Raison interne"

    return False, ""

def load_ban_create_list():
    """
    Lit l'onglet VIP_BAN_CREATE et retourne une liste d'entrées ban.
    Colonnes attendues: pseudo_ref, aliases, discord_id, reason, added_by, added_at, notes
    """
    rows = ws_ban_create.get_all_records()
    bans = []
    for r in rows:
        pseudo_ref = normalize_name(r.get("pseudo_ref", ""))
        aliases = split_aliases(r.get("aliases", ""))
        discord_id = str(r.get("discord_id", "")).strip()
        reason = str(r.get("reason", "")).strip()

        bans.append({
            "pseudo_ref": pseudo_ref,
            "aliases": aliases,
            "discord_id": discord_id,
            "reason": reason,
        })
    return bans

def split_aliases(raw: str):
    """
    aliases peut être: "abc, def; ghi | jkl"
    On split sur , ; |
    """
    if not raw:
        return []
    raw = str(raw)
    for sep in [";", "|"]:
        raw = raw.replace(sep, ",")
    items = [normalize_name(x) for x in raw.split(",")]
    return [x for x in items if x]

def log_create_blocked(
    staff_id: int,
    pseudo_attempted: str,
    discord_id: str = "",
    reason: str = ""
):
    """
    Log une tentative de création VIP bloquée (ban pré-création).
    Écrit uniquement dans l'onglet LOG (staff only).
    """

    timestamp = now_iso()

    details = f"Tentative création VIP bloquée | pseudo='{pseudo_attempted}'"
    if discord_id:
        details += f" | discord_id={discord_id}"
    if reason:
        details += f" | reason={reason}"

    ws_log.append_row([
        timestamp,              # timestamp
        str(staff_id),           # staff_id
        "",                      # code_vip (vide car non créé)
        "CREATE_BLOCKED",        # action_key
        1,                       # quantité
        0,                       # points_unite
        0,                       # delta_points
        details                  # raison
    ])

#
# 2) Commandes challenges interactives (boutons S1..S11 et S12)


class DefiValidateView(discord.ui.View):
    def __init__(self, *, author: discord.Member, code: str, wk: int, wk_key: str, wk_label: str,
                 row_i: int, row: dict, tasks: list[str], vip_pseudo: str):
        super().__init__(timeout=180)

        self.author = author
        self.code = code
        self.wk = wk
        self.wk_key = wk_key
        self.wk_label = wk_label
        self.row_i = row_i
        self.row = row
        self.tasks = tasks
        self.vip_pseudo = vip_pseudo

        # état initial depuis la sheet
        self.state = {
            1: bool(str(row.get("d1", "")).strip()),
            2: bool(str(row.get("d2", "")).strip()),
            3: bool(str(row.get("d3", "")).strip()),
            4: bool(str(row.get("d4", "")).strip()),
        }

        # IMPORTANT: tampon -> si un défi est déjà validé, on verrouille son bouton (pas de gomme)
        self.locked = {
            1: self.state[1],
            2: self.state[2],
            3: self.state[3],
            4: self.state[4],
        }

        self.message: discord.Message | None = None
        self._refresh_buttons()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(
                catify("😾 Pas touche. Lance ta propre commande `!defi CODE`."),
                ephemeral=True
            )
            return False
        return True

    def _build_embed(self) -> discord.Embed:
        wk_start, wk_end, _ = get_week_window()
        lines = []
        for i in range(1, 5):
            lines.append(f"{yn_emoji(self.state[i])} {self.tasks[i-1]}")

        desc = (
            f"👤 **{self.vip_pseudo}** • `{self.code}`\n"
            f"📌 {self.wk_label}\n"
            f"🗓️ **{wk_start.strftime('%d/%m %H:%M')} → {wk_end.strftime('%d/%m %H:%M')}** (FR)\n\n"
            + "\n".join(lines) +
            "\n\nClique pour cocher les ❌. Les ✔️ déjà tamponnés sont verrouillés."
        )

        embed = discord.Embed(
            title="📸 Validation des défis (HG)",
            description=desc,
            color=discord.Color.dark_purple()
        )
        embed.set_footer(text="Tampon Mikasa: une fois posé, il ne s’efface pas. 🐾")
        return embed

    def _refresh_buttons(self):
        for child in self.children:
            if isinstance(child, discord.ui.Button) and child.custom_id and child.custom_id.startswith("defi_toggle_"):
                n = int(child.custom_id.split("_")[-1])
                child.label = f"{yn_emoji(self.state[n])} Défi {n}"
                # verrou si déjà validé en sheet
                child.disabled = bool(self.locked[n])

    async def _edit(self, interaction: discord.Interaction):
        self._refresh_buttons()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    @discord.ui.button(label="❌ Défi 1", style=discord.ButtonStyle.secondary, custom_id="defi_toggle_1")
    async def toggle_1(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.state[1] = not self.state[1]
        await self._edit(interaction)

    @discord.ui.button(label="❌ Défi 2", style=discord.ButtonStyle.secondary, custom_id="defi_toggle_2")
    async def toggle_2(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.state[2] = not self.state[2]
        await self._edit(interaction)

    @discord.ui.button(label="❌ Défi 3", style=discord.ButtonStyle.secondary, custom_id="defi_toggle_3")
    async def toggle_3(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.state[3] = not self.state[3]
        await self._edit(interaction)

    @discord.ui.button(label="❌ Défi 4", style=discord.ButtonStyle.secondary, custom_id="defi_toggle_4")
    async def toggle_4(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.state[4] = not self.state[4]
        await self._edit(interaction)

    @discord.ui.button(label="✅ VALIDER", style=discord.ButtonStyle.success)
    async def commit(self, interaction: discord.Interaction, button: discord.ui.Button):
        # sécurité anti-double clic
        await interaction.response.defer()

        # --- TON CODE ICI ---
        # ex:
        # enregistrer les défis cochés
        # update Google Sheet
        # envoyer confirmation

        for child in self.children:
            child.disabled = True

        await interaction.message.edit(view=self)

        # ex: update sheet, calculs, etc.

        try:
            await interaction.edit_original_response(embed=final_embed, view=self)
        except Exception:
            try:
                await interaction.followup.send(embed=final_embed, ephemeral=True)
            except Exception:
                pass

    
            # relire la ligne DEFIS pour éviter conflit
        row_i2, row2 = get_defis_row(self.code, self.wk_key)
        if not row_i2:
            await interaction.response.send_message(catify("❌ Ligne DEFIS introuvable. Relance `!defi CODE`."), ephemeral=True)
            return
    
        done_before = defis_done_count(row2)
        now_dt = now_fr()
        stamp = now_dt.strftime("%Y-%m-%d %H:%M:%S")
    
        updates = []

        for n in range(1, 5):
            if self.state.get(n) and not str(row2.get(f"d{n}", "")).strip():
                col = col_letter_for_defi(n)
                updates.append({
                    "range": f"{col}{row_i2}",
                    "values": [[stamp]]
                })


    
            if updates:
                ws_defis.batch_update(updates)
    
            # reload
            row_i3, row3 = get_defis_row(self.code, self.wk_key)
            done_after = defis_done_count(row3)
    
            awarded = False
    
            # points UNIQUEMENT au 1er défi de la semaine
            if done_before == 0 and done_after > 0:
                ok1, _ = add_points_by_action(self.code, "BLEETER", 1, interaction.user.id, f"1er défi validé ({self.wk_key})", author_is_hg=True)
                ok2, _ = add_points_by_action(self.code, "DEFI_HEBDO", 1, interaction.user.id, f"1er défi validé ({self.wk_key})", author_is_hg=True)
                awarded = bool(ok1 and ok2)
    
            # si 4/4 -> completed + bonus + annonce (une seule fois)
            if done_after >= 4 and str(row3.get("completed_at", "")).strip() == "":
                comp_stamp = now_fr().strftime("%Y-%m-%d %H:%M:%S")
                ws_defis.batch_update([
                    {"range": f"G{row_i3}", "values": [[comp_stamp]]},
                    {"range": f"H{row_i3}", "values": [[str(interaction.user.id)]]},
                ])
    
                add_points_by_action(self.code, "TOUS_DEFIS_HEBDO", 1, interaction.user.id, f"4/4 défis complétés ({self.wk_key})", author_is_hg=True)
    
                if ANNOUNCE_CHANNEL_ID:
                    ch = bot.get_channel(int(ANNOUNCE_CHANNEL_ID))
                    if ch:
                        await ch.send(catify(
                            f"🎉 **{self.vip_pseudo}** vient de finir les **4 défis** de la {self.wk_label} !\n"
                            f"😼 Mikasa tamponne le carnet VIP: **COMPLET**. 🐾",
                            chance=0.10
                        ))
    
            # verrouille tout et affiche résultat
            for item in self.children:
                item.disabled = True
    
            final_embed = self._build_embed()
            extra = "🎁 Récompense donnée (1er défi de la semaine)." if awarded else "🧾 Récompense déjà prise cette semaine (ou aucune case nouvelle)."
            final_embed.add_field(name="✅ Enregistré", value=f"Progression: **{done_after}/4**\n{extra}", inline=False)
            final_embed.set_footer(text="Tampon posé. Mikasa referme le carnet. 🐾")

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                emb = self.message.embeds[0] if self.message.embeds else None
                if emb:
                    emb.set_footer(text="Menu expiré • Relance `!defi CODE` 🐾")
                    await self.message.edit(embed=emb, view=self)
                else:
                    await self.message.edit(view=self)
            except Exception:
                pass

# =========================
# VIEW SEMAINE 12 : 12 toggles (max 4) + VALIDER (tampon)
# =========================

class DefiWeek12View(discord.ui.View):
    def __init__(self, *, author: discord.Member, code: str, wk: int, wk_key: str, wk_label: str,
                 row_i: int, row: dict, choices: list[str], vip_pseudo: str):
        super().__init__(timeout=180)

        self.author = author
        self.code = code
        self.wk = wk
        self.wk_key = wk_key
        self.wk_label = wk_label
        self.row_i = row_i
        self.row = row
        self.choices = choices  # 12 textes
        self.vip_pseudo = vip_pseudo

        # d1..d4 déjà tamponnés ?
        self.state_slots = {
            1: bool(str(row.get("d1", "")).strip()),
            2: bool(str(row.get("d2", "")).strip()),
            3: bool(str(row.get("d3", "")).strip()),
            4: bool(str(row.get("d4", "")).strip()),
        }
        # verrou slots tamponnés
        self.locked_slots = {
            1: self.state_slots[1],
            2: self.state_slots[2],
            3: self.state_slots[3],
            4: self.state_slots[4],
        }

        # sélection en cours (jusqu’à 4) -> indices 0..11
        self.selected: set[int] = set()

        self.message: discord.Message | None = None

        # build 12 boutons dynamiques
        for i in range(12):
            self.add_item(Week12ChoiceButton(i))

        self.add_item(Week12ValidateButton())
        self._refresh_all()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(
                catify("😾 Pas touche. Lance ta propre commande `!defi CODE`."),
                ephemeral=True
            )
            return False
        return True

    def selected_count(self) -> int:
        return len(self.selected)

    def slots_done_count(self) -> int:
        return sum(1 for n in range(1, 5) if self.state_slots[n])

    def available_slots(self) -> int:
        return 4 - self.slots_done_count()

    def _build_embed(self) -> discord.Embed:
        wk_start, wk_end, _ = get_week_window()
        done = self.slots_done_count()
        lines = []
        for idx, txt in enumerate(self.choices):
            mark = "✔️" if idx in self.selected else "❌"
            lines.append(f"{mark} {txt}")

        desc = (
            f"👤 **{self.vip_pseudo}** • `{self.code}`\n"
            f"📌 {self.wk_label} (Freestyle)\n"
            f"🗓️ **{wk_start.strftime('%d/%m %H:%M')} → {wk_end.strftime('%d/%m %H:%M')}** (FR)\n\n"
            f"✅ Slots déjà validés: **{done}/4** (tampon)\n"
            f"🧩 Sélection en cours: **{self.selected_count()}/4** (max)\n\n"
            + "\n".join(lines)
            + "\n\nChoisis jusqu’à 4 défis, puis **VALIDER**."
        )

        embed = discord.Embed(
            title="🎭 Semaine 12 Freestyle (HG)",
            description=desc,
            color=discord.Color.purple()
        )
        embed.set_footer(text="Freestyle: Mikasa compte exactement 4 preuves. 🐾")
        return embed

    def _refresh_all(self):
        # refresh labels + disabled selon sélection
        for item in self.children:
            if isinstance(item, Week12ChoiceButton):
                idx = item.idx
                item.label = f"{'✔️' if idx in self.selected else '❌'} {idx+1}"
                # si déjà 4 sélectionnées, on désactive les non-sélectionnées
                if self.selected_count() >= 4 and idx not in self.selected:
                    item.disabled = True
                else:
                    item.disabled = False

            if isinstance(item, Week12ValidateButton):
                item.disabled = (self.selected_count() == 0)

    async def _edit(self, interaction: discord.Interaction):
        self._refresh_all()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    async def commit_selected(self, interaction: discord.Interaction):
        # relire row
        row_i2, row2 = get_defis_row(self.code, self.wk_key)
        if not row_i2:
            await interaction.response.send_message(catify("❌ Ligne DEFIS introuvable. Relance `!defi CODE`."), ephemeral=True)
            return

        done_before = defis_done_count(row2)
        now_dt = now_fr()
        stamp = now_dt.strftime("%Y-%m-%d %H:%M:%S")

        # slots disponibles = cases vides d1..d4
        empty_slots = []
        for n in range(1, 5):
            if not str(row2.get(f"d{n}", "")).strip():
                empty_slots.append(n)

        # Tampon: on ne remplace jamais une case déjà remplie
        # On remplit les slots vides avec la sélection (jusqu’à 4)
        to_write = list(self.selected)[:len(empty_slots)]
        updates = []

        for k, choice_idx in enumerate(to_write):
            slot_n = empty_slots[k]
            col = col_letter_for_defi(slot_n)
            updates.append({"range": f"{col}{row_i2}", "values": [[stamp]]})

            # On stocke dans d_notes la trace du choix
            picked_txt = self.choices[choice_idx]
            old_note = str(row2.get("d_notes", "")).strip()
            merged = (old_note + " | " if old_note else "") + f"W12:{slot_n}:{picked_txt}"
            ws_defis.update(f"I{row_i2}", merged)

        if updates:
            ws_defis.batch_update(updates)

        # reload
        row_i3, row3 = get_defis_row(self.code, self.wk_key)
        done_after = defis_done_count(row3)

        awarded = False
        if done_before == 0 and done_after > 0:
            ok1, _ = add_points_by_action(self.code, "BLEETER", 1, interaction.user.id, f"1er défi validé ({self.wk_key})", author_is_hg=True)
            ok2, _ = add_points_by_action(self.code, "DEFI_HEBDO", 1, interaction.user.id, f"1er défi validé ({self.wk_key})", author_is_hg=True)
            awarded = bool(ok1 and ok2)

        if done_after >= 4 and str(row3.get("completed_at", "")).strip() == "":
            comp_stamp = now_fr().strftime("%Y-%m-%d %H:%M:%S")
            ws_defis.batch_update([
                {"range": f"G{row_i3}", "values": [[comp_stamp]]},
                {"range": f"H{row_i3}", "values": [[str(interaction.user.id)]]},
            ])

            add_points_by_action(self.code, "TOUS_DEFIS_HEBDO", 1, interaction.user.id, f"4/4 défis complétés ({self.wk_key})", author_is_hg=True)

            if ANNOUNCE_CHANNEL_ID:
                ch = bot.get_channel(int(ANNOUNCE_CHANNEL_ID))
                if ch:
                    await ch.send(catify(
                        f"🎉 **{self.vip_pseudo}** vient de finir les **4 défis** de la {self.wk_label} !\n"
                        f"😼 Mikasa tamponne le carnet VIP: **COMPLET**. 🐾",
                        chance=0.10
                    ))

        # finish
        for item in self.children:
            item.disabled = True

        emb = self._build_embed()
        extra = "🎁 Récompense donnée (1er défi de la semaine)." if awarded else "🧾 Récompense déjà prise cette semaine (ou slots déjà complets)."
        emb.add_field(name="✅ Enregistré", value=f"Progression: **{done_after}/4**\n{extra}", inline=False)
        emb.set_footer(text="Freestyle enregistré. Mikasa range les preuves. 🐾")

        await interaction.response.edit_message(embed=emb, view=self)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                emb = self.message.embeds[0] if self.message.embeds else None
                if emb:
                    emb.set_footer(text="Menu expiré • Relance `!defi CODE` 🐾")
                    await self.message.edit(embed=emb, view=self)
                else:
                    await self.message.edit(view=self)
            except Exception:
                pass

class Week12ChoiceButton(discord.ui.Button):
    def __init__(self, idx: int):
        super().__init__(label=f"❌ {idx+1}", style=discord.ButtonStyle.secondary, custom_id=f"w12_choice_{idx}")
        self.idx = idx

    async def callback(self, interaction: discord.Interaction):
        view: DefiWeek12View = self.view  # type: ignore
        if self.idx in view.selected:
            view.selected.remove(self.idx)
        else:
            if view.selected_count() >= 4:
                await interaction.response.send_message(catify("😾 Max **4** choix en semaine 12."), ephemeral=True)
                return
            view.selected.add(self.idx)
        await view._edit(interaction)
        
class Week12ValidateButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="✅ VALIDER", style=discord.ButtonStyle.success, custom_id="w12_commit")

    async def callback(self, interaction: discord.Interaction):
        view: DefiWeek12View = self.view  # type: ignore
        await view.commit_selected(interaction)
        
# =========================
# COMMANDE !defi (HG only) : ouvre le bon panneau selon semaine
# =========================

@bot.command(name="defi")
async def defi(ctx, code_vip: str = None):
    """
    HG only
    Usage: !defi SUB-XXXX-XXXX
    Ouvre un panneau interactif:
    - Semaines 1..11: 4 toggles (tampon, pas gomme)
    - Semaine 12: 12 choix, max 4, puis commit en remplissant d1..d4
    """
    if not is_hg(ctx.author):
        await ctx.send(catify("😾 Seuls les HG peuvent valider les défis."))
        return

    if not code_vip:
        await ctx.send(catify("❌ Utilisation: `!defi SUB-XXXX-XXXX`"))
        return

    code = normalize_code(code_vip)

    # fenêtre semaine actuelle
    wk_start, wk_end, wk = get_week_window()  # (start, end, wk)
    if wk == 0 or not wk_start or not wk_end:
        await ctx.send(catify("😺 Les défis ne sont pas encore lancés."))
        return

    now_dt = now_fr()
    if not (wk_start <= now_dt < wk_end):
        await ctx.send(catify(
            f"⛔ Hors fenêtre défis.\n"
            f"🗓️ Fenêtre actuelle: **{wk_start.strftime('%d/%m %H:%M')} → {wk_end.strftime('%d/%m %H:%M')}** (FR)"
        ))
        return

    #wk_key = week_key_for(wk, wk_start)
    wk_key = week_key_for(wk)
    wk_label = week_label_for(wk)

    # VIP existe ?
    row_vip_i, vip = find_vip_row_by_code(code)
    if not row_vip_i:
        await ctx.send(catify("❌ Code VIP introuvable."))
        return

    pseudo = display_name(vip.get("pseudo", "Quelqu’un"))

    # DEFIS row
    row_i, row = ensure_defis_row(code, wk_key, wk_label)

    # semaine 12 special
    if wk == 12:
        choices = get_week_tasks_for_view(12)  # 12 items
        view = DefiWeek12View(
            author=ctx.author,
            code=code,
            wk=wk,
            wk_key=wk_key,
            wk_label=wk_label,
            row_i=row_i,
            row=row,
            choices=choices,
            vip_pseudo=pseudo
        )
        emb = view._build_embed()
        msg = await ctx.send(embed=emb, view=view)
        view.message = msg
        return

    # semaine 1..11 standard 4 défis
    tasks = get_week_tasks_for_view(wk)  # 4 items
    view = DefiValidateView(
        author=ctx.author,
        code=code,
        wk=wk,
        wk_key=wk_key,
        wk_label=wk_label,
        row_i=row_i,
        row=row,
        tasks=tasks,
        vip_pseudo=pseudo
    )
    emb = view._build_embed()
    msg = await ctx.send(embed=emb, view=view)
    view.message = msg

@bot.command(name="defitop")
async def defitop(ctx, n: str = "10"):
    if not (is_employee(ctx.author) or is_hg(ctx.author)):
        await ctx.send(catify("⛔ Réservé staff (employés/HG)."))
        return

    try:
        limit = max(3, min(25, int(n)))
    except:
        limit = 10

    start, end, wk = get_current_week_window()
    if wk == 0:
        await ctx.send(catify("😺 Les défis ne sont pas encore lancés."))
        return
    
    wk_key = week_key_for(wk)
    wk_label = week_label_for(wk)

    rows = ws_defis.get_all_records()
    pack = []
    for r in rows:
        if str(r.get("week_key", "")).strip() != wk_key:
            continue
        code = str(r.get("code_vip", "")).strip().upper()
        if not code:
            continue

        done = defis_done_count(r)
        completed_at = str(r.get("completed_at", "")).strip()  # vide si pas fini

        # récup pseudo depuis VIP sheet
        _, vip = find_vip_row_by_code(code)
        pseudo = display_name(vip.get("pseudo", code)) if vip else code

        pack.append((done, completed_at, pseudo, code))

    if not pack:
        await ctx.send(catify("📭 Aucun défi enregistré pour cette semaine."))
        return

    # tri: d'abord le + de défis, puis ceux qui finissent en premier, sinon pseudo
    pack.sort(key=lambda x: (-x[0], x[1] or "9999", x[2].lower()))
    pack = pack[:limit]

    lines = []
    for i, (done, comp, pseudo, code) in enumerate(pack, start=1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "🏁"
        lines.append(f"{medal} **#{i}** {pseudo} — **{done}/4** (`{code}`)")

    await ctx.send(catify(
        f"🏆 **Classement Défis** — {wk_label}\n" + "\n".join(lines),
        chance=0.12
    ))

@bot.command(name="cave")
@hg_only()
async def cave(ctx, action: str = None, *, rest: str = ""):
    """
    HG only.
    Usages:
    - !cave
    - !cave add PSEUDO | alias1, alias2
    - !cave remove TERME (pseudo_ref ou alias)
    """

    action = (action or "").strip().lower()
    rest = (rest or "").strip()

    # =========================
    # RÉACTIONS MIKASA
    # =========================
    ADD_REACTIONS = [
        "😾 *Hssss…*",
        "🐾 **Le carnet VIP se referme d’un coup sec.**",
        "🕯️ **La cave de Mikasa accueille un nouveau nom.**",
        "😼 **Un coup de patte efface le nom.**",
        "🐱 **Le silence retombe. Le nom est scellé.**",
    ]

    REMOVE_REACTIONS = [
        "🐱 *Hmm…*",
        "🐾 **La porte grince lentement.**",
        "😼 **Mikasa raye le nom avec prudence.**",
        "🕯️ **La chaîne est retirée, mais le regard reste vigilant.**",
        "🐱 **Une chance de plus. Pas une promesse.**",
    ]

    REPEAT_REACTIONS = [
        "😾 *Tsssk…*",
        "🐱 **Le carnet ne s’ouvre même pas.**",
        "🐾 **La décision est ancienne. Et définitive.**",
        "🕯️ **La cave n’a pas besoin de doublons.**",
        "😼 **Mikasa ne répète pas ses décisions.**",
    ]

    # =========================
    # 1) LISTE
    # =========================
    if not action:
        rows = ws_ban_create.get_all_records()
        if not rows:
            await ctx.send(catify("🐱 La cave de Mikasa est vide… pour l’instant.", chance=0.35))
            return

        lines = []
        for r in rows:
            pseudo_ref_raw = str(r.get("pseudo_ref", "")).strip()
            if not pseudo_ref_raw:
                continue

            aliases_raw = r.get("aliases", "")
            aliases_list_norm = split_aliases(aliases_raw)  # retourne des alias normalisés
            aliases_display = ", ".join(display_name(a) for a in aliases_list_norm) if aliases_list_norm else ""

            pseudo_display = display_name(pseudo_ref_raw)

            if aliases_display:
                lines.append(f"🔒 **{pseudo_display}** _(alias: {aliases_display})_")
            else:
                lines.append(f"🔒 **{pseudo_display}**")

        await ctx.send(catify("🕯️ **La cave de Mikasa**", chance=0.30) + "\n" + "\n".join(lines))
        return

    # =========================
    # 2) ADD
    # =========================
    if action == "add":
        if not rest:
            await ctx.send(catify("❌ Utilisation: `!cave add PSEUDO | alias1, alias2`"))
            return
    
        if "|" in rest:
            pseudo_ref_raw, aliases_raw = rest.split("|", 1)
        else:
            pseudo_ref_raw, aliases_raw = rest, ""
    
        pseudo_ref_raw = pseudo_ref_raw.strip()
        aliases_raw = aliases_raw.strip()
    
        if not pseudo_ref_raw:
            await ctx.send(catify("❌ Il me faut au moins un pseudo."))
            return
    
        pseudo_norm = normalize_name(pseudo_ref_raw)
        aliases_list_norm = split_aliases(aliases_raw)
    
        # 🔍 Vérification doublon (PAS d'append ici)
        rows = ws_ban_create.get_all_records()
        for r in rows:
            existing_pseudo = normalize_name(r.get("pseudo_ref", ""))
            existing_aliases = split_aliases(r.get("aliases", ""))
    
            if pseudo_norm == existing_pseudo or pseudo_norm in existing_aliases:
                await ctx.send(catify("😾 Ce nom est déjà dans la cave."))
                return
    
        # ✅ Append UNE SEULE FOIS (hors boucle)
        ws_ban_create.append_row([
            pseudo_ref_raw,
            ", ".join(aliases_list_norm),
            "",                    # discord_id
            "BAN_CREATE",
            str(ctx.author.id),
            now_iso(),
            ""
        ])
    
        await ctx.send(catify(
            f"🔒 **{display_name(pseudo_ref_raw)}** est enfermé dans la cave de Mikasa.",
            chance=0.4
        ))
        return

            
    # =========================
    # 3) REMOVE (par pseudo OU alias)
    # =========================
    if action == "remove":
        if not rest:
            await ctx.send(catify("❌ Utilisation: `!cave remove PSEUDO|ALIAS`"))
            return

        term_norm = normalize_name(rest)

        values = ws_ban_create.get_all_values()
        if not values or len(values) < 2:
            await ctx.send(catify("🐾 Rien à libérer… la cave est vide."))
            return

        header = [h.strip() for h in values[0]]
        data = values[1:]

        if "pseudo_ref" not in header:
            await ctx.send(catify("❌ Colonne `pseudo_ref` introuvable dans VIP_BAN_CREATE."))
            return

        col_pseudo = header.index("pseudo_ref")
        col_aliases = header.index("aliases") if "aliases" in header else None

        for idx, row in enumerate(data, start=2):  # start=2 car ligne 1 = header
            pseudo_ref_raw = row[col_pseudo] if col_pseudo < len(row) else ""
            pseudo_ref_norm = normalize_name(pseudo_ref_raw)

            aliases_norm = []
            if col_aliases is not None and col_aliases < len(row):
                aliases_norm = split_aliases(row[col_aliases])

            if term_norm == pseudo_ref_norm or (aliases_norm and term_norm in aliases_norm):
                ws_ban_create.delete_rows(idx)

                await ctx.send(catify(
                    f"🔓 **{display_name(pseudo_ref_raw)}** est retiré de la cave.\n"
                    + random.choice(REMOVE_REACTIONS),
                    chance=0.45
                ))
                return

        await ctx.send(catify("😾 **Mikasa ne trouve aucun nom correspondant dans la cave.**"))
        return
    # =========================
    # 4) INFO (par pseudo OU alias)
    # =========================
    if action == "info":
        if not rest:
            await ctx.send(catify("❌ Utilisation: `!cave info PSEUDO|ALIAS`"))
            return

        term_norm = normalize_name(rest)

        rows = ws_ban_create.get_all_records()
        for r in rows:
            pseudo_ref_raw = str(r.get("pseudo_ref", "")).strip()
            pseudo_ref_norm = normalize_name(pseudo_ref_raw)

            aliases_norm = split_aliases(r.get("aliases", ""))  # déjà normalisés via normalize_name()
            if term_norm == pseudo_ref_norm or (aliases_norm and term_norm in aliases_norm):
                # Champs
                reason = str(r.get("reason", "—")).strip() or "—"
                added_by = str(r.get("added_by", "—")).strip() or "—"
                added_at = str(r.get("added_at", "—")).strip() or "—"
                notes = str(r.get("notes", "—")).strip() or "—"
                discord_id = str(r.get("discord_id", "—")).strip() or "—"

                # joli affichage
                pseudo_display = display_name(pseudo_ref_raw)
                aliases_display = ", ".join(display_name(a) for a in aliases_norm) if aliases_norm else "—"

                # mention staff si possible
                staff_mention = f"<@{added_by}>" if added_by.isdigit() else added_by

                msg = (
                    f"🕯️ **Dossier cave Mikasa**\n"
                    f"🔒 Nom: **{pseudo_display}**\n"
                    f"🏷️ Alias: {aliases_display}\n"
                    f"📌 Reason: `{reason}`\n"
                    f"👤 Ajouté par: {staff_mention}\n"
                    f"📅 Ajouté le: `{added_at}`\n"
                    f"🪪 discord_id (si renseigné): `{discord_id}`\n"
                    f"📝 Notes: {notes}"
                )
                await ctx.send(catify(msg, chance=0.25))
                return

        await ctx.send(catify("😾 Aucun dossier trouvé dans la cave pour ce terme."))
        return

    await ctx.send(catify("❌ Action inconnue. Utilise `!cave`, `!cave add`, ou `!cave remove`."))
    
@bot.command(name="vip_event")
@employee_only()
async def vip_event(ctx, code_vip: str, action_key: str, qty: int, *, event_name: str = ""):
    if STAFF_CHANNEL_ID and ctx.channel.id != int(STAFF_CHANNEL_ID):
        await ctx.send(catify("😾 Commande utilisable uniquement dans le salon staff."))
        return

    code_vip = (code_vip or "").strip().upper()
    action_key = (action_key or "").strip().upper()
    event_name = (event_name or "").strip()

    if not code_vip or not action_key or qty <= 0 or not event_name:
        await ctx.send(catify("❌ Utilisation: `!vip_event SUB-XXXX-XXXX ACTION 1 nom_event`"))
        return

    reason = f"event:{event_name.replace(' ', '_')}"
    ok, res = add_points_by_action(code_vip, action_key, qty, ctx.author.id, reason, author_is_hg=is_hg(ctx.author))
    if not ok:
        await ctx.send(catify(f"❌ {res}"))
        return

    delta, new_points, old_level, new_level = res
    await ctx.send(catify(f"✅ +{delta} points ajoutés"))


# ============================================================
# 16) RUN
# ============================================================
async def main():
    async with bot:
        await bot.start(DISCORD_TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
