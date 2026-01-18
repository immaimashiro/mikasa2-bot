# bot.py
# -*- coding: utf-8 -*-

import os
import io
import traceback
import asyncio
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from services import SheetsService, S3Service, catify, display_name, normalize_code, gen_code, now_iso, fmt_fr
import services
import domain
import ui

# ----------------------------
# ENV + creds file
# ----------------------------
GOOGLE_CREDS_ENV = (os.getenv("GOOGLE_CREDS") or "").strip()
if GOOGLE_CREDS_ENV:
    with open("credentials.json", "w", encoding="utf-8") as f:
        f.write(GOOGLE_CREDS_ENV)

DISCORD_TOKEN = (os.getenv("DISCORD_TOKEN") or "").strip()
SHEET_ID = (os.getenv("SHEET_ID") or "").strip()
GUILD_ID = int(os.getenv("GUILD_ID", "0"))

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN manquant.")
if not SHEET_ID:
    raise RuntimeError("SHEET_ID manquant.")
if not GUILD_ID:
    raise RuntimeError("GUILD_ID manquant.")

EMPLOYEE_ROLE_ID = int(os.getenv("EMPLOYEE_ROLE_ID", "0"))
HG_ROLE_ID = int(os.getenv("HG_ROLE_ID", "0"))
ANNOUNCE_CHANNEL_ID = int(os.getenv("ANNOUNCE_CHANNEL_ID", "0"))

VIP_TEMPLATE_PATH = os.getenv("VIP_TEMPLATE_PATH", "template.png")
VIP_FONT_PATH = os.getenv("VIP_FONT_PATH", "PaybAck.ttf")

# ----------------------------
# Bot init (slash only = stable)
# ----------------------------
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

sheets = SheetsService(SHEET_ID, creds_path="credentials.json")
s3 = S3Service()

scheduler = AsyncIOScheduler(timezone=services.PARIS_TZ)

vip_group = app_commands.Group(name="vip", description="Commandes VIP (staff)")
defi_group = app_commands.Group(name="defi", description="Commandes défis (HG)")
cave_group = app_commands.Group(name="cave", description="Cave Mikasa (HG)")

bot.tree.add_command(vip_group)
bot.tree.add_command(defi_group)
bot.tree.add_command(cave_group)

# ----------------------------
# VIP autocomplete cache
# ----------------------------
_VIP_CACHE = {"ts": 0.0, "rows": []}

def _vip_cache_get():
    import time
    now = time.time()
    # refresh toutes les 60s
    if not _VIP_CACHE["rows"] or (now - _VIP_CACHE["ts"]) > 60:
        _VIP_CACHE["rows"] = sheets.get_all_records("VIP")
        _VIP_CACHE["ts"] = now
    return _VIP_CACHE["rows"]

def _vip_label(r: dict) -> str:
    code = normalize_code(str(r.get("code_vip", "")))
    pseudo = display_name(r.get("pseudo", code))
    status = str(r.get("status", "ACTIVE")).strip().upper()
    dot = "🟢" if status == "ACTIVE" else "🔴"
    return f"{dot} {pseudo} ({code})"

# ----------------------------
# Perm checks
# ----------------------------
def has_role(member: discord.Member, role_id: int) -> bool:
    return role_id != 0 and any(r.id == role_id for r in getattr(member, "roles", []))

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

async def defer_ephemeral(interaction: discord.Interaction):
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)

async def reply_ephemeral(interaction: discord.Interaction, content: str = "", *, embed: discord.Embed | None = None):
    if interaction.response.is_done():
        await interaction.followup.send(content=content, embed=embed, ephemeral=True)
    else:
        await interaction.response.send_message(content=content, embed=embed, ephemeral=True)

# ----------------------------
# Error handler (unique)
# ----------------------------
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    original = getattr(error, "original", error)
    print("=== SLASH ERROR ===")
    traceback.print_exception(type(original), original, original.__traceback__)
    msg = f"❌ Erreur: `{type(original).__name__}`"
    detail = str(original)
    if detail:
        msg += f"\n`{detail[:1500]}`"
    try:
        await reply_ephemeral(interaction, msg)
    except Exception:
        pass
        
def safe_tree_command(name: str, description: str):
    """
    Décorateur qui n'ajoute la commande que si elle n'existe pas déjà dans bot.tree.
    Evite les crash CommandAlreadyRegistered pendant les copier/coller.
    """
    def decorator(func):
        if bot.tree.get_command(name) is not None:
            print(f"[SKIP] Command déjà enregistrée: {name}")
            return func
        return bot.tree.command(name=name, description=description)(func)
    return decorator

def safe_group_command(group: app_commands.Group, name: str, description: str):
    """
    Idem mais pour app_commands.Group (ex: vip_group).
    """
    def decorator(func):
        if any(cmd.name == name for cmd in group.commands):
            print(f"[SKIP] Group command déjà enregistrée: {group.name} {name}")
            return func
        return group.command(name=name, description=description)(func)
    return decorator

# ----------------------------
# Level up announce (optionnel)
# ----------------------------
async def announce_level_up(code_vip: str, pseudo: str, old_level: int, new_level: int):
    if not ANNOUNCE_CHANNEL_ID:
        return
    ch = bot.get_channel(int(ANNOUNCE_CHANNEL_ID))
    if not ch:
        return

    pseudo_disp = display_name(pseudo)
    _, raw_av = domain.get_level_info(sheets, new_level)
    unlocked = domain.split_avantages(raw_av)
    unlocked_lines = "\n".join([f"✅ {a}" for a in unlocked]) if unlocked else "✅ (Avantages non listés)"

    msg = (
        f"🎊 **LEVEL UP VIP**\n"
        f"👤 **{pseudo_disp}** passe **Niveau {new_level}** !\n\n"
        f"🎁 **Débloque :**\n{unlocked_lines}\n\n"
        f"😼 Mikasa tamponne le registre. *clac* 🐾"
    )
    await ch.send(catify(msg, chance=0.12))

