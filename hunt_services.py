# hunt_services.py
# -*- coding: utf-8 -*-

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import random

from services import SheetsService, PARIS_TZ, now_fr, now_iso, normalize_code, display_name, challenge_week_window


# ==========================================================
# Tables Sheets (tu les as déjà dans ton Google Sheets)
# ==========================================================
T_PLAYERS = "HUNT_PLAYERS"
T_DAILY = "HUNT_DAILY"
T_WEEKLY = "HUNT_WEEKLY"
T_KEYS = "HUNT_KEYS"
T_LOG = "HUNT_LOG"
T_ITEMS = "HUNT_ITEMS"
T_BOSSES = "HUNT_BOSSES"
T_REPUTATION = "HUNT_REPUTATION"


# ==========================================================
# Helpers clés
# ==========================================================
def today_key_fr(now: Optional[datetime] = None) -> str:
    now = (now or now_fr()).astimezone(PARIS_TZ)
    return now.strftime("%Y-%m-%d")

def week_key_fr(now: Optional[datetime] = None) -> str:
    """
    Une clé stable hebdo basée sur ta fenêtre challenge_week_window()
    (vendredi 17:00 -> vendredi 17:00).
    """
    start, _ = challenge_week_window(now or now_fr())
    return start.astimezone(PARIS_TZ).strftime("W%Y-%m-%d")  # ex: W2026-01-09

def _safe_int(x: Any, default: int = 0) -> int:
    try:
        return int(x)
    except Exception:
        return default

def _safe_str(x: Any) -> str:
    return str(x or "").strip()

def _find_row_by_key(
    rows: List[Dict[str, Any]],
    *,
    key_fields: List[str],
    key_values: List[str],
) -> Optional[Tuple[int, Dict[str, Any]]]:
    """
    rows vient de get_all_records -> index start=2 (ligne Sheets)
    """
    for idx, r in enumerate(rows, start=2):
        ok = True
        for f, v in zip(key_fields, key_values):
            if _safe_str(r.get(f)).lower() != _safe_str(v).lower():
                ok = False
                break
        if ok:
            return idx, r
    return None

def append_log(s: SheetsService, payload: Dict[str, Any]) -> None:
    """
    Log RP optionnel: si l’onglet existe + headers ok.
    """
    try:
        s.append_by_headers(T_LOG, payload)
    except Exception:
        # log non bloquant
        pass


# ==========================================================
# PLAYERS
# Colonnes conseillées (si tu veux aligner tes headers):
# discord_id | code_vip | pseudo | avatar_tag | level | xp | money
# hp | max_hp | str | dex | int | cha | perception
# ally_tag | ally_week | jail_until | created_at | last_seen
# ==========================================================
def ensure_player(
    s: SheetsService,
    *,
    discord_id: int,
    code_vip: str,
    pseudo: str,
    avatar_tag: str = "",
) -> Tuple[int, Dict[str, Any]]:
    code = normalize_code(code_vip)
    did = str(discord_id)

    rows = s.get_all_records(T_PLAYERS)
    found = _find_row_by_key(rows, key_fields=["discord_id"], key_values=[did])
    if found:
        row_i, row = found
        # update soft: last_seen + pseudo si vide
        try:
            s.update_cell_by_header(T_PLAYERS, row_i, "last_seen", now_iso())
        except Exception:
            pass
        if not _safe_str(row.get("pseudo")) and pseudo:
            try:
                s.update_cell_by_header(T_PLAYERS, row_i, "pseudo", display_name(pseudo))
            except Exception:
                pass
        if not _safe_str(row.get("code_vip")) and code:
            try:
                s.update_cell_by_header(T_PLAYERS, row_i, "code_vip", code)
            except Exception:
                pass
        return row_i, row

    # create minimal safe defaults
    payload = {
        "discord_id": did,
        "code_vip": code,
        "pseudo": display_name(pseudo),
        "avatar_tag": _safe_str(avatar_tag),

        "level": 1,
        "xp": 0,
        "money": 0,

        "max_hp": 20,
        "hp": 20,

        "str": 1,
        "dex": 1,
        "int": 1,
        "cha": 1,
        "perception": 1,

        "ally_tag": "",
        "ally_week": "",
        "jail_until": "",
        "created_at": now_iso(),
        "last_seen": now_iso(),
    }
    s.append_by_headers(T_PLAYERS, payload)

    # relire
    rows2 = s.get_all_records(T_PLAYERS)
    found2 = _find_row_by_key(rows2, key_fields=["discord_id"], key_values=[did])
    if not found2:
        raise RuntimeError("Impossible de créer/récupérer le joueur HUNT_PLAYERS.")
    return found2[0], found2[1]


def get_player(s: SheetsService, discord_id: int) -> Optional[Tuple[int, Dict[str, Any]]]:
    did = str(discord_id)
    rows = s.get_all_records(T_PLAYERS)
    return _find_row_by_key(rows, key_fields=["discord_id"], key_values=[did])


def add_money(s: SheetsService, player_row_i: int, current_money: int, delta: int) -> int:
    new_money = max(0, int(current_money) + int(delta))
    s.update_cell_by_header(T_PLAYERS, player_row_i, "money", new_money)
    return new_money

def set_jail_until(s: SheetsService, player_row_i: int, until_iso: str) -> None:
    s.update_cell_by_header(T_PLAYERS, player_row_i, "jail_until", until_iso)


def is_in_jail(player: Dict[str, Any], now: Optional[datetime] = None) -> Tuple[bool, Optional[datetime]]:
    now = (now or now_fr()).astimezone(PARIS_TZ)
    raw = _safe_str(player.get("jail_until"))
    if not raw:
        return False, None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(PARIS_TZ)
        if now < dt:
            return True, dt
        return False, None
    except Exception:
        return False, None


