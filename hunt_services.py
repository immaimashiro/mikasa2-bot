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

# ----------------------------
# equipped_json helpers
# ----------------------------
def equipped_load(raw: str) -> Dict[str, Any]:
    try:
        if isinstance(raw, dict):
            return raw
        return json.loads(raw) if raw else {}
    except Exception:
        return {}

def equipped_dump(obj: Dict[str, Any]) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False)
    except Exception:
        return "{}"

def player_equipped_get(row: Dict[str, Any]) -> Dict[str, Any]:
    return equipped_load(str(row.get("equipped_json", "") or ""))

def player_equipped_set(sheets, row_i: int, eq: Dict[str, Any]) -> None:
    sheets.update_cell_by_header(T_PLAYERS, int(row_i), "equipped_json", equipped_dump(eq))

def equip_get(row: Dict[str, Any], *, who: str, slot: str) -> str:
    eq = player_equipped_get(row)
    root = "equip_player" if who == "player" else "equip_ally"
    d = eq.get(root, {}) if isinstance(eq.get(root, {}), dict) else {}
    return str(d.get(slot, "") or "").strip()

def equip_set(sheets, row_i: int, row: Dict[str, Any], *, who: str, slot: str, item_id: str) -> None:
    eq = player_equipped_get(row)
    root = "equip_player" if who == "player" else "equip_ally"
    if not isinstance(eq.get(root, {}), dict):
        eq[root] = {}
    eq[root][slot] = (item_id or "").strip()
    player_equipped_set(sheets, int(row_i), eq)

def equip_clear(sheets, row_i: int, row: Dict[str, Any], *, who: str, slot: str) -> None:
    equip_set(sheets, row_i, row, who=who, slot=slot, item_id="")

def ally_change_week_key_get(row: Dict[str, Any]) -> str:
    eq = player_equipped_get(row)
    return str(eq.get("ally_change_week_key", "") or "").strip()

def ally_change_week_key_set(sheets, row_i: int, row: Dict[str, Any], week_key: str) -> None:
    eq = player_equipped_get(row)
    eq["ally_change_week_key"] = str(week_key)
    player_equipped_set(sheets, int(row_i), eq)

# ----------------------------
# Weekly score
# ----------------------------
def weekly_score_calc(weekly_row: Dict[str, Any]) -> int:
    def _i(k: str) -> int:
        try:
            return int(weekly_row.get(k, 0) or 0)
        except Exception:
            return 0

    wins = _i("wins")
    deaths = _i("deaths")
    boss = _i("boss_kills")
    steals = _i("steals")
    jail = _i("jail_count")

    # formule stable & lisible (tu ajusteras après tests)
    score = (
        wins * 10
        + boss * 50
        + steals * 15
        - deaths * 20
        - jail * 10
    )
    return int(score)

def weekly_find_row(sheets, week_key: str, discord_id: int) -> Tuple[int, Optional[Dict[str, Any]]]:
    rows = sheets.get_all_records(T_WEEKLY)
    did = str(int(discord_id))
    for idx, r in enumerate(rows, start=2):  # header row = 1
        if str(r.get("week_key", "")).strip() == week_key and str(r.get("discord_id", "")).strip() == did:
            return idx, r
    return 0, None

def weekly_ensure_row(sheets, *, week_key: str, discord_id: int, code_vip: str, pseudo: str) -> Tuple[int, Dict[str, Any]]:
    row_i, row = weekly_find_row(sheets, week_key, discord_id)
    if row_i and row:
        return row_i, row

    base = {
        "week_key": week_key,
        "discord_id": str(int(discord_id)),
        "code_vip": (code_vip or "").strip(),
        "pseudo": (pseudo or "").strip(),
        "score": 0,
        "good_runs": 0,
        "wins": 0,
        "deaths": 0,
        "boss_kills": 0,
        "steals": 0,
        "jail_count": 0,
        "earned_dollars": 0,
        "earned_xp": 0,
        "bonus_claimed": 0,
        "top_rank": 0,
        "updated_at": "",
    }
    sheets.append_by_headers(T_WEEKLY, base)

    # relire
    row_i2, row2 = weekly_find_row(sheets, week_key, discord_id)
    return row_i2, (row2 or base)