# ----------------------------
# Weekly challenges announce
# ----------------------------
async def post_weekly_challenges_announcement():
    if not ANNOUNCE_CHANNEL_ID:
        return
    ch = bot.get_channel(int(ANNOUNCE_CHANNEL_ID))
    if not ch:
        return

    wk = domain.current_challenge_week_number()
    start, end = services.challenge_week_window()

    tasks = domain.WEEKLY_CHALLENGES.get(wk, [])
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

# VIP AUTOCOMPLETE

async def vip_autocomplete(interaction: discord.Interaction, current: str):
    current = (current or "").strip().lower()
    rows = _vip_cache_get()

    scored = []
    for r in rows:
        code = normalize_code(str(r.get("code_vip", "")))
        pseudo = display_name(r.get("pseudo", code))
        hay = f"{code} {pseudo}".lower()

        if not current:
            score = 1
        elif hay.startswith(current):
            score = 100
        elif current in hay:
            score = 50
        else:
            continue

        scored.append((score, pseudo, code, r))

    # tri: meilleur score puis alpha
    scored.sort(key=lambda x: (-x[0], x[1].lower(), x[2]))

    # Discord: max 25 suggestions
    out = []
    for score, pseudo, code, r in scored[:25]:
        out.append(app_commands.Choice(name=f"{pseudo} ({code})", value=code))
    return out

# ----------------------------
# /vip actions
# ----------------------------
@safe_group_command(vip_group, name="actions", description="Liste des actions et points (staff).")
@staff_check()
async def vip_actions(interaction: discord.Interaction):
    await defer_ephemeral(interaction)

    actions = domain.get_actions_map(sheets)
    m = staff_member(interaction)
    hg = bool(m and is_hg(m))

    lines = []
    for k in sorted(actions.keys()):
        if (not hg) and (k not in domain.EMPLOYEE_ALLOWED_ACTIONS):
            continue
        pu = actions[k]["points_unite"]
        lim = actions[k]["limite"]
        lines.append(f"• **{k}**: {pu} pts/unité" + (f" _(limite: {lim})_" if lim else ""))

    if not lines:
        return await interaction.followup.send("😾 Aucune action accessible.", ephemeral=True)

    await interaction.followup.send("📋 **Actions disponibles :**\n" + "\n".join(lines[:40]), ephemeral=True)

# ----------------------------
# /vip add
# ----------------------------
@safe_group_command(vip_group, name="add", description="Ajouter une action/points à un VIP (staff).")
@staff_check()
@app_commands.describe(code_vip="SUB-XXXX-XXXX", action_key="Action", quantite="Quantité", raison="Optionnel")
async def vip_add(interaction: discord.Interaction, code_vip: str, action_key: str, quantite: int, raison: str = ""):
    await defer_ephemeral(interaction)

    m = staff_member(interaction)
    author_is_hg = bool(m and is_hg(m))

    ok, res = domain.add_points_by_action(
        sheets, code_vip, action_key, int(quantite), interaction.user.id, raison,
        author_is_hg=author_is_hg
    )
    if not ok:
        return await interaction.followup.send(f"❌ {res}", ephemeral=True)

    delta, new_points, old_level, new_level = res
    msg = f"✅ `{normalize_code(code_vip)}` → **{action_key.upper()}** x{quantite} = **+{delta} pts**\n➡️ Total: **{new_points}** | Niveau: **{new_level}**"
    await interaction.followup.send(msg, ephemeral=True)

    if new_level > old_level:
        _, vip = domain.find_vip_row_by_code(sheets, code_vip)
        pseudo = vip.get("pseudo", "VIP") if vip else "VIP"
        await announce_level_up(normalize_code(code_vip), pseudo, old_level, new_level)

# ------------------------------
# /vip bleeter (fenêtre de vente)
# ------------------------------

@safe_group_command(vip_group, name="bleeter", description="Ajouter ou modifier le Bleeter d’un VIP (staff).")
@staff_check()
@app_commands.describe(
    query="Code VIP SUB-XXXX-XXXX ou pseudo",
    bleeter="Pseudo Bleeter (ex: @K.Gails). Laisse vide pour retirer."
)
async def vip_bleeter(
    interaction: discord.Interaction,
    query: str,
    bleeter: str = ""
):
    await defer_ephemeral(interaction)

    # retrouver le VIP
    row_i, vip = domain.find_vip_row_by_code_or_pseudo(sheets, query.strip())
    if not row_i or not vip:
        return await interaction.followup.send("❌ VIP introuvable (code ou pseudo).", ephemeral=True)

    code = normalize_code(str(vip.get("code_vip", "")))
    pseudo = display_name(vip.get("pseudo", code))

    bleeter_clean = (bleeter or "").strip()

    # update VIP
    sheets.update_cell_by_header("VIP", row_i, "bleeter", bleeter_clean)

    # log
    sheets.append_by_headers("LOG", {
        "timestamp": now_iso(),
        "staff_id": str(interaction.user.id),
        "code_vip": code,
        "action_key": "SET_BLEETER",
        "quantite": 1,
        "points_unite": 0,
        "delta_points": 0,
        "raison": f"Bleeter défini à '{bleeter_clean}'" if bleeter_clean else "Bleeter retiré",
    })

    if bleeter_clean:
        msg = f"✅ Bleeter mis à jour pour **{pseudo}** → **{bleeter_clean}**"
    else:
        msg = f"🗑️ Bleeter retiré pour **{pseudo}**"

    await interaction.followup.send(msg, ephemeral=True)

