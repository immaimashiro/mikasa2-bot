# hunt_services.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import json
import random
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timedelta

from services import (
    SheetsService,
    PARIS_TZ,
    now_fr,
    now_iso,
    normalize_code,
    display_name,
    challenge_week_window,
)

# ==========================================================
# Tables
# ==========================================================
T_PLAYERS = "HUNT_PLAYERS"
T_DAILY = "HUNT_DAILY"
T_KEYS = "HUNT_KEYS"
T_WEEKLY = "HUNT_WEEKLY"
T_LOG = "HUNT_LOG"
T_ITEMS = "HUNT_ITEMS"
T_BOSSES = "HUNT_BOSSES"
T_REPUTATION = "HUNT_REPUTATION"

# ==========================================================
# HEADERS EXACTS (TES COLONNES)
# ==========================================================
H_PLAYERS = [
    "discord_id","code_vip","pseudo","is_employee",
    "avatar_tag","avatar_url",
    "ally_tag","ally_url",
    "level","xp","xp_total",
    "stats_hp","stats_atk","stats_def","stats_per","stats_cha","stats_luck",
    "hunt_dollars","heat",
    "jail_until","last_daily_date",
    "weekly_week_key","weekly_wins",
    "total_runs","total_wins","total_deaths",
    "inventory_json",
    "created_at","updated_at"
]

H_DAILY = [
    "date_key","discord_id","code_vip",
    "started_at","finished_at",
    "status","step",
    "state_json","result_summary",
    "xp_earned","dollars_earned",
    "dmg_taken","death_flag","jail_flag"
]

H_KEYS = [
    "week_key","code_vip","discord_id",
    "key_type",
    "claimed_at","claimed_by",
    "opened_at",
    "open_item_id","open_qty","open_rarity"
]

H_WEEKLY = [
    "week_key","discord_id","code_vip","pseudo",
    "score",
    "good_runs","wins","deaths",
    "boss_kills","steals","jail_count",
    "earned_dollars","earned_xp",
    "bonus_claimed","top_rank",
    "updated_at"
]

H_LOG = ["timestamp","discord_id","code_vip","kind","message"]
H_ITEMS = ["item_id","name","type","rarity","price","power_json","image_url","description"]

H_BOSSES = [
    "boss_id","name","kind","week_key","phase",
    "base_hp","base_atk","base_def",
    "ai_profile",
    "escape_rule_json",
    "taunts_json",
    "image_url","image_url_alt",
    "enabled"
]

H_REPUTATION = [
    "discord_id","code_vip","pseudo",
    "rep","total_rep",
    "rank_title",
    "last_rep_date",
    "streak_days",
    "updated_at"
]

# ==========================================================
# Settings
# ==========================================================
MAX_JAIL_HOURS = 12

# IDs qui ignorent prison/quotas (tests)
# - tu peux laisser en dur + ajouter via env "HUNT_TESTER_IDS=1,2,3"
HUNT_TESTER_IDS_HARDCODED: set[int] = set([
    135114378981801984,
])

def tester_ids() -> set[int]:
    out = set(HUNT_TESTER_IDS_HARDCODED)
    raw = (os.getenv("HUNT_TESTER_IDS") or "").strip()
    if raw:
        for part in raw.split(","):
            part = part.strip()
            if part.isdigit():
                out.add(int(part))
    return out

def is_tester(discord_id: int) -> bool:
    return int(discord_id) in tester_ids()

# ==========================================================
# JSON helpers
# ==========================================================
def json_loads_safe(s: str, default: Any) -> Any:
    try:
        if not s:
            return default
        return json.loads(s)
    except Exception:
        return default