def weekly_recalc_and_save(sheets, week_key: str, discord_id: int) -> None:
    row_i, row = weekly_find_row(sheets, week_key, discord_id)
    if not row_i or not row:
        return
    score = weekly_score_calc(row)
    sheets.update_cell_by_header(T_WEEKLY, int(row_i), "score", str(score))
    # si tu as services.now_iso() ailleurs, remplace
    # sheets.update_cell_by_header(T_WEEKLY, int(row_i), "updated_at", services.now_iso())

def weekly_top(sheets, week_key: str, limit: int = 10) -> List[Dict[str, Any]]:
    rows = sheets.get_all_records(T_WEEKLY)
    wk = str(week_key).strip()
    pool = [r for r in rows if str(r.get("week_key", "")).strip() == wk]
    def _score(r):
        try:
            return int(r.get("score", 0) or 0)
        except Exception:
            return 0
    pool.sort(key=_score, reverse=True)
    return pool[: max(1, int(limit))]

def equipped_load(raw: str) -> Dict[str, Any]:
    try:
        if isinstance(raw, dict):
            return raw
        return json.loads(raw) if raw else {}
    except Exception:
        return {}

def equipped_dump(obj: Dict[str, Any]) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False)
    except Exception:
        return "{}"

def player_equipped_get(row: Dict[str, Any]) -> Dict[str, Any]:
    return equipped_load(str(row.get("equipped_json", "") or ""))

def player_equipped_set(sheets, row_i: int, eq: Dict[str, Any]) -> None:
    sheets.update_cell_by_header(T_PLAYERS, int(row_i), "equipped_json", equipped_dump(eq))

# --- Ally roll cooldown (hebdo) stocké dans equipped_json ---
def ally_roll_week_key_get(row: Dict[str, Any]) -> str:
    eq = player_equipped_get(row)
    return str(eq.get("ally_roll_week_key", "") or "").strip()

def ally_roll_week_key_set(sheets, row_i: int, week_key: str) -> None:
    # set "déjà tenté cette semaine" même si fail, pour empêcher le spam
    # (on l'écrit au moment du roll, succès ou échec)
    # => view/UI dira "déjà tenté"
    row_i = int(row_i)
    # reload row? optionnel si tu as déjà row sous la main
    # ici on suppose que l'appelant a row, sinon tu peux fetch
    # (je te laisse simple: on écrit direct en lisant avant via get_player_row)
    _, row = get_player_row(sheets, int(sheets.get_last_discord_id_placeholder()) )  # <-- REMOVE si tu n’as pas ce helper
    # ↑ IMPORTANT: si tu n'as pas ce helper, ignore ce bloc et fais la version "safe" ci-dessous.
    pass

def ally_roll_week_key_set_with_row(sheets, row_i: int, row: Dict[str, Any], week_key: str) -> None:
    eq = player_equipped_get(row)
    eq["ally_roll_week_key"] = str(week_key)
    player_equipped_set(sheets, int(row_i), eq)

def player_get_ally(row: Dict[str, Any]) -> Tuple[str, str]:
    return (str(row.get("ally_tag", "") or "").strip(), str(row.get("ally_url", "") or "").strip())

def player_set_ally(sheets, row_i: int, ally_tag: str, ally_url: str) -> None:
    sheets.update_cell_by_header(T_PLAYERS, int(row_i), "ally_tag", (ally_tag or "").strip())
    sheets.update_cell_by_header(T_PLAYERS, int(row_i), "ally_url", (ally_url or "").strip())

def player_clear_ally(sheets, row_i: int) -> None:
    player_set_ally(sheets, int(row_i), "", "")

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

def inv_iter(inv: dict):
    for k, v in (inv or {}).items():
        try:
            yield str(k), int(v or 0)
        except Exception:
            continue

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

# ---------- JSON helpers ----------
def _json_load(s: str, default):
    try:
        if not s:
            return default
        return json.loads(s)
    except Exception:
        return default

def inv_load(s: str) -> Dict[str, int]:
    data = _json_load(s, {})
    if not isinstance(data, dict):
        return {}
    out: Dict[str, int] = {}
    for k, v in data.items():
        try:
            out[str(k)] = max(0, int(v))
        except Exception:
            pass
    return out

