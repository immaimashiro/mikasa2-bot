# domain.py
# -*- coding: utf-8 -*-

from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime

from services import (
    SheetsService, S3Service,
    normalize_code, normalize_name, display_name, now_iso, now_fr, fmt_fr,
    parse_iso_dt, extract_tag, challenge_week_window,
)

# Employés autorisés (on ajoute ACHAT_LIMITEE comme demandé)
EMPLOYEE_ALLOWED_ACTIONS = {"ACHAT", "ACHAT_LIMITEE", "RECYCLAGE"}

# Défis hebdo (tu peux modifier)
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

# ----------------------------
# VIP Queries
# ----------------------------
def get_all_vips(s: SheetsService) -> List[Dict[str, Any]]:
    return s.get_all_records("VIP")

def find_vip_row_by_code(s: SheetsService, code_vip: str) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
    code = normalize_code(code_vip)
    rows = s.get_all_records("VIP")
    for idx, r in enumerate(rows, start=2):
        if normalize_code(str(r.get("code_vip", ""))) == code:
            return idx, r
    return None, None

def find_vip_row_by_discord_id(s: SheetsService, discord_id: int) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
    rows = s.get_all_records("VIP")
    for idx, r in enumerate(rows, start=2):
        if str(r.get("discord_id", "")).strip() == str(discord_id):
            return idx, r
    return None, None

def find_vip_row_by_pseudo(s: SheetsService, pseudo: str) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
    target = normalize_name(pseudo)
    rows = s.get_all_records("VIP")
    for idx, r in enumerate(rows, start=2):
        if normalize_name(str(r.get("pseudo", ""))) == target:
            return idx, r
    return None, None

def find_vip_row_by_code_or_pseudo(s: SheetsService, term: str) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
    if not term:
        return None, None
    t = term.strip()
    if t.upper().startswith("SUB-"):
        return find_vip_row_by_code(s, t)
    return find_vip_row_by_pseudo(s, t)

def get_rank_among_active(s: SheetsService, code_vip: str) -> Tuple[int, int]:
    code = normalize_code(code_vip)
    rows = s.get_all_records("VIP")
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

def log_rows_for_vip(s: SheetsService, code_vip: str) -> List[Dict[str, Any]]:
    code = normalize_code(code_vip)
    out = []
    for r in s.get_all_records("LOG"):
        c = normalize_code(str(r.get("code_vip", "")))
        if c == code:
            out.append(r)
    return out

def get_last_actions(s: SheetsService, code_vip: str, n: int = 3):
    items = []
    for r in log_rows_for_vip(s, code_vip):
        t = str(r.get("timestamp", "")).strip()
        dt = parse_iso_dt(t)
        if not dt:
            continue
        a = str(r.get("action_key", r.get("action", ""))).strip().upper()
        try:
            qty = int(r.get("quantite", 1))
        except Exception:
            qty = 1
        try:
            pts_add = int(r.get("delta_points", 0))
        except Exception:
            pts_add = 0
        reason = str(r.get("raison", "") or "").strip()
        items.append((dt, a, qty, pts_add, reason))
    items.sort(key=lambda x: x[0], reverse=True)
    return items[:n]


# ----------------------------
# Niveaux
# ----------------------------
def get_levels(s: SheetsService) -> List[Tuple[int, int, str]]:
    rows = s.get_all_records("NIVEAUX")
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

def calc_level(s: SheetsService, points: int) -> int:
    lvl = 1
    for n, pmin, _ in get_levels(s):
        if points >= pmin:
            lvl = n
    return lvl

def get_level_info(s: SheetsService, lvl: int) -> Tuple[int, str]:
    for n, pmin, av in get_levels(s):
        if n == lvl:
            return pmin, av
    return 0, ""

def get_next_level(s: SheetsService, lvl: int):
    levels = get_levels(s)
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

def get_all_unlocked_advantages(s: SheetsService, current_level: int) -> str:
    all_adv = []
    for lvl in range(1, current_level + 1):
        _, raw = get_level_info(s, lvl)
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


# ----------------------------
# Actions + limites
# ----------------------------
def get_actions_map(s: SheetsService) -> Dict[str, Dict[str, Any]]:
    rows = s.get_all_records("ACTIONS")
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

def count_usage(
    s: SheetsService,
    code_vip: str,
    action_key: str,
    start_dt,
    end_dt,
    tag_prefix: Optional[str] = None,
    tag_value: Optional[str] = None
) -> int:
    action = (action_key or "").strip().upper()
    rows = log_rows_for_vip(s, code_vip)
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