# ----------------------------
# /vip sale (fenêtre de vente)
# ----------------------------
CATEGORIES = [
    ("Haut", "TSHIRT/HOODIES"),
    ("Bas", "PANTS"),
    ("Chaussures", "SHOES"),
    ("Masque", "MASKS"),
    ("Accessoire", "ACCESSORY"),
    ("Autre", "OTHER"),
]

@safe_group_command(vip_group, name="sale", description="Ouvrir une fenêtre de vente (panier) pour un VIP.")
@staff_check()
@app_commands.describe(query="Code VIP SUB-XXXX-XXXX ou pseudo")
async def vip_sale(interaction: discord.Interaction, query: str):
    await defer_ephemeral(interaction)

    # 1) retrouver le VIP
    row_i, vip = domain.find_vip_row_by_code_or_pseudo(sheets, query)
    if not row_i or not vip:
        return await interaction.followup.send("❌ VIP introuvable (code ou pseudo).", ephemeral=True)

    code = domain.normalize_code(str(vip.get("code_vip", "")))
    pseudo = domain.display_name(vip.get("pseudo", code))

    # 2) ouvrir la fenêtre panier
    view = ui.SaleCartView(
        author_id=interaction.user.id,
        categories=CATEGORIES,
        services=sheets,         # SheetsService
        code_vip=code,
        vip_pseudo=pseudo,
        author_is_hg=is_hg_slash(interaction),  # ou ma fonction is_hg_slash
    )

    await interaction.followup.send(
        embed=view.build_embed(),
        view=view,
        ephemeral=True
    )
