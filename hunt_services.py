# hunt_services.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import random
from typing import Any, Dict, List, Optional, Tuple, Iterator
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

def today_key(dt=None) -> str:
    dt = dt or now_fr()
    return dt.strftime("%Y-%m-%d")

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
# NOTE: on AJOUTE equipped_json (sinon impossible de stocker equip + meta ally/week)
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
    "equipped_json",  # ✅ AJOUT
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
    "open_item_id","open_qty","open_rarity",
    # "open_item_name", "meta_json"  # si tu veux les ajouter plus tard: OK, mais pas requis
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
def json_loads_safe(s: Any, default: Any) -> Any:
    try:
        if s is None:
            return default
        if isinstance(s, (dict, list)):
            return s
        ss = str(s).strip()
        if not ss:
            return default
        return json.loads(ss)
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
    Semaine HUNT calée sur: vendredi 17:00 -> vendredi 17:00
    On utilise la date du START comme identifiant stable.
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
# Logging (unique)
# ==========================================================
def log(sheets: SheetsService, *, discord_id: int, code_vip: str, kind: str, message: str, meta: Optional[Dict[str, Any]] = None) -> None:
    # meta: on le stringify dans message si tu veux, mais on ne dépend pas d'une colonne meta_json
    msg = (message or "").strip()
    if meta:
        try:
            msg = f"{msg} | meta={json.dumps(meta, ensure_ascii=False)}"
        except Exception:
            pass

    sheets.append_by_headers(T_LOG, {
        "timestamp": now_iso(),
        "discord_id": str(int(discord_id)),
        "code_vip": normalize_code(code_vip),
        "kind": (kind or "INFO").strip(),
        "message": msg[:1800],
    })

# Alias compat (si ton code appelle encore hs.hunt_log)
def hunt_log(sheets: SheetsService, *, discord_id: int, code_vip: str, kind: str, message: str) -> None:
    log(sheets, discord_id=discord_id, code_vip=code_vip, kind=kind, message=message)

# ==========================================================
# Inventory JSON (simple: dict {item_id: qty})
# ==========================================================
def inv_load(s: Any) -> Dict[str, int]:
    d = json_loads_safe(s, {})
    if not isinstance(d, dict):
        return {}
    out: Dict[str, int] = {}
    for k, v in d.items():
        try:
            out[str(k)] = max(0, int(v))
        except Exception:
            out[str(k)] = 0
    return out

def inv_dump(inv: Dict[str, int]) -> str:
    clean = {str(k): int(v) for k, v in (inv or {}).items() if int(v) > 0}
    return json.dumps(clean, ensure_ascii=False)

def inv_add(inv: Dict[str, int], item_id: str, qty: int) -> None:
    iid = (item_id or "").strip()
    if not iid:
        return
    inv[iid] = max(0, int(inv.get(iid, 0)) + int(qty))

def inv_remove(inv: Dict[str, int], item_id: str, qty: int) -> bool:
    iid = (item_id or "").strip()
    if not iid:
        return False
    q = int(qty)
    if q <= 0:
        return True
    cur = int(inv.get(iid, 0))
    if cur < q:
        return False
    newv = cur - q
    if newv <= 0:
        inv.pop(iid, None)
    else:
        inv[iid] = newv
    return True

def inv_count(inv: Dict[str, int], item_id: str) -> int:
    return int(inv.get((item_id or "").strip(), 0))

def inv_iter(inv: Dict[str, int]) -> Iterator[Tuple[str, int]]:
    for k, v in sorted((inv or {}).items(), key=lambda kv: (-int(kv[1]), str(kv[0]))):
        yield str(k), int(v)

# ==========================================================
# equipped_json schema (unique, stable)
# {
#   "player": {"weapon":"", "armor":"", "stim":""},
#   "ally":   {"weapon":"", "armor":"", "stim":""},
#   "meta":   {"ally_roll_week_key":"", "ally_change_week_key":""}
# }
# ==========================================================
def equipped_load(s: Any) -> Dict[str, Any]:
    d = json_loads_safe(s, {})
    if not isinstance(d, dict):
        d = {}
    d.setdefault("player", {})
    d.setdefault("ally", {})
    d.setdefault("meta", {})
    d["player"].setdefault("weapon", "")
    d["player"].setdefault("armor", "")
    d["player"].setdefault("stim", "")
    d["ally"].setdefault("weapon", "")
    d["ally"].setdefault("armor", "")
    d["ally"].setdefault("stim", "")
    d["meta"].setdefault("ally_roll_week_key", "")
    d["meta"].setdefault("ally_change_week_key", "")
    return d