# ==========================================================
# DAILY (anti double participation)
# Colonnes conseillées:
# day_key | discord_id | code_vip | started_at | finished_at | seed | result | notes
# ==========================================================
def daily_already_started(s: SheetsService, discord_id: int, day_key: Optional[str] = None) -> bool:
    dk = day_key or today_key_fr()
    did = str(discord_id)
    rows = s.get_all_records(T_DAILY)
    return _find_row_by_key(rows, key_fields=["day_key", "discord_id"], key_values=[dk, did]) is not None

def start_daily(s: SheetsService, *, discord_id: int, code_vip: str, seed: str = "") -> None:
    """
    On écrit une ligne dès le lancement pour bloquer le multi-try.
    """
    dk = today_key_fr()
    did = str(discord_id)
    if daily_already_started(s, discord_id, dk):
        return

    payload = {
        "day_key": dk,
        "discord_id": did,
        "code_vip": normalize_code(code_vip),
        "started_at": now_iso(),
        "finished_at": "",
        "seed": seed or "",
        "result": "",
        "notes": "",
    }
    s.append_by_headers(T_DAILY, payload)

def finish_daily(s: SheetsService, *, discord_id: int, day_key: Optional[str] = None, result: str = "", notes: str = "") -> None:
    dk = day_key or today_key_fr()
    did = str(discord_id)
    rows = s.get_all_records(T_DAILY)
    found = _find_row_by_key(rows, key_fields=["day_key", "discord_id"], key_values=[dk, did])
    if not found:
        return
    row_i, _ = found
    try:
        s.update_cell_by_header(T_DAILY, row_i, "finished_at", now_iso())
    except Exception:
        pass
    if result:
        try:
            s.update_cell_by_header(T_DAILY, row_i, "result", result[:200])
        except Exception:
            pass
    if notes:
        try:
            s.update_cell_by_header(T_DAILY, row_i, "notes", notes[:500])
        except Exception:
            pass


# ==========================================================
# WEEKLY (score hebdo)
# Colonnes conseillées:
# week_key | discord_id | code_vip | pseudo | score | wins | last_played
# ==========================================================
def add_weekly_score(
    s: SheetsService,
    *,
    discord_id: int,
    code_vip: str,
    pseudo: str,
    delta_score: int,
) -> int:
    wk = week_key_fr()
    did = str(discord_id)
    code = normalize_code(code_vip)
    rows = s.get_all_records(T_WEEKLY)
    found = _find_row_by_key(rows, key_fields=["week_key", "discord_id"], key_values=[wk, did])

    if not found:
        payload = {
            "week_key": wk,
            "discord_id": did,
            "code_vip": code,
            "pseudo": display_name(pseudo),
            "score": int(delta_score),
            "wins": 0,
            "last_played": now_iso(),
        }
        s.append_by_headers(T_WEEKLY, payload)
        return int(delta_score)

    row_i, row = found
    cur = _safe_int(row.get("score"), 0)
    newv = max(0, cur + int(delta_score))
    s.update_cell_by_header(T_WEEKLY, row_i, "score", newv)
    try:
        s.update_cell_by_header(T_WEEKLY, row_i, "last_played", now_iso())
    except Exception:
        pass
    return newv


# ==========================================================
# KEYS (staff claim)
# Colonnes conseillées:
# week_key | code_vip | discord_id | tier | claimed_at | claimed_by | opened_at | reward
# ==========================================================
def key_already_claimed_this_week(s: SheetsService, code_vip: str) -> bool:
    wk = week_key_fr()
    code = normalize_code(code_vip)
    rows = s.get_all_records(T_KEYS)
    return _find_row_by_key(rows, key_fields=["week_key", "code_vip"], key_values=[wk, code]) is not None

def claim_key(
    s: SheetsService,
    *,
    code_vip: str,
    discord_id: int,
    tier: str,          # "NORMAL" | "GOLD"
    staff_id: int,
) -> Tuple[bool, str]:
    wk = week_key_fr()
    code = normalize_code(code_vip)
    t = (tier or "NORMAL").strip().upper()
    if t not in ("NORMAL", "GOLD"):
        t = "NORMAL"

    if key_already_claimed_this_week(s, code):
        return False, f"Clé déjà claim cette semaine pour `{code}`."

    payload = {
        "week_key": wk,
        "code_vip": code,
        "discord_id": str(discord_id),
        "tier": t,
        "claimed_at": now_iso(),
        "claimed_by": str(staff_id),
        "opened_at": "",
        "reward": "",
    }
    s.append_by_headers(T_KEYS, payload)

    append_log(s, {
        "timestamp": now_iso(),
        "event": "KEY_CLAIM",
        "code_vip": code,
        "discord_id": str(discord_id),
        "staff_id": str(staff_id),
        "details": f"tier={t} week={wk}",
    })

    return True, f"✅ Clé `{t}` claim pour `{code}` (week {wk})."


# ==========================================================
# Mini RNG utilitaire (pour daily)
# ==========================================================
def roll_d20() -> int:
    return random.randint(1, 20)

def roll_range(a: int, b: int) -> int:
    return random.randint(a, b)

def weighted_choice(items: List[Tuple[str, int]]) -> str:
    """
    items = [(value, weight), ...]
    """
    total = sum(w for _, w in items)
    r = random.randint(1, max(1, total))
    acc = 0
    for val, w in items:
        acc += w
        if r <= acc:
            return val
    return items[-1][0] if items else ""
