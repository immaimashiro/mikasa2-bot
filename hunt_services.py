# hunt_services.py
# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import services  # ton services.py
from services import SheetsService, now_fr, now_iso, PARIS_TZ

# ==========================================================
# Tables Sheets attendues (tu as dit qu'elles existent déjà)
# ==========================================================
# HUNT_PLAYERS: profil joueur (vip, avatar, progression, monnaie)
# HUNT_DAILY: une ligne par jour et par joueur (anti double participation)
# HUNT_WEEKLY: score hebdo par joueur (top semaine + bonus)
# HUNT_KEYS: clés attribuées par la direction (claim staff) + coffre ouvert
# HUNT_LOG: log RP (optionnel mais utile)

T_PLAYERS = "HUNT_PLAYERS"
T_DAILY   = "HUNT_DAILY"
T_WEEKLY  = "HUNT_WEEKLY"
T_KEYS    = "HUNT_KEYS"
T_LOG     = "HUNT_LOG"


# ==========================================================
# Helpers date (jour FR)
# ==========================================================

def fr_day_key(dt: Optional[datetime] = None) -> str:
    """YYYY-MM-DD (FR)"""
    dt = dt or now_fr()
    dt = dt.astimezone(PARIS_TZ)
    return dt.strftime("%Y-%m-%d")

def fr_week_key(dt: Optional[datetime] = None) -> str:
    """
    Semaine ISO "YYYY-Www" (FR).
    Exemple: 2026-W03
    """
    dt = dt or now_fr()
    dt = dt.astimezone(PARIS_TZ)
    y, w, _ = dt.isocalendar()
    return f"{y}-W{w:02d}"


# ==========================================================
# Utils Sheets "find row by headers"
# ==========================================================

def _safe_str(x: Any) -> str:
    return str(x).strip() if x is not None else ""

def _safe_int(x: Any, default: int = 0) -> int:
    try:
        return int(x)
    except Exception:
        return default

def _normalize_code(code_vip: str) -> str:
    return services.normalize_code(code_vip)

def find_row(
    s: SheetsService,
    table: str,
    predicate,
) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
    """
    Retourne (row_index_sheet, row_dict) avec row_index_sheet en index Google Sheets (1=header).
    """
    rows = s.get_all_records(table)
    for idx, r in enumerate(rows, start=2):
        try:
            if predicate(r):
                return idx, r
        except Exception:
            continue
    return None, None

def upsert_row_by_headers(
    s: SheetsService,
    table: str,
    row_i: Optional[int],
    data: Dict[str, Any],
):
    """
    Si row_i est None -> append.
    Sinon -> update cellule par cellule via headers.
    """
    if not row_i:
        s.append_by_headers(table, data)
        return
    for k, v in data.items():
        if k:
            s.update_cell_by_header(table, row_i, k, v)


# ==========================================================
# Player profile
# ==========================================================

@dataclass
class PlayerProfile:
    code_vip: str
    discord_id: str
    avatar_tag: str
    dollars: int
    xp: int
    level: int
    ally_tag: str
    ally_active_week: str  # week_key quand ally obtenu (pour limiter à 1/sem)
    last_daily_day: str    # pour debug
    created_at: str

def profile_from_row(r: Dict[str, Any]) -> PlayerProfile:
    return PlayerProfile(
        code_vip=_normalize_code(_safe_str(r.get("code_vip"))),
        discord_id=_safe_str(r.get("discord_id")),
        avatar_tag=_safe_str(r.get("avatar_tag")).upper(),
        dollars=_safe_int(r.get("dollars"), 0),
        xp=_safe_int(r.get("xp"), 0),
        level=_safe_int(r.get("level"), 1),
        ally_tag=_safe_str(r.get("ally_tag")).upper(),
        ally_active_week=_safe_str(r.get("ally_active_week")),
        last_daily_day=_safe_str(r.get("last_daily_day")),
        created_at=_safe_str(r.get("created_at")),
    )

