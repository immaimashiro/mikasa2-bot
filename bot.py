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

# ----------------------------
# /vip actions
# ----------------------------
@vip_group.command(name="actions", description="Liste des actions et points (staff).")
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
@vip_group.command(name="add", description="Ajouter une action/points à un VIP (staff).")
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

# ----------------------------
# /vip sale (fenêtre de vente)
# ----------------------------
@vip_group.command(name="sale", description="Ouvrir la fenêtre de vente (ACHAT + ACHAT_LIMITEE).")
@staff_check()
@app_commands.describe(code_vip="SUB-XXXX-XXXX ou pseudo (staff)")
async def vip_sale(interaction: discord.Interaction, code_vip: str):
    await defer_ephemeral(interaction)

    row_i, vip = domain.find_vip_row_by_code_or_pseudo(sheets, code_vip)
    if not row_i or not vip:
        return await interaction.followup.send("❌ VIP introuvable (code ou pseudo).", ephemeral=True)

    m = staff_member(interaction)
    author_is_hg = bool(m and is_hg(m))

    code = normalize_code(str(vip.get("code_vip", "")))
    pseudo = display_name(vip.get("pseudo", code))

    view = ui.SaleWindowView(author=interaction.user, services=sheets, code_vip=code, vip_pseudo=pseudo, author_is_hg=author_is_hg)
    # Ajoute le bouton Valider propre (type-check)
    view.add_item(ui.SaleValidateButton())
    await interaction.followup.send(embed=view.embed(), view=view, ephemeral=True)

# ----------------------------
# /vip create
# ----------------------------
@vip_group.command(name="create", description="Créer un profil VIP (staff).")
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
@vip_group.command(name="card_generate", description="Générer la carte VIP (staff).")
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

    await interaction.followup.send("🖨️ Mikasa imprime… *prrrt prrrt* 🐾", ephemeral=True)

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
    await interaction.followup.send(
        content=f"✅ Carte VIP générée pour **{display_name(full_name)}**\n🔗 {url}",
        file=file,
        ephemeral=True
    )

# ----------------------------
# /vip card_show
# ----------------------------
@vip_group.command(name="card_show", description="Afficher une carte VIP (staff).")
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
@vip_group.command(name="sales_summary", description="Résumé des ventes (staff).")
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

# ----------------------------
# Ready + sync + scheduler
# ----------------------------
@bot.event
async def on_ready():
    print(f"Mikasa V2 connectée en tant que {bot.user}")

    # Sync sur ton serveur (évite les surprises)
    try:
        guild = discord.Object(id=GUILD_ID)
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
