# hunt_services.py
# -*- coding: utf-8 -*-

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import random

from services import SheetsService, PARIS_TZ, now_fr, now_iso, normalize_code, display_name, challenge_week_window
import domain

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


def _find_player_row_by_discord_id(sheets, discord_id: int) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
    rows = sheets.get_all_records(T_PLAYERS)
    for idx, r in enumerate(rows, start=2):
        if str(r.get("discord_id", "")).strip() == str(discord_id):
            return idx, r
    return None, None


def ensure_hunt_player(sheets, *, discord_id: int, code_vip: str, pseudo: str, is_employee: bool) -> Tuple[int, Dict[str, Any]]:
    """
    Crée la ligne HUNT_PLAYERS si elle n'existe pas, sinon met à jour les champs de base.
    Retourne (row_index, row_dict).
    """
    row_i, row = _find_player_row_by_discord_id(sheets, discord_id)
    ts = now_iso()

    if row_i and row:
        # rafraîchir infos de base
        sheets.update_cell_by_header(T_PLAYERS, row_i, "code_vip", code_vip)
        sheets.update_cell_by_header(T_PLAYERS, row_i, "pseudo", display_name(pseudo))
        sheets.update_cell_by_header(T_PLAYERS, row_i, "is_employee", "TRUE" if is_employee else "FALSE")
        sheets.update_cell_by_header(T_PLAYERS, row_i, "updated_at", ts)
        # relire proprement
        row_i2, row2 = _find_player_row_by_discord_id(sheets, discord_id)
        return (row_i2 or row_i), (row2 or row)

    # create defaults
    base = {
        "discord_id": str(discord_id),
        "code_vip": code_vip,
        "pseudo": display_name(pseudo),
        "is_employee": "TRUE" if is_employee else "FALSE",

        "avatar_tag": "",
        "avatar_url": "",
        "ally_tag": "",
        "ally_url": "",

        "level": 1,
        "xp": 0,
        "xp_total": 0,

        "stats_hp": 20,
        "stats_hp_max": 20,
        "stats_atk": 3,
        "stats_def": 2,
        "stats_per": 2,
        "stats_cha": 2,
        "stats_luck": 1,

        "hunt_dollars": 0,
        "heat": 0,
        "jail_until": "",
        "last_daily_date": "",

        "weekly_week_key": "",
        "weekly_wins": 0,

        "total_runs": 0,
        "total_wins": 0,
        "total_deaths": 0,

        "inventory_json": "{}",

        "created_at": ts,
        "updated_at": ts,
    }

    sheets.append_by_headers(T_PLAYERS, base)
    row_i3, row3 = _find_player_row_by_discord_id(sheets, discord_id)
    if not row_i3 or not row3:
        raise RuntimeError("Impossible de créer/récupérer la ligne HUNT_PLAYERS.")
    return row_i3, row3


def set_avatar(sheets, *, discord_id: int, avatar_tag: str, avatar_url: str) -> None:
    row_i, row = _find_player_row_by_discord_id(sheets, discord_id)
    if not row_i:
        raise RuntimeError("Profil HUNT introuvable (HUNT_PLAYERS).")

    sheets.update_cell_by_header(T_PLAYERS, row_i, "avatar_tag", avatar_tag)
    sheets.update_cell_by_header(T_PLAYERS, row_i, "avatar_url", avatar_url)
    sheets.update_cell_by_header(T_PLAYERS, row_i, "updated_at", now_iso())

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

# hunt_services.py (ajouts)
from datetime import timedelta
from services import now_fr, now_iso, PARIS_TZ

T_PLAYERS = "HUNT_PLAYERS"   # déjà chez toi normalement
T_LOG = "HUNT_LOG"

def iso_fr(dt):
    return dt.astimezone(PARIS_TZ).isoformat(timespec="seconds")

def parse_iso_fr(s: str):
    from datetime import datetime
    try:
        return datetime.fromisoformat(s).astimezone(PARIS_TZ)
    except Exception:
        return None

def get_player(s, discord_id: int):
    rows = s.get_all_records(T_PLAYERS)
    did = str(discord_id)
    for idx, r in enumerate(rows, start=2):
        if str(r.get("discord_id","")).strip() == did:
            return idx, r
    return None

def ensure_player(s, discord_id: int, code_vip: str = "", pseudo: str = ""):
    got = get_player(s, discord_id)
    if got:
        return got
    s.append_by_headers(T_PLAYERS, {
        "discord_id": str(discord_id),
        "code_vip": code_vip,
        "pseudo": pseudo,
        "hunt_dollars": 0,
        "jail_until": "",
        "heat": 0,           # récidive
        "avatar_tag": "",    # ex: MAI/ROXY/...
        "avatar_url": "",    # image portrait
        "created_at": now_iso(),
        "updated_at": now_iso(),
    })
    return get_player(s, discord_id)

def is_jailed(s, discord_id: int):
    got = get_player(s, discord_id)
    if not got:
        return False, None
    _, row = got
    until = parse_iso_fr(str(row.get("jail_until","") or "").strip())
    if not until:
        return False, None
    return (now_fr() < until), until

def add_heat(s, discord_id: int, amount: int):
    got = ensure_player(s, discord_id)
    row_i, row = got
    heat = 0
    try: heat = int(row.get("heat", 0) or 0)
    except Exception: heat = 0
    heat = max(0, min(100, heat + int(amount)))
    s.update_cell_by_header(T_PLAYERS, row_i, "heat", heat)
    s.update_cell_by_header(T_PLAYERS, row_i, "updated_at", now_iso())
    return heat

def set_jail(s, discord_id: int, hours: float, reason: str):
    """
    cap 12h. hours peut être décimal (0.5h=30min).
    """
    got = ensure_player(s, discord_id)
    row_i, row = got

    cap_hours = min(12.0, max(0.0, float(hours)))
    until = now_fr() + timedelta(seconds=int(cap_hours * 3600))

    s.update_cell_by_header(T_PLAYERS, row_i, "jail_until", iso_fr(until))
    s.update_cell_by_header(T_PLAYERS, row_i, "updated_at", now_iso())

    # log RP
    try:
        s.append_by_headers(T_LOG, {
            "timestamp": now_iso(),
            "discord_id": str(discord_id),
            "type": "JAIL",
            "value": f"{cap_hours:.2f}h",
            "notes": reason[:500],
        })
    except Exception:
        pass

    return until

def compute_sentence_hours(crime: str, heat: int, roll: int):
    """
    crime: 'STEAL' | 'KILL'
    roll: d20 ou autre (pour variance)
    """
    heat = max(0, min(100, int(heat)))
    # multiplicateur récidive 1.0 -> 1.4
    mult = 1.0 + (0.4 * (heat / 100.0))

    if crime == "STEAL":
        # 0.5h -> 3h
        base = 0.5 + (max(0, 18 - roll) / 18.0) * 2.5
    else:  # KILL
        # 4h -> 12h
        base = 4.0 + (max(0, 18 - roll) / 18.0) * 8.0

    hours = base * mult
    return min(12.0, max(0.25, hours))