def check_action_limit(
    s: SheetsService,
    code_vip: str,
    action_key: str,
    qty: int,
    reason: str,
    author_is_hg: bool
) -> Tuple[bool, str, bool]:
    actions = get_actions_map(s)
    row = actions.get((action_key or "").strip().upper())
    if not row:
        return False, "Action inconnue dans l’onglet ACTIONS.", False

    lim_raw = str(row.get("limite", "")).strip().lower()

    if ("illimit" in lim_raw) or (lim_raw == ""):
        return True, "", False

    start, end = challenge_week_window()

    ev = extract_tag(reason or "", "event:")
    poche = extract_tag(reason or "", "poche:")

    if "semaine" in lim_raw and "/" in lim_raw:
        try:
            max_per_week = int(lim_raw.split("/")[0].strip())
        except Exception:
            max_per_week = 1

        used = count_usage(s, code_vip, action_key, start, end)
        if used + qty <= max_per_week:
            return True, "", False

        if author_is_hg:
            return False, f"Limite hebdo atteinte (**{used}/{max_per_week}**). HG peut forcer.", True
        return False, f"😾 Limite hebdo atteinte (**{used}/{max_per_week}**).", False

    if "par event" in lim_raw:
        if not ev:
            return False, "😾 Ajoute `event:NomEvent` dans la raison.", False
        used = count_usage(
            s, code_vip, action_key,
            start_dt=datetime.min.replace(tzinfo=start.tzinfo),
            end_dt=datetime.max.replace(tzinfo=start.tzinfo),
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
            s, code_vip, action_key,
            start_dt=datetime.min.replace(tzinfo=start.tzinfo),
            end_dt=datetime.max.replace(tzinfo=start.tzinfo),
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


def add_points_by_action(
    s: SheetsService,
    code_vip: str,
    action_key: str,
    qty: int,
    staff_id: int,
    reason: str,
    author_is_hg: bool = False,
    employee_can: Optional[set] = None
):
    action_key = (action_key or "").strip().upper()
    code = normalize_code(code_vip)
    employee_can = employee_can or EMPLOYEE_ALLOWED_ACTIONS

    # Permissions employés
    if not author_is_hg and action_key not in employee_can:
        return False, f"😾 Action réservée aux HG. Employés: {', '.join(sorted(employee_can))}."

    # Limites
    ok_lim, msg_lim, needs_confirm = check_action_limit(s, code, action_key, qty, reason or "", author_is_hg)
    if not ok_lim:
        if needs_confirm:
            return False, msg_lim + " Utilise `/vip force` (HG) pour forcer."
        return False, msg_lim

    if qty <= 0:
        return False, "La quantité doit être > 0."

    row_i, vip = find_vip_row_by_code(s, code)
    if not row_i or not vip:
        return False, "Code VIP introuvable."

    status = str(vip.get("status", "ACTIVE")).strip().upper()
    if status != "ACTIVE":
        return False, "VIP désactivé."

    actions = get_actions_map(s)
    if action_key not in actions:
        return False, f"Action inconnue: {action_key}."

    try:
        pu = int(actions[action_key]["points_unite"])
    except Exception:
        pu = 0

    delta = pu * qty

    try:
        old_points = int(vip.get("points", 0) or 0)
    except Exception:
        old_points = 0
    new_points = old_points + delta

    try:
        old_level = int(vip.get("niveau", 1) or 1)
    except Exception:
        old_level = 1
    new_level = calc_level(s, new_points)

    # update VIP
    s.update_cell_by_header("VIP", row_i, "points", new_points)
    s.update_cell_by_header("VIP", row_i, "niveau", new_level)

    # append LOG
    s.append_by_headers("LOG", {
        "timestamp": now_iso(),
        "staff_id": str(staff_id),
        "code_vip": code,
        "action_key": action_key,
        "quantite": qty,
        "points_unite": pu,
        "delta_points": delta,
        "raison": reason or "",
    })

    # ✅ succès: on renvoie un tuple exploitable
    return True, (delta, new_points, old_level, new_level)

# ----------------------------
# Cave (BAN CREATE)
# ----------------------------
def split_aliases(raw: str) -> List[str]:
    if not raw:
        return []
    raw = str(raw)
    for sep in [";", "|"]:
        raw = raw.replace(sep, ",")
    items = [normalize_name(x) for x in raw.split(",")]
    return [x for x in items if x]

def load_ban_create_list(s: SheetsService):
    rows = s.get_all_records("VIP_BAN_CREATE")
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

def check_banned_for_create(s: SheetsService, pseudo: str = "", discord_id: str = ""):
    p = normalize_name(pseudo)
    did = str(discord_id or "").strip()

    for b in load_ban_create_list(s):
        if did and b["discord_id"] and did == b["discord_id"]:
            return True, b["reason"] or "Raison interne"
        if p and b["pseudo_ref"] and p == b["pseudo_ref"]:
            return True, b["reason"] or "Raison interne"
        if p and b["aliases"] and p in b["aliases"]:
            return True, b["reason"] or "Raison interne"
    return False, ""

def log_create_blocked(s: SheetsService, staff_id: int, pseudo_attempted: str, discord_id: str = "", reason: str = ""):
    details = f"Tentative création VIP bloquée | pseudo='{pseudo_attempted}'"
    if discord_id:
        details += f" | discord_id={discord_id}"
    if reason:
        details += f" | reason={reason}"

    s.append_by_headers("LOG", {
        "timestamp": now_iso(),
        "staff_id": str(staff_id),
        "code_vip": "",
        "action_key": "CREATE_BLOCKED",
        "quantite": 1,
        "points_unite": 0,
        "delta_points": 0,
        "raison": details,
    })


# ----------------------------
# Défis
# ----------------------------
def week_key_for(k: int) -> str:
    return f"W{k:02d}"

def week_label_for(k: int) -> str:
    return f"Semaine {k}/12"

def current_challenge_week_number(now=None) -> int:
    """
    Semaine 1..12 basée sur CHALLENGE_START (FR).
    Fenêtre de validation reste vendredi 17h -> vendredi 17h.
    """
    import os
    from datetime import datetime

    now = now or now_fr()
    start = os.getenv("CHALLENGE_START", "2026-01-02 17:00")
    try:
        dt0 = datetime.strptime(start, "%Y-%m-%d %H:%M").replace(tzinfo=now.tzinfo)
    except Exception:
        dt0 = now.replace(year=2026, month=1, day=2, hour=17, minute=0, second=0, microsecond=0)

    weeks_since = int(((now - dt0).total_seconds()) // (7 * 24 * 3600))
    wk = (weeks_since % 12) + 1
    if weeks_since < 0:
        return 1
    return wk

def defis_done_count(row: Dict[str, Any]) -> int:
    return sum(1 for k in ["d1", "d2", "d3", "d4"] if str(row.get(k, "")).strip() != "")

def get_defis_row(s: SheetsService, code_vip: str, wk_key: str) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
    rows = s.get_all_records("DEFIS")
    code = normalize_code(code_vip)
    for idx, r in enumerate(rows, start=2):
        if normalize_code(str(r.get("code_vip", ""))) == code and str(r.get("week_key", "")).strip() == wk_key:
            return idx, r
    return None, None

def ensure_defis_row(s: SheetsService, code_vip: str, wk_key: str, wk_label: str) -> Tuple[int, Dict[str, Any]]:
    row_i, row = get_defis_row(s, code_vip, wk_key)
    if row_i and row:
        return row_i, row

    # DEFIS : week_key, code_vip, d1..d4, completed_at, completed_by, d_notes, week_label
    s.append_by_headers("DEFIS", {
        "week_key": wk_key,
        "code_vip": normalize_code(code_vip),
        "d1": "", "d2": "", "d3": "", "d4": "",
        "completed_at": "",
        "completed_by": "",
        "d_notes": "",
        "week_label": wk_label,
    })
    row_i2, row2 = get_defis_row(s, code_vip, wk_key)
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

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from services import PARIS_TZ, parse_iso_dt

def _start_of_day_fr(dt):
    dt = dt.astimezone(PARIS_TZ)
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)

def _start_of_week_fr(dt):
    # semaine = lundi 00:00
    dt = _start_of_day_fr(dt)
    return dt - timedelta(days=dt.weekday())

def _start_of_month_fr(dt):
    dt = _start_of_day_fr(dt)
    return dt.replace(day=1)

def sales_summary(
    s: SheetsService,
    period: str = "day",  # "day" | "week" | "month"
    category: str = "",   # ex: "TSHIRT"
):
    now = now_fr()

    if period == "week":
        start = _start_of_week_fr(now)
    elif period == "month":
        start = _start_of_month_fr(now)
    else:
        start = _start_of_day_fr(now)

    end = now

    rows = s.get_all_records("LOG")

    # staff_id -> stats
    stats = {}
    total = {"achat_qty": 0, "lim_qty": 0, "delta": 0, "ops": 0}

    for r in rows:
        dt = parse_iso_dt(str(r.get("timestamp", "")).strip())
        if not dt:
            continue
        if not (start <= dt <= end):
            continue

        action = str(r.get("action_key", "")).strip().upper()
        if action not in ("ACHAT", "ACHAT_LIMITEE"):
            continue

        raison = str(r.get("raison", "") or "").strip()
        cat = extract_tag(raison, "vente:")
        if category:
            if not cat or cat.upper() != category.upper():
                continue

        staff_id = str(r.get("staff_id", "")).strip() or "UNKNOWN"
        try:
            qty = int(r.get("quantite", 0) or 0)
        except Exception:
            qty = 0
        try:
            delta = int(r.get("delta_points", 0) or 0)
        except Exception:
            delta = 0

        if staff_id not in stats:
            stats[staff_id] = {"achat_qty": 0, "lim_qty": 0, "delta": 0, "ops": 0}

        if action == "ACHAT":
            stats[staff_id]["achat_qty"] += qty
            total["achat_qty"] += qty
        else:
            stats[staff_id]["lim_qty"] += qty
            total["lim_qty"] += qty

        stats[staff_id]["delta"] += delta
        stats[staff_id]["ops"] += 1

        total["delta"] += delta
        total["ops"] += 1

    # tri: plus gros delta points
    ordered = sorted(stats.items(), key=lambda kv: kv[1]["delta"], reverse=True)
    return start, end, ordered, total