# ----------------------------
# /vip create
# ----------------------------
@safe_group_command(vip_group, name="create", description="Créer un profil VIP (staff).")
@staff_check()
@app_commands.describe(
    pseudo="Nom/Pseudo RP (obligatoire)",
    membre="Optionnel: lier directement à un membre Discord",
    bleeter="Optionnel",
    dob="Optionnel: JJ/MM/AAAA",
    phone="Optionnel",
    note="Optionnel: note interne (log)"
)
async def vip_create(
    interaction: discord.Interaction,
    pseudo: str,
    membre: Optional[discord.Member] = None,
    bleeter: str = "",
    dob: str = "",
    phone: str = "",
    note: str = ""
):
    await defer_ephemeral(interaction)

    pseudo_clean = display_name((pseudo or "").strip())
    if not pseudo_clean:
        return await interaction.followup.send("❌ Pseudo vide.", ephemeral=True)

    banned, ban_reason = domain.check_banned_for_create(
        sheets,
        pseudo=pseudo_clean,
        discord_id=str(membre.id) if membre else ""
    )
    if banned:
        domain.log_create_blocked(sheets, interaction.user.id, pseudo_clean, str(membre.id) if membre else "", ban_reason or "Match VIP_BAN_CREATE")
        return await interaction.followup.send(catify("😾 Mikasa refuse d’écrire ce nom."), ephemeral=True)

    if membre:
        existing_row, _ = domain.find_vip_row_by_discord_id(sheets, membre.id)
        if existing_row:
            return await interaction.followup.send("😾 Ce membre a déjà un VIP lié.", ephemeral=True)

    code = gen_code()
    while True:
        r, _ = domain.find_vip_row_by_code(sheets, code)
        if not r:
            break
        code = gen_code()

    points = 0
    niveau = domain.calc_level(sheets, points)
    created_at = now_iso()

    sheets.append_by_headers("VIP", {
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
        "card_url": "",
        "card_generated_at": "",
        "card_generated_by": "",
    })

    sheets.append_by_headers("LOG", {
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

# ----------------------------
# /vip card_generate (dans n’importe quel salon)
# ----------------------------
@safe_group_command(vip_group, name="card_generate", description="Générer la carte VIP (staff).")
@staff_check()
@app_commands.describe(code_vip="SUB-XXXX-XXXX")
async def vip_card_generate(interaction: discord.Interaction, code_vip: str):
    await defer_ephemeral(interaction)

    row_i, vip = domain.find_vip_row_by_code(sheets, code_vip)
    if not row_i or not vip:
        return await interaction.followup.send("❌ Code VIP introuvable.", ephemeral=True)

    full_name = str(vip.get("pseudo", "")).strip()
    dob = str(vip.get("dob", "")).strip()
    phone = str(vip.get("phone", "")).strip()
    bleeter = str(vip.get("bleeter", "")).strip()

    if not dob or not phone:
        return await interaction.followup.send("😾 Impossible: il manque **dob** ou **phone**.", ephemeral=True)

    if not s3.enabled():
        return await interaction.followup.send("❌ S3 non configuré (AWS_ENDPOINT_URL / BUCKET).", ephemeral=True)

    await interaction.followup.send("🖨️ Mikasa imprime… *prrrt prrrt* 🐾", ephemeral=False)

    png = services.generate_vip_card_image(
        VIP_TEMPLATE_PATH, VIP_FONT_PATH,
        normalize_code(code_vip), full_name, dob, phone, bleeter
    )
    object_key = f"vip_cards/{normalize_code(code_vip)}.png"
    url = s3.upload_png(png, object_key)

    sheets.update_cell_by_header("VIP", row_i, "card_url", url)
    sheets.update_cell_by_header("VIP", row_i, "card_generated_at", now_iso())
    sheets.update_cell_by_header("VIP", row_i, "card_generated_by", str(interaction.user.id))

    file = discord.File(io.BytesIO(png), filename=f"VIP_{normalize_code(code_vip)}.png")

    # 🔥 message PUBLIC
    public_embed = discord.Embed(
        title="🖨️ Impression carte VIP",
        description=f"✅ Carte VIP générée pour **{display_name(full_name)}**\n🎴 Code: `{normalize_code(code_vip)}`\n👤 Imprimée par: {interaction.user.mention}",
        color=discord.Color.green()
    )
    public_embed.set_image(url=f"attachment://VIP_{normalize_code(code_vip)}.png")
    public_embed.set_footer(text="Mikasa crache le papier… prrr 🐾")

    # envoi dans le salon
    await interaction.channel.send(embed=public_embed, file=file)

    # et tu confirmes en privé (pour éviter spam)
    await interaction.followup.send(f"✅ Impression envoyée dans {interaction.channel.mention}", ephemeral=True)


# ----------------------------
# /vip card_show
# ----------------------------
@safe_group_command(vip_group, name="card_show", description="Afficher une carte VIP (staff).")
@staff_check()
@app_commands.describe(query="SUB-XXXX-XXXX ou pseudo")
async def vip_card_show(interaction: discord.Interaction, query: str):
    await defer_ephemeral(interaction)

    row_i, vip = domain.find_vip_row_by_code_or_pseudo(sheets, query.strip())
    if not row_i or not vip:
        return await interaction.followup.send(f"❌ Aucun VIP trouvé pour **{query}**.", ephemeral=True)

    code_vip = normalize_code(str(vip.get("code_vip", "")))
    pseudo = display_name(vip.get("pseudo", query))
    status = str(vip.get("status", "ACTIVE")).strip().upper()
    badge = "🟢" if status == "ACTIVE" else "🔴"

    signed = s3.signed_url(f"vip_cards/{code_vip}.png", expires_seconds=3600) if s3.enabled() else None
    if not signed:
        return await interaction.followup.send("😾 Carte introuvable. Génère-la avec `/vip card_generate`.", ephemeral=True)

    embed = discord.Embed(
        title=f"{badge} Carte VIP de {pseudo}",
        description=f"🎴 Code: `{code_vip}`\n⏳ Lien temporaire (1h): {signed}",
    )
    embed.set_image(url=signed)
    embed.set_footer(text="Mikasa entrouvre la cachette… prrr 🐾")
    await interaction.followup.send(embed=embed, ephemeral=True)

# ----------------------------
# /vip sales_sum 
# ----------------------------
@safe_group_command(vip_group, name="sales_summary", description="Résumé des ventes (staff).")
@staff_check()
@app_commands.describe(
    periode="day | week | month",
    categorie="Optionnel: TSHIRT, HOODIE, PANTS, JACKET, ACCESSORY, OTHER"
)
async def vip_sales_summary(interaction: discord.Interaction, periode: str = "day", categorie: str = ""):
    await defer_ephemeral(interaction)

    periode = (periode or "day").strip().lower()
    if periode not in ("day", "week", "month"):
        return await interaction.followup.send("❌ `periode` doit être: day / week / month", ephemeral=True)

    start, end, ordered, total = domain.sales_summary(sheets, period=periode, category=categorie.strip())

    title_map = {"day": "📊 Résumé ventes du jour", "week": "📊 Résumé ventes de la semaine", "month": "📊 Résumé ventes du mois"}
    title = title_map.get(periode, "📊 Résumé ventes")

    if categorie:
        title += f" • {categorie.upper()}"

    emb = discord.Embed(
        title=title,
        description=f"🗓️ **{fmt_fr(start)} → {fmt_fr(end)}** (FR)\n"
                    f"🧾 Ops: **{total['ops']}**\n"
                    f"🛍️ ACHAT: **{total['achat_qty']}** | 🎟️ LIMITEE: **{total['lim_qty']}**\n"
                    f"⭐ Points distribués: **{total['delta']}**",
        color=discord.Color.gold()
    )

    if not ordered:
        emb.add_field(name="Aucune donnée", value="Aucune vente enregistrée sur cette période.", inline=False)
        return await interaction.followup.send(embed=emb, ephemeral=True)

    # affiche top 15
    lines = []
    for staff_id, st in ordered[:15]:
        lines.append(
            f"• <@{staff_id}>: ops **{st['ops']}** | "
            f"ACHAT **{st['achat_qty']}** | LIMITEE **{st['lim_qty']}** | "
            f"pts **{st['delta']}**"
        )

    emb.add_field(name="Top vendeurs", value="\n".join(lines), inline=False)
    emb.set_footer(text="Mikasa fait les comptes. Calculatrice dans une patte. 🐾")
    await interaction.followup.send(embed=emb, ephemeral=True)


# ----------------------------
# /defi panel (HG)
# ----------------------------
@defi_group.command(name="panel", description="Ouvrir le panneau de validation des défis (HG).")
@hg_check()
@app_commands.describe(code_vip="SUB-XXXX-XXXX")
async def defi_panel(interaction: discord.Interaction, code_vip: str):
    await defer_ephemeral(interaction)

    code = normalize_code(code_vip)
    wk = domain.current_challenge_week_number()
    wk_key = domain.week_key_for(wk)
    wk_label = domain.week_label_for(wk)

    row_vip_i, vip = domain.find_vip_row_by_code(sheets, code)
    if not row_vip_i or not vip:
        return await interaction.followup.send("❌ Code VIP introuvable.", ephemeral=True)

    pseudo = display_name(vip.get("pseudo", "Quelqu’un"))
    row_i, row = domain.ensure_defis_row(sheets, code, wk_key, wk_label)

    if wk == 12:
        choices = domain.get_week_tasks_for_view(12)
        view = ui.DefiWeek12View(
            author=interaction.user,
            services=sheets,
            code=code,
            wk=wk,
            wk_key=wk_key,
            wk_label=wk_label,
            row_i=row_i,
            row=row,
            choices=choices,
            vip_pseudo=pseudo
        )
        await interaction.followup.send(embed=view._build_embed(), view=view, ephemeral=True)
        return

    tasks = domain.get_week_tasks_for_view(wk)
    view = ui.DefiValidateView(
        author=interaction.user,
        services=sheets,
        code=code,
        wk=wk,
        wk_key=wk_key,
        wk_label=wk_label,
        row_i=row_i,
        row=row,
        tasks=tasks,
        vip_pseudo=pseudo
    )
    await interaction.followup.send(embed=view._build_embed(), view=view, ephemeral=True)

# ----------------------------
# /defi week_announce (HG)
# ----------------------------
@defi_group.command(name="week_announce", description="Poster l'annonce de la semaine (HG).")
@hg_check()
async def defi_week_announce(interaction: discord.Interaction):
    await defer_ephemeral(interaction)
    await post_weekly_challenges_announcement()
    await interaction.followup.send("✅ Annonce postée. 🐾", ephemeral=True)

# ----------------------------
# /cave list/add/remove/info (HG)
# ----------------------------
@cave_group.command(name="list", description="Lister la cave (HG).")
@hg_check()
async def cave_list(interaction: discord.Interaction):
    await defer_ephemeral(interaction)
    rows = sheets.get_all_records("VIP_BAN_CREATE")
    if not rows:
        return await interaction.followup.send("🐱 La cave est vide…", ephemeral=True)

    lines = []
    for r in rows:
        pseudo_ref_raw = str(r.get("pseudo_ref", "")).strip()
        if not pseudo_ref_raw:
            continue
        aliases_norm = domain.split_aliases(r.get("aliases", ""))
        aliases_display = ", ".join(display_name(a) for a in aliases_norm) if aliases_norm else ""
        lines.append(f"🔒 **{display_name(pseudo_ref_raw)}**" + (f" _(alias: {aliases_display})_" if aliases_display else ""))

    await interaction.followup.send("🕯️ **La cave de Mikasa**\n" + "\n".join(lines[:50]), ephemeral=True)

@cave_group.command(name="add", description="Ajouter un nom dans la cave (HG).")
@hg_check()
@app_commands.describe(pseudo="Nom principal", aliases="Optionnel: alias séparés par , ; |", discord_id="Optionnel", reason="Optionnel")
async def cave_add(interaction: discord.Interaction, pseudo: str, aliases: str = "", discord_id: str = "", reason: str = ""):
    await defer_ephemeral(interaction)

    pseudo_ref_raw = (pseudo or "").strip()
    if not pseudo_ref_raw:
        return await interaction.followup.send("❌ Il me faut au moins un pseudo.", ephemeral=True)

    pseudo_norm = domain.normalize_name(pseudo_ref_raw)
    aliases_list_norm = domain.split_aliases(aliases)

    rows = sheets.get_all_records("VIP_BAN_CREATE")
    for r in rows:
        existing_pseudo = domain.normalize_name(r.get("pseudo_ref", ""))
        existing_aliases = domain.split_aliases(r.get("aliases", ""))
        if pseudo_norm == existing_pseudo or pseudo_norm in existing_aliases:
            return await interaction.followup.send(catify("😾 Ce nom est déjà dans la cave."), ephemeral=True)

    sheets.append_by_headers("VIP_BAN_CREATE", {
        "pseudo_ref": pseudo_ref_raw,
        "aliases": ", ".join(aliases_list_norm),
        "discord_id": (discord_id or "").strip(),
        "reason": (reason or "BAN_CREATE").strip(),
        "added_by": str(interaction.user.id),
        "added_at": now_iso(),
        "notes": "",
    })

    await interaction.followup.send(catify(f"🔒 **{display_name(pseudo_ref_raw)}** est enfermé dans la cave."), ephemeral=True)

@cave_group.command(name="remove", description="Retirer un nom de la cave (HG).")
@hg_check()
@app_commands.describe(term="Pseudo_ref ou un de ses alias")
async def cave_remove(interaction: discord.Interaction, term: str):
    await defer_ephemeral(interaction)

    term_norm = domain.normalize_name(term)
    values = sheets.get_all_values("VIP_BAN_CREATE")
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
        pseudo_ref_norm = domain.normalize_name(pseudo_ref_raw)

        aliases_norm = []
        if col_aliases is not None and col_aliases < len(row):
            aliases_norm = domain.split_aliases(row[col_aliases])

        if term_norm == pseudo_ref_norm or (aliases_norm and term_norm in aliases_norm):
            sheets.delete_row("VIP_BAN_CREATE", idx)
            return await interaction.followup.send(catify(f"🔓 **{display_name(pseudo_ref_raw)}** est retiré de la cave."), ephemeral=True)

    await interaction.followup.send(catify("😾 Aucun nom correspondant dans la cave."), ephemeral=True)

@cave_group.command(name="info", description="Afficher un dossier cave (HG).")
@hg_check()
@app_commands.describe(term="Pseudo_ref ou alias")
async def cave_info(interaction: discord.Interaction, term: str):
    await defer_ephemeral(interaction)

    term_norm = domain.normalize_name(term)
    rows = sheets.get_all_records("VIP_BAN_CREATE")

    for r in rows:
        pseudo_ref_raw = str(r.get("pseudo_ref", "")).strip()
        pseudo_ref_norm = domain.normalize_name(pseudo_ref_raw)
        aliases_norm = domain.split_aliases(r.get("aliases", ""))

        if term_norm == pseudo_ref_norm or (aliases_norm and term_norm in aliases_norm):
            msg = (
                f"🕯️ **Dossier cave Mikasa**\n"
                f"🔒 Nom: **{display_name(pseudo_ref_raw)}**\n"
                f"🏷️ Alias: {', '.join(display_name(a) for a in aliases_norm) if aliases_norm else '—'}\n"
                f"📌 Reason: `{str(r.get('reason','—') or '—')}`\n"
                f"👤 Ajouté par: <@{r.get('added_by','—')}> \n"
                f"📅 Ajouté le: `{str(r.get('added_at','—') or '—')}`\n"
                f"🪪 discord_id: `{str(r.get('discord_id','—') or '—')}`\n"
                f"📝 Notes: {str(r.get('notes','—') or '—')}"
            )
            return await interaction.followup.send(catify(msg, chance=0.25), ephemeral=True)

    await interaction.followup.send(catify("😾 Aucun dossier trouvé."), ephemeral=True)

#VIP HELP

@safe_group_command(vip_group, name="guide", description="Guide VIP – informations pour les clients VIP.")
async def vip_guide(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    embed = discord.Embed(
        title="🎴 Guide VIP – Mikasa",
        description=(
            "Bienvenue dans le **programme VIP SubUrban**.\n\n"
            "Ce guide est destiné aux **clients VIP** pour consulter leurs informations."
        ),
        color=discord.Color.gold()
    )

    embed.add_field(
        name="👤 Voir ton profil VIP",
        value=(
            "Utilise la commande :\n"
            "**`/vipme`**\n\n"
            "Elle te permet de voir:\n"
            "• 🎖️ ton **niveau VIP**\n"
            "• ⭐ tes **points**\n"
            "• 🎁 les **avantages débloqués**"
        ),
        inline=False
    )

    embed.add_field(
        name="📸 Défis de la semaine",
        value=(
            "Dans `/vipme`, tu peux aussi consulter:\n"
            "• l’**avancement de tes défis hebdomadaires**\n"
            "• les défis validés ou en attente\n\n"
            "⚠️ Les défis sont validés par le staff."
        ),
        inline=False
    )

    embed.add_field(
        name="ℹ️ Besoin d’aide ?",
        value=(
            "Si une information est incorrecte ou manquante:\n"
            "• adresse-toi à un **vendeur**\n"
            "• ou à un membre du **staff SubUrban**"
        ),
        inline=False
    )

    embed.set_footer(text="Mikasa surveille les registres VIP. 🐾")

    await interaction.followup.send(embed=embed, ephemeral=True)

@safe_group_command(vip_group, name="staff_guide", description="Guide interactif VIP/Staff.")
@staff_check()
@app_commands.describe(section="vip | staff | defi | tout")
async def vip_help(interaction: discord.Interaction, section: str = "tout"):
    await defer_ephemeral(interaction)

    section = (section or "tout").strip().lower()
    if section not in ("vip", "staff", "defi", "tout"):
        section = "tout"

    lines = ["📌 **Aide Mikasa**"]

    if section in ("vip", "tout"):
        lines += [
            "",
            "### Gestion du VIP",
            "• `/vip create` Créer un VIP",
            "• `/vip add` Ajouter une action/points",
            "• `/vip sale` Fenêtre panier de vente",
            "• `/vip card_generate` Générer la carte VIP",
            "• `/vip card_show` Afficher la carte VIP",
            "• `/vip actions` Voir les actions",
            "• `/vip sales_summary` Résumé ventes",
            "• `/vipstats` Stats globales VIP",
            "• `/vipsearch` Rechercher un VIP",
            "• `/niveau_top` Top VIP (actifs) par points",
            "• `/niveau <pseudo ou code>` Voir le niveau VIP d’un client",
        ]

    if section in ("defi", "tout"):
        lines += [
            "",
            "### Défis (HG)",
            "• `/defi panel` Valider défis",
            "• `/defi week_announce` Poster l’annonce hebdo",
        ]

    if section in ("staff", "tout"):
        lines += [
            "",
            "### Staff",
            "Astuce: utilisez `/vip sale <codeVIP/pseudo>` pour éviter de taper 2 commandes.",
        ]

    if section in ("log", "tout"):
        lines += [
            "🧾 Vérification par le staff",
            "Si tu as un doute sur tes points / une vente / un défi:\n",
            "➡️ Demande à un vendeur.\n\n",
            "Le staff peut vérifier ton historique via:\n",
            "• **`/viplog <ton pseudo ou ton code>`**",
        ]

    await interaction.followup.send("\n".join(lines), ephemeral=True)

# VIP commandes

@safe_tree_command(name="vipme", description="Ouvrir ton espace VIP (niveau & défis).")
async def vipme(interaction: discord.Interaction):
    await defer_ephemeral(interaction)

    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return await interaction.followup.send("❌ À utiliser sur le serveur.", ephemeral=True)

    row_i, vip = domain.find_vip_row_by_discord_id(sheets, interaction.user.id)
    if not row_i or not vip:
        return await interaction.followup.send("😾 Ton Discord n’est pas lié à un VIP. Demande au staff.", ephemeral=True)

    code = domain.normalize_code(str(vip.get("code_vip", "")))
    pseudo = domain.display_name(vip.get("pseudo", code))

    view = ui.VipHubView(services=sheets, code_vip=code, vip_pseudo=pseudo)
    await interaction.followup.send(embed=view.hub_embed(), view=view, ephemeral=True)

#VIP edit

@safe_group_command(vip_group, name="edit", description="Modifier un VIP (autocomplete + sélection interactive).")
@staff_check()
@app_commands.describe(vip="Choisis un VIP (autocomplete)", recherche="Optionnel si tu veux taper un nom approximatif")
@app_commands.autocomplete(vip=vip_autocomplete)
async def vip_edit(interaction: discord.Interaction, vip: str = "", recherche: str = ""):
    await defer_ephemeral(interaction)

    term = (vip or recherche or "").strip()
    if not term:
        return await interaction.followup.send("❌ Donne un VIP (autocomplete) ou une recherche.", ephemeral=True)

    # 1) si vip vient de l'autocomplete, c'est un code direct
    row_i, row = domain.find_vip_row_by_code(sheets, term)
    if row_i and row:
        code = normalize_code(str(row.get("code_vip", "")))
        pseudo = display_name(row.get("pseudo", code))
        view = ui.VipEditView(services=sheets, author_id=interaction.user.id, code_vip=code, vip_pseudo=pseudo)
        return await interaction.followup.send(embed=view.build_embed(), view=view, ephemeral=True)

    # 2) sinon: recherche "floue" dans cache et propose une sélection interactive
    q = term.lower()
    rows = _vip_cache_get()

    matches = []
    for r in rows:
        code = normalize_code(str(r.get("code_vip", "")))
        pseudo = display_name(r.get("pseudo", code))
        hay = f"{code} {pseudo}".lower()
        if q in hay:
            matches.append((pseudo, code, r))

    # pas trouvé
    if not matches:
        return await interaction.followup.send("❌ Aucun VIP trouvé pour cette recherche.", ephemeral=True)

    # si 1 match: ouvre direct
    if len(matches) == 1:
        pseudo, code, r = matches[0]
        view = ui.VipEditView(services=sheets, author_id=interaction.user.id, code_vip=code, vip_pseudo=pseudo)
        return await interaction.followup.send(embed=view.build_embed(), view=view, ephemeral=True)

    # sinon: menu interactif (max 25)
    matches = matches[:25]
    pick_view = ui.VipPickView(
        author_id=interaction.user.id,
        services=sheets,
        matches=[(p, c) for (p, c, _) in matches]
    )
    await interaction.followup.send(
        content="🔎 Plusieurs VIP trouvés. Choisis le bon dans la liste :",
        view=pick_view,
        ephemeral=True
    )

#VIP niveau

@safe_tree_command(name="niveau", description="Voir le niveau VIP d’un client (staff).")
@staff_check()
@app_commands.describe(query="Pseudo ou code VIP (SUB-XXXX-XXXX)")
async def niveau(interaction: discord.Interaction, query: str):
    await defer_ephemeral(interaction)

    row_i, vip = domain.find_vip_row_by_code_or_pseudo(sheets, query.strip())
    if not row_i or not vip:
        return await interaction.followup.send("❌ VIP introuvable (pseudo/code).", ephemeral=True)

    code = normalize_code(str(vip.get("code_vip", "")))
    pseudo = display_name(vip.get("pseudo", code))
    status = str(vip.get("status", "ACTIVE")).strip().upper()

    try:
        points = int(vip.get("points", 0) or 0)
    except Exception:
        points = 0
    try:
        lvl = int(vip.get("niveau", 1) or 1)
    except Exception:
        lvl = 1

    rank, total = domain.get_rank_among_active(sheets, code)
    unlocked = domain.get_all_unlocked_advantages(sheets, lvl)
    nxt = domain.get_next_level(sheets, lvl)

    if nxt:
        nxt_lvl, nxt_min, _ = nxt
        remaining = max(0, int(nxt_min) - points)
        prog = int((points / max(1, int(nxt_min))) * 100)
        next_line = f"Prochain: **Niveau {nxt_lvl}** à **{nxt_min}** pts | Progression **{prog}%** (reste {remaining})"
    else:
        next_line = "🔥 Niveau max atteint."

    badge = "🟢" if status == "ACTIVE" else "🔴"

    emb = discord.Embed(
        title=f"{badge} Niveau VIP",
        description=(
            f"👤 **{pseudo}**\n"
            f"🎴 `{code}`\n"
            f"⭐ Points: **{points}**\n"
            f"🏅 Niveau: **{lvl}**\n"
            f"🏁 Rang: **#{rank} / {total}** (VIP actifs)\n\n"
            f"⬆️ {next_line}"
        ),
        color=discord.Color.gold()
    )
    emb.add_field(name="🎁 Avantages débloqués", value=unlocked, inline=False)
    emb.set_footer(text="Mikasa sort le registre. 🐾")

    await interaction.followup.send(embed=emb, ephemeral=True)

@safe_tree_command(name="niveau_top", description="Top VIP (actifs) par points (staff).")
@staff_check()
async def niveau_top(interaction: discord.Interaction):
    await defer_ephemeral(interaction)

    rows = sheets.get_all_records("VIP")
    active = []
    for r in rows:
        status = str(r.get("status", "ACTIVE")).strip().upper()
        if status != "ACTIVE":
            continue
        code = normalize_code(str(r.get("code_vip", "")))
        pseudo = display_name(r.get("pseudo", code))
        try:
            pts = int(r.get("points", 0) or 0)
        except Exception:
            pts = 0
        try:
            lvl = int(r.get("niveau", 1) or 1)
        except Exception:
            lvl = 1
        if code:
            active.append((pts, lvl, pseudo, code))

    if not active:
        return await interaction.followup.send("😾 Aucun VIP actif trouvé.", ephemeral=True)

    active.sort(key=lambda x: x[0], reverse=True)
    top = active[:15]

    lines = []
    for i, (pts, lvl, pseudo, code) in enumerate(top, start=1):
        lines.append(f"**{i}.** **{pseudo}** (`{code}`) — ⭐ {pts} pts • 🎖️ niv {lvl}")

    emb = discord.Embed(
        title="🏆 Top VIP (actifs)",
        description="\n".join(lines),
        color=discord.Color.purple()
    )
    emb.set_footer(text="Mikasa compte… *tap tap* 🐾")
    await interaction.followup.send(embed=emb, ephemeral=True)

@safe_tree_command(name="vipsearch", description="Rechercher un VIP (staff).")
@staff_check()
@app_commands.describe(term="Pseudo (partiel), code (partiel) ou discord_id (exact)")
async def vipsearch(interaction: discord.Interaction, term: str):
    await defer_ephemeral(interaction)

    t = (term or "").strip()
    if not t:
        return await interaction.followup.send("❌ Donne un terme de recherche.", ephemeral=True)

    rows = sheets.get_all_records("VIP")
    out = []

    # si num -> discord id
    is_num = t.isdigit()

    for r in rows:
        code = normalize_code(str(r.get("code_vip", "")))
        pseudo = display_name(r.get("pseudo", code))
        did = str(r.get("discord_id", "")).strip()
        status = str(r.get("status", "ACTIVE")).strip().upper()
        try:
            pts = int(r.get("points", 0) or 0)
        except Exception:
            pts = 0

        hit = False
        if is_num and did and did == t:
            hit = True
        if t.lower() in pseudo.lower():
            hit = True
        if t.upper() in code.upper():
            hit = True

        if hit:
            badge = "🟢" if status == "ACTIVE" else "🔴"
            out.append((status == "ACTIVE", pts, f"{badge} **{pseudo}** (`{code}`) — ⭐ {pts} pts" + (f" • <@{did}>" if did else "")))

    if not out:
        return await interaction.followup.send("😾 Aucun VIP trouvé.", ephemeral=True)

    # actifs d’abord, puis plus de points
    out.sort(key=lambda x: (x[0], x[1]), reverse=True)
    lines = [x[2] for x in out[:15]]

    emb = discord.Embed(
        title="🔎 Résultats VIP",
        description="\n".join(lines),
        color=discord.Color.blurple()
    )
    emb.set_footer(text="Astuce: cherche aussi par code SUB-…")
    await interaction.followup.send(embed=emb, ephemeral=True)

@safe_tree_command(name="vipstats", description="Stats globales VIP (staff).")
@staff_check()
async def vipstats(interaction: discord.Interaction):
    await defer_ephemeral(interaction)

    rows = sheets.get_all_records("VIP")
    if not rows:
        return await interaction.followup.send("😾 Aucun VIP en base.", ephemeral=True)

    total = len(rows)
    active = 0
    disabled = 0
    pts_active = 0
    lvl_counts = {}

    top_pts = []
    for r in rows:
        status = str(r.get("status", "ACTIVE")).strip().upper()
        try:
            pts = int(r.get("points", 0) or 0)
        except Exception:
            pts = 0
        try:
            lvl = int(r.get("niveau", 1) or 1)
        except Exception:
            lvl = 1

        lvl_counts[lvl] = lvl_counts.get(lvl, 0) + 1

        if status == "ACTIVE":
            active += 1
            pts_active += pts
            code = normalize_code(str(r.get("code_vip", "")))
            pseudo = display_name(r.get("pseudo", code))
            top_pts.append((pts, pseudo, code))
        else:
            disabled += 1

    avg = int(pts_active / max(1, active))

    top_pts.sort(key=lambda x: x[0], reverse=True)
    top3 = top_pts[:3]
    top_lines = "\n".join([f"• **{p}** (`{c}`) — ⭐ {pts}" for pts, p, c in top3]) if top3 else "—"

    # niveaux les plus fréquents (top 5)
    lvl_top = sorted(lvl_counts.items(), key=lambda kv: kv[1], reverse=True)[:5]
    lvl_lines = "\n".join([f"• Niveau **{lvl}**: **{n}** VIP" for lvl, n in lvl_top]) if lvl_top else "—"

    emb = discord.Embed(
        title="📊 Stats VIP",
        description=(
            f"👥 Total VIP: **{total}**\n"
            f"🟢 Actifs: **{active}**\n"
            f"🔴 Désactivés: **{disabled}**\n"
            f"⭐ Moyenne points (actifs): **{avg}**"
        ),
        color=discord.Color.green()
    )
    emb.add_field(name="🏆 Top 3 (actifs)", value=top_lines, inline=False)
    emb.add_field(name="🎖️ Répartition niveaux (top 5)", value=lvl_lines, inline=False)
    emb.set_footer(text="Mikasa fait tourner Excel dans sa tête. 🐾")

    await interaction.followup.send(embed=emb, ephemeral=True)

# ----------------------------
# Ready + sync + scheduler
# ----------------------------
@bot.event
async def on_ready():
    print(f"Mikasa V2 connectée en tant que {bot.user}")

    guild = discord.Object(id=GUILD_ID)

    try:
        # Sync uniquement sur la guilde (rapide et stable)
        bot.tree.copy_global_to(guild=guild)
        await bot.tree.sync(guild=guild)
        print(f"Slash commands sync sur GUILD_ID={GUILD_ID}")
    except Exception as e:
        print("Sync slash failed:", e)

    # scheduler vendredi 17:00
    if not getattr(bot, "_mikasa_scheduler_started", False):
        bot._mikasa_scheduler_started = True
        trigger = CronTrigger(day_of_week="fri", hour=17, minute=0, timezone=services.PARIS_TZ)
        scheduler.add_job(lambda: bot.loop.create_task(post_weekly_challenges_announcement()), trigger)
        scheduler.start()
        print("Scheduler: annonces hebdo activées (vendredi 17:00).")
# ----------------------------
# Run
# ----------------------------
async def main():
    async with bot:
        await bot.start(DISCORD_TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