def get_or_create_player(
    s: SheetsService,
    *,
    code_vip: str,
    discord_id: int,
    default_avatar_tag: str,
) -> Tuple[int, PlayerProfile, bool]:
    """
    Récupère ou crée le profil HUNT_PLAYERS.
    returns (row_i, profile, created_bool)
    """
    code = _normalize_code(code_vip)
    did = str(discord_id)

    row_i, row = find_row(s, T_PLAYERS, lambda r: _normalize_code(_safe_str(r.get("code_vip"))) == code)
    if row_i and row:
        return row_i, profile_from_row(row), False

    # Create
    data = {
        "code_vip": code,
        "discord_id": did,
        "avatar_tag": (default_avatar_tag or "").upper(),
        "dollars": 0,
        "xp": 0,
        "level": 1,
        "ally_tag": "",
        "ally_active_week": "",
        "last_daily_day": "",
        "created_at": now_iso(),
    }
    s.append_by_headers(T_PLAYERS, data)

    row_i2, row2 = find_row(s, T_PLAYERS, lambda r: _normalize_code(_safe_str(r.get("code_vip"))) == code)
    if not row_i2 or not row2:
        raise RuntimeError("Impossible de créer le profil HUNT_PLAYERS.")
    return row_i2, profile_from_row(row2), True

def update_player_fields(s: SheetsService, row_i: int, **fields):
    clean = {}
    for k, v in fields.items():
        if v is None:
            continue
        clean[k] = v
    if clean:
        upsert_row_by_headers(s, T_PLAYERS, row_i, clean)


# ==========================================================
# Daily participation (anti double)
# ==========================================================

@dataclass
class DailyState:
    day_key: str
    week_key: str
    code_vip: str
    discord_id: str
    started_at: str
    finished_at: str
    state: str         # "STARTED" | "FINISHED"
    correct: int       # utile si tu veux QCM plus tard
    points_awarded: int
    details: str

def daily_from_row(r: Dict[str, Any]) -> DailyState:
    return DailyState(
        day_key=_safe_str(r.get("day_key")),
        week_key=_safe_str(r.get("week_key")),
        code_vip=_normalize_code(_safe_str(r.get("code_vip"))),
        discord_id=_safe_str(r.get("discord_id")),
        started_at=_safe_str(r.get("started_at")),
        finished_at=_safe_str(r.get("finished_at")),
        state=_safe_str(r.get("state")) or "STARTED",
        correct=_safe_int(r.get("correct"), 0),
        points_awarded=_safe_int(r.get("points_awarded"), 0),
        details=_safe_str(r.get("details")),
    )

def get_daily_row(s: SheetsService, code_vip: str, day_key: str) -> Tuple[Optional[int], Optional[DailyState]]:
    code = _normalize_code(code_vip)
    row_i, row = find_row(
        s, T_DAILY,
        lambda r: _normalize_code(_safe_str(r.get("code_vip"))) == code and _safe_str(r.get("day_key")) == day_key
    )
    if row_i and row:
        return row_i, daily_from_row(row)
    return None, None

def create_daily_started(
    s: SheetsService,
    *,
    code_vip: str,
    discord_id: int,
    day_key: str,
    week_key: str,
    details: str = "",
) -> DailyState:
    data = {
        "day_key": day_key,
        "week_key": week_key,
        "code_vip": _normalize_code(code_vip),
        "discord_id": str(discord_id),
        "started_at": now_iso(),
        "finished_at": "",
        "state": "STARTED",
        "correct": 0,
        "points_awarded": 0,
        "details": details or "",
    }
    s.append_by_headers(T_DAILY, data)
    _, st = get_daily_row(s, code_vip, day_key)
    if not st:
        raise RuntimeError("Impossible de créer la ligne HUNT_DAILY.")
    return st

def mark_daily_finished(
    s: SheetsService,
    row_i: int,
    *,
    correct: int = 0,
    points_awarded: int = 0,
    details: str = "",
):
    upsert_row_by_headers(s, T_DAILY, row_i, {
        "finished_at": now_iso(),
        "state": "FINISHED",
        "correct": int(correct),
        "points_awarded": int(points_awarded),
        "details": details or "",
    })


# ==========================================================
# Weekly scoreboard
# ==========================================================

@dataclass
class WeeklyScore:
    week_key: str
    code_vip: str
    discord_id: str
    wins: int
    points: int
    updated_at: str

def weekly_from_row(r: Dict[str, Any]) -> WeeklyScore:
    return WeeklyScore(
        week_key=_safe_str(r.get("week_key")),
        code_vip=_normalize_code(_safe_str(r.get("code_vip"))),
        discord_id=_safe_str(r.get("discord_id")),
        wins=_safe_int(r.get("wins"), 0),
        points=_safe_int(r.get("points"), 0),
        updated_at=_safe_str(r.get("updated_at")),
    )