def equipped_dump(d: Dict[str, Any]) -> str:
    return json.dumps(equipped_load(d), ensure_ascii=False)

def equip_get(player_row: Dict[str, Any], *, who: str, slot: str) -> str:
    eq = equipped_load(player_row.get("equipped_json", ""))
    who = "ally" if (who or "").strip().lower() == "ally" else "player"
    slot = (slot or "").strip().lower()
    return str(eq.get(who, {}).get(slot, "") or "").strip()

def equip_set(sheets: SheetsService, row_i: int, player_row: Dict[str, Any], *, who: str, slot: str, item_id: str) -> None:
    eq = equipped_load(player_row.get("equipped_json", ""))
    who = "ally" if (who or "").strip().lower() == "ally" else "player"
    slot = (slot or "").strip().lower()
    eq.setdefault(who, {})
    eq[who][slot] = (item_id or "").strip()
    sheets.update_cell_by_header(T_PLAYERS, int(row_i), "equipped_json", equipped_dump(eq))
    sheets.update_cell_by_header(T_PLAYERS, int(row_i), "updated_at", now_iso())

def meta_get(player_row: Dict[str, Any], key: str, default=None):
    eq = equipped_load(player_row.get("equipped_json", ""))
    return eq.get("meta", {}).get(key, default)

def meta_set(sheets: SheetsService, row_i: int, player_row: Dict[str, Any], key: str, value: Any) -> None:
    eq = equipped_load(player_row.get("equipped_json", ""))
    eq.setdefault("meta", {})
    eq["meta"][str(key)] = value
    sheets.update_cell_by_header(T_PLAYERS, int(row_i), "equipped_json", equipped_dump(eq))
    sheets.update_cell_by_header(T_PLAYERS, int(row_i), "updated_at", now_iso())

def ally_roll_week_key_get(row: Dict[str, Any]) -> str:
    return str(meta_get(row, "ally_roll_week_key", "") or "").strip()

def ally_roll_week_key_set_with_row(sheets: SheetsService, row_i: int, row: Dict[str, Any], week_key: str) -> None:
    meta_set(sheets, int(row_i), row, "ally_roll_week_key", str(week_key))

def ally_change_week_key_get(row: Dict[str, Any]) -> str:
    return str(meta_get(row, "ally_change_week_key", "") or "").strip()

def ally_change_week_key_set(sheets: SheetsService, row_i: int, row: Dict[str, Any], week_key: str) -> None:
    meta_set(sheets, int(row_i), row, "ally_change_week_key", str(week_key))

# ==========================================================
# Rows with row index (robuste)
# ==========================================================
def _records_with_row_index(sheets: SheetsService, tab_name: str) -> List[Tuple[int, Dict[str, Any]]]:
    ws_fn = getattr(sheets, "ws", None)
    if callable(ws_fn):
        ws = ws_fn(tab_name)
        values = ws.get_all_values()
        if not values or len(values) < 2:
            return []
        headers = [h.strip() for h in values[0]]
        out: List[Tuple[int, Dict[str, Any]]] = []
        for i, row in enumerate(values[1:], start=2):
            if not any(str(cell).strip() for cell in row):
                continue
            rec = {headers[j]: (row[j] if j < len(row) else "") for j in range(len(headers))}
            out.append((i, rec))
        return out

    rows = sheets.get_all_records(tab_name) or []
    return [(idx, r) for idx, r in enumerate(rows, start=2)]

# ==========================================================
# Players (single API: get_player_row / ensure_player)
# ==========================================================
def get_player_row(sheets: SheetsService, discord_id: int) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
    did = str(int(discord_id))
    for row_i, r in _records_with_row_index(sheets, T_PLAYERS):
        if str(r.get("discord_id", "")).strip() == did:
            return row_i, r
    return None, None