def inv_dump(inv: Dict[str, int]) -> str:
    clean = {k: int(v) for k, v in inv.items() if int(v) > 0}
    return json.dumps(clean, ensure_ascii=False)

def inv_count(inv: Dict[str, int], item_id: str) -> int:
    return int(inv.get(item_id, 0) or 0)

def inv_add(inv: Dict[str, int], item_id: str, qty: int) -> None:
    if qty <= 0:
        return
    inv[item_id] = int(inv.get(item_id, 0) or 0) + int(qty)

def inv_remove(inv: Dict[str, int], item_id: str, qty: int) -> bool:
    if qty <= 0:
        return True
    cur = int(inv.get(item_id, 0) or 0)
    if cur < qty:
        return False
    newv = cur - qty
    if newv <= 0:
        inv.pop(item_id, None)
    else:
        inv[item_id] = newv
    return True

def equipped_load(s: str) -> Dict[str, Any]:
    data = _json_load(s, {})
    return data if isinstance(data, dict) else {}

def equipped_dump(eq: Dict[str, Any]) -> str:
    return json.dumps(eq or {}, ensure_ascii=False)

# ---------- Rows with row index (robuste) ----------
def _records_with_row_index(sheets, tab_name: str) -> List[Tuple[int, Dict[str, Any]]]:
    """
    Retourne [(row_index, record_dict)].
    row_index = index Google Sheets (1-based). On suppose headers en row 1, donc data row starts at 2.
    """
    ws_fn = getattr(sheets, "ws", None)
    if callable(ws_fn):
        ws = ws_fn(tab_name)
        values = ws.get_all_values()
        if not values or len(values) < 2:
            return []
        headers = [h.strip() for h in values[0]]
        out = []
        for i, row in enumerate(values[1:], start=2):
            if not any(cell.strip() for cell in row):
                continue
            rec = {headers[j]: (row[j] if j < len(row) else "") for j in range(len(headers))}
            out.append((i, rec))
        return out

    # fallback: enumerate get_all_records (moins fiable si trous)
    rows = sheets.get_all_records(tab_name) or []
    out = []
    for idx, r in enumerate(rows, start=2):
        out.append((idx, r))
    return out

# ---------- Players ----------
def get_player_row(sheets, discord_id: int) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
    did = str(int(discord_id))
    for row_i, r in _records_with_row_index(sheets, T_PLAYERS):
        if str(r.get("discord_id", "")).strip() == did:
            return row_i, r
    return None, None

