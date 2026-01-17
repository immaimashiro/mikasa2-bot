# logique VIP / actions / défis / cave (mes fonctions)

# ============================================================
# VIP
# ============================================================

def find_vip_row_by_code(code_vip: str) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
    code = normalize_code(code_vip)
    rows = services.ws("VIP").get_all_records()
    for idx, r in enumerate(rows, start=2):
        if normalize_code(str(r.get("code_vip", ""))) == code:
            return idx, r
    return None, None

def find_vip_row_by_discord_id(discord_id: int) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
    rows = services.ws("VIP").get_all_records()
    for idx, r in enumerate(rows, start=2):
        if str(r.get("discord_id", "")).strip() == str(discord_id):
            return idx, r
    return None, None

def find_vip_row_by_pseudo(pseudo: str) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
    target = normalize_name(pseudo)
    rows = services.ws("VIP").get_all_records()
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
    rows = services.ws("VIP").get_all_records()
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
# Actions
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

    services.ws("VIP").batch_update([
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
# Niveaux
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

# ============================================================
# Cave
# ============================================================

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

# ============================================================
# Défis
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

def defis_done_count(row: Dict[str, Any]) -> int:
    return sum(1 for k in ["d1", "d2", "d3", "d4"] if str(row.get(k, "")).strip() != "")