def ensure_player(
    sheets: SheetsService,
    *,
    discord_id: int,
    vip_code: str,
    pseudo: str,
    is_employee: bool = False
) -> Tuple[int, Dict[str, Any]]:
    """
    Crée un profil minimal si absent (cohérent avec H_PLAYERS).
    """
    row_i, row = get_player_row(sheets, discord_id)
    if row_i and row:
        # update de base (pseudo, vip, employee) sans casser le reste
        sheets.update_cell_by_header(T_PLAYERS, int(row_i), "code_vip", normalize_code(vip_code))
        sheets.update_cell_by_header(T_PLAYERS, int(row_i), "pseudo", display_name(pseudo) or normalize_code(vip_code))
        sheets.update_cell_by_header(T_PLAYERS, int(row_i), "is_employee", "TRUE" if is_employee else "FALSE")
        sheets.update_cell_by_header(T_PLAYERS, int(row_i), "updated_at", now_iso())
        row_i2, row2 = get_player_row(sheets, discord_id)
        return int(row_i2 or row_i), (row2 or row)

    now = now_iso()
    payload: Dict[str, Any] = {
        "discord_id": str(int(discord_id)),
        "code_vip": normalize_code(vip_code),
        "pseudo": display_name(pseudo) or normalize_code(vip_code),
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

        "inventory_json": "{}",
        "equipped_json": equipped_dump({}),
        "created_at": now,
        "updated_at": now,
    }
    sheets.append_by_headers(T_PLAYERS, payload)

    row_i2, row2 = get_player_row(sheets, discord_id)
    if not row_i2 or not row2:
        raise RuntimeError("Impossible de créer HUNT_PLAYERS (ligne non retrouvée).")
    return int(row_i2), row2

def player_set_avatar(sheets: SheetsService, row_i: int, tag: str, url: str) -> None:
    sheets.update_cell_by_header(T_PLAYERS, int(row_i), "avatar_tag", (tag or "").strip().upper())
    sheets.update_cell_by_header(T_PLAYERS, int(row_i), "avatar_url", (url or "").strip())
    sheets.update_cell_by_header(T_PLAYERS, int(row_i), "updated_at", now_iso())

def player_get_ally(row: Dict[str, Any]) -> Tuple[str, str]:
    return (str(row.get("ally_tag", "") or "").strip().upper(), str(row.get("ally_url", "") or "").strip())

def player_set_ally(sheets: SheetsService, row_i: int, ally_tag: str, ally_url: str) -> None:
    sheets.update_cell_by_header(T_PLAYERS, int(row_i), "ally_tag", (ally_tag or "").strip().upper())
    sheets.update_cell_by_header(T_PLAYERS, int(row_i), "ally_url", (ally_url or "").strip())
    sheets.update_cell_by_header(T_PLAYERS, int(row_i), "updated_at", now_iso())

def player_clear_ally(sheets: SheetsService, row_i: int) -> None:
    player_set_ally(sheets, int(row_i), "", "")

def player_money_get(row: Dict[str, Any]) -> int:
    try:
        return int(row.get("hunt_dollars", 0) or 0)
    except Exception:
        return 0

def player_money_set(sheets: SheetsService, row_i: int, new_amount: int) -> None:
    sheets.update_cell_by_header(T_PLAYERS, int(row_i), "hunt_dollars", str(max(0, int(new_amount))))
    sheets.update_cell_by_header(T_PLAYERS, int(row_i), "updated_at", now_iso())

def player_money_add(sheets: SheetsService, row_i: int, delta: int) -> int:
    row_i = int(row_i)
    _, row = get_player_row(sheets, int(sheets.get_all_records(T_PLAYERS)[row_i-2].get("discord_id", 0))) if False else (None, None)  # no-op
    # reload propre:
    row_i2, row2 = _player_row_by_index(sheets, row_i)
    cur = player_money_get(row2 or {})
    newv = max(0, cur + int(delta))
    player_money_set(sheets, row_i, newv)
    return newv

def _player_row_by_index(sheets: SheetsService, row_i: int) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
    # petit helper interne: récupérer la row dict via row_i
    # fallback: on relit tout et on prend index
    rows = sheets.get_all_records(T_PLAYERS) or []
    idx0 = int(row_i) - 2
    if 0 <= idx0 < len(rows):
        return int(row_i), rows[idx0]
    return None, None

def player_inv_get(row: Dict[str, Any]) -> Dict[str, int]:
    return inv_load(row.get("inventory_json", ""))

def player_inv_set(sheets: SheetsService, row_i: int, inv: Dict[str, int]) -> None:
    sheets.update_cell_by_header(T_PLAYERS, int(row_i), "inventory_json", inv_dump(inv))
    sheets.update_cell_by_header(T_PLAYERS, int(row_i), "updated_at", now_iso())

# ==========================================================
# Items
# ==========================================================
_ITEMS_CACHE: Dict[str, Dict[str, Any]] = {}

def items_all(sheets: SheetsService) -> List[Dict[str, Any]]:
    rows = sheets.get_all_records(T_ITEMS) or []
    out: List[Dict[str, Any]] = []
    for r in rows:
        iid = str(r.get("item_id", "")).strip()
        if iid:
            out.append(r)
    return out

