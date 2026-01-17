# domain.py
# -*- coding: utf-8 -*-

from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Any, Dict, List, Optional, Tuple

from services import SheetsService, normalize_code, normalize_name, display_name, parse_iso_dt, extract_tag, now_iso

# --------------------------
# Levels
# --------------------------

async def get_levels(sheets: SheetsService) -> List[Tuple[int, int, str]]:
    rows = await sheets.all_records("NIVEAUX")
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

async def calc_level(sheets: SheetsService, points: int) -> int:
    lvl = 1
    for n, pmin, _ in await get_levels(sheets):
        if points >= pmin:
            lvl = n
    return lvl

async def get_level_info(sheets: SheetsService, lvl: int) -> Tuple[int, str]:
    for n, pmin, av in await get_levels(sheets):
        if n == lvl:
            return pmin, av
    return 0, ""

def split_avantages(raw: str) -> List[str]:
    raw = (raw or "").strip()
    if not raw:
        return []
    return [p.strip() for p in raw.split("|") if p.strip()]

async def get_all_unlocked_advantages(sheets: SheetsService, current_level: int) -> str:
    all_adv = []
    for lvl in range(1, current_level + 1):
        _, raw = await get_level_info(sheets, lvl)
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

# --------------------------
# VIP queries
# --------------------------

async def find_vip_row_by_code(sheets: SheetsService, code_vip: str) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
    code = normalize_code(code_vip)
    rows = await sheets.all_records("VIP")
    for idx, r in enumerate(rows, start=2):
        if normalize_code(str(r.get("code_vip", ""))) == code:
            return idx, r
    return None, None

async def find_vip_row_by_discord_id(sheets: SheetsService, discord_id: int) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
    rows = await sheets.all_records("VIP")
    for idx, r in enumerate(rows, start=2):
        if str(r.get("discord_id", "")).strip() == str(discord_id):
            return idx, r
    return None, None

async def find_vip_row_by_pseudo(sheets: SheetsService, pseudo: str) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
    target = normalize_name(pseudo)
    rows = await sheets.all_records("VIP")
    for idx, r in enumerate(rows, start=2):
        if normalize_name(str(r.get("pseudo", ""))) == target:
            return idx, r
    return None, None

async def find_vip_row_by_code_or_pseudo(sheets: SheetsService, term: str) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
    if not term:
        return None, None
    t = term.strip()
    if t.upper().startswith("SUB-"):
        return await find_vip_row_by_code(sheets, t)
    return await find_vip_row_by_pseudo(sheets, t)

async def get_rank_among_active(sheets: SheetsService, code_vip: str) -> Tuple[int, int]:
    code = normalize_code(code_vip)
    rows = await sheets.all_records("VIP")
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

async def log_rows_for_vip(sheets: SheetsService, code_vip: str) -> List[Dict[str, Any]]:
    code = normalize_code(code_vip)
    out = []
    for r in await sheets.all_records("LOG"):
        c = normalize_code(str(r.get("code_vip", "")))
        if c == code:
            out.append(r)
    return out

async def get_last_actions(sheets: SheetsService, code_vip: str, tz: ZoneInfo, n: int = 3):
    items = []
    rows = await log_rows_for_vip(sheets, code_vip)
    for r in rows:
        dt = parse_iso_dt(str(r.get("timestamp", "")).strip(), tz)
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
        reason = str(r.get("raison", "") or "").strip()
        items.append((dt, a, qty, pts_add, reason))
    items.sort(key=lambda x: x[0], reverse=True)
    return items[:n]

# --------------------------
# Actions + limits
# --------------------------

async def get_actions_map(sheets: SheetsService) -> Dict[str, Dict[str, Any]]:
    rows = await sheets.all_records("ACTIONS")
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

def last_friday_17(now: datetime) -> datetime:
    target_weekday = 4
    candidate = now.replace(hour=17, minute=0, second=0, microsecond=0)
    days_back = (candidate.weekday() - target_weekday) % 7
    candidate = candidate - timedelta(days=days_back)
    if now < candidate:
        candidate -= timedelta(days=7)
    return candidate

def challenge_week_window(now: datetime) -> Tuple[datetime, datetime]:
    start = last_friday_17(now)
    end = start + timedelta(days=7)
    return start, end

async def count_usage(
    sheets: SheetsService,
    code_vip: str,
    action_key: str,
    start_dt: datetime,
    end_dt: datetime,
    tz: ZoneInfo,
    tag_prefix: Optional[str] = None,
    tag_value: Optional[str] = None
) -> int:
    action = (action_key or "").strip().upper()
    rows = await log_rows_for_vip(sheets, code_vip)
    total = 0
    for r in rows:
        dt = parse_iso_dt(str(r.get("timestamp", "")).strip(), tz)
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