def get_weekly_row(s: SheetsService, code_vip: str, week_key: str) -> Tuple[Optional[int], Optional[WeeklyScore]]:
    code = _normalize_code(code_vip)
    row_i, row = find_row(
        s, T_WEEKLY,
        lambda r: _safe_str(r.get("week_key")) == week_key and _normalize_code(_safe_str(r.get("code_vip"))) == code
    )
    if row_i and row:
        return row_i, weekly_from_row(row)
    return None, None

def bump_weekly_score(
    s: SheetsService,
    *,
    code_vip: str,
    discord_id: int,
    week_key: str,
    add_points: int = 0,
    add_wins: int = 0,
):
    row_i, row = get_weekly_row(s, code_vip, week_key)
    if not row_i or not row:
        s.append_by_headers(T_WEEKLY, {
            "week_key": week_key,
            "code_vip": _normalize_code(code_vip),
            "discord_id": str(discord_id),
            "wins": int(add_wins),
            "points": int(add_points),
            "updated_at": now_iso(),
        })
        return

    upsert_row_by_headers(s, T_WEEKLY, row_i, {
        "wins": int(row.wins + add_wins),
        "points": int(row.points + add_points),
        "updated_at": now_iso(),
    })


# ==========================================================
# Keys (staff claim + open)
# ==========================================================

@dataclass
class KeyEntry:
    week_key: str
    code_vip: str
    discord_id: str
    key_type: str          # KEY_NORMAL | KEY_GOLD
    claimed_at: str
    claimed_by: str        # staff discord id
    opened_at: str
    loot_id: str
    loot_name: str

def key_from_row(r: Dict[str, Any]) -> KeyEntry:
    return KeyEntry(
        week_key=_safe_str(r.get("week_key")),
        code_vip=_normalize_code(_safe_str(r.get("code_vip"))),
        discord_id=_safe_str(r.get("discord_id")),
        key_type=_safe_str(r.get("key_type")).upper(),
        claimed_at=_safe_str(r.get("claimed_at")),
        claimed_by=_safe_str(r.get("claimed_by")),
        opened_at=_safe_str(r.get("opened_at")),
        loot_id=_safe_str(r.get("loot_id")),
        loot_name=_safe_str(r.get("loot_name")),
    )

def key_already_claimed_this_week(s: SheetsService, code_vip: str, week_key: str) -> bool:
    code = _normalize_code(code_vip)
    _, row = find_row(
        s, T_KEYS,
        lambda r: _safe_str(r.get("week_key")) == week_key and _normalize_code(_safe_str(r.get("code_vip"))) == code
    )
    return bool(row)

def add_key_claim(
    s: SheetsService,
    *,
    code_vip: str,
    discord_id: int,
    week_key: str,
    key_type: str,
    claimed_by_staff_id: int,
):
    s.append_by_headers(T_KEYS, {
        "week_key": week_key,
        "code_vip": _normalize_code(code_vip),
        "discord_id": str(discord_id),
        "key_type": (key_type or "").upper(),
        "claimed_at": now_iso(),
        "claimed_by": str(claimed_by_staff_id),
        "opened_at": "",
        "loot_id": "",
        "loot_name": "",
    })

def list_unopened_keys(s: SheetsService, code_vip: str) -> List[Tuple[int, KeyEntry]]:
    code = _normalize_code(code_vip)
    out: List[Tuple[int, KeyEntry]] = []
    rows = s.get_all_records(T_KEYS)
    for idx, r in enumerate(rows, start=2):
        if _normalize_code(_safe_str(r.get("code_vip"))) != code:
            continue
        opened = _safe_str(r.get("opened_at"))
        if opened:
            continue
        out.append((idx, key_from_row(r)))
    # plus ancien d'abord
    out.sort(key=lambda x: x[1].claimed_at or "")
    return out

def mark_key_opened(s: SheetsService, row_i: int, loot_id: str, loot_name: str):
    upsert_row_by_headers(s, T_KEYS, row_i, {
        "opened_at": now_iso(),
        "loot_id": loot_id,
        "loot_name": loot_name,
    })


# ==========================================================
# Optional log RP (pratique)
# ==========================================================

def append_hunt_log(
    s: SheetsService,
    *,
    code_vip: str,
    discord_id: int,
    kind: str,
    details: str,
):
    try:
        s.append_by_headers(T_LOG, {
            "timestamp": now_iso(),
            "code_vip": _normalize_code(code_vip),
            "discord_id": str(discord_id),
            "kind": (kind or "").upper(),
            "details": details or "",
        })
    except Exception:
        # Log = optionnel, jamais bloquant
        pass