def items_refresh_cache(sheets: SheetsService) -> None:
    global _ITEMS_CACHE
    _ITEMS_CACHE = {}
    for r in items_all(sheets):
        _ITEMS_CACHE[str(r.get("item_id", "")).strip()] = r

def item_get(sheets: SheetsService, item_id: str) -> Optional[Dict[str, Any]]:
    iid = (item_id or "").strip()
    if not iid:
        return None
    if iid not in _ITEMS_CACHE:
        items_refresh_cache(sheets)
    return _ITEMS_CACHE.get(iid)

# compat: ton UI appelle parfois item_by_id
def item_by_id(sheets: SheetsService, item_id: str) -> Optional[Dict[str, Any]]:
    return item_get(sheets, item_id)

def item_price(it: Dict[str, Any]) -> int:
    try:
        return int(it.get("price", 0) or 0)
    except Exception:
        return 0

def item_type(it: Dict[str, Any]) -> str:
    return str(it.get("type", "") or "").strip()

def item_rarity(it: Dict[str, Any]) -> str:
    return str(it.get("rarity", "") or "").strip()

def item_power(it: Dict[str, Any]) -> Dict[str, Any]:
    raw = it.get("power_json", "") or ""
    d = json_loads_safe(raw, {})
    return d if isinstance(d, dict) else {}

# ==========================================================
# Weekly score / classement
# ==========================================================
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

    score = (
        wins * 10
        + boss * 50
        + steals * 15
        - deaths * 20
        - jail * 10
    )
    return int(score)

def weekly_find_row(sheets: SheetsService, week_key: str, discord_id: int) -> Tuple[int, Optional[Dict[str, Any]]]:
    rows = sheets.get_all_records(T_WEEKLY) or []
    did = str(int(discord_id))
    wk = str(week_key).strip()
    for idx, r in enumerate(rows, start=2):
        if str(r.get("week_key", "")).strip() == wk and str(r.get("discord_id", "")).strip() == did:
            return idx, r
    return 0, None

def weekly_ensure_row(sheets: SheetsService, *, week_key: str, discord_id: int, code_vip: str, pseudo: str) -> Tuple[int, Dict[str, Any]]:
    row_i, row = weekly_find_row(sheets, week_key, discord_id)
    if row_i and row:
        return row_i, row

    base = {
        "week_key": str(week_key).strip(),
        "discord_id": str(int(discord_id)),
        "code_vip": normalize_code(code_vip),
        "pseudo": display_name(pseudo) or normalize_code(code_vip),

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
        "updated_at": now_iso(),
    }
    sheets.append_by_headers(T_WEEKLY, base)

    row_i2, row2 = weekly_find_row(sheets, week_key, discord_id)
    return int(row_i2 or 0), (row2 or base)

def weekly_recalc_and_save(sheets: SheetsService, week_key: str, discord_id: int) -> None:
    row_i, row = weekly_find_row(sheets, week_key, discord_id)
    if not row_i or not row:
        return
    score = weekly_score_calc(row)
    sheets.update_cell_by_header(T_WEEKLY, int(row_i), "score", str(int(score)))
    sheets.update_cell_by_header(T_WEEKLY, int(row_i), "updated_at", now_iso())

def weekly_top(sheets: SheetsService, week_key: str, limit: int = 10) -> List[Dict[str, Any]]:
    rows = sheets.get_all_records(T_WEEKLY) or []
    wk = str(week_key).strip()
    pool = [r for r in rows if str(r.get("week_key", "")).strip() == wk]

    def _score(r):
        try:
            return int(r.get("score", 0) or 0)
        except Exception:
            return 0

    pool.sort(key=_score, reverse=True)
    return pool[: max(1, int(limit))]

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
    row_i, row = get_player_row(sheets, discord_id)
    if not row_i or not row:
        raise RuntimeError("Profil HUNT introuvable (HUNT_PLAYERS).")
    try:
        heat = int(row.get("heat", 0) or 0)
    except Exception:
        heat = 0
    heat = max(0, min(100, heat + int(delta)))
    sheets.update_cell_by_header(T_PLAYERS, int(row_i), "heat", str(int(heat)))
    sheets.update_cell_by_header(T_PLAYERS, int(row_i), "updated_at", now_iso())
    return heat