def ensure_player(sheets, *, discord_id: int, vip_code: str, pseudo: str, is_employee: bool = False) -> Tuple[int, Dict[str, Any]]:
    row_i, row = get_player_row(sheets, discord_id)
    if row_i and row:
        return row_i, row

    payload = {
        "discord_id": str(int(discord_id)),
        "vip_code": (vip_code or "").strip(),
        "pseudo": (pseudo or "").strip() or (vip_code or "").strip(),
        "is_employee": "1" if is_employee else "0",
        "avatar_tag": "",
        "avatar_url": "",
        "ally_tag": "",
        "ally_url": "",
        "level": "1",
        "xp": "0",
        "xp_total": "0",
        "stats_hp": "10",
        "stats_atk": "2",
        "stats_def": "1",
        "stats_per": "1",
        "stats_cha": "1",
        "stats_luck": "1",
        "hunt_dollars": "0",
        "heat": "0",
        "jail_until": "",
        "last_daily_date": "",
        "weekly_week_key": "",
        "weekly_wins": "0",
        "total_runs": "0",
        "total_wins": "0",
        "total_deaths": "0",
        "inventory_json": "{}",
        "equipped_json": "{}",
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    sheets.append_by_headers(T_PLAYERS, payload)
    # re-fetch
    row_i2, row2 = get_player_row(sheets, discord_id)
    return int(row_i2 or 2), (row2 or payload)

def player_set_avatar(sheets, row_i: int, *, tag: str, url: str) -> None:
    sheets.update_cell_by_header(T_PLAYERS, row_i, "avatar_tag", (tag or "").strip())
    sheets.update_cell_by_header(T_PLAYERS, row_i, "avatar_url", (url or "").strip())
    sheets.update_cell_by_header(T_PLAYERS, row_i, "updated_at", now_iso())

def player_money_get(row: Dict[str, Any]) -> int:
    try:
        return int(row.get("hunt_dollars", 0) or 0)
    except Exception:
        return 0

def player_money_set(sheets, row_i: int, new_amount: int) -> None:
    sheets.update_cell_by_header(T_PLAYERS, row_i, "hunt_dollars", str(max(0, int(new_amount))))
    sheets.update_cell_by_header(T_PLAYERS, row_i, "updated_at", now_iso())

def player_inv_get(row: Dict[str, Any]) -> Dict[str, int]:
    return inv_load(str(row.get("inventory_json", "") or ""))

def player_inv_set(sheets, row_i: int, inv: Dict[str, int]) -> None:
    sheets.update_cell_by_header(T_PLAYERS, row_i, "inventory_json", inv_dump(inv))
    sheets.update_cell_by_header(T_PLAYERS, row_i, "updated_at", now_iso())

def player_eq_get(row: Dict[str, Any]) -> Dict[str, Any]:
    return equipped_load(str(row.get("equipped_json", "") or ""))

def player_eq_set(sheets, row_i: int, eq: Dict[str, Any]) -> None:
    sheets.update_cell_by_header(T_PLAYERS, row_i, "equipped_json", equipped_dump(eq))
    sheets.update_cell_by_header(T_PLAYERS, row_i, "updated_at", now_iso())

# ---------- Items ----------
def items_all(sheets) -> List[Dict[str, Any]]:
    return sheets.get_all_records(T_ITEMS) or []

def item_by_id(sheets, item_id: str) -> Optional[Dict[str, Any]]:
    iid = (item_id or "").strip()
    if not iid:
        return None
    for it in items_all(sheets):
        if str(it.get("item_id", "")).strip() == iid:
            return it
    return None

def item_price(it: Dict[str, Any]) -> int:
    try:
        return int(it.get("price", 0) or 0)
    except Exception:
        return 0

# ---------- Keys (open) ----------
def find_unopened_key_row(sheets, discord_id: int, key_type: Optional[str] = None) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
    did = str(int(discord_id))
    kt = (key_type or "").strip().lower()
    for row_i, r in _records_with_row_index(sheets, T_KEYS):
        if str(r.get("discord_id", "")).strip() != did:
            continue
        if str(r.get("opened_at", "")).strip():
            continue
        if kt and str(r.get("key_type", "")).strip().lower() != kt:
            continue
        return row_i, r
    return None, None

def log(sheets, *, discord_id: int, code_vip: str, kind: str, message: str, meta: Dict[str, Any] | None = None) -> None:
    sheets.append_by_headers(T_LOG, {
        "timestamp": now_iso(),
        "discord_id": str(int(discord_id)),
        "code_vip": (code_vip or "").strip(),
        "kind": (kind or "").strip(),
        "message": (message or "").strip(),
        "meta_json": json.dumps(meta or {}, ensure_ascii=False),
    })

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

# -------------------------
# Items
# -------------------------
_ITEMS_CACHE: Dict[str, Dict[str, Any]] = {}

def items_all(sheets) -> List[Dict[str, Any]]:
    rows = sheets.get_all_records(T_ITEMS) or []
    out = []
    for r in rows:
        item_id = str(r.get("item_id", "")).strip()
        if not item_id:
            continue
        out.append(r)
    return out

def items_refresh_cache(sheets) -> None:
    global _ITEMS_CACHE
    _ITEMS_CACHE = {}
    for r in items_all(sheets):
        _ITEMS_CACHE[str(r.get("item_id", "")).strip()] = r

def item_get(sheets, item_id: str) -> Optional[Dict[str, Any]]:
    iid = (item_id or "").strip()
    if not iid:
        return None
    if iid not in _ITEMS_CACHE:
        items_refresh_cache(sheets)
    return _ITEMS_CACHE.get(iid)

def item_price(item_row: Dict[str, Any]) -> int:
    try:
        return int(item_row.get("price", 0) or 0)
    except Exception:
        return 0

def item_type(item_row: Dict[str, Any]) -> str:
    return str(item_row.get("type", "") or "").strip().lower()

def item_rarity(item_row: Dict[str, Any]) -> str:
    return str(item_row.get("rarity", "") or "").strip()

def item_power(item_row: Dict[str, Any]) -> Dict[str, Any]:
    raw = item_row.get("power_json", "") or ""
    if isinstance(raw, dict):
        return raw
    s = str(raw).strip()
    if not s:
        return {}
    try:
        return json.loads(s)
    except Exception:
        return {}

# -------------------------
# Equipped JSON
# -------------------------
def equip_load(raw: str) -> Dict[str, Any]:
    if isinstance(raw, dict):
        d = raw
    else:
        s = str(raw or "").strip()
        if not s:
            d = {}
        else:
            try:
                d = json.loads(s)
            except Exception:
                d = {}
    # schema minimal
    d.setdefault("player_weapon", "")
    d.setdefault("player_armor", "")
    d.setdefault("ally_weapon", "")
    d.setdefault("ally_armor", "")
    return d

def equip_dump(equip: Dict[str, Any]) -> str:
    try:
        return json.dumps(equip or {}, ensure_ascii=False)
    except Exception:
        return "{}"

def equip_set_slot(equip: Dict[str, Any], slot: str, item_id: str) -> Dict[str, Any]:
    slot = (slot or "").strip()
    equip = equip_load(equip)
    equip[slot] = (item_id or "").strip()
    return equip

# -------------------------
# Money helpers (si jamais)
# -------------------------
def player_money_get(row: Dict[str, Any]) -> int:
    # si tu l'as déjà, ignore cette fonction
    try:
        return int(row.get("hunt_dollars", 0) or 0)
    except Exception:
        return 0

def player_money_set(sheets, row_i: int, amount: int) -> None:
    sheets.update_cell_by_header(T_PLAYERS, row_i, "hunt_dollars", str(int(amount)))

def keys_find_unopened_for_player(sheets, *, discord_id: int) -> List[Tuple[int, Dict[str, Any]]]:
    """
    Retourne [(row_i, row_dict)] des clés claimées mais pas ouvertes, pour ce joueur.
    row_i est 2-indexé (comme d’habitude dans tes helpers), si ton système l’est.
    """
    rows = sheets.get_all_records(T_KEYS) or []
    out: List[Tuple[int, Dict[str, Any]]] = []
    for idx, r in enumerate(rows, start=2):
        did = str(r.get("discord_id", "")).strip()
        if did != str(int(discord_id)):
            continue
        opened_at = str(r.get("opened_at", "")).strip()
        if opened_at:
            continue
        out.append((idx, r))
    return out

def keys_count_in_inventory(player_row: Dict[str, Any]) -> Tuple[int, int]:
    inv = inv_load(str(player_row.get("inventory_json", "")))
    normal = int(inv_count(inv, "key"))
    gold = int(inv_count(inv, "gold_key"))
    return normal, gold

def keys_log_open_result(
    sheets,
    *,
    key_row_i: int,
    opened_at: str,
    item_id: str,
    qty: int,
    rarity: str,
    item_name: str,
    meta: Optional[Dict[str, Any]] = None
) -> None:
    sheets.update_cell_by_header(T_KEYS, key_row_i, "opened_at", opened_at)
    sheets.update_cell_by_header(T_KEYS, key_row_i, "open_item_id", str(item_id))
    sheets.update_cell_by_header(T_KEYS, key_row_i, "open_qty", str(int(qty)))
    sheets.update_cell_by_header(T_KEYS, key_row_i, "open_rarity", str(rarity))
    sheets.update_cell_by_header(T_KEYS, key_row_i, "open_item_name", str(item_name))

    # meta_json optionnel (tu l’as ajouté)
    if meta is not None:
        try:
            sheets.update_cell_by_header(T_KEYS, key_row_i, "meta_json", json.dumps(meta, ensure_ascii=False))
        except Exception:
            pass

def player_hp_get(row: Dict[str, Any]) -> int:
    try:
        return int(row.get("stats_hp", 0) or 0)
    except Exception:
        return 0

def player_hp_set(sheets, row_i: int, hp: int) -> None:
    sheets.update_cell_by_header(T_PLAYERS, row_i, "stats_hp", str(int(hp)))