def json_dumps_safe(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        return "{}"

# ==========================================================
# Date helpers
# ==========================================================
def date_key_fr(dt: Optional[datetime] = None) -> str:
    dt = (dt or now_fr()).astimezone(PARIS_TZ)
    return dt.strftime("%Y-%m-%d")

def hunt_week_key(dt: Optional[datetime] = None) -> str:
    """
    Semaine HUNT calée sur ta fenêtre: vendredi 17:00 -> vendredi 17:00
    On prend la date du START comme identifiant stable.
    """
    start, _ = challenge_week_window(dt or now_fr())
    return start.astimezone(PARIS_TZ).strftime("W%Y-%m-%d")  # ex: W2026-01-09

def parse_iso_or_empty(s: str) -> Optional[datetime]:
    try:
        if not s:
            return None
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(PARIS_TZ)
    except Exception:
        return None

# ==========================================================
# Sheet sanity checks
# ==========================================================
def _ensure_headers(sheets: SheetsService, title: str, expected_headers: List[str]) -> None:
    hdr = sheets.headers(title)
    missing = [h for h in expected_headers if h not in hdr]
    if missing:
        raise RuntimeError(
            f"[{title}] Colonnes manquantes: {missing}\n"
            f"👉 Mets exactement ces headers (au moins ceux-là) en ligne 1."
        )

def ensure_hunt_tables_ready(sheets: SheetsService) -> None:
    _ensure_headers(sheets, T_PLAYERS, H_PLAYERS)
    _ensure_headers(sheets, T_DAILY, H_DAILY)
    _ensure_headers(sheets, T_KEYS, H_KEYS)
    _ensure_headers(sheets, T_WEEKLY, H_WEEKLY)
    _ensure_headers(sheets, T_LOG, H_LOG)
    _ensure_headers(sheets, T_ITEMS, H_ITEMS)
    _ensure_headers(sheets, T_BOSSES, H_BOSSES)
    _ensure_headers(sheets, T_REPUTATION, H_REPUTATION)

# ==========================================================
# Logging
# ==========================================================
def hunt_log(sheets: SheetsService, *, discord_id: int, code_vip: str, kind: str, message: str) -> None:
    sheets.append_by_headers(T_LOG, {
        "timestamp": now_iso(),
        "discord_id": str(discord_id),
        "code_vip": normalize_code(code_vip),
        "kind": (kind or "INFO").strip().upper(),
        "message": (message or "").strip()[:1800],
    })

# ==========================================================
# Players
# ==========================================================
def find_player_row(sheets: SheetsService, discord_id: int) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
    rows = sheets.get_all_records(T_PLAYERS)
    did = str(discord_id)
    for idx, r in enumerate(rows, start=2):
        if str(r.get("discord_id", "")).strip() == did:
            return idx, r
    return None, None

def upsert_player(
    sheets: SheetsService,
    *,
    discord_id: int,
    code_vip: str,
    pseudo: str,
    is_employee: bool,
) -> Tuple[int, Dict[str, Any]]:
    """
    Crée le profil si absent, sinon refresh code/pseudo/is_employee.
    """
    row_i, row = find_player_row(sheets, discord_id)
    now = now_iso()
    code = normalize_code(code_vip)
    ps = display_name(pseudo)

    if row_i and row:
        sheets.update_cell_by_header(T_PLAYERS, row_i, "code_vip", code)
        sheets.update_cell_by_header(T_PLAYERS, row_i, "pseudo", ps)
        sheets.update_cell_by_header(T_PLAYERS, row_i, "is_employee", "TRUE" if is_employee else "FALSE")
        sheets.update_cell_by_header(T_PLAYERS, row_i, "updated_at", now)
        row_i2, row2 = find_player_row(sheets, discord_id)
        return row_i2 or row_i, row2 or row

    base = {
        "discord_id": str(discord_id),
        "code_vip": code,
        "pseudo": ps,
        "is_employee": "TRUE" if is_employee else "FALSE",

        "avatar_tag": "",
        "avatar_url": "",
        "ally_tag": "",
        "ally_url": "",

        "level": 1,
        "xp": 0,
        "xp_total": 0,

        "stats_hp": 30,
        "stats_atk": 6,
        "stats_def": 4,
        "stats_per": 4,
        "stats_cha": 4,
        "stats_luck": 2,

        "hunt_dollars": 0,
        "heat": 0,
        "jail_until": "",
        "last_daily_date": "",

        "weekly_week_key": "",
        "weekly_wins": 0,

        "total_runs": 0,
        "total_wins": 0,
        "total_deaths": 0,

        # inventaire: dict items + keys "stash"
        "inventory_json": json_dumps_safe({"items": {}, "keys": []}),

        "created_at": now,
        "updated_at": now,
    }
    sheets.append_by_headers(T_PLAYERS, base)
    row_i2, row2 = find_player_row(sheets, discord_id)
    if not row_i2 or not row2:
        raise RuntimeError("Impossible de créer HUNT_PLAYERS (ligne non retrouvée).")
    return row_i2, row2

def set_avatar(sheets: SheetsService, *, discord_id: int, avatar_tag: str, avatar_url: str) -> None:
    row_i, _ = find_player_row(sheets, discord_id)
    if not row_i:
        raise RuntimeError("Profil HUNT introuvable (HUNT_PLAYERS).")
    sheets.update_cell_by_header(T_PLAYERS, row_i, "avatar_tag", (avatar_tag or "").strip().upper())
    sheets.update_cell_by_header(T_PLAYERS, row_i, "avatar_url", (avatar_url or "").strip())
    sheets.update_cell_by_header(T_PLAYERS, row_i, "updated_at", now_iso())

def set_ally(sheets: SheetsService, *, discord_id: int, ally_tag: str, ally_url: str) -> None:
    row_i, _ = find_player_row(sheets, discord_id)
    if not row_i:
        raise RuntimeError("Profil HUNT introuvable (HUNT_PLAYERS).")
    sheets.update_cell_by_header(T_PLAYERS, row_i, "ally_tag", (ally_tag or "").strip().upper())
    sheets.update_cell_by_header(T_PLAYERS, row_i, "ally_url", (ally_url or "").strip())
    sheets.update_cell_by_header(T_PLAYERS, row_i, "updated_at", now_iso())

# ==========================================================
# Jail + quotas
# ==========================================================
def is_in_jail(player_row: Dict[str, Any]) -> Tuple[bool, Optional[datetime]]:
    ju = str(player_row.get("jail_until", "")).strip()
    dt = parse_iso_or_empty(ju)
    if not dt:
        return False, None
    return (now_fr() < dt), dt

def can_run_daily(player_row: Dict[str, Any], *, dt: Optional[datetime] = None) -> Tuple[bool, str]:
    dt = dt or now_fr()

    if is_tester(int(player_row.get("discord_id", "0") or 0)):
        return True, ""

    in_jail, until = is_in_jail(player_row)
    if in_jail and until:
        return False, f"⛓️ Tu es en prison jusqu’à **{until.strftime('%d/%m %H:%M')}** (FR)."

    last = str(player_row.get("last_daily_date", "")).strip()
    today = date_key_fr(dt)
    if last == today:
        return False, "😾 Tu as déjà fait ton /hunt daily aujourd’hui."
    return True, ""

def add_heat(sheets: SheetsService, *, discord_id: int, delta: int) -> int:
    row_i, row = find_player_row(sheets, discord_id)
    if not row_i or not row:
        raise RuntimeError("Profil HUNT introuvable (HUNT_PLAYERS).")
    try:
        heat = int(row.get("heat", 0) or 0)
    except Exception:
        heat = 0
    heat = max(0, min(100, heat + int(delta)))
    sheets.update_cell_by_header(T_PLAYERS, row_i, "heat", heat)
    sheets.update_cell_by_header(T_PLAYERS, row_i, "updated_at", now_iso())
    return heat

def compute_sentence_hours(*, crime: str, heat: int, roll: int) -> float:
    """
    crime: 'STEAL' ou 'KILL'
    roll: d20
    Heat augmente la peine (récidive) jusqu’à +40%.
    """
    heat = max(0, min(100, int(heat)))
    mult = 1.0 + (0.4 * (heat / 100.0))

    crime = (crime or "").upper().strip()
    roll = max(1, min(20, int(roll)))

    if crime == "STEAL":
        # 0.5h -> 3h (si mauvais roll)
        base = 0.5 + (max(0, 18 - roll) / 18.0) * 2.5
    else:
        # KILL: 4h -> 12h
        base = 4.0 + (max(0, 18 - roll) / 18.0) * 8.0

    hours = base * mult
    return float(min(MAX_JAIL_HOURS, max(0.25, hours)))

def set_jail(sheets: SheetsService, *, discord_id: int, hours: float, reason: str = "") -> datetime:
    row_i, _ = find_player_row(sheets, discord_id)
    if not row_i:
        raise RuntimeError("Profil HUNT introuvable (HUNT_PLAYERS).")

    hours = float(min(MAX_JAIL_HOURS, max(0.0, hours)))
    until = now_fr() + timedelta(seconds=int(hours * 3600))

    sheets.update_cell_by_header(T_PLAYERS, row_i, "jail_until", until.astimezone(PARIS_TZ).isoformat(timespec="seconds"))
    sheets.update_cell_by_header(T_PLAYERS, row_i, "updated_at", now_iso())

    if reason:
        hunt_log(sheets, discord_id=discord_id, code_vip="", kind="JAIL", message=f"{hours:.2f}h | {reason}")
    return until

# ==========================================================
# HUNT_DAILY helpers
# ==========================================================
def find_daily_row(sheets: SheetsService, *, discord_id: int, date_key: str) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
    rows = sheets.get_all_records(T_DAILY)
    did = str(discord_id)
    for idx, r in enumerate(rows, start=2):
        if str(r.get("discord_id", "")).strip() == did and str(r.get("date_key","")).strip() == date_key:
            return idx, r
    return None, None

def ensure_daily(sheets: SheetsService, *, discord_id: int, code_vip: str, date_key: str) -> Tuple[int, Dict[str, Any]]:
    row_i, row = find_daily_row(sheets, discord_id=discord_id, date_key=date_key)
    if row_i and row:
        return row_i, row

    base = {
        "date_key": date_key,
        "discord_id": str(discord_id),
        "code_vip": normalize_code(code_vip),

        "started_at": now_iso(),
        "finished_at": "",

        "status": "RUNNING",
        "step": 0,

        "state_json": json_dumps_safe({}),
        "result_summary": "",

        "xp_earned": 0,
        "dollars_earned": 0,

        "dmg_taken": 0,
        "death_flag": "FALSE",
        "jail_flag": "FALSE",
    }
    sheets.append_by_headers(T_DAILY, base)
    row_i2, row2 = find_daily_row(sheets, discord_id=discord_id, date_key=date_key)
    if not row_i2 or not row2:
        raise RuntimeError("Impossible de créer/récupérer HUNT_DAILY.")
    return row_i2, row2

def save_daily_state(sheets: SheetsService, row_i: int, *, step: int, state: dict) -> None:
    sheets.update_cell_by_header(T_DAILY, row_i, "step", int(step))
    sheets.update_cell_by_header(T_DAILY, row_i, "state_json", json_dumps_safe(state))

def finish_daily(
    sheets: SheetsService,
    row_i: int,
    *,
    summary: str,
    xp: int,
    dollars: int,
    dmg: int,
    died: bool,
    jailed: bool,
) -> None:
    sheets.update_cell_by_header(T_DAILY, row_i, "finished_at", now_iso())
    sheets.update_cell_by_header(T_DAILY, row_i, "status", "DONE")
    sheets.update_cell_by_header(T_DAILY, row_i, "result_summary", (summary or "")[:1800])
    sheets.update_cell_by_header(T_DAILY, row_i, "xp_earned", int(xp))
    sheets.update_cell_by_header(T_DAILY, row_i, "dollars_earned", int(dollars))
    sheets.update_cell_by_header(T_DAILY, row_i, "dmg_taken", int(dmg))
    sheets.update_cell_by_header(T_DAILY, row_i, "death_flag", "TRUE" if died else "FALSE")
    sheets.update_cell_by_header(T_DAILY, row_i, "jail_flag", "TRUE" if jailed else "FALSE")

# ==========================================================
# HUNT_KEYS (claim hebdo)
# ==========================================================
def player_has_claimed_key_this_week(sheets: SheetsService, *, discord_id: int, week_key: str) -> bool:
    rows = sheets.get_all_records(T_KEYS)
    did = str(discord_id)
    for r in rows:
        if str(r.get("discord_id","")).strip() == did and str(r.get("week_key","")).strip() == week_key:
            return True
    return False

def claim_weekly_key(
    sheets: SheetsService,
    *,
    code_vip: str,
    discord_id: int,
    claimed_by: int,
    key_type: str,  # "NORMAL" | "GOLD"
) -> Tuple[bool, str]:
    wk = hunt_week_key()
    code = normalize_code(code_vip)
    kt = (key_type or "NORMAL").strip().upper()
    if kt not in ("NORMAL","GOLD"):
        kt = "NORMAL"

    # 1 clé / semaine / VIP (selon ta règle)
    rows = sheets.get_all_records(T_KEYS)
    for r in rows:
        if str(r.get("week_key","")).strip() == wk and normalize_code(str(r.get("code_vip",""))) == code:
            return False, "😾 Une clé a déjà été claim cette semaine pour ce VIP."

    sheets.append_by_headers(T_KEYS, {
        "week_key": wk,
        "code_vip": code,
        "discord_id": str(discord_id),
        "key_type": kt,
        "claimed_at": now_iso(),
        "claimed_by": str(claimed_by),
        "opened_at": "",
        "open_item_id": "",
        "open_qty": "",
        "open_rarity": "",
    })

    return True, f"✅ Clé **{kt}** attribuée (semaine `{wk}`)."

# ==========================================================
# RNG helpers (d20 etc.)
# ==========================================================
def roll_d20() -> int:
    return random.randint(1, 20)

def roll_range(a: int, b: int) -> int:
    return random.randint(int(a), int(b))

def weighted_choice(items: List[Tuple[str, int]]) -> str:
    """
    items = [(value, weight), ...]
    """
    total = sum(int(w) for _, w in items)
    r = random.randint(1, max(1, total))
    acc = 0
    for val, w in items:
        acc += int(w)
        if r <= acc:
            return val
    return items[-1][0] if items else ""

# ==========================================================
# Loot table (simple, prêt pour shop/keys)
# ==========================================================
LOOT_ITEMS: Dict[str, Dict[str, Any]] = {
    "bandage":   {"label": "Bandage", "rarity": "COMMON",    "kind": "heal"},
    "medkit":    {"label": "Kit de soin", "rarity": "UNCOMMON","kind": "heal"},
    "pistol":    {"label": "Pistolet", "rarity": "UNCOMMON", "kind": "weapon"},
    "smg":       {"label": "SMG", "rarity": "RARE",          "kind": "weapon"},
    "batte":     {"label": "Batte", "rarity": "COMMON",      "kind": "weapon"},
    "couteau":   {"label": "Couteau", "rarity": "COMMON",    "kind": "weapon"},
    "lucille":   {"label": "Lucille", "rarity": "LEGENDARY", "kind": "weapon"},
    "jail_card": {"label": "Carte de sortie de prison", "rarity": "RARE", "kind": "utility"},
}

def roll_loot(*, gold_bonus: bool = False) -> List[Tuple[str, int]]:
    """
    Retourne [(item_id, qty)].
    - gold_bonus augmente la proba rare/légendaire.
    - petite proba de "jail_card" dans les coffres.
    """
    r = random.random()

    # proba jail card (petite)
    jail_card_p = 0.03 if not gold_bonus else 0.06
    if r < jail_card_p:
        return [("jail_card", 1)]

    # ensuite loot normal
    r2 = random.random()
    if gold_bonus:
        # GOLD: push rare/legend
        if r2 < 0.48:
            return [("bandage", 1)]
        if r2 < 0.68:
            return [(random.choice(["batte", "couteau"]), 1)]
        if r2 < 0.88:
            return [(random.choice(["pistol", "medkit"]), 1)]
        if r2 < 0.985:
            return [("smg", 1)]
        return [("lucille", 1)]

    # NORMAL
    if r2 < 0.60:
        return [("bandage", 1)]
    if r2 < 0.80:
        return [(random.choice(["batte", "couteau"]), 1)]
    if r2 < 0.92:
        return [(random.choice(["pistol", "medkit"]), 1)]
    if r2 < 0.99:
        return [("smg", 1)]
    return [("lucille", 1)]

def money_reward() -> int:
    # petit filet d'argent quasi tout le temps
    return random.randint(15, 45)

def xp_reward() -> int:
    return random.randint(8, 20)