def compute_sentence_hours(*, crime: str, heat: int, roll: int) -> float:
    heat = max(0, min(100, int(heat)))
    mult = 1.0 + (0.4 * (heat / 100.0))

    crime = (crime or "").upper().strip()
    roll = max(1, min(20, int(roll)))

    if crime == "STEAL":
        base = 0.5 + (max(0, 18 - roll) / 18.0) * 2.5
    else:
        base = 4.0 + (max(0, 18 - roll) / 18.0) * 8.0

    hours = base * mult
    return float(min(MAX_JAIL_HOURS, max(0.25, hours)))

def set_jail(sheets: SheetsService, *, discord_id: int, hours: float, reason: str = "", code_vip: str = "") -> datetime:
    row_i, _ = get_player_row(sheets, discord_id)
    if not row_i:
        raise RuntimeError("Profil HUNT introuvable (HUNT_PLAYERS).")

    hours = float(min(MAX_JAIL_HOURS, max(0.0, hours)))
    until = now_fr() + timedelta(seconds=int(hours * 3600))

    sheets.update_cell_by_header(T_PLAYERS, int(row_i), "jail_until", until.astimezone(PARIS_TZ).isoformat(timespec="seconds"))
    sheets.update_cell_by_header(T_PLAYERS, int(row_i), "updated_at", now_iso())

    if reason:
        log(sheets, discord_id=discord_id, code_vip=code_vip, kind="JAIL", message=f"{hours:.2f}h | {reason}")
    return until

# ==========================================================
# HUNT_DAILY helpers (minimal, stable)
# ==========================================================
def find_daily_row(sheets: SheetsService, *, discord_id: int, date_key: str) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
    rows = sheets.get_all_records(T_DAILY) or []
    did = str(int(discord_id))
    dk = str(date_key).strip()
    for idx, r in enumerate(rows, start=2):
        if str(r.get("discord_id", "")).strip() == did and str(r.get("date_key","")).strip() == dk:
            return idx, r
    return None, None

def ensure_daily(sheets: SheetsService, *, discord_id: int, code_vip: str, date_key: str) -> Tuple[int, Dict[str, Any]]:
    row_i, row = find_daily_row(sheets, discord_id=discord_id, date_key=date_key)
    if row_i and row:
        return int(row_i), row

    base = {
        "date_key": str(date_key).strip(),
        "discord_id": str(int(discord_id)),
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
    return int(row_i2), row2

def save_daily_state(sheets: SheetsService, row_i: int, *, step: int, state: dict) -> None:
    sheets.update_cell_by_header(T_DAILY, int(row_i), "step", int(step))
    sheets.update_cell_by_header(T_DAILY, int(row_i), "state_json", json_dumps_safe(state))

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
    sheets.update_cell_by_header(T_DAILY, int(row_i), "finished_at", now_iso())
    sheets.update_cell_by_header(T_DAILY, int(row_i), "status", "DONE")
    sheets.update_cell_by_header(T_DAILY, int(row_i), "result_summary", (summary or "")[:1800])
    sheets.update_cell_by_header(T_DAILY, int(row_i), "xp_earned", int(xp))
    sheets.update_cell_by_header(T_DAILY, int(row_i), "dollars_earned", int(dollars))
    sheets.update_cell_by_header(T_DAILY, int(row_i), "dmg_taken", int(dmg))
    sheets.update_cell_by_header(T_DAILY, int(row_i), "death_flag", "TRUE" if died else "FALSE")
    sheets.update_cell_by_header(T_DAILY, int(row_i), "jail_flag", "TRUE" if jailed else "FALSE")

# ==========================================================
# HUNT_KEYS (claim hebdo)
# ==========================================================
def player_has_claimed_key_this_week(sheets: SheetsService, *, discord_id: int, week_key: str) -> bool:
    rows = sheets.get_all_records(T_KEYS) or []
    did = str(int(discord_id))
    wk = str(week_key).strip()
    for r in rows:
        if str(r.get("discord_id","")).strip() == did and str(r.get("week_key","")).strip() == wk:
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

    rows = sheets.get_all_records(T_KEYS) or []
    for r in rows:
        if str(r.get("week_key","")).strip() == wk and normalize_code(str(r.get("code_vip",""))) == code:
            return False, "😾 Une clé a déjà été claim cette semaine pour ce VIP."

    sheets.append_by_headers(T_KEYS, {
        "week_key": wk,
        "code_vip": code,
        "discord_id": str(int(discord_id)),
        "key_type": kt,
        "claimed_at": now_iso(),
        "claimed_by": str(int(claimed_by)),
        "opened_at": "",
        "open_item_id": "",
        "open_qty": "",
        "open_rarity": "",
    })

    return True, f"✅ Clé **{kt}** attribuée (semaine `{wk}`)."