async def check_action_limit(
    sheets: SheetsService,
    code_vip: str,
    action_key: str,
    qty: int,
    reason: str,
    author_is_hg: bool,
    tz: ZoneInfo,
) -> Tuple[bool, str, bool]:
    actions = await get_actions_map(sheets)
    row = actions.get((action_key or "").strip().upper())
    if not row:
        return False, "Action inconnue dans l’onglet ACTIONS.", False

    lim_raw = str(row.get("limite", "")).strip().lower()
    if ("illimit" in lim_raw) or (lim_raw == ""):
        return True, "", False

    now = datetime.now(tz)
    start, end = challenge_week_window(now)

    ev = extract_tag(reason or "", "event:")
    poche = extract_tag(reason or "", "poche:")

    if "semaine" in lim_raw and "/" in lim_raw:
        try:
            max_per_week = int(lim_raw.split("/")[0].strip())
        except Exception:
            max_per_week = 1

        used = await count_usage(sheets, code_vip, action_key, start, end, tz)
        if used + qty <= max_per_week:
            return True, "", False
        if author_is_hg:
            return False, f"Limite hebdo atteinte (**{used}/{max_per_week}**). HG peut forcer.", True
        return False, f"😾 Limite hebdo atteinte (**{used}/{max_per_week}**).", False

    if "par event" in lim_raw:
        if not ev:
            return False, "😾 Ajoute `event:NomEvent` dans la raison (ou utilise la fenêtre de vente + note).", False
        used = await count_usage(
            sheets, code_vip, action_key,
            start_dt=datetime.min.replace(tzinfo=tz),
            end_dt=datetime.max.replace(tzinfo=tz),
            tz=tz,
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
        used = await count_usage(
            sheets, code_vip, action_key,
            start_dt=datetime.min.replace(tzinfo=tz),
            end_dt=datetime.max.replace(tzinfo=tz),
            tz=tz,
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

# --------------------------
# Add points (central)
# --------------------------

async def add_points_by_action(
    sheets: SheetsService,
    code_vip: str,
    action_key: str,
    qty: int,
    staff_id: int,
    reason: str,
    author_is_hg: bool,
    employee_allowed_actions: set[str],
    tz: ZoneInfo
):
    action_key = (action_key or "").strip().upper()
    code = normalize_code(code_vip)

    if qty <= 0:
        return False, "La quantité doit être > 0."

    # employé limité
    if not author_is_hg and action_key not in employee_allowed_actions:
        return False, "😾 Action réservée aux HG. Employés: ACHAT, RECYCLAGE, VENTE."

    ok_lim, msg_lim, needs_confirm = await check_action_limit(sheets, code, action_key, qty, reason or "", author_is_hg, tz)
    if not ok_lim:
        if needs_confirm:
            return False, msg_lim + " (HG peut forcer via une commande dédiée si tu veux l'ajouter)."
        return False, msg_lim

    row_i, vip = await find_vip_row_by_code(sheets, code)
    if not row_i or not vip:
        return False, "Code VIP introuvable."

    status = str(vip.get("status", "ACTIVE")).strip().upper()
    if status != "ACTIVE":
        return False, "VIP désactivé."

    actions = await get_actions_map(sheets)
    if action_key not in actions:
        return False, f"Action inconnue: {action_key}."

    pu = int(actions[action_key]["points_unite"])
    delta = pu * qty

    old_points = int(vip.get("points", 0))
    new_points = old_points + delta
    old_level = int(vip.get("niveau", 1))
    new_level = await calc_level(sheets, new_points)

    # update VIP
    await sheets.batch_update("VIP", [
        {"range": f"D{row_i}", "values": [[new_points]]},  # points
        {"range": f"E{row_i}", "values": [[new_level]]},   # niveau
    ])

    # log
    await sheets.append_by_headers("LOG", {
        "timestamp": now_iso(),
        "staff_id": str(staff_id),
        "code_vip": code,
        "action_key": action_key,
        "quantite": int(qty),
        "points_unite": int(pu),
        "delta_points": int(delta),
        "raison": reason or "",
    })

    return True, (delta, new_points, old_level, new_level)

# --------------------------
# Cave ban create
# --------------------------

def split_aliases(raw: str) -> List[str]:
    if not raw:
        return []
    raw = str(raw)
    for sep in [";", "|"]:
        raw = raw.replace(sep, ",")
    items = [normalize_name(x) for x in raw.split(",")]
    return [x for x in items if x]

async def load_ban_create_list(sheets: SheetsService):
    rows = await sheets.all_records("VIP_BAN_CREATE")
    bans = []
    for r in rows:
        pseudo_ref = normalize_name(r.get("pseudo_ref", ""))
        aliases = split_aliases(r.get("aliases", ""))
        discord_id = str(r.get("discord_id", "")).strip()
        reason = str(r.get("reason", "")).strip()
        bans.append({"pseudo_ref": pseudo_ref, "aliases": aliases, "discord_id": discord_id, "reason": reason})
    return bans

async def check_banned_for_create(sheets: SheetsService, pseudo: str = "", discord_id: str = ""):
    p = normalize_name(pseudo)
    did = str(discord_id or "").strip()
    for b in await load_ban_create_list(sheets):
        if did and b["discord_id"] and did == b["discord_id"]:
            return True, b["reason"] or "Raison interne"
        if p and b["pseudo_ref"] and p == b["pseudo_ref"]:
            return True, b["reason"] or "Raison interne"
        if p and b["aliases"] and p in b["aliases"]:
            return True, b["reason"] or "Raison interne"
    return False, ""

async def log_create_blocked(sheets: SheetsService, staff_id: int, pseudo_attempted: str, discord_id: str = "", reason: str = ""):
    details = f"Tentative création VIP bloquée | pseudo='{pseudo_attempted}'"
    if discord_id:
        details += f" | discord_id={discord_id}"
    if reason:
        details += f" | reason={reason}"
    await sheets.append_by_headers("LOG", {
        "timestamp": now_iso(),
        "staff_id": str(staff_id),
        "code_vip": "",
        "action_key": "CREATE_BLOCKED",
        "quantite": 1,
        "points_unite": 0,
        "delta_points": 0,
        "raison": details,
    })
