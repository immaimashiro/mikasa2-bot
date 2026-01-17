import os
import random
import string
from datetime import datetime, timezone

import io

import gspread
from PIL import Image, ImageDraw, ImageFont
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.service_account import Credentials

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

import discord
from discord.ext import commands

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import asyncio
import re

# ======== DEFIS CONFIG ========
ANNOUNCE_CHANNEL_ID = int(os.getenv("ANNOUNCE_CHANNEL_ID", "0"))  # canal annonce défis
VIP_START = os.getenv("VIP_START", "2026-01-02 17:00")    # début semaine 1
#VIP_TZ = os.getenv("VIP_TZ", "Europe/Paris")

# ============================================================
# Cooldown spécial (VIP ciblé)
# ============================================================

SPECIAL_VIP_DISCORD_ID = 326742031961686026
SPECIAL_VIP_CODE = "SUB-MYAP-ZPXS"
SPECIAL_VIP_COOLDOWN_SECONDS = 48 * 60 * 60  # 48h = 172800s


#TZ_FR = ZoneInfo(VIP_TZ)

TZ_FR = ZoneInfo("Europe/Paris")
# ============================================================
# 0) Railway: écrire credentials.json depuis GOOGLE_CREDS
# ============================================================
GOOGLE_CREDS_ENV = os.getenv("GOOGLE_CREDS")
if GOOGLE_CREDS_ENV:
    with open("credentials.json", "w", encoding="utf-8") as f:
        f.write(GOOGLE_CREDS_ENV)

# ============================================================
# 1) Config
# ============================================================
# --- VIP Card assets
VIP_TEMPLATE_PATH = "template.png"
VIP_FONT_PATH = "PaybAck.ttf"

# --- Railway Bucket (S3 compatible)
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_DEFAULT_REGION = os.getenv("AWS_DEFAULT_REGION", "auto")
AWS_ENDPOINT_URL = os.getenv("AWS_ENDPOINT_URL")
AWS_S3_BUCKET_NAME = os.getenv("AWS_S3_BUCKET_NAME")

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
SHEET_ID = os.getenv("SHEET_ID")

EMPLOYEE_ROLE_ID = 1413872714032222298  # rôle employés SubUrban
HG_ROLE_ID = 1413856422659358741  # <-- remplace par l'ID du rôle HG du Didi
ANNOUNCE_CHANNEL_ID = 1459372711452086478 # pour les annonces de niveau qui monte et les s
# ===== Permissions actions VIP =====
EMPLOYEE_ALLOWED_ACTIONS = {"ACHAT", "RECYCLAGE", "ACHAT_LIMITEE"}  # seuls ces 3 là pour employés


DRIVE_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID")
STAFF_CHANNEL_ID = int(os.getenv("STAFF_CHANNEL_ID", "0"))


W1_START = datetime(2026, 1, 2, 17, 0, tzinfo=TZ_FR)   # 02/01/26 17:00 FR
W2_START = datetime(2026, 1, 16, 17, 0, tzinfo=TZ_FR)  # 16/01/26 17:00 FR (fin S1 / début S2)


#ANNOUNCE_CHANNEL_ID = int(os.getenv("ANNOUNCE_CHANNEL_ID", "0"))
#HG_ROLE_ID = int(os.getenv("HG_ROLE_ID", "0"))

TEMPLATE_PATH = "template.png"
FONT_PATH = "PaybAck.ttf"

PARIS_TZ = ZoneInfo(os.getenv("PARIS_TZ", "Europe/Paris"))

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]
WEEKLY_CHALLENGES = {
  1: [
    "Photo devant le SubUrban",
    "Photo avec un autre client SubUrban",
    "Photo Bleeter qui montre le meilleur spot pour votre tenue",
    "Photo dans un lieu emblématique : Vespucci Beach",
  ],
  2: [
    "Photo mur tagué / street art",
    "Photo outfit dans une rue très fréquentée",
    "Photo devant une vitrine SubUrban",
    "Photo sur une place publique (Legion Square, par ex.)",
  ],
  3: [
    "Photo de nuit dans les rues de Los Santos",
    "Photo sous un éclairage néon",
    "Photo rooftop (toit bâtiment)",
    "Photo ambiance nocturne (boîte, bar, etc.)",
  ],
  4: [
    "Photo prise par un ami avec pose imposée",
    "Photo en mouvement (running, drift, skate…)",
    "Photo devant SubUrban avec une pose stylée",
    "Photo en duo / groupe coordonné",
  ],
  5: [
    "Photo au Mont Chiliad",
    "Photo avec skyline de Los Santos",
    "Photo sur un toit très élevé",
    "Photo à l’observatoire (Griffith)",
  ],
  6: [
    "Photo en voiture + outfit SubUrban",
    "Photo devant un garage custom",
    "Photo à une station-service avec attitude",
    "Photo devant un véhicule de luxe (propre ou ami)",
  ],
  7: [
    "Photo sur une plage en tenue estivale SubUrban",
    "Photo chill sur banc / terrasse / café",
    "Photo Sunset (coucher de soleil)",
    "Photo nature / parc / promenade",
  ],
  8: [
    "Photo avec un vendeur SubUrban (Nouvelle EXIGENCE)",
    "Photo en train d’essayer une tenue (screen cabine)",
    "Photo devant un miroir",
    "Photo devant l’enseigne SubUrban",
  ],
  9: [
    "Photo avec pièce favorite du catalogue",
    "Photo type Lookbook",
    "Photo minimaliste (fond simple)",
    "Photo outfit monochrome",
  ],
  10: [
    "Photo devant un musée / galerie d’art",
    "Photo artistique (silhouette / ombre)",
    "Photo devant un bâtiment architectural",
    "Photo posée dans un lieu original (sculpture, fontaine…)",
  ],
  11: [
    "Photo devant un club / salle de concert",
    "Photo ambiance musique (instrument, DJ, scène…)",
    "Photo clip-friendly (pose caméra)",
    "Photo ambiance backstage",
  ],
  12: [
    "Freestyle - choisir 4 s parmi la liste :",
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
    "Photo posée / attitude",
  ],
}

scheduler = AsyncIOScheduler(timezone=PARIS_TZ)

VIPHELP_TIMEOUT_SECONDS = 240  # 4 minutes (anti-flood)

# ----------------------------
# Pages VIPHELP (contenu)
# ----------------------------

CLIENT_PAGE = {
    "title": "👤 Commandes Clients",
    "body": (
        "• `!niveau` → Voir ton niveau VIP, points, avantages, progression.\n"
        "• `!viphelp` → Afficher l’aide Mikasa."
    )
}

EMPLOYEE_PAGES = [
    {
        "title": "🪪 Création & gestion VIP",
        "body": (
            "• `!vipcreate @membre`\n"
            "• `!vipcreate PSEUDO`\n"
            "• `!vipcreatenote PSEUDO | NOTE`\n"
            "• `!viplink CODE @membre`\n"
            "• `!vipbleeter CODE PSEUDO`\n"
            "• `!vipsetdob CODE JJ/MM/AAAA`\n"
            "• `!vipsetphone CODE 06XXXXXXXX`\n"
        )
    },
    {
        "title": "🎯 Points & actions",
        "body": (
            "• `!vip CODE ACTION QTE [raison...]`\n"
            "• `!vipactions`\n"
            "• `!vip_event CODE ACTION QTE NOM_EVENT`\n"
            "• `!vipforce CODE ACTION QTE [raison...]` *(HG only)*\n\n"
            "📌 Exemples:\n"
            "• `!vip SUB-XXXX-XXXX ACHAT 50`\n"
            "• `!vip SUB-XXXX-XXXX RECYCLAGE 20`\n"
            "• `!vip_event SUB-XXXX-XXXX EVENT_SUB 1 Opening2026`\n"
        )
    },
    {
        "title": "🖼️ Cartes VIP",
        "body": (
            "• `!vipcard CODE` → Générer/MAJ la carte VIP *(salon staff)*\n"
            "• `!vipcardshow CODE|PSEUDO` → Afficher la carte (URL signée)\n"
        )
    },
    {
        "title": "🔎 Consultation",
        "body": (
            "• `!niveau PSEUDO` *(employé)*\n"
            "• `!niveau CODE` *(employé)*\n"
            "• `!niveau top` / `!niveau_top [N]`\n"
            "• `!vipsearch TEXTE`\n"
            "• `!vipstats`\n"
        )
    },
    {
        "title": "📸 Défis hebdo",
        "body": (
            "⏱️ Semaine défis: **Vendredi 17:00 → Vendredi suivant 16:59** (heure FR)\n"
            "• `!defiweek` → Publier l’annonce des défis *(HG only)*\n"
            "_Validation défis: HG uniquement._"
        )
    },
]

HG_PAGES = [
    {
        "title": "🕳️ Cave (bans VIP)",
        "body": (
            "• `!cave` → Liste des bans VIP\n"
            "• `!cave add PSEUDO | alias1, alias2`\n"
            "• `!cave remove PSEUDO|ALIAS`\n"
            "• `!cave info PSEUDO|ALIAS`\n\n"
            "😾 Mikasa garde la cave fermée. Claque la porte si récidive."
        )
    },
    {
        "title": "🛡️ Overrides HG",
        "body": (
            "• `!vipforce CODE ACTION QTE [raison...]` → Forcer une limite\n"
            "• Forçage utilisé seulement si nécessaire (traces dans LOG)\n"
        )
    },
    {
        "title": "📣 Défis (HG)",
        "body": (
            "• `!defiweek` → Poster les défis de la semaine (canal annonce)\n"
            "_Les défis ne sont validables que par HG._"
        )
    },
]
if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN manquant (Railway -> Variables).")

if not SHEET_ID:
    raise RuntimeError("SHEET_ID manquant (Railway -> Variables).")

# ============================================================
# 2) Helpers
# ============================================================
def now_fr() -> datetime:
    return datetime.now(tz=TZ_FR)

def get_vip_week_index(now: datetime | None = None) -> int:
    """
    Retourne:
    0 si pas commencé
    1 si dans la fenêtre S1 (14 jours)
    2..12 ensuite par tranches de 7 jours
    """
    now = now or now_fr()

    if now < W1_START:
        return 0
    if now < W2_START:
        return 1

    weeks_after = int((now - W2_START) // timedelta(days=7))
    wk = 2 + weeks_after
    return min(12, wk)

def get_week_window(week: int | None = None, now: datetime | None = None) -> tuple[datetime, datetime, int]:
    """
    Retourne (start, end, week_index)
    - Si week=None: calcule la semaine actuelle
    - end = borne de fin exclusive (pratique pour comparaisons)
    """
    now = now or now_fr()

    wk = week if week is not None else get_vip_week_index(now)

    if wk <= 0:
        # fenêtre vide (pas lancé)
        return (W1_START, W1_START, 0)

    if wk == 1:
        start = W1_START
        end = W2_START
        return (start, end, 1)

    start = W2_START + timedelta(days=7 * (wk - 2))
    end = start + timedelta(days=7)
    return (start, end, wk)

def week_key_for(k: int) -> str:
    return f"W{k:02d}"

def week_label_for(k: int) -> str:
    return f"Semaine {k}/12"

def fmt_fr(dt: datetime) -> str:
    return dt.astimezone(TZ_FR).strftime("%d/%m %H:%M")
# =========================
# HELPERS UI DEFIS
# =========================

import discord
from datetime import datetime

def yn_emoji(flag: bool) -> str:
    return "✔️" if flag else "❌"

def col_letter_for_defi(n: int) -> str:
    # DEFIS sheet: C..F = d1..d4
    return chr(ord("C") + (n - 1))

def get_week_tasks_for_view(wk: int) -> list[str]:
    """
    Semaines 1..11: 4 tâches
    Semaine 12: on renvoie 12 tâches "choix" (liste)
    """
    tasks = WEEKLY_CHALLENGES.get(wk, [])
    if wk == 12:
        # on attend une liste de 12 propositions
        if not tasks:
            return ["(Aucun défi configuré)"] * 12
        # si quelqu’un a mis 1 seule grosse ligne, on la garde mais ça fera 1 item:
        if len(tasks) == 1:
            # fallback: 12 copies (pas idéal mais évite crash)
            return [tasks[0]] * 12
        return tasks[:12]

    # semaines 1..11
    tasks = tasks[:4]
    while len(tasks) < 4:
        tasks.append("(Défi non configuré)")
    return tasks


# =========================
# VIEW S1..S11 : 4 toggles + VALIDER (tampon)
# =========================

class DefiValidateView(discord.ui.View):
    def __init__(self, *, author: discord.Member, code: str, wk: int, wk_key: str, wk_label: str,
                 row_i: int, row: dict, tasks: list[str], vip_pseudo: str):
        super().__init__(timeout=180)

        self.author = author
        self.code = code
        self.wk = wk
        self.wk_key = wk_key
        self.wk_label = wk_label
        self.row_i = row_i
        self.row = row
        self.tasks = tasks
        self.vip_pseudo = vip_pseudo

        # état initial depuis la sheet
        self.state = {
            1: bool(str(row.get("d1", "")).strip()),
            2: bool(str(row.get("d2", "")).strip()),
            3: bool(str(row.get("d3", "")).strip()),
            4: bool(str(row.get("d4", "")).strip()),
        }

        # IMPORTANT: tampon -> si un défi est déjà validé, on verrouille son bouton (pas de gomme)
        self.locked = {
            1: self.state[1],
            2: self.state[2],
            3: self.state[3],
            4: self.state[4],
        }

        self.message: discord.Message | None = None
        self._refresh_buttons()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(
                catify("😾 Pas touche. Lance ta propre commande `!defi CODE`."),
                ephemeral=True
            )
            return False
        return True

    def _build_embed(self) -> discord.Embed:
        wk_start, wk_end, _ = get_week_window()
        lines = []
        for i in range(1, 5):
            lines.append(f"{yn_emoji(self.state[i])} {self.tasks[i-1]}")

        desc = (
            f"👤 **{self.vip_pseudo}** • `{self.code}`\n"
            f"📌 {self.wk_label}\n"
            f"🗓️ **{wk_start.strftime('%d/%m %H:%M')} → {wk_end.strftime('%d/%m %H:%M')}** (FR)\n\n"
            + "\n".join(lines) +
            "\n\nClique pour cocher les ❌. Les ✔️ déjà tamponnés sont verrouillés."
        )

        embed = discord.Embed(
            title="📸 Validation des défis (HG)",
            description=desc,
            color=discord.Color.dark_purple()
        )
        embed.set_footer(text="Tampon Mikasa: une fois posé, il ne s’efface pas. 🐾")
        return embed

    def _refresh_buttons(self):
        for child in self.children:
            if isinstance(child, discord.ui.Button) and child.custom_id and child.custom_id.startswith("defi_toggle_"):
                n = int(child.custom_id.split("_")[-1])
                child.label = f"{yn_emoji(self.state[n])} Défi {n}"
                # verrou si déjà validé en sheet
                child.disabled = bool(self.locked[n])

    async def _edit(self, interaction: discord.Interaction):
        self._refresh_buttons()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    @discord.ui.button(label="❌ Défi 1", style=discord.ButtonStyle.secondary, custom_id="defi_toggle_1")
    async def toggle_1(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.state[1] = not self.state[1]
        await self._edit(interaction)

    @discord.ui.button(label="❌ Défi 2", style=discord.ButtonStyle.secondary, custom_id="defi_toggle_2")
    async def toggle_2(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.state[2] = not self.state[2]
        await self._edit(interaction)

    @discord.ui.button(label="❌ Défi 3", style=discord.ButtonStyle.secondary, custom_id="defi_toggle_3")
    async def toggle_3(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.state[3] = not self.state[3]
        await self._edit(interaction)

    @discord.ui.button(label="❌ Défi 4", style=discord.ButtonStyle.secondary, custom_id="defi_toggle_4")
    async def toggle_4(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.state[4] = not self.state[4]
        await self._edit(interaction)

    @discord.ui.button(label="✅ VALIDER", style=discord.ButtonStyle.success)
    async def commit(self, interaction: discord.Interaction, button: discord.ui.Button):
        # sécurité anti-double clic
        await interaction.response.defer()

        # --- TON CODE ICI ---
        # ex:
        # enregistrer les défis cochés
        # update Google Sheet
        # envoyer confirmation

        for child in self.children:
            child.disabled = True

        await interaction.message.edit(view=self)

        # ex: update sheet, calculs, etc.

        try:
            await interaction.edit_original_response(embed=final_embed, view=self)
        except Exception:
            try:
                await interaction.followup.send(embed=final_embed, ephemeral=True)
            except Exception:
                pass

    
            # relire la ligne DEFIS pour éviter conflit
        row_i2, row2 = get_defis_row(self.code, self.wk_key)
        if not row_i2:
            await interaction.response.send_message(catify("❌ Ligne DEFIS introuvable. Relance `!defi CODE`."), ephemeral=True)
            return
    
        done_before = defis_done_count(row2)
        now_dt = now_fr()
        stamp = now_dt.strftime("%Y-%m-%d %H:%M:%S")
    
        updates = []

        for n in range(1, 5):
            if self.state.get(n) and not str(row2.get(f"d{n}", "")).strip():
                col = col_letter_for_defi(n)
                updates.append({
                    "range": f"{col}{row_i2}",
                    "values": [[stamp]]
                })


    
            if updates:
                ws_defis.batch_update(updates)
    
            # reload
            row_i3, row3 = get_defis_row(self.code, self.wk_key)
            done_after = defis_done_count(row3)
    
            awarded = False
    
            # points UNIQUEMENT au 1er défi de la semaine
            if done_before == 0 and done_after > 0:
                ok1, _ = add_points_by_action(self.code, "BLEETER", 1, interaction.user.id, f"1er défi validé ({self.wk_key})", author_is_hg=True)
                ok2, _ = add_points_by_action(self.code, "DEFI_HEBDO", 1, interaction.user.id, f"1er défi validé ({self.wk_key})", author_is_hg=True)
                awarded = bool(ok1 and ok2)
    
            # si 4/4 -> completed + bonus + annonce (une seule fois)
            if done_after >= 4 and str(row3.get("completed_at", "")).strip() == "":
                comp_stamp = now_fr().strftime("%Y-%m-%d %H:%M:%S")
                ws_defis.batch_update([
                    {"range": f"G{row_i3}", "values": [[comp_stamp]]},
                    {"range": f"H{row_i3}", "values": [[str(interaction.user.id)]]},
                ])
    
                add_points_by_action(self.code, "TOUS_DEFIS_HEBDO", 1, interaction.user.id, f"4/4 défis complétés ({self.wk_key})", author_is_hg=True)
    
                if ANNOUNCE_CHANNEL_ID:
                    ch = bot.get_channel(int(ANNOUNCE_CHANNEL_ID))
                    if ch:
                        await ch.send(catify(
                            f"🎉 **{self.vip_pseudo}** vient de finir les **4 défis** de la {self.wk_label} !\n"
                            f"😼 Mikasa tamponne le carnet VIP: **COMPLET**. 🐾",
                            chance=0.10
                        ))
    
            # verrouille tout et affiche résultat
            for item in self.children:
                item.disabled = True
    
            final_embed = self._build_embed()
            extra = "🎁 Récompense donnée (1er défi de la semaine)." if awarded else "🧾 Récompense déjà prise cette semaine (ou aucune case nouvelle)."
            final_embed.add_field(name="✅ Enregistré", value=f"Progression: **{done_after}/4**\n{extra}", inline=False)
            final_embed.set_footer(text="Tampon posé. Mikasa referme le carnet. 🐾")

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                emb = self.message.embeds[0] if self.message.embeds else None
                if emb:
                    emb.set_footer(text="Menu expiré • Relance `!defi CODE` 🐾")
                    await self.message.edit(embed=emb, view=self)
                else:
                    await self.message.edit(view=self)
            except Exception:
                pass


# =========================
# VIEW SEMAINE 12 : 12 toggles (max 4) + VALIDER (tampon)
# =========================

class DefiWeek12View(discord.ui.View):
    def __init__(self, *, author: discord.Member, code: str, wk: int, wk_key: str, wk_label: str,
                 row_i: int, row: dict, choices: list[str], vip_pseudo: str):
        super().__init__(timeout=180)

        self.author = author
        self.code = code
        self.wk = wk
        self.wk_key = wk_key
        self.wk_label = wk_label
        self.row_i = row_i
        self.row = row
        self.choices = choices  # 12 textes
        self.vip_pseudo = vip_pseudo

        # d1..d4 déjà tamponnés ?
        self.state_slots = {
            1: bool(str(row.get("d1", "")).strip()),
            2: bool(str(row.get("d2", "")).strip()),
            3: bool(str(row.get("d3", "")).strip()),
            4: bool(str(row.get("d4", "")).strip()),
        }
        # verrou slots tamponnés
        self.locked_slots = {
            1: self.state_slots[1],
            2: self.state_slots[2],
            3: self.state_slots[3],
            4: self.state_slots[4],
        }

        # sélection en cours (jusqu’à 4) -> indices 0..11
        self.selected: set[int] = set()

        self.message: discord.Message | None = None

        # build 12 boutons dynamiques
        for i in range(12):
            self.add_item(Week12ChoiceButton(i))

        self.add_item(Week12ValidateButton())
        self._refresh_all()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(
                catify("😾 Pas touche. Lance ta propre commande `!defi CODE`."),
                ephemeral=True
            )
            return False
        return True

    def selected_count(self) -> int:
        return len(self.selected)

    def slots_done_count(self) -> int:
        return sum(1 for n in range(1, 5) if self.state_slots[n])

    def available_slots(self) -> int:
        return 4 - self.slots_done_count()

    def _build_embed(self) -> discord.Embed:
        wk_start, wk_end, _ = get_week_window()
        done = self.slots_done_count()
        lines = []
        for idx, txt in enumerate(self.choices):
            mark = "✔️" if idx in self.selected else "❌"
            lines.append(f"{mark} {txt}")

        desc = (
            f"👤 **{self.vip_pseudo}** • `{self.code}`\n"
            f"📌 {self.wk_label} (Freestyle)\n"
            f"🗓️ **{wk_start.strftime('%d/%m %H:%M')} → {wk_end.strftime('%d/%m %H:%M')}** (FR)\n\n"
            f"✅ Slots déjà validés: **{done}/4** (tampon)\n"
            f"🧩 Sélection en cours: **{self.selected_count()}/4** (max)\n\n"
            + "\n".join(lines)
            + "\n\nChoisis jusqu’à 4 défis, puis **VALIDER**."
        )

        embed = discord.Embed(
            title="🎭 Semaine 12 Freestyle (HG)",
            description=desc,
            color=discord.Color.purple()
        )
        embed.set_footer(text="Freestyle: Mikasa compte exactement 4 preuves. 🐾")
        return embed

    def _refresh_all(self):
        # refresh labels + disabled selon sélection
        for item in self.children:
            if isinstance(item, Week12ChoiceButton):
                idx = item.idx
                item.label = f"{'✔️' if idx in self.selected else '❌'} {idx+1}"
                # si déjà 4 sélectionnées, on désactive les non-sélectionnées
                if self.selected_count() >= 4 and idx not in self.selected:
                    item.disabled = True
                else:
                    item.disabled = False

            if isinstance(item, Week12ValidateButton):
                item.disabled = (self.selected_count() == 0)

    async def _edit(self, interaction: discord.Interaction):
        self._refresh_all()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    async def commit_selected(self, interaction: discord.Interaction):
        # relire row
        row_i2, row2 = get_defis_row(self.code, self.wk_key)
        if not row_i2:
            await interaction.response.send_message(catify("❌ Ligne DEFIS introuvable. Relance `!defi CODE`."), ephemeral=True)
            return

        done_before = defis_done_count(row2)
        now_dt = now_fr()
        stamp = now_dt.strftime("%Y-%m-%d %H:%M:%S")

        # slots disponibles = cases vides d1..d4
        empty_slots = []
        for n in range(1, 5):
            if not str(row2.get(f"d{n}", "")).strip():
                empty_slots.append(n)

        # Tampon: on ne remplace jamais une case déjà remplie
        # On remplit les slots vides avec la sélection (jusqu’à 4)
        to_write = list(self.selected)[:len(empty_slots)]
        updates = []

        for k, choice_idx in enumerate(to_write):
            slot_n = empty_slots[k]
            col = col_letter_for_defi(slot_n)
            updates.append({"range": f"{col}{row_i2}", "values": [[stamp]]})

            # On stocke dans d_notes la trace du choix
            picked_txt = self.choices[choice_idx]
            old_note = str(row2.get("d_notes", "")).strip()
            merged = (old_note + " | " if old_note else "") + f"W12:{slot_n}:{picked_txt}"
            ws_defis.update(f"I{row_i2}", merged)

        if updates:
            ws_defis.batch_update(updates)

        # reload
        row_i3, row3 = get_defis_row(self.code, self.wk_key)
        done_after = defis_done_count(row3)

        awarded = False
        if done_before == 0 and done_after > 0:
            ok1, _ = add_points_by_action(self.code, "BLEETER", 1, interaction.user.id, f"1er défi validé ({self.wk_key})", author_is_hg=True)
            ok2, _ = add_points_by_action(self.code, "DEFI_HEBDO", 1, interaction.user.id, f"1er défi validé ({self.wk_key})", author_is_hg=True)
            awarded = bool(ok1 and ok2)

        if done_after >= 4 and str(row3.get("completed_at", "")).strip() == "":
            comp_stamp = now_fr().strftime("%Y-%m-%d %H:%M:%S")
            ws_defis.batch_update([
                {"range": f"G{row_i3}", "values": [[comp_stamp]]},
                {"range": f"H{row_i3}", "values": [[str(interaction.user.id)]]},
            ])

            add_points_by_action(self.code, "TOUS_DEFIS_HEBDO", 1, interaction.user.id, f"4/4 défis complétés ({self.wk_key})", author_is_hg=True)

            if ANNOUNCE_CHANNEL_ID:
                ch = bot.get_channel(int(ANNOUNCE_CHANNEL_ID))
                if ch:
                    await ch.send(catify(
                        f"🎉 **{self.vip_pseudo}** vient de finir les **4 défis** de la {self.wk_label} !\n"
                        f"😼 Mikasa tamponne le carnet VIP: **COMPLET**. 🐾",
                        chance=0.10
                    ))

        # finish
        for item in self.children:
            item.disabled = True

        emb = self._build_embed()
        extra = "🎁 Récompense donnée (1er défi de la semaine)." if awarded else "🧾 Récompense déjà prise cette semaine (ou slots déjà complets)."
        emb.add_field(name="✅ Enregistré", value=f"Progression: **{done_after}/4**\n{extra}", inline=False)
        emb.set_footer(text="Freestyle enregistré. Mikasa range les preuves. 🐾")

        await interaction.response.edit_message(embed=emb, view=self)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                emb = self.message.embeds[0] if self.message.embeds else None
                if emb:
                    emb.set_footer(text="Menu expiré • Relance `!defi CODE` 🐾")
                    await self.message.edit(embed=emb, view=self)
                else:
                    await self.message.edit(view=self)
            except Exception:
                pass


class Week12ChoiceButton(discord.ui.Button):
    def __init__(self, idx: int):
        super().__init__(label=f"❌ {idx+1}", style=discord.ButtonStyle.secondary, custom_id=f"w12_choice_{idx}")
        self.idx = idx

    async def callback(self, interaction: discord.Interaction):
        view: DefiWeek12View = self.view  # type: ignore
        if self.idx in view.selected:
            view.selected.remove(self.idx)
        else:
            if view.selected_count() >= 4:
                await interaction.response.send_message(catify("😾 Max **4** choix en semaine 12."), ephemeral=True)
                return
            view.selected.add(self.idx)
        await view._edit(interaction)


class Week12ValidateButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="✅ VALIDER", style=discord.ButtonStyle.success, custom_id="w12_commit")

    async def callback(self, interaction: discord.Interaction):
        view: DefiWeek12View = self.view  # type: ignore
        await view.commit_selected(interaction)

def get_week_tasks(wk: int):
    tasks = WEEKLY_CHALLENGES.get(wk, [])
    # semaines 1..11 : 4 tâches attendues
    if wk != 12:
        # sécurise si jamais tu as moins/plus
        tasks = tasks[:4]
        while len(tasks) < 4:
            tasks.append("(Défi non configuré)")
        return tasks
    # semaine 12 : freestyle, on affiche une ligne générique dans le panel
    return ["Freestyle: choisir 4 défis parmi la liste (voir annonce)"] * 4

def append_row_by_headers(ws, data: dict):
    """
    Ajoute une ligne en alignant les valeurs sur les colonnes (headers) de la sheet.
    Les headers doivent être en ligne 1.
    """
    headers = [h.strip() for h in ws.row_values(1)]
    row = [""] * len(headers)

    for k, v in data.items():
        if k in headers:
            row[headers.index(k)] = v

    ws.append_row(row, value_input_option="RAW")


def get_defis_row(code_vip: str, wk_key: str):
    rows = ws_defis.get_all_records()
    for idx, r in enumerate(rows, start=2):  # ligne sheet
        if str(r.get("code_vip", "")).strip().upper() == code_vip and str(r.get("week_key", "")).strip() == wk_key:
            return idx, r
    return None, None

def ensure_defis_row(code_vip: str, wk_key: str, wk_label: str):
    row_i, row = get_defis_row(code_vip, wk_key)
    if row_i:
        return row_i, row

    ws_defis.append_row([
        wk_key,            # week_key
        code_vip,          # code_vip
        "", "", "", "",    # d1..d4
        "", "",            # completed_at, completed_by
        "",                # d_notes
        wk_label           # week_label
    ])
    row_i, row = get_defis_row(code_vip, wk_key)
    return row_i, row

def defis_done_count(row: dict):
    return sum(1 for k in ["d1", "d2", "d3", "d4"] if str(row.get(k, "")).strip() != "")

def is_defi_done(row: dict, n: int):
    return str(row.get(f"d{n}", "")).strip() != ""

def parse_start_dt():
    # "2026-01-02 17:00"
    return datetime.strptime(VIP_START, "%Y-%m-%d %H:%M").replace(tzinfo=TZ_FR)

def get_week_key():
    wk = get_vip_week_index()
    start, _ = get_week_window(wk)
    return f"VIPW{wk:02d}-{start.strftime('%Y%m%d')}"

def get_week_label():
    wk = get_vip_week_index()
    return f"Semaine {wk}/12"

def is_employee(member) -> bool:
    return has_employee_role(member)

def is_hg(member) -> bool:
    return has_hg_role(member)

def get_week_window_by_week(week: int) -> tuple[datetime, datetime]:
    """Fenêtre (start, end) pour une semaine donnée. end exclusif."""
    if week <= 0:
        return (W1_START, W1_START)
    if week == 1:
        return (W1_START, W2_START)

    start = W2_START + timedelta(days=7 * (week - 2))
    end = start + timedelta(days=7)
    return (start, end)

async def announce_level_up_async(code_vip: str, pseudo: str, old_level: int, new_level: int):
    if not ANNOUNCE_CHANNEL_ID:
        return

    ch = bot.get_channel(int(ANNOUNCE_CHANNEL_ID))
    if not ch:
        return

    pseudo_disp = display_name(pseudo)

    # avantages du niveau atteint
    _, raw_av = get_level_info(new_level)
    unlocked = split_avantages(raw_av)
    unlocked_lines = "\n".join([f"✅ {a}" for a in unlocked]) if unlocked else "✅ (Avantages non listés)"

    msg = (
        f"🎊 **LEVEL UP VIP**\n"
        f"👤 **{pseudo_disp}** vient de passer **Niveau {new_level}** !\n\n"
        f"🎁 **Débloque :**\n{unlocked_lines}\n\n"
        f"😼 Mikasa lève la patte comme pour tamponner le registre. *clac* 🐾"
    )

    await ch.send(catify(msg, chance=0.12))

def get_current_week_window(now: datetime | None = None) -> tuple[datetime | None, datetime | None, int]:
    """Retourne (start, end, week) pour maintenant."""
    now = now or now_fr()
    wk = get_vip_week_index(now)
    if wk == 0:
        return None, None, 0
    start, end = get_week_window_by_week(wk)
    return start, end, wk
    
def current_challenge_week_number(now=None) -> int:
    if now is None:
        now = datetime.now(PARIS_TZ)

    bootstrap_end = parse_bootstrap_end()
    if bootstrap_end and now < bootstrap_end:
        return 1

    # Date de référence = le vendredi 17:00 qui déclenche la Semaine 2 (juste après bootstrap)
    # On fixe REF = bootstrap_end (vendredi 16 à 17h), donc semaine 2 commence là.
    # Si tu veux que bootstrap_end soit "fin semaine 1", c'est parfait.
    ref = bootstrap_end
    if not ref:
        # fallback si pas configuré: on démarre semaine 1 au dernier vendredi 17h
        ref = last_friday_17(now)

    # Calcule combien de semaines depuis ref
    start = last_friday_17(now)
    weeks_since = int((start - ref).total_seconds() // (7 * 24 * 3600))

    # weeks_since = 0 -> semaine 2
    wk = ((weeks_since + 1) % 12) + 1   # +1 car semaine 2 à ref
    # explication: à ref -> wk=2, puis 3, etc.
    return wk


def get_rank_among_active(code_vip: str) -> tuple[int, int]:
    rows = ws_vip.get_all_records()
    active = []
    for r in rows:
        status = str(r.get("status", "ACTIVE")).strip().upper()
        if status != "ACTIVE":
            continue
        code = str(r.get("code_vip", "")).strip().upper()
        try:
            pts = int(r.get("points", 0))
        except Exception:
            pts = 0
        active.append((pts, code))

    active.sort(key=lambda x: x[0], reverse=True)
    total = len(active)
    rank = 0
    for i, (_, c) in enumerate(active, start=1):
        if c == code_vip.strip().upper():
            rank = i
            break
    return rank, total


def get_last_actions(code_vip: str, n: int = 3):
    rows = log_rows_for_vip(code_vip)
    items = []
    for r in rows:
        t = str(r.get("timestamp", r.get("created_at", "")) ).strip()
        dt = parse_iso_dt(t)
        if not dt:
            continue
        a = str(r.get("action", r.get("action_key", r.get("type", "")))).strip().upper()
        try:
            qty = int(r.get("qty", r.get("quantity", 1)))
        except Exception:
            qty = 1
        try:
            pts_added = int(r.get("points_added", r.get("points", r.get("delta", 0))))
        except Exception:
            pts_added = 0
        reason = str(r.get("reason", r.get("raison", "")) or "").strip()
        items.append((dt, a, qty, pts_added, reason))

    items.sort(key=lambda x: x[0], reverse=True)
    return items[:n]

    
def check_action_limit(code_vip: str, action_key: str, qty: int, reason: str, author_is_hg: bool):
    row = get_action_info(action_key)
    if not row:
        return False, "Action inconnue dans l’onglet ACTIONS.", False

    lim_raw = str(row.get("limite", "")).strip().lower()

    # Illimité
    if "illimit" in lim_raw or lim_raw == "":
        return True, "", False

    # fenêtre semaine défis (vendredi->vendredi)
    start, end = challenge_week_window()

    # tags
    ev = extract_tag(reason, "event:")
    poche = extract_tag(reason, "poche:")

    # 1 / semaine, 4 / semaine etc
    if "semaine" in lim_raw and "/" in lim_raw:
        # ex: "1 / semaine"
        try:
            max_per_week = int(lim_raw.split("/")[0].strip())
        except Exception:
            max_per_week = 1

        used = count_usage(code_vip, action_key, start, end)
        if used + qty <= max_per_week:
            return True, "", False

        if author_is_hg:
            return False, f"Limite hebdo atteinte (**{used}/{max_per_week}**). HG peut forcer.", True
        return False, f"😾 Limite hebdo atteinte (**{used}/{max_per_week}**). Mikasa refuse.", False

    # Par event
    if "par event" in lim_raw:
        if not ev:
            return False, "😾 Ajoute un tag `event:NomEvent` dans la raison (ou utilise `!vip_event`).", False

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
        return False, f"😾 Déjà validé pour **event:{ev}**. Mikasa bloque.", False

    # Par poche
    if "par poche" in lim_raw:
        if not poche:
            return False, "😾 Ajoute un tag `poche:XXX` dans la raison.", False

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
        return False, f"😾 Déjà validé pour **poche:{poche}**. Mikasa bloque.", False

    # A valider par staff (employé ok)
    if "a valider" in lim_raw:
        return True, "", False

    # Selon règles (HG only)
    if "selon" in lim_raw:
        if author_is_hg:
            return True, "", False
        return False, "😾 Cette action nécessite validation HG (SELON RÈGLES).", False

    return True, "", False

def parse_iso_dt(s: str):
    try:
        # now_iso() chez toi renvoie ISO UTC. On parse et on convertit en Paris.
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.astimezone(PARIS_TZ)
    except Exception:
        return None


def log_rows_for_vip(code_vip: str):
    code = (code_vip or "").strip().upper()
    out = []
    for r in ws_log.get_all_records():
        c = str(r.get("code_vip", "")).strip().upper()
        if c == code:
            out.append(r)
    return out


def count_usage(code_vip: str, action_key: str, start_dt, end_dt, tag_prefix=None, tag_value=None) -> int:
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

def get_action_info(action_key: str):
    key = (action_key or "").strip().upper()
    for r in ws_actions.get_all_records():
        k = str(r.get("action_key", "")).strip().upper()
        if k == key and k:
            return r
    return None


def normalize_limit(limit_raw: str) -> str:
    x = (limit_raw or "").strip().upper()
    x = x.replace(" ", "")
    x = x.replace("É", "E")
    x = x.replace("È", "E")
    x = x.replace("Ê", "E")
    return x


def get_limit_type(action_row: dict) -> str:
    lim = str(action_row.get("limite", "")).strip()
    x = lim.upper().replace(" ", "")
    x = x.replace("É", "E").replace("È", "E").replace("Ê", "E")
    return x


def has_hg_role(member) -> bool:
    if not HG_ROLE_ID:
        return False
    return any(r.id == HG_ROLE_ID for r in getattr(member, "roles", []))

def parse_bootstrap_end():
    s = (os.getenv("CHALLENGE_BOOTSTRAP_END") or "").strip()
    if not s:
        return None
    # format: YYYY-MM-DD HH:MM
    try:
        dt = datetime.strptime(s, "%Y-%m-%d %H:%M")
        return dt.replace(tzinfo=PARIS_TZ)
    except Exception:
        return None

def challenge_week_window(now=None):
    """
    Fenêtre défis: Vendredi 17:00 → Vendredi suivant 16:59:59
    + exception: tant que now < BOOTSTRAP_END, on reste en Semaine 1 (fenêtre étendue)
    """
    if now is None:
        now = datetime.now(PARIS_TZ)
    else:
        if now.tzinfo is None:
            now = now.replace(tzinfo=PARIS_TZ)

    bootstrap_end = parse_bootstrap_end()
    if bootstrap_end and now < bootstrap_end:
        # Semaine 1 démarre "à partir de maintenant" (on la fixe au premier lancement)
        # On prend comme début: le dernier vendredi 17:00 avant maintenant
        start = last_friday_17(now)
        end = bootstrap_end
        return start, end

    # normal: semaine glissante vendredi 17:00 → vendredi suivant 17:00
    start = last_friday_17(now)
    end = start + timedelta(days=7)
    return start, end

def last_friday_17(now):
    # Trouver le dernier vendredi 17:00 (Paris)
    # weekday: Monday=0 ... Sunday=6, Friday=4
    target_weekday = 4
    # on reconstruit une datetime du jour à 17:00
    candidate = now.replace(hour=17, minute=0, second=0, microsecond=0)
    # recule jusqu'au vendredi
    days_back = (candidate.weekday() - target_weekday) % 7
    candidate = candidate - timedelta(days=days_back)
    # si on est vendredi mais avant 17:00, on recule d'une semaine
    if now < candidate:
        candidate -= timedelta(days=7)
    return candidate


def extract_tag(text: str, prefix: str):
    """
    Cherche un tag du style 'event:xxx' ou 'poche:xxx' dans text.
    Retourne la valeur ('xxx') ou None.
    """
    if not text:
        return None
    t = text.lower().split()
    for tok in t:
        if tok.startswith(prefix.lower()):
            return tok.split(":", 1)[1].strip() if ":" in tok else None
    return None


def get_s3_client():
    """
    Client S3 compatible Railway Bucket.
    """
    endpoint = (os.getenv("AWS_ENDPOINT_URL") or "").strip()
    region = (os.getenv("AWS_DEFAULT_REGION") or "auto").strip()

    return boto3.client(
        "s3",
        endpoint_url=endpoint if endpoint else None,
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        region_name=region,
        config=Config(signature_version="s3v4"),
    )


def object_exists_in_bucket(key: str) -> bool:
    try:
        s3 = get_s3_client()
        s3.head_object(Bucket=AWS_S3_BUCKET_NAME, Key=key)
        return True
    except ClientError:
        return False


def generate_signed_url(key: str, expires_seconds: int = 3600) -> str | None:
    """
    Génère une URL signée pour lire un objet privé pendant X secondes.
    Retourne None si l'objet n'existe pas.
    """
    if not key:
        return None

    if not object_exists_in_bucket(key):
        return None

    s3 = get_s3_client()
    url = s3.generate_presigned_url(
        ClientMethod="get_object",
        Params={"Bucket": AWS_S3_BUCKET_NAME, "Key": key},
        ExpiresIn=int(expires_seconds),
    )
    return url


def download_png_from_bucket(object_key: str) -> bytes:
    s3 = get_s3_client()
    obj = s3.get_object(Bucket=AWS_S3_BUCKET_NAME, Key=object_key)
    return obj["Body"].read()

def set_vip_field_by_code(code_vip: str, field: str, value: str):
    row_i, vip = find_vip_row_by_code(code_vip)
    if not row_i:
        return False, "Code VIP introuvable."
    vip_update_cell_by_header(row_i, field, value)
    return True, vip


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_card_url_for_code(code_vip: str):
    row_i, vip = find_vip_row_by_code(code_vip)
    if not row_i:
        return None, None, None
    url = str(vip.get("card_url", "")).strip()
    pseudo = str(vip.get("pseudo", "")).strip()
    return url, pseudo, vip

def upload_card_to_drive(file_path: str, filename: str) -> str:
    """
    Upload l’image dans le dossier Drive et renvoie une URL partageable.
    """
    if not DRIVE_FOLDER_ID:
        raise RuntimeError("DRIVE_FOLDER_ID manquant")

    file_metadata = {
        "name": filename,
        "parents": [DRIVE_FOLDER_ID],
    }

    media = MediaFileUpload(file_path, mimetype="image/png")

    created = drive_service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id"
    ).execute()

    file_id = created["id"]

    # Rendre le fichier lisible via lien (option: restreindre à domaine, mais là on simplifie)
    drive_service.permissions().create(
        fileId=file_id,
        body={"type": "anyone", "role": "reader"},
    ).execute()

    return f"https://drive.google.com/file/d/{file_id}/view"

def find_vip_row_by_code(code_vip: str):
    code_up = str(code_vip).strip().upper()
    rows = ws_vip.get_all_records()
    for idx, r in enumerate(rows, start=2):
        code = str(r.get("code_vip", "")).strip().upper()
        if code and code == code_up:
            return idx, r
    return None, None

def vip_update_cell_by_header(row_i: int, header_name: str, value): #Petite fonction pour update colonnes par header
    headers = ws_vip.row_values(1)
    if header_name not in headers:
        raise RuntimeError(f"Colonne `{header_name}` introuvable dans VIP")
    col = headers.index(header_name) + 1
    ws_vip.update_cell(row_i, col, value)
    
#def generate_vip_card_image(code_vip: str, full_name: str, dob: str, phone: str, bleeter: str) -> str:
   # """
   # Génère une image VIP (PNG) à partir du template.
   # Retourne le chemin du fichier généré.
  #  """
  #  img = Image.open(TEMPLATE_PATH).convert("RGBA")
  #  draw = ImageDraw.Draw(img)
    
    # Tailles de police (ajustables)
  #  font_name = ImageFont.truetype(FONT_PATH, 54)
  #  font_line = ImageFont.truetype(FONT_PATH, 40)
  #  font_id = ImageFont.truetype(FONT_PATH, 46)

    # Coordonnées (adaptées à ton template)
  #  x = 70
  #  y = 120
  #  line_gap = 70

    # Normalisation d’affichage
  #  full_name = (full_name)
 #   dob = dob.strip()
  #  phone = phone.strip()
  #  bleeter = bleeter.strip()
 #   if bleeter and not bleeter.startswith("@"):
  #      bleeter = "@" + bleeter

    # Couleur texte (blanc légèrement cassé)
 #   color = (245, 245, 245, 255)

    # Nom Prénom (ligne unique)
 #   draw.text((x, y), full_name, font=font_name, fill=color)

    # DN / TEL / BLEETER
 #   draw.text((x, y + line_gap * 1), f"DN : {dob}", font=font_line, fill=color)
  #  draw.text((x, y + line_gap * 2), f"TÉLÉPHONE : {phone}", font=font_line, fill=color)
 #   draw.text((x, y + line_gap * 3), f"BLEETER : {bleeter if bleeter else 'non renseigné'}", font=font_line, fill=color)

    # Card ID en bas (centré)
 #   card_text = f"CARD ID : {code_vip}"
 #   w, h = img.size
 #   tw = draw.textlength(card_text, font=font_id)
 #   draw.text(((w - tw) / 2, h - 95), card_text, font=font_id, fill=(220, 30, 30, 255))

 #   out_path = f"/tmp/{code_vip}.png"
 #   img.save(out_path, "PNG")
 #   return out_path

def find_vip_row_by_code_or_pseudo(term: str):
    """
    Retourne (row_index, vip_dict) en cherchant:
    - par code_vip exact (insensible à la casse)
    - sinon par pseudo (avec normalize_name -> '_' = espace)
    """
    if not term:
        return None, None

    term_raw = str(term).strip()
    term_up = term_raw.upper()
    term_norm = normalize_name(term_raw)

    rows = ws_vip.get_all_records()

    for idx, r in enumerate(rows, start=2):  # start=2 car ligne 1 = header
        code = str(r.get("code_vip", "")).strip().upper()
        pseudo = str(r.get("pseudo", "")).strip()

        if code and term_up == code:
            return idx, r

        if pseudo and term_norm == normalize_name(pseudo):
            return idx, r

    return None, None

def mikasa_ban_block_reaction() -> str:
    return random.choice([
        "😾 **Mikasa hérisse les poils.** Ce nom est déjà sur sa liste noire.",
        "🐾 *Tsssk…* **La cave a déjà une place réservée pour ce nom.**",
        "🕯️ **Mikasa pose une patte sur le registre.** Refus immédiat.",
        "😼 **Mikasa ne discute pas avec la cave.**",
        "😾 *Hssss…* **Impossible.**",
    ])
    
def find_vip_by_code_or_name(term: str):
    """
    Retourne la ligne VIP si `term` est un code VIP ou un pseudo.
    """
    if not term:
        return None

    term_raw = term.strip()
    term_norm = normalize_name(term_raw)

    rows = ws_vip.get_all_records()

    for r in rows:
        code = str(r.get("code_vip", "")).strip()
        pseudo = str(r.get("pseudo", "")).strip()

        # match par code VIP exact
        if term_raw.upper() == code.upper():
            return r

        # match par pseudo normalisé
        if term_norm == normalize_name(pseudo):
            return r

    return None

def normalize_name(name: str) -> str:
    """
    Normalise un nom VIP pour comparaisons :
    - minuscules
    - _ = espace
    - espaces multiples réduits
    """
    if not name:
        return ""

    s = str(name).lower().strip()
    s = s.replace("_", " ")

    while "  " in s:
        s = s.replace("  ", " ")

    return s

def parse_points_filter(tokens):
    """
    Accepte: points > 1000, points>=1000, points = 500 etc.
    Retourne (op, value) ou (None, None)
    """
    if not tokens:
        return None, None

    s = " ".join(tokens).strip().lower()
    s = s.replace("pts", "points").replace("point", "points")

    m = re.search(r"points\s*(>=|<=|=|>|<)\s*(\d+)", s)
    if not m:
        return None, None
    op = m.group(1)
    val = int(m.group(2))
    return op, val


def cmp_int(x, op, y):
    if op == ">":
        return x > y
    if op == "<":
        return x < y
    if op == ">=":
        return x >= y
    if op == "<=":
        return x <= y
    return x == y


def parse_kv_filters(query: str):
    """
    Extrait des filtres simples:
    - code <val>
    - bleeter <val>
    - status active|inactive
    - points <op> <val>

    Retourne dict avec clés: code, bleeter, status, points_op, points_val, text
    """
    q = (query or "").strip()
    low = q.lower()

    # points filter
    points_op, points_val = parse_points_filter([q])

    # status
    status = None
    m = re.search(r"\bstatus\s+(active|inactive)\b", low)
    if m:
        status = m.group(1).upper()

    # code
    code = None
    m = re.search(r"\bcode\s+([A-Z0-9\-]+)\b", q, flags=re.I)
    if m:
        code = m.group(1).strip().upper()

    # bleeter
    bleeter = None
    m = re.search(r"\bbleeter\s+([^\s]+)\b", q, flags=re.I)
    if m:
        bleeter = m.group(1).strip()

    # texte libre = si pas de filtre explicite ou si on a juste un mot
    # On retire les morceaux reconnus pour éviter que "points" perturbe la recherche texte
    cleaned = q
    cleaned = re.sub(r"points\s*(>=|<=|=|>|<)\s*\d+", "", cleaned, flags=re.I).strip()
    cleaned = re.sub(r"\bstatus\s+(active|inactive)\b", "", cleaned, flags=re.I).strip()
    cleaned = re.sub(r"\bcode\s+[A-Z0-9\-]+\b", "", cleaned, flags=re.I).strip()
    cleaned = re.sub(r"\bbleeter\s+[^\s]+\b", "", cleaned, flags=re.I).strip()
    text = cleaned.strip()

    return {
        "code": code,
        "bleeter": bleeter,
        "status": status,
        "points_op": points_op,
        "points_val": points_val,
        "text": text
    }
    
def pipe_to_lines(raw: str, bullet: bool = True) -> str:
    """
    Convertit un texte "a|b|c" en lignes Discord.
    bullet=True -> ajoute "✅ " devant chaque ligne.
    """
    raw = (raw or "").strip()
    if not raw:
        return "✅ (Aucun avantage listé)"

    parts = [p.strip() for p in raw.split("|") if p.strip()]
    if not parts:
        return "✅ (Aucun avantage listé)"

    if bullet:
        return "\n".join([f"✅ {p}" for p in parts])
    return "\n".join(parts)

def display_name(name: str) -> str:
    """
    Formate un nom VIP pour affichage :
    - '_' remplacé par espace
    - chaque mot avec majuscule
    """
    if not name:
        return ""

    s = str(name).replace("_", " ").strip()

    # Nettoyage des espaces multiples
    while "  " in s:
        s = s.replace("  ", " ")

    # Majuscule à chaque mot
    return " ".join(word.capitalize() for word in s.split(" "))


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

def gen_code() -> str:
    # SUB-XXXX-XXXX
    alphabet = string.ascii_uppercase + string.digits
    a = "".join(random.choice(alphabet) for _ in range(4))
    b = "".join(random.choice(alphabet) for _ in range(4))
    return f"SUB-{a}-{b}"

def normalize_code(code: str) -> str:
    """
    Normalisation anti-typo:
    - majuscules
    - supprime espaces
    - remplace O par 0 (pour éviter XTOO vs XT00)
    """
    code = (code or "").strip().upper().replace(" ", "")
    return code.replace("O", "0")

def has_employee_role(member: discord.Member) -> bool:
    return any(r.id == EMPLOYEE_ROLE_ID for r in getattr(member, "roles", []))

def employee_only():
    async def predicate(ctx: commands.Context):
        if not ctx.guild:
            return False
        return has_employee_role(ctx.author)
    return commands.check(predicate)

def hg_only():
    async def predicate(ctx: commands.Context):
        if not ctx.guild:
            return False
        return has_hg_role(ctx.author)
    return commands.check(predicate)

def split_avantages(raw: str):
    raw = (raw or "").strip()
    if not raw:
        return []
    parts = [p.strip() for p in raw.split("|")]
    return [p for p in parts if p]

def progress_bar(current: int, target: int, width: int = 14) -> str:
    if target <= 0:
        return "█" * width
    ratio = max(0.0, min(1.0, current / target))
    filled = int(round(ratio * width))
    return "█" * filled + "░" * (width - filled)

CAT_EMOJIS = ["🐱", "🐾", "😺", "😸", "😼", "🐈"]
def catify(text: str, chance: float = 0.22) -> str:
    if random.random() < chance:
        return f"{text} {random.choice(CAT_EMOJIS)}"
    return text

# ============================================================
# Anti-spam VIP (cooldown par commande)
# - Bypass: employés + HG
# - Bloque seulement les clients (VIP) qui spam
# ============================================================

COMMAND_COOLDOWNS_SECONDS = {
    "niveau_public": 43200,       # !niveau (sans argument)
    "defistatus_public": 43200,   # !defistatus (sans argument)
}

_last_command_use: dict[tuple[int, str], datetime] = {}

async def anti_spam_vip(ctx: commands.Context, key: str) -> bool:
    """
    Cooldown par commande.
    - Staff (employés / HG) bypass
    - VIP spécifique : cooldown 48h
    """
    # Staff bypass total
    if has_employee_role(ctx.author) or has_hg_role(ctx.author):
        return True

    now = now_fr()

    # ============================
    # VIP SPÉCIAL (48h)
    # ============================
    if ctx.author.id == SPECIAL_VIP_DISCORD_ID:
        cd = SPECIAL_VIP_COOLDOWNS_SECONDS
    else:
        cd = int(COMMAND_COOLDOWNS_SECONDS.get(key, 0))

    if cd <= 0:
        return True

    k = (ctx.author.id, key)
    last = _last_command_use.get(k)

    if last and (now - last).total_seconds() < cd:
        remaining = int(cd - (now - last).total_seconds())

        # joli format temps
        if remaining >= 3600:
            h = remaining // 3600
            m = (remaining % 3600) // 60
            wait_txt = f"{h}h {m}min"
        elif remaining >= 60:
            wait_txt = f"{remaining // 60}min"
        else:
            wait_txt = f"{remaining}s"

        await ctx.send(
            catify(f"😾 Patience… Mikasa a noté ton passage. Reviens dans **{wait_txt}**."),
            delete_after=8
        )
        return False

    _last_command_use[k] = now
    return True

def mikasa_card_missing_reaction(code_vip: str):
    lines = [
        f"😾 **Mikasa fouille partout…** Sous le coussin, derrière l’armoire… Rien.",
        f"🐾 **Mikasa renverse une boîte.** *prrrt*… Toujours pas de carte.",
        f"😿 **La cachette est vide.** La carte VIP a disparu…",
    ]

    suggestion = (
        f"\n\n🖨️ Tu peux la régénérer avec :\n"
        f"`!vipcard {code_vip}`"
    )

    return random.choice(lines) + suggestion


# ============================================================
# 3) Google Sheets init
# ============================================================
creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
gc = gspread.authorize(creds)
drive_service = build("drive", "v3", credentials=creds)
sh = gc.open_by_key(SHEET_ID)

ws_vip = sh.worksheet("VIP")
ws_actions = sh.worksheet("ACTIONS")
ws_log = sh.worksheet("LOG")
ws_niveaux = sh.worksheet("NIVEAUX")
ws_ban_create = sh.worksheet("VIP_BAN_CREATE")
ws_defis = sh.worksheet("DEFIS")

# ============================================================
# 4) Niveaux (depuis onglet NIVEAUX)
# ============================================================
def get_levels():
    rows = ws_niveaux.get_all_records()
    levels = []
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
    
def get_all_unlocked_advantages(current_level: int) -> str:
    """
    Retourne TOUS les avantages débloqués du niveau 1 jusqu'au niveau actuel.
    Format final prêt pour Discord (avec ✅ et sauts de ligne).
    """
    all_advantages = []

    for lvl in range(1, current_level + 1):
        _, raw_av = get_level_info(lvl)
        if raw_av:
            parts = [p.strip() for p in raw_av.split("|") if p.strip()]
            all_advantages.extend(parts)

    if not all_advantages:
        return "✅ (Aucun avantage débloqué pour le moment)"

    # dédoublonnage propre en gardant l’ordre
    seen = set()
    unique = []
    for a in all_advantages:
        if a not in seen:
            seen.add(a)
            unique.append(a)

    return "\n".join([f"✅ {a}" for a in unique])

def calc_level(points: int) -> int:
    lvl = 1
    for n, pmin, _ in get_levels():
        if points >= pmin:
            lvl = n
    return lvl

def get_level_info(lvl: int):
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

# ============================================================
# 5) Actions (depuis onglet ACTIONS)
# ============================================================
def get_actions_map():
    rows = ws_actions.get_all_records()
    m = {}
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

# ============================================================
# 6) VIP: recherches / updates
# ============================================================
def get_all_vips():
    """
    Retourne la liste des VIP (records) de l'onglet VIP.
    Chaque item est un dict avec: code_vip, discord_id, pseudo, points, niveau, created_at, created_by, status
    """
    return ws_vip.get_all_records()

def find_vip_row_by_pseudo(pseudo: str):
    pseudo = (pseudo or "").strip().lower()
    rows = ws_vip.get_all_records()
    for idx, r in enumerate(rows, start=2):
        if str(r.get("pseudo", "")).strip().lower() == pseudo:
            return idx, r
    return None, None

def find_vip_row_by_code(code: str):
    code = normalize_code(code)
    rows = ws_vip.get_all_records()
    for idx, r in enumerate(rows, start=2):
        if normalize_code(str(r.get("code_vip", ""))) == code:
            return idx, r
    return None, None

def find_vip_row_by_discord_id(discord_id: int):
    rows = ws_vip.get_all_records()
    for idx, r in enumerate(rows, start=2):
        if str(r.get("discord_id", "")).strip() == str(discord_id):
            return idx, r
    return None, None

def code_exists(code: str) -> bool:
    _, r = find_vip_row_by_code(code)
    return r is not None

def create_vip_for_member(member: discord.Member, staff_id: int):
    """
    Crée un VIP lié à un membre Discord.
    Retourne (True, code_vip) si OK
    ou (False, message_erreur) si refus
    """

    # 1) Vérifier si le membre a déjà un VIP lié
    existing = ws_vip.get_all_records()
    for r in existing:
        if str(r.get("discord_id", "")).strip() == str(member.id):
            return False, "😾 Ce membre possède déjà un accès VIP."

    # 2) Check BAN pré-création (pseudo/alias/discord_id)
    banned, ban_reason = check_banned_for_create(
        pseudo=member.display_name,
        discord_id=str(member.id),
    )
    if banned:
        # Log staff interne (invisible publiquement)
        log_create_blocked(
            staff_id=staff_id,
            pseudo_attempted=member.display_name,
            discord_id=str(member.id),
            reason=ban_reason or "Match VIP_BAN_CREATE"
        )

        rp_messages = [
            "😾 **Mikasa hérisse les poils.** Ce nom ne lui inspire pas confiance… Le carnet VIP reste fermé.",
            "🐾 **Mikasa renifle l’air, puis referme le registre VIP.** Quelque chose cloche.",
            "😼 **Mikasa s’assoit sur le carnet VIP.** Impossible de l’ouvrir pour ce nom.",
            "🐱 **Les oreilles de Mikasa se plaquent en arrière.** Elle refuse d’écrire ce nom.",
            "😾 **Un léger feulement retentit.** Mikasa décide de ne pas aller plus loin.",
        ]
        return False, mikasa_ban_block_reaction()

    # 3) Générer un code VIP unique
    code = gen_code()
    while code_exists(code):
        code = gen_code()

    # 4) Valeurs initiales
    points = 0
    niveau = calc_level(points)
    created_at = now_iso()
    pseudo = member.display_name

    # 5) Écrire dans l’onglet VIP
    ws_vip.append_row([
        code,            # code_vip
        str(member.id),  # discord_id
        pseudo,          # pseudo
        points,          # points
        niveau,          # niveau
        created_at,      # created_at
        str(staff_id),   # created_by
        "ACTIVE",        # status
        ""               # bleeter (vide par défaut)
    ])

    # 6) Log de création
    ws_log.append_row([
        created_at,
        str(staff_id),
        code,
        "CREATE",
        1,
        0,
        0,
        f"Création VIP (lié Discord) pour {pseudo} ({member.id})"
    ])

    return True, code

def create_vip_manual(pseudo: str, staff_id: int, note: str = ""):
    """
    Crée un VIP manuel (non lié Discord).
    Retourne (True, code_vip) si OK
    ou (False, message_erreur) si refus
    """

    # 0) Normalisation pseudo (underscore -> espaces + belles majuscules)
    pseudo_clean = display_name((pseudo or "").strip())
    if not pseudo_clean:
        return False, "❌ Pseudo vide. Utilise: `!vipcreate PSEUDO` ou `!vipcreatenote PSEUDO | NOTE`"

    # 1) Check BAN pré-création (par pseudo / alias)
    banned, ban_reason = check_banned_for_create(pseudo=pseudo_clean, discord_id="")
    if banned:
        # Log staff interne (invisible publiquement)
        log_create_blocked(
            staff_id=staff_id,
            pseudo_attempted=pseudo_clean,
            discord_id="",
            reason=ban_reason or "Match VIP_BAN_CREATE"
        )

        return False, mikasa_ban_block_reaction()

    # 2) Générer un code VIP unique
    code = gen_code()
    while code_exists(code):
        code = gen_code()

    # 3) Valeurs initiales
    points = 0
    niveau = calc_level(points)
    created_at = now_iso()

    # 4) Écrire la ligne VIP
    # Actuellement : code_vip, discord_id, pseudo, points, niveau, created_at, created_by, status, bleeter
    # On ajoute dob/phone/card_url plus tard, test et ensuite on met des "" ici aussi.
    ws_vip.append_row([
        code,            # code_vip
        "",              # discord_id (vide)
        pseudo_clean,    # pseudo
        points,          # points
        niveau,          # niveau
        created_at,      # created_at
        str(staff_id),   # created_by
        "ACTIVE",        # status
        "",              # bleeter (vide par défaut)
        "",              # date de naissance
        "",              # téléphone
        "",              # card_url
        "",              # card_generated_at
        ""               # card_generated_by
    ])

    # 5) Log de création
    reason = f"Création VIP (manuel) pour {pseudo_clean}"
    if note and str(note).strip():
        reason += f" | Note: {str(note).strip()}"

    ws_log.append_row([
        created_at,
        str(staff_id),
        code,
        "CREATE_MANUAL",
        1,
        0,
        0,
        reason
    ])

    return True, code


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

def add_points_by_action(
    code_vip: str,
    action_key: str,
    qty: int,
    staff_id: int,
    reason: str,
    author_is_hg: bool = False
):
    action_key = (action_key or "").strip().upper()
        # Sécurité: si pas HG -> uniquement actions whitelist employé
    if not author_is_hg and action_key not in EMPLOYEE_ALLOWED_ACTIONS:
        return False, "😾 Action réservée aux HG. Employés: ACHAT, RECYCLAGE, ACHAT_LIMITEE."

    code = normalize_code(code_vip)

    # 0) check limites (ACTIONS)
    ok_lim, msg_lim, needs_confirm = check_action_limit(
        code,
        action_key,
        qty,
        reason or "",
        author_is_hg
    )

    if not ok_lim:
        # si besoin confirm HG: on renvoie un message spécial
        if needs_confirm:
            return False, msg_lim + " Tape `!vipforce CODE ACTION QTE ...` (HG) pour forcer."
        return False, msg_lim

    if qty <= 0:
        return False, "La quantité doit être > 0."

    row_i, vip = find_vip_row_by_code(code)
    if not row_i:
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

    # update points + niveau (Google Sheets)
    ws_vip.batch_update([
        {"range": f"D{row_i}", "values": [[new_points]]},
        {"range": f"E{row_i}", "values": [[new_level]]},
    ])

    # annonce level-up
    # ici on reste sync; on se contente d'un return qui permettra à la commande d'annoncer.

    ws_log.append_row([
        now_iso(),
        str(staff_id),
        code,
        action_key,
        qty,
        pu,
        delta,
        reason or "",
    ])

    return True, (delta, new_points, old_level, new_level)

# ============================================================
# 7) Templates RP pour actions
# ============================================================
ACTION_TEMPLATES = {
    "ACHAT": "🛍️ **{pseudo}** a effectué {qty} achat(s) chez SubUrban, ce qui lui a rapporté **{delta} points** au total.",
    "ACHAT_LIMITEE": "💎 **{pseudo}** a acheté {qty} pièce(s) **édition limitée**, gagnant ainsi **{delta} points** au total.",
    "RECYCLAGE": "♻️ **{pseudo}** a ramené {qty} vêtement(s) à recycler chez SubUrban, ce qui lui a rapporté **{delta} points** au total.",
    "BLEETER": "📸 **{pseudo}** a publié {qty} photo(s) Bleeter avec le style SubUrban, remportant **{delta} points**.",
    "DON_SANG": "🩸 **{pseudo}** a participé à un don du sang lors d’un event SubUrban et a gagné **{delta} points**.",
    "COLLAB_EVENT": "🤝 **{pseudo}** était présent(e) à {qty} event(s) partenaire(s) avec SubUrban, gagnant **{delta} points**.",
    "EVENT_SUB": "🎉 **{pseudo}** a participé à {qty} event(s) SubUrban, ce qui lui a rapporté **{delta} points**.",
    "TOUS_DEFIS_HEBDO": "🔥 **{pseudo}** a complété **tous les défis de la semaine**, remportant **{delta} points**.",
    "CONSEIL_STYLE": "🧵 **{pseudo}** a offert un conseil style / une interaction qualitative, validée par le staff, gagnant **{delta} points**.",
    "LOOKBOOK": "📖 **{pseudo}** a participé au LookBook SubUrban, remportant **{delta} points**.",
    "GAGNANT_PHOTO": "🏆 **{pseudo}** a remporté le concours de la meilleure photo de la semaine et gagne **{delta} points**.",
    "DEFI_HEBDO": "⚡ **{pseudo}** a validé {qty} défi(s) hebdomadaire(s), gagnant **{delta} points**.",
}

def format_action_message(action_key: str, pseudo: str, qty: int, delta: int, raison: str = "") -> str:
    key = (action_key or "").strip().upper()
    tpl = ACTION_TEMPLATES.get(key)

    if tpl:
        base = tpl.format(pseudo=pseudo, qty=qty, delta=delta)
    else:
        base = f"✅ **{pseudo}** a effectué **{key}** x{qty} → **{delta} points**."

    if raison and raison.strip():
        base += f"\n📝 Raison : {raison.strip()}"

    return catify(base)

# ============================================================
# 8) Discord bot
# ============================================================
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

def build_viphelp_embed(user: discord.abc.User, section: str, page_index: int, is_emp: bool, is_hg: bool) -> discord.Embed:
    color = random.choice([discord.Color.purple(), discord.Color.magenta(), discord.Color.dark_purple()])
    embed = discord.Embed(
        title="📚 Aide VIP SubUrban – Mikasa 🐾",
        description=(
            "Les `_` sont compris comme des espaces (ex: `Mai_Mashiro` = `Mai Mashiro`). 😼\n"
            "Semaine défis: **Vendredi 17:00 → Vendredi suivant 16:59** (heure FR)."
        ),
        color=color,
    )
    embed.set_thumbnail(url="https://i.postimg.cc/W4xjMp93/mikasa-cat.png")

    # Détermine la page à afficher
    if section == "client":
        embed.add_field(name=CLIENT_PAGE["title"], value=CLIENT_PAGE["body"], inline=False)
        embed.set_footer(text="Mikasa te montre le minimum… et garde le reste sous clé 🐾")
        return embed

    if section == "employee":
        if not is_emp:
            embed.add_field(
                name="⛔ Accès refusé",
                value="Cette section est réservée aux employés SubUrban. 😾",
                inline=False,
            )
            embed.set_footer(text="Mikasa grogne doucement. *hsss*")
            return embed

        page_index = max(0, min(page_index, len(EMPLOYEE_PAGES) - 1))
        p = EMPLOYEE_PAGES[page_index]
        embed.add_field(name=p["title"], value=p["body"], inline=False)
        embed.set_footer(text=f"Employés • Page {page_index + 1}/{len(EMPLOYEE_PAGES)} • Mikasa patrouille 🐾")
        return embed

    # section == "hg"
    if not is_hg:
        embed.add_field(
            name="🕯️ Accès Hautes Griffes",
            value="😾 Pas de clés, pas d’entrée. (HG uniquement)",
            inline=False,
        )
        embed.set_footer(text="Mikasa referme la trappe de la cave. *clac*")
        return embed

    page_index = max(0, min(page_index, len(HG_PAGES) - 1))
    p = HG_PAGES[page_index]
    embed.add_field(name=p["title"], value=p["body"], inline=False)
    embed.set_footer(text=f"Hautes Griffes • Page {page_index + 1}/{len(HG_PAGES)} • Silence dans la cave… 🐾")
    return embed


# ----------------------------
# View interactive (dropdown + boutons)
# ----------------------------

class VipHelpView(discord.ui.View):
    def __init__(self, author: discord.Member, start_section: str, is_emp: bool, is_hg: bool):
        super().__init__(timeout=VIPHELP_TIMEOUT_SECONDS)
        self.author = author
        self.section = start_section  # client | employee | hg
        self.page = 0
        self.is_emp = is_emp
        self.is_hg = is_hg
        self.message: discord.Message | None = None

        # pages max selon section
        self._sync_buttons()

    def _max_pages(self):
        if self.section == "employee":
            return len(EMPLOYEE_PAGES)
        if self.section == "hg":
            return len(HG_PAGES)
        return 1

    def _sync_buttons(self):
        # boutons actifs seulement pour employee/hg
        nav_enabled = self.section in ("employee", "hg")
        for child in self.children:
            if isinstance(child, discord.ui.Button) and child.custom_id in ("viphelp_prev", "viphelp_next"):
                child.disabled = not nav_enabled

        # si nav enabled, disable selon page
        if nav_enabled:
            maxp = self._max_pages()
            for child in self.children:
                if isinstance(child, discord.ui.Button) and child.custom_id == "viphelp_prev":
                    child.disabled = (self.page <= 0)
                if isinstance(child, discord.ui.Button) and child.custom_id == "viphelp_next":
                    child.disabled = (self.page >= maxp - 1)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # anti-flood: seul l'auteur du !viphelp peut cliquer
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(
                catify("😾 Pas touche. Ouvre ton propre `!viphelp`."), ephemeral=True
            )
            return False
        return True

    async def on_timeout(self):
        # désactive les composants à la fin
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                # on garde l'embed mais on ajoute un petit indice "expiré"
                embed = self.message.embeds[0] if self.message.embeds else None
                if embed:
                    embed.set_footer(text="Menu expiré • Relance `!viphelp` si besoin 🐾")
                    await self.message.edit(embed=embed, view=self)
                else:
                    await self.message.edit(view=self)
            except Exception:
                pass

    @discord.ui.select(
        placeholder="Choisir une catégorie…",
        options=[
            discord.SelectOption(label="Client", value="client", emoji="👤", description="Commandes publiques"),
            discord.SelectOption(label="Employé", value="employee", emoji="👮", description="Gestion VIP (staff)"),
            discord.SelectOption(label="Hautes Griffes", value="hg", emoji="🕯️", description="Cave & overrides (HG)"),
        ],
        custom_id="viphelp_select",
        min_values=1,
        max_values=1
    )
    async def select_callback(self, interaction: discord.Interaction, select: discord.ui.Select):
        choice = select.values[0]

        # accès intelligent / verrouillages
        if choice == "employee" and not self.is_emp:
            self.section = "employee"
            self.page = 0
        elif choice == "hg" and not self.is_hg:
            self.section = "hg"
            self.page = 0
        else:
            self.section = choice
            self.page = 0

        self._sync_buttons()
        embed = build_viphelp_embed(interaction.user, self.section, self.page, self.is_emp, self.is_hg)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary, custom_id="viphelp_prev")
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = max(0, self.page - 1)
        self._sync_buttons()
        embed = build_viphelp_embed(interaction.user, self.section, self.page, self.is_emp, self.is_hg)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary, custom_id="viphelp_next")
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = min(self._max_pages() - 1, self.page + 1)
        self._sync_buttons()
        embed = build_viphelp_embed(interaction.user, self.section, self.page, self.is_emp, self.is_hg)
        await interaction.response.edit_message(embed=embed, view=self)


# ----------------------------
# Commande !viphelp (interactive)
# ----------------------------

from discord import ui, Interaction, SelectOption

VIPHELP_TIMEOUT = 90  # secondes


class VipHelpRoleSelect(ui.Select):
    def __init__(self, author):
        self.author = author

        options = [
            SelectOption(
                label="Client VIP",
                description="Commandes accessibles aux clients",
                emoji="👤",
                value="client"
            ),
            SelectOption(
                label="Employé SubUrban",
                description="Commandes de gestion VIP",
                emoji="👮",
                value="employee"
            ),
            SelectOption(
                label="Hautes Griffes (HG)",
                description="Commandes sensibles et modération",
                emoji="🕯️",
                value="hg"
            ),
        ]

        super().__init__(
            placeholder="🐾 Choisis ton rôle…",
            options=options,
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction: Interaction):
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(
                "😾 Mikasa te regarde… ce menu n’est pas pour toi.",
                ephemeral=True
            )
            return

        role = self.values[0]

        if role == "client":
            embed = build_viphelp_client_embed()

            if interaction.response.is_done():
                await interaction.followup.edit_message(interaction.message.id, embed=embed, view=view)
            else:
                await interaction.response.edit_message(embed=embed, view=view)

           # return

        view = VipHelpCategoryView(self.author, role)
        embed = build_viphelp_category_embed(role)
        await interaction.response.edit_message(embed=embed, view=view)


        await interaction.response.edit_message(
            embed=embed,
            view=view
        )


class VipHelpCategorySelect(ui.Select):
    def __init__(self, author, role):
        self.author = author
        self.role = role

        options = []

        if role == "employee":
            options = [
                SelectOption(label="Création & profils", emoji="🆕", value="create"),
                SelectOption(label="Points & actions", emoji="🎯", value="points"),
                SelectOption(label="Consultation", emoji="📊", value="consult"),
                SelectOption(label="Cartes VIP", emoji="🎴", value="cards"),
            ]

        elif role == "hg":
            options = [
                SelectOption(label="Défis VIP", emoji="📸", value="defis"),
                SelectOption(label="Cave & bans", emoji="🕳️", value="cave"),
                SelectOption(label="Forçage & exceptions", emoji="⚠️", value="force"),
            ]

        super().__init__(
            placeholder="📂 Choisis une catégorie…",
            options=options,
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction: Interaction):
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(
                "😾 Mikasa claque la queue. Accès refusé.",
                ephemeral=True
            )
            return

        category = self.values[0]
        embed = build_viphelp_detail_embed(self.role, category)

        await interaction.response.edit_message(
            embed=embed,
            view=self.view
        )


class VipHelpCategoryView(ui.View):
    def __init__(self, author, role):
        super().__init__(timeout=VIPHELP_TIMEOUT)
        self.author = author
        self.role = role
        self.add_item(VipHelpCategorySelect(author, role))

    @ui.button(label="↩ Retour", style=discord.ButtonStyle.secondary)
    async def back_button(self, interaction: Interaction, button: ui.Button):
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(
                "😾 Mikasa te bloque le passage. Ouvre ton propre `!viphelp`.",
                ephemeral=True
            )
            return

        # Retour à la sélection du rôle
        view = VipHelpRoleView(self.author)
        embed = base_viphelp_embed(
            "📚 Aide VIP SubUrban – Mikasa 🐾",
            "Sélectionne ton rôle pour afficher l’aide correspondante."
        )
        await interaction.response.edit_message(embed=embed, view=view)


class VipHelpRoleView(ui.View):
    def __init__(self, author):
        super().__init__(timeout=VIPHELP_TIMEOUT)
        self.add_item(VipHelpRoleSelect(author))


# ===== EMBEDS =====

def base_viphelp_embed(title: str, description: str) -> discord.Embed:
    embed = discord.Embed(
        title=title,
        description=description,
        color=random.choice([
            discord.Color.purple(),
            discord.Color.magenta(),
            discord.Color.dark_purple()
        ])
    )
    embed.set_thumbnail(
        url="https://i.postimg.cc/W4xjMp93/mikasa-cat.png"
    )
    embed.set_footer(
        text=random.choice([
            "Mikasa te regarde… puis cligne des yeux 🐾",
            "Mrrp~ Mikasa est satisfaite 😼",
            "Hsss… touche pas au VIP 😾",
            "Mikasa • Gardienne du SubUrban VIP"
        ])
    )
    return embed


def build_viphelp_client_embed():
    return base_viphelp_embed(
        "👤 Aide VIP – Client",
        (
            "• `!niveau` → Voir ton niveau, points et avantages\n"
            "• `!viphelp` → Afficher cette aide\n\n"
            "_Les `_` sont compris comme des espaces._ 😺"
        )
    )


def build_viphelp_category_embed(role: str):
    if role == "employee":
        return base_viphelp_embed(
            "👮 Aide VIP – Employé",
            "Choisis une catégorie pour voir les commandes disponibles."
        )
    return base_viphelp_embed(
        "🕯️ Aide VIP – Hautes Griffes",
        "Accès réservé. Mikasa surveille. 😾"
    )


def build_viphelp_detail_embed(role: str, category: str):
    if role == "employee":
        if category == "create":
            return base_viphelp_embed(
                "🆕 Création & Profils",
                (
                    "• `!vipcreate @membre`\n"
                    "• `!vipcreate PSEUDO`\n"
                    "• `!vipcreatenote PSEUDO | NOTE`\n"
                    "• `!viplink CODE @membre`\n"
                    "• `!vipbleeter CODE PSEUDO`\n"
                    "• `!vipsetdob CODE JJ/MM/AAAA`\n"
                    "• `!vipsetphone CODE TEL`"
                )
            )

        if category == "points":
            return base_viphelp_embed(
                "🎯 Points & Actions",
                (
                    "• `!vip CODE ACHAT QTE`\n"
                    "• `!vip CODE RECYCLAGE QTE`\n"
                    "• `!vipactions`\n"
                    "_Les autres actions sont HG only._"
                )
            )

        if category == "consult":
            return base_viphelp_embed(
                "📊 Consultation",
                (
                    "• `!niveau PSEUDO`\n"
                    "• `!niveau_top`\n"
                    "• `!vipsearch ...`\n"
                    "• `!vipstats`"
                )
            )

        if category == "cards":
            return base_viphelp_embed(
                "🎴 Cartes VIP",
                (
                    "• `!vipcard CODE`\n"
                    "• `!vipcardshow CODE|PSEUDO`"
                )
            )

    if role == "hg":
        if category == "defis":
            return base_viphelp_embed(
                "📸 Défis VIP",
                (
                    "• `!defi CODE 1 [note]`\n"
                    "• `!defistatus`\n"
                    "• `!defiweek`"
                )
            )

        if category == "cave":
            return base_viphelp_embed(
                "🕳️ Cave de Mikasa",
                (
                    "• `!cave`\n"
                    "• `!cave add PSEUDO | alias`\n"
                    "• `!cave remove PSEUDO|ALIAS`\n"
                    "• `!cave info PSEUDO|ALIAS`"
                )
            )

        if category == "force":
            return base_viphelp_embed(
                "⚠️ Forçage & Exceptions",
                (
                    "• `!vipforce ...`\n"
                    "• Accès limites / bypass défis\n\n"
                    "_Mikasa n’oublie rien._ 😾"
                )
            )

    return base_viphelp_embed("Erreur", "Catégorie inconnue.")


# ===== COMMANDE =====

@bot.command(name="viphelp")
async def viphelp(ctx):
    view = VipHelpRoleView(ctx.author)
    embed = base_viphelp_embed(
        "📚 Aide VIP SubUrban – Mikasa 🐾",
        "Sélectionne ton rôle pour afficher l’aide correspondante."
    )
    await ctx.send(embed=embed, view=view)

    
@bot.event
async def on_command_error(ctx, error):
    import traceback
    traceback.print_exception(type(error), error, error.__traceback__)

    if isinstance(error, commands.CommandNotFound):
        return  # on ignore

    if isinstance(error, commands.CheckFailure):
        await ctx.send(catify("⛔ Pas les permissions pour cette commande."))
        return

    await ctx.send(catify(f"❌ Erreur: `{type(error).__name__}`"))


async def post_weekly_challenges_announcement():
    if not ANNOUNCE_CHANNEL_ID:
        return
    ch = bot.get_channel(int(ANNOUNCE_CHANNEL_ID))
    if not ch:
        return

    wk = current_challenge_week_number()
    start, end = challenge_week_window()

    tasks = WEEKLY_CHALLENGES.get(wk, [])
    title = f"📸 Défis VIP SubUrban, en tenue complète SubUrban #DEFISUBURBAN | Semaine {wk}/12"

    lines = []
    if wk == 12:
        lines.append("🎭 **SEMAINE FINALE – FREESTYLE**")
        lines.append("Choisissez **4 défis** parmi les propositions :")
        lines.append(f"• {tasks[0]}")
    else:
        lines.append("Voici les **4 défis** à valider cette semaine :")
        for i, t in enumerate(tasks, start=1):
            lines.append(f"**{i}.** {t}")

    lines.append("")
    lines.append(f"🗓️ Période: **{start.strftime('%d/%m %H:%M')} → {end.strftime('%d/%m %H:%M')}** (heure FR)")
    lines.append("✅ Validation des défis: **HG uniquement**")
    lines.append("😼 Mikasa annonce la chasse aux photos. prrr 🐾")

    msg = f"**{title}**\n" + "\n".join(lines)
    await ch.send(msg)


@bot.event
async def on_ready():
    print(f"Mikasa connectée en tant que {bot.user}")

    # éviter double schedule si reconnect
    if not getattr(bot, "_mikasa_scheduler_started", False):
        bot._mikasa_scheduler_started = True

        trigger = CronTrigger(day_of_week="fri", hour=17, minute=0, timezone=PARIS_TZ)
        scheduler.add_job(lambda: bot.loop.create_task(post_weekly_challenges_announcement()), trigger)
        scheduler.start()

        print("Scheduler Mikasa: annonces hebdo activées (vendredi 17:00).")

# ============================================================
# 9) Commandes PUBLIQUES
# ============================================================
@bot.command(name="niveau")
async def niveau(ctx, *, pseudo: str = None):
    # ======================================================
    # CAS 1 — !niveau (public, pour soi-même)
    # ======================================================
    if pseudo is None:
        if not await anti_spam_vip(ctx, "niveau_public"):
            return

        row_i, vip = find_vip_row_by_discord_id(ctx.author.id)
        
        if not row_i:
            await ctx.send(catify("Tu n'as pas de VIP lié. Va voir un employé SubUrban pour la création."))
            return

        points = int(vip.get("points", 0))
        lvl = int(vip.get("niveau", 1))
        created_at = str(vip.get("created_at", "—"))
        pseudo_vip = display_name(vip.get("pseudo", ctx.author.display_name))
        bleeter = str(vip.get("bleeter", "")).strip()

    # ======================================================
    # CAS 2 — !niveau PSEUDO (employé uniquement)
    # ======================================================
    else:
        if not has_employee_role(ctx.author):
            await ctx.send(catify("⛔ Cette commande est réservée aux employés SubUrban."))
            return

        row_i, vip = find_vip_row_by_code_or_pseudo(pseudo)
        if not row_i:
            await ctx.send(catify(f"❌ Aucun VIP trouvé pour **{display_name(pseudo)}**."))
            return

        points = int(vip.get("points", 0))
        lvl = int(vip.get("niveau", 1))
        created_at = str(vip.get("created_at", "—"))
        pseudo_vip = display_name(vip.get("pseudo", pseudo))
        bleeter = str(vip.get("bleeter", "")).strip()

    # ======================================================
    # AFFICHAGE COMMUN
    # ======================================================
    date_simple = created_at[:10] if len(created_at) >= 10 else created_at

    # 🛰️ Bleeter "ultra cool"
    if bleeter:
        bleeter_line = f"🛰️ Bleeter : **@{bleeter}**"
    else:
        bleeter_line = "🛰️ Bleeter : _non enregistré_ (demande au staff 😺)"

    # avantages débloqués (format: "a|b|c" -> lignes)
    # 🎁 Avantages débloqués (cumulés depuis le niveau 1)
    unlocked_lines = get_all_unlocked_advantages(lvl)

    # Rang global
    code_cur = str(vip.get("code_vip", "")).strip().upper()
    rank, total = get_rank_among_active(code_cur)
    rank_line = f"🏁 Rang: **#{rank}** sur **{total}** VIP actifs" if rank else "🏁 Rang: _non classé_"

    # 3 dernières actions
    last = get_last_actions(code_cur, n=3)
    if last:
        lines = []
        for dt, a, q, pts_add, _rsn in last:
            icon = "🧾"
            if "ACHAT" in a:
                icon = "🛍️"
            elif "RECYCL" in a:
                icon = "♻️"
            elif "EVENT" in a:
                icon = "🎫"
            elif "CREATE" in a:
                icon = "🆕"
            lines.append(f"• {icon} **{a}** x{q} → **+{pts_add}** pts")
        last_block = "\n".join(lines)
    else:
        last_block = "_Aucune action récente._"

    # prochain niveau
    nxt = get_next_level(lvl)
    if nxt:
        next_lvl, next_min, next_av = nxt
        missing = max(0, int(next_min) - points)

        cur_min, _ = get_level_info(lvl)
        span = max(1, int(next_min) - int(cur_min))
        into = max(0, points - int(cur_min))
        bar = progress_bar(into, span, width=14)

        # aperçu prochain niveau (2 max)
        preview_lines_full = pipe_to_lines(next_av, bullet=False)
        preview_lines_list = [line for line in preview_lines_full.split("\n") if line.strip()]
        if preview_lines_list:
            preview_lines = "\n".join([f"🔒 {l}" for l in preview_lines_list[:2]])
        else:
            preview_lines = "🔒 (à venir)"

        
        pct = int((into / span) * 100) if span > 0 else 100
        pct = max(0, min(100, pct))

        next_block = (
            f"⬆️ Prochain: **Niveau {next_lvl}** à **{next_min}** points\n"
            f"📈 Progression: `{bar}` **{pct}%**  (+{missing} pts)\n"
            f"{preview_lines}"
        )
    else:
        next_block = "🏁 **Niveau max atteint**. Respect. 😼"

    msg = (
        f"🎖️ **VIP SubUrban**\n"
        f"👤 **{pseudo_vip}**\n"
        f"{bleeter_line}\n"
        f"📊 Niveau **{lvl}** | **{points}** points\n"
        f"📅 VIP depuis : `{date_simple}`\n"
        f"{rank_line}\n\n"
        f"🧾 **Dernières actions**\n"
        f"{last_block}\n\n"
        f"🎁 **Avantages débloqués**\n"
        f"{unlocked_lines}\n\n"
        f"{next_block}"
    )

    await ctx.send(catify(msg, chance=0.18))

#
#ESSAI
#


def generate_vip_card_image(code_vip: str, full_name: str, dob: str, phone: str, bleeter: str) -> bytes:
    """
    Génère l'image VIP en mémoire et retourne les bytes PNG.
    """
    img = Image.open(VIP_TEMPLATE_PATH).convert("RGBA")
    draw = ImageDraw.Draw(img)

    # Police
    font_name = ImageFont.truetype(VIP_FONT_PATH, 56)
    font_line = ImageFont.truetype(VIP_FONT_PATH, 38)
    font_id   = ImageFont.truetype(VIP_FONT_PATH, 46)

    # Couleurs
    white = (245, 245, 245, 255)
    red   = (220, 30, 30, 255)
    shadow = (0, 0, 0, 160)
    
    def shadow_text(x, y, text, font, fill):
        # petite ombre pour lisibilité
        draw.text((x+2, y+2), text, font=font, fill=shadow)
        draw.text((x, y), text, font=font, fill=fill)
        
    # --- TITRE EN HAUT : VIP (rouge) + WINTER EDITION (blanc), centré
    title_font = ImageFont.truetype(VIP_FONT_PATH, 56)  # Frozen Caps
    w, h = img.size

    vip_txt = "VIP"
    winter_txt = " WINTER EDITION"

    vip_w = draw.textlength(vip_txt, font=title_font)
    winter_w = draw.textlength(winter_txt, font=title_font)
    total_w = vip_w + winter_w

    x0 = int((w - total_w) / 2)
    y0 = 35  # ajuste si besoin (25-55 selon rendu)

    # ombre légère
    def shadow_text2(x, y, text, font, fill):
        draw.text((x+2, y+2), text, font=font, fill=(0, 0, 0, 160))
        draw.text((x, y), text, font=font, fill=fill)

    shadow_text2(x0, y0, vip_txt, title_font, (220, 30, 30, 255))             # VIP rouge
    shadow_text2(x0 + vip_w, y0, winter_txt, title_font, (245, 245, 245, 255)) # Winter blanc

    # Normalisation affichage
    full_name = display_name(full_name).upper()
    dob = (dob or "").strip()
    phone = (phone or "").strip()
    bleeter = (bleeter or "").strip()
    if bleeter and not bleeter.startswith("@"):
        bleeter = "@" + bleeter

    # Positions (adaptées à ton template)
    x = 70
    y = 140
    gap = 70

    shadow_text(x, y, f"{full_name}", font_name, white)
    shadow_text(x, y + gap*1, f"DN : {dob}", font_line, white)
    shadow_text(x, y + gap*2, f"TELEPHONE : {phone}", font_line, white)
    shadow_text(x, y + gap*3, f"BLEETER : {bleeter if bleeter else 'NON RENSEIGNE'}", font_line, white)

    # Card ID en bas centré
    w, h = img.size
    card_text = f"CARD ID : {code_vip}"
    tw = draw.textlength(card_text, font=font_id)
    shadow_text(int((w - tw)/2), h - 95, card_text, font_id, red)

    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()

#def get_s3_client():
  #  return boto3.client(
   #     "s3",
  #      aws_access_key_id=AWS_ACCESS_KEY_ID,
    #    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    #    region_name=AWS_DEFAULT_REGION,
   #     endpoint_url=AWS_ENDPOINT_URL,
  #  )

def upload_png_to_bucket(png_bytes: bytes, object_key: str) -> str:
    """
    Upload dans le bucket Railway et retourne une URL.
    """
    s3 = get_s3_client()

    extra = {"ContentType": "image/png"}
    # on tente public-read (si le provider l'accepte)
    extra_try_acl = dict(extra)
    extra_try_acl["ACL"] = "public-read"

    try:
        s3.put_object(Bucket=AWS_S3_BUCKET_NAME, Key=object_key, Body=png_bytes, **extra_try_acl)
    except ClientError:
        # fallback sans ACL si refusé
        s3.put_object(Bucket=AWS_S3_BUCKET_NAME, Key=object_key, Body=png_bytes, **extra)

    # URL "directe" (souvent OK sur Railway bucket)
    base = (AWS_ENDPOINT_URL or "").rstrip("/")
    return f"{base}/{AWS_S3_BUCKET_NAME}/{object_key}"

# ============================================================
# 10) Commandes EMPLOYÉS
# ============================================================
@bot.command(name="vip_event")
@employee_only()
async def vip_event(ctx, code_vip: str, action_key: str, qty: int, *, event_name: str = ""):
    if STAFF_CHANNEL_ID and ctx.channel.id != int(STAFF_CHANNEL_ID):
        await ctx.send(catify("😾 Commande utilisable uniquement dans le salon staff."))
        return

    code_vip = (code_vip or "").strip().upper()
    action_key = (action_key or "").strip().upper()
    event_name = (event_name or "").strip()

    if not code_vip or not action_key or qty <= 0 or not event_name:
        await ctx.send(catify("❌ Utilisation: `!vip_event SUB-XXXX-XXXX ACTION 1 nom_event`"))
        return

    reason = f"event:{event_name.replace(' ', '_')}"
    ok, res = add_points_by_action(code_vip, action_key, qty, ctx.author.id, reason, author_is_hg=has_hg_role(ctx.author))
    if not ok:
        await ctx.send(catify(f"❌ {res}"))
        return

    delta, new_points, old_level, new_level = res
    await ctx.send(catify(f"✅ +{delta} points ajoutés"))



@bot.command(name="vipsetdob")
@employee_only()
async def vipsetdob(ctx, code_vip: str = "", dob: str = ""):
    if STAFF_CHANNEL_ID and ctx.channel.id != int(STAFF_CHANNEL_ID):
        await ctx.send(catify("😾 Modifs VIP uniquement dans le salon staff."))
        return

    code_vip = (code_vip or "").strip().upper()
    dob = (dob or "").strip()

    if not code_vip or not dob:
        await ctx.send(catify("❌ Utilisation: `!vipsetdob SUB-XXXX-XXXX 27/12/2004`"))
        return

    ok, res = set_vip_field_by_code(code_vip, "dob", dob)
    if not ok:
        await ctx.send(catify(f"❌ {res}"))
        return

    pseudo = display_name(res.get("pseudo", "VIP"))
    await ctx.send(catify(f"✅ DN enregistrée pour **{pseudo}** : `{dob}` 🐾", chance=0.18))


@bot.command(name="vipsetphone")
@employee_only()
async def vipsetphone(ctx, code_vip: str = "", phone: str = ""):
    if STAFF_CHANNEL_ID and ctx.channel.id != int(STAFF_CHANNEL_ID):
        await ctx.send(catify("😾 Modifs VIP uniquement dans le salon staff."))
        return

    code_vip = (code_vip or "").strip().upper()
    phone = (phone or "").strip()

    if not code_vip or not phone:
        await ctx.send(catify("❌ Utilisation: `!vipsetphone SUB-XXXX-XXXX 0612345678`"))
        return

    ok, res = set_vip_field_by_code(code_vip, "phone", phone)
    if not ok:
        await ctx.send(catify(f"❌ {res}"))
        return

    pseudo = display_name(res.get("pseudo", "VIP"))
    await ctx.send(catify(f"✅ Téléphone enregistré pour **{pseudo}** : `{phone}` 😺", chance=0.18))


@bot.command(name="vipcard")
@employee_only()
async def vipcard(ctx, code_vip: str = ""):
    # salon staff only
    if STAFF_CHANNEL_ID and ctx.channel.id != int(STAFF_CHANNEL_ID):
        await ctx.send(catify("😾 Les cartes VIP se font uniquement dans le salon staff."))
        return

    code_vip = (code_vip or "").strip().upper()
    if not code_vip:
        await ctx.send(catify("❌ Utilisation: `!vipcard SUB-XXXX-XXXX`"))
        return

    row_i, vip = find_vip_row_by_code(code_vip)
    if not row_i:
        await ctx.send(catify("❌ Code VIP introuvable."))
        return

    full_name = str(vip.get("pseudo", "")).strip()
    dob = str(vip.get("dob", "")).strip()
    phone = str(vip.get("phone", "")).strip()
    bleeter = str(vip.get("bleeter", "")).strip()

    # check infos obligatoires
    if not dob or not phone:
        await ctx.send(catify(
            "😾 Impossible de générer la carte: il manque **DN** ou **Téléphone**.\n"
            "➡️ Renseigne `dob` et `phone` dans la sheet (onglet VIP), puis relance."
        ))
        return

    await ctx.send(catify("🖨️ Mikasa imprime… *prrrt prrrt* 🐾", chance=0.25))

    try:
        png = generate_vip_card_image(code_vip, full_name, dob, phone, bleeter)
        object_key = f"vip_cards/{code_vip}.png"
        url = upload_png_to_bucket(png, object_key)

        # stocker dans sheet (par header)
        vip_update_cell_by_header(row_i, "card_url", url)
        vip_update_cell_by_header(row_i, "card_generated_at", now_iso())
        vip_update_cell_by_header(row_i, "card_generated_by", str(ctx.author.id))

        # envoyer image + url
        file = discord.File(io.BytesIO(png), filename=f"VIP_{code_vip}.png")
        await ctx.send(
            content=catify(f"✅ Carte VIP générée pour **{display_name(full_name)}**\n🔗 {url}", chance=0.18),
            file=file
        )

    except Exception as e:
        await ctx.send(catify(f"❌ Erreur génération carte: `{e}`"))

@bot.command(name="vipbleeter")
@employee_only()
async def vipbleeter(ctx, term: str = None, bleeter_pseudo: str = None):
    # salon staff only (si tu veux garder la règle)
    if STAFF_CHANNEL_ID and ctx.channel.id != int(STAFF_CHANNEL_ID):
        await ctx.send(catify("😾 Modifs VIP uniquement dans le salon staff."))
        return

    if not term or not bleeter_pseudo:
        await ctx.send(catify("❌ Utilisation: `!vipbleeter CODE|PSEUDO pseudo_bleeter`"))
        return

    term = (term or "").strip()
    bleeter_clean = (bleeter_pseudo or "").strip()
    if not bleeter_clean:
        await ctx.send(catify("❌ Utilisation: `!vipbleeter CODE|PSEUDO pseudo_bleeter`"))
        return

    # 1) retrouver VIP par code ou pseudo
    row_i, vip_row = find_vip_row_by_code_or_pseudo(term)
    if not row_i:
        await ctx.send(catify("❌ VIP introuvable (code ou pseudo incorrect)."))
        return

    code_norm = normalize_code(str(vip_row.get("code_vip", "")))
    pseudo = display_name(vip_row.get("pseudo", "VIP"))

    # 2) Update colonne bleeter
    # (IMPORTANT: update en 2D list pour gspread)
    ws_vip.update(values=[[bleeter_clean]], range_name=f"I{row_i}")

    # 3) Log
    ws_log.append_row([
        now_iso(),
        str(ctx.author.id),
        code_norm,
        "SET_BLEETER",
        1,
        0,
        0,
        f"Bleeter set to @{bleeter_clean}"
    ])

    await ctx.send(catify(
        f"✅ Bleeter de **{pseudo}** mis à jour : **@{bleeter_clean}** 🛰️",
        chance=0.25
    ))

@bot.command(name="vipcardshow")
@employee_only()
async def vipcardshow(ctx, *, query: str = ""):
    """
    Usage:
    !vipcardshow SUB-XXXX-XXXX
    !vipcardshow PSEUDO
    """

    # salon staff only
    if STAFF_CHANNEL_ID and ctx.channel.id != int(STAFF_CHANNEL_ID):
        await ctx.send(catify("😾 Les cartes VIP se consultent uniquement dans le salon staff."))
        return

    q = (query or "").strip()
    if not q:
        await ctx.send(catify("❌ Utilisation: `!vipcardshow SUB-XXXX-XXXX` ou `!vipcardshow PSEUDO`"))
        return

    # retrouver VIP
    code_vip = q.strip().upper()
    row_i, vip = (None, None)

    if code_vip.startswith("SUB-"):
        row_i, vip = find_vip_row_by_code(code_vip)
    else:
        row_i, vip = find_vip_row_by_pseudo(q)
        if vip:
            code_vip = str(vip.get("code_vip", "")).strip().upper()

    if not row_i or not vip:
        await ctx.send(catify(f"❌ Aucun VIP trouvé pour **{q}**."))
        return

    pseudo = display_name(vip.get("pseudo", q))
    status = str(vip.get("status", "ACTIVE")).strip().upper()
    badge = "🟢" if status == "ACTIVE" else "🔴"

    object_key = f"vip_cards/{code_vip}.png"

    # URL signée (1h)
    signed = generate_signed_url(object_key, expires_seconds=3600)
    if not signed:
        await ctx.send(catify(mikasa_card_missing_reaction(code_vip), chance=0.35))
        return

    embed = discord.Embed(
        title=f"{badge} Carte VIP de {pseudo}",
        description=f"🎴 Code: `{code_vip}`\n⏳ Lien temporaire (1h): {signed}",
    )
    embed.set_image(url=signed)
    embed.set_footer(text="Mikasa entrouvre la cachette… prrr 🐾")

    await ctx.send(embed=embed)

@bot.command(name="vipsearch")
@employee_only()
async def vipsearch(ctx, *, query: str):
    q = (query or "").strip()
    if not q:
        await ctx.send(catify("❌ Utilisation: `!vipsearch ma` ou `!vipsearch points > 1000` ou `!vipsearch status active`"))
        return

    f = parse_kv_filters(q)

    vips = get_all_vips()  # doit renvoyer dicts avec: code_vip, pseudo, points, niveau, status, bleeter
    results = []

    for r in vips:
        pseudo_raw = str(r.get("pseudo", "")).strip()
        pseudo_disp = display_name(pseudo_raw)

        code = str(r.get("code_vip", "")).strip().upper()
        status = str(r.get("status", "ACTIVE")).strip().upper()
        bleeter = str(r.get("bleeter", "")).strip()

        try:
            pts = int(r.get("points", 0))
        except Exception:
            pts = 0

        try:
            lvl = int(r.get("niveau", 1))
        except Exception:
            lvl = 1

        # filtre code
        if f["code"] and f["code"] != code:
            continue

        # filtre status
        if f["status"]:
            target = "ACTIVE" if f["status"] == "ACTIVE" else "INACTIVE"
            if status != target:
                continue

        # filtre bleeter (contient)
        if f["bleeter"]:
            if f["bleeter"].lower() not in bleeter.lower():
                continue

        # filtre points
        if f["points_op"] and f["points_val"] is not None:
            if not cmp_int(pts, f["points_op"], f["points_val"]):
                continue

        # texte libre (par défaut: match pseudo)
        if f["text"]:
            if f["text"].lower() not in pseudo_raw.lower():
                continue

        badge = "🟢" if status == "ACTIVE" else "🔴"
        btxt = f" • 🛰️ @{bleeter}" if bleeter else ""
        results.append((pts, f"{badge} {pseudo_disp} • Niveau **{lvl}** • **{pts}** pts • `{code}`{btxt}"))

    if not results:
        await ctx.send(catify(f"🔎 Aucun résultat pour **{query}**."))
        return

    # tri par points desc
    results.sort(key=lambda x: x[0], reverse=True)
    lines = [line for _, line in results[:15]]

    header = f"🔎 **Recherche VIP**: `{query}`\n"
    await ctx.send(catify(header + "\n".join(lines), chance=0.18))

@bot.command(name="niveau_top")
@employee_only()
async def niveau_top(ctx, n: int = 10):
    # Limites de sécurité
    try:
        n = int(n)
    except:
        n = 10
    n = max(3, min(n, 25))

    vips = get_all_vips()
    results = []

    for r in vips:
        status = str(r.get("status", "ACTIVE")).strip().upper()
        if status != "ACTIVE":
            continue

        pseudo_raw = str(r.get("pseudo", "")).strip()
        pseudo_display = display_name(pseudo_raw)

        try:
            pts = int(r.get("points", 0))
        except:
            pts = 0

        lvl = r.get("niveau", "?")
        code = str(r.get("code_vip", "—")).strip()

        # Bleeter (optionnel)
        bleeter_raw = str(r.get("bleeter", "")).strip()
        bleeter_display = f" • 🛰️ @{bleeter_raw}" if bleeter_raw else ""

        results.append((pts, pseudo_display, lvl, code, bleeter_display))

    if not results:
        await ctx.send(catify("😾 Aucun VIP actif trouvé."))
        return

    results.sort(key=lambda x: x[0], reverse=True)
    results = results[:n]

    lines = []
    for i, (pts, pseudo_display, lvl, code, bleeter_display) in enumerate(results, start=1):
        medal = "🏆" if i == 1 else ("🥈" if i == 2 else ("🥉" if i == 3 else "🐾"))
        lines.append(f"{medal} **#{i}** {pseudo_display}{bleeter_display} • Niveau **{lvl}** • **{pts}** pts • `{code}`")

    msg = f"🏆 **Top VIP (actifs)** — Top {n}\n" + "\n".join(lines)
    await ctx.send(catify(msg, chance=0.18))

@bot.command(name="vipcreate")
@employee_only()
async def vipcreate(ctx, *, pseudo: str = None):
    """
    Deux usages:
    1) !vipcreate @membre    -> VIP lié au Discord
    2) !vipcreate PSEUDO     -> VIP manuel non lié (pseudo multi-mots OK)
    """

    # --- Salon staff only (optionnel mais conseillé)
    if STAFF_CHANNEL_ID and ctx.channel.id != int(STAFF_CHANNEL_ID):
        await ctx.send(catify("😾 La création VIP se fait uniquement dans le salon staff."))
        return

    # Cas 1: mention
    if ctx.message.mentions:
        member = ctx.message.mentions[0]
        ok, res = create_vip_for_member(member, ctx.author.id)
        if not ok:
            await ctx.send(catify(f"❌ {res}"))
            return

        code = res
        await ctx.send(catify(f"✅ VIP créé pour **{member.display_name}**. Code: `{code}`"))

        try:
            await member.send(catify(
                f"🎟️ Ton code VIP SubUrban: `{code}`\nGarde-le précieusement.",
                chance=0.35
            ))
        except Exception:
            pass
        return

    # Cas 2: pseudo manuel
    pseudo = (pseudo or "").strip()
    pseudo = display_name(pseudo)  # "_" => espaces + jolies majuscules

    if not pseudo:
        await ctx.send(catify("❌ Utilisation: `!vipcreate @membre` ou `!vipcreate PSEUDO`"))
        return

    ok, res = create_vip_manual(pseudo=pseudo, staff_id=ctx.author.id, note="")
    if not ok:
        await ctx.send(catify(f"❌ {res}"))
        return

    code = res
    await ctx.send(catify(f"✅ VIP créé pour **{pseudo}**. Code: `{code}`"))

@bot.command(name="vipcreatenote")
@employee_only()
async def vipcreatenote(ctx, *, content: str = None):
    """
    Usage:
    !vipcreatenote PSEUDO | NOTE
    Exemple:
    !vipcreatenote Mai Mashiro | DN 27/12/2004 - tel en attente
    """

    # --- Salon staff only (optionnel mais conseillé)
    if STAFF_CHANNEL_ID and ctx.channel.id != int(STAFF_CHANNEL_ID):
        await ctx.send(catify("😾 La création VIP (note) se fait uniquement dans le salon staff."))
        return

    content = (content or "").strip()
    if not content or "|" not in content:
        await ctx.send(catify("❌ Utilisation: `!vipcreatenote PSEUDO | NOTE`"))
        return

    left, right = content.split("|", 1)
    pseudo = display_name(left.strip())
    note = right.strip()

    if not pseudo:
        await ctx.send(catify("❌ Pseudo manquant. Exemple: `!vipcreatenote Mai Mashiro | note...`"))
        return
    if not note:
        await ctx.send(catify("❌ Note manquante. Exemple: `!vipcreatenote Mai Mashiro | note...`"))
        return

    ok, res = create_vip_manual(pseudo=pseudo, staff_id=ctx.author.id, note=note)
    if not ok:
        await ctx.send(catify(f"❌ {res}"))
        return

    code = res
    await ctx.send(catify(f"✅ VIP créé pour **{pseudo}**. Code: `{code}` (note enregistrée) 🐾", chance=0.18))


@bot.command(name="viplink")
@employee_only()
async def viplink(ctx, code_vip: str, member: discord.Member):
    code_norm = normalize_code(code_vip)

    row_i, vip_row = find_vip_row_by_code(code_norm)
    if not row_i:
        await ctx.send(catify("❌ Code VIP introuvable."))
        return

    # VIP headers: A code_vip, B discord_id, C pseudo ...
    ws_vip.batch_update([
        {"range": f"B{row_i}", "values": [[str(member.id)]]},
        {"range": f"C{row_i}", "values": [[member.display_name]]},
    ])

    ws_log.append_row([
        now_iso(),
        str(ctx.author.id),
        code_norm,
        "LINK",
        1,
        0,
        0,
        f"Link vers {member.display_name} ({member.id})",
    ])

    await ctx.send(catify(f"🔗 `{code_norm}` lié à {member.mention} ✅"))

@bot.command(name="vip")
@employee_only()
async def vip(ctx, *, raw: str):
    """
    Format attendu:
    !vip CODE ACTION QTE [raison...]
    Ex:
    !vip SUB-AYWZ-EV3I DON_SANG 1
    !vip SUB-AYWZ-EV3I ACHAT 20 Acheté pendant l’event
    """
    raw = (raw or "").strip()
    parts = raw.split()
    
    if len(parts) < 3:
        await ctx.send(catify("❌ Utilisation: `!vip CODE ACTION QTE [raison...]`"))
        return

    code_vip = parts[0]
    action_key = parts[1]

    action_up = action_key.strip().upper()

    # ✅ Employés: uniquement ACHAT + RECYCLAGE
    # ✅ HG: tout
    if not has_hg_role(ctx.author):
        if action_up not in EMPLOYEE_ALLOWED_ACTIONS:
            await ctx.send(catify(
                "😾 Action réservée aux **HG**.\n"
                "✅ Employés autorisés: **ACHAT**, **RECYCLAGE**, **ACHAT_LIMITEE**."
            ))
            return
    
    qty_str = parts[2]
        
   # if action_key.strip().upper() in ["BLEETER", "DEFI_HEBDO", "TOUS_DEFIS_HEBDO"]:
    #    if not has_hg_role(ctx.author):
     #       await ctx.send(catify("😾 Seuls les HG peuvent valider Bleeter et Défis."))
      #      return
            
    raison = " ".join(parts[3:]).strip() if len(parts) > 3 else ""

    # qty safe
    try:
        qty = int(qty_str)
    except ValueError:
        await ctx.send(catify("❌ La quantité doit être un nombre. Exemple: `!vip SUB-XXXX-XXXX DON_SANG 1`"))
        return

    code_norm = normalize_code(code_vip)

    row_i, vip_row = find_vip_row_by_code(code_norm)
    if not row_i:
        await ctx.send(catify("❌ Code VIP introuvable."))
        return

    pseudo = str(vip_row.get("pseudo", "Quelqu’un"))
    author_is_hg = has_hg_role(ctx.author)

    ok, res = add_points_by_action(code_norm, action_key, qty, ctx.author.id, raison, author_is_hg=author_is_hg)
    if not ok:
        await ctx.send(catify(f"❌ {res}"))
        return

    # nouveau retour: (delta, new_points, old_level, new_level)
    delta, new_points, old_level, new_level = res

    rp_msg = format_action_message(action_key, pseudo, qty, delta, raison)

    await ctx.send(
        rp_msg
        + f"\n➡️ Code: `{code_norm}` | Total: **{new_points}** | Niveau: **{new_level}**"
    )

    # annonce level up auto
    if new_level > old_level:
        try:
            await announce_level_up_async(code_norm, pseudo, old_level, new_level)
        except Exception:
            pass


@bot.command(name="vipactions")
@employee_only()
async def vipactions(ctx):
    actions = get_actions_map()
    if not actions:
        await ctx.send(catify("Aucune action trouvée dans l'onglet ACTIONS."))
        return

    is_hg = has_hg_role(ctx.author)

    lines = []
    for k in sorted(actions.keys()):
        # Employés : uniquement ACHAT + RECYCLAGE
        if not is_hg and k not in EMPLOYEE_ALLOWED_ACTIONS:
            continue

        pu = actions[k]["points_unite"]
        lim = actions[k]["limite"]

        if lim:
            lines.append(f"• **{k}**: {pu} pts/unité _(limite: {lim})_")
        else:
            lines.append(f"• **{k}**: {pu} pts/unité")

    if not lines:
        await ctx.send(catify("😾 Aucune action accessible avec ton grade."))
        return

    msg = "📋 **Actions disponibles:**\n" + "\n".join(lines[:40])
    await ctx.send(catify(msg, chance=0.12))



@bot.command(name="vipstats")
@employee_only()
async def vipstats(ctx):
    vips = get_all_vips()
    if not vips:
        await ctx.send(catify("Aucun VIP enregistré."))
        return

    active = []
    inactive = 0
    total_points = 0

    top_vip = None  # (points, pseudo, code, niveau)

    for r in vips:
        status = str(r.get("status", "ACTIVE")).strip().upper()
        try:
            pts = int(r.get("points", 0))
        except:
            pts = 0

        if status == "ACTIVE":
            active.append(r)
            total_points += pts

            pseudo = str(r.get("pseudo", "—"))
            code = str(r.get("code_vip", "—"))
            niveau = r.get("niveau", "?")
            if top_vip is None or pts > top_vip[0]:
                top_vip = (pts, pseudo, code, niveau)
        else:
            inactive += 1

    count_active = len(active)
    count_total = len(vips)
    avg_points = int(total_points / count_active) if count_active > 0 else 0

    if top_vip:
        top_line = f"🏆 Top: **{top_vip[1]}** (Niv {top_vip[3]}) • **{top_vip[0]}** pts • `{top_vip[2]}`"
    else:
        top_line = "🏆 Top: —"

    msg = (
        "📈 **Stats VIP SubUrban**\n"
        f"• VIP totaux: **{count_total}**\n"
        f"• Actifs: **{count_active}** | Inactifs: **{inactive}**\n"
        f"• Points totaux (actifs): **{total_points}**\n"
        f"• Moyenne points (actifs): **{avg_points}**\n"
        f"{top_line}"
    )

    await ctx.send(catify(msg, chance=0.18))



    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        try:
            if hasattr(self, "message") and self.message:
                emb = self.message.embeds[0] if self.message.embeds else None
                if emb:
                    emb.set_footer(text="Menu expiré • Relance `!defi CODE` 🐾")
                    await self.message.edit(embed=emb, view=self)
                else:
                    await self.message.edit(view=self)
        except Exception:
            pass



# =========================
# COMMANDE !defi (HG only) : ouvre le bon panneau selon semaine
# =========================

@bot.command(name="defi")
async def defi(ctx, code_vip: str = None):
    """
    HG only
    Usage: !defi SUB-XXXX-XXXX
    Ouvre un panneau interactif:
    - Semaines 1..11: 4 toggles (tampon, pas gomme)
    - Semaine 12: 12 choix, max 4, puis commit en remplissant d1..d4
    """
    if not has_hg_role(ctx.author):
        await ctx.send(catify("😾 Seuls les HG peuvent valider les défis."))
        return

    if not code_vip:
        await ctx.send(catify("❌ Utilisation: `!defi SUB-XXXX-XXXX`"))
        return

    code = normalize_code(code_vip)

    # fenêtre semaine actuelle
    wk_start, wk_end, wk = get_week_window()  # (start, end, wk)
    if wk == 0 or not wk_start or not wk_end:
        await ctx.send(catify("😺 Les défis ne sont pas encore lancés."))
        return

    now_dt = now_fr()
    if not (wk_start <= now_dt < wk_end):
        await ctx.send(catify(
            f"⛔ Hors fenêtre défis.\n"
            f"🗓️ Fenêtre actuelle: **{wk_start.strftime('%d/%m %H:%M')} → {wk_end.strftime('%d/%m %H:%M')}** (FR)"
        ))
        return

    #wk_key = week_key_for(wk, wk_start)
    wk_key = week_key_for(wk)
    wk_label = week_label_for(wk)

    # VIP existe ?
    row_vip_i, vip = find_vip_row_by_code(code)
    if not row_vip_i:
        await ctx.send(catify("❌ Code VIP introuvable."))
        return

    pseudo = display_name(vip.get("pseudo", "Quelqu’un"))

    # DEFIS row
    row_i, row = ensure_defis_row(code, wk_key, wk_label)

    # semaine 12 special
    if wk == 12:
        choices = get_week_tasks_for_view(12)  # 12 items
        view = DefiWeek12View(
            author=ctx.author,
            code=code,
            wk=wk,
            wk_key=wk_key,
            wk_label=wk_label,
            row_i=row_i,
            row=row,
            choices=choices,
            vip_pseudo=pseudo
        )
        emb = view._build_embed()
        msg = await ctx.send(embed=emb, view=view)
        view.message = msg
        return

    # semaine 1..11 standard 4 défis
    tasks = get_week_tasks_for_view(wk)  # 4 items
    view = DefiValidateView(
        author=ctx.author,
        code=code,
        wk=wk,
        wk_key=wk_key,
        wk_label=wk_label,
        row_i=row_i,
        row=row,
        tasks=tasks,
        vip_pseudo=pseudo
    )
    emb = view._build_embed()
    msg = await ctx.send(embed=emb, view=view)
    view.message = msg

@bot.command(name="defi_old")
async def defi(ctx, code_vip: str = None, defi_num: str = None, *, note: str = ""):
    # =============================
    # HG ONLY
    # =============================
    if not has_hg_role(ctx.author):
        await ctx.send(catify("😾 Seuls les HG peuvent valider les défis."))
        return

    if not code_vip or not defi_num:
        await ctx.send(catify("❌ Utilisation: `!defi CODE 1 [note...]` (1 à 4)"))
        return

    code = normalize_code(code_vip)

    try:
        n = int(defi_num)
    except ValueError:
        await ctx.send(catify("❌ Le numéro doit être 1, 2, 3 ou 4."))
        return

    if n < 1 or n > 4:
        await ctx.send(catify("❌ Le numéro doit être 1, 2, 3 ou 4."))
        return

    # =============================
    # FENÊTRE DE TEMPS
    # =============================
    wk_start, wk_end, wk = get_current_week_window()
    if wk == 0:
        await ctx.send(catify("😺 Les défis ne sont pas encore lancés."))
        return
    
    now_dt = now_fr()
    if not (wk_start <= now_dt < wk_end):
        await ctx.send(catify(
            f"⛔ Hors fenêtre défis.\n"
            f"🗓️ Fenêtre actuelle: **{fmt_fr(wk_start)} → {fmt_fr(wk_end - timedelta(minutes=1))}** (FR)"
        ))
        return


    wk_key = week_key_for(wk)
    wk_label = week_label_for(wk)

    # =============================
    # VIP EXISTE ?
    # =============================
    row_vip_i, vip = find_vip_row_by_code(code)
    if not row_vip_i:
        await ctx.send(catify("❌ Code VIP introuvable."))
        return

    pseudo = display_name(vip.get("pseudo", "Quelqu’un"))

    # =============================
    # DEFIS ROW (GET / CREATE)
    # =============================
    row_i, row = ensure_defis_row(code, wk_key, wk_label)

    done_before = defis_done_count(row)

    # déjà fait ?
    if is_defi_done(row, n):
        await ctx.send(catify(
            f"😼 Défi **{n}** déjà validé pour **{pseudo}** cette semaine."
        ))
        return

    # =============================
    # ÉCRITURE DU DÉFI
    # =============================
    stamp = now_dt.strftime("%Y-%m-%d %H:%M:%S")
    col_letter = chr(ord("C") + (n - 1))  # C..F → d1..d4

    ws_defis.update(f"{col_letter}{row_i}", [[stamp]])

    # reload row après écriture
    row_i2, row2 = get_defis_row(code, wk_key)
    done_after = defis_done_count(row2)

    # =============================
    # NOTE OPTIONNELLE
    # =============================
    if note.strip():
        old_note = str(row2.get("d_notes", "")).strip()
        merged = (old_note + " | " if old_note else "") + f"d{n}:{note.strip()}"
        ws_defis.update(f"I{row_i2}", [[merged]])

    # =============================
    # POINTS — SEULEMENT LE 1ER DÉFI
    # =============================
    awarded = False
    if done_before == 0:
        add_points_by_action(
            code,
            "BLEETER",
            1,
            ctx.author.id,
            f"1er défi validé ({wk_key})",
            author_is_hg=True
        )
        add_points_by_action(
            code,
            "DEFI_HEBDO",
            1,
            ctx.author.id,
            f"1er défi validé ({wk_key})",
            author_is_hg=True
        )
        awarded = True

    if awarded:
        award_line = "🎁 Récompense: **+5** (Bleeter) + **+30** (Défi)."
    else:
        award_line = "🧾 Défi noté. (Récompense déjà prise cette semaine 😼)"

    # =============================
    # MESSAGE CONFIRMATION
    # =============================
    await ctx.send(catify(
        f"✅ Défi **{n}** validé pour **{pseudo}** ({wk_label}).\n"
        f"{award_line}\n"
        f"📸 Progression: **{done_after}/4** défis validés cette semaine. 🐾",
        chance=0.12
    ))

    # =============================
    # BONUS 4/4 + ANNONCE
    # =============================
    if done_after >= 4 and str(row2.get("completed_at", "")).strip() == "":
        comp_stamp = now_fr().strftime("%Y-%m-%d %H:%M:%S")

        ws_defis.batch_update([
            {"range": f"G{row_i2}", "values": [[comp_stamp]]},          # completed_at
            {"range": f"H{row_i2}", "values": [[str(ctx.author.id)]]},  # completed_by
        ])

        add_points_by_action(
            code,
            "TOUS_DEFIS_HEBDO",
            1,
            ctx.author.id,
            f"4/4 défis complétés ({wk_key})",
            author_is_hg=True
        )

        if ANNOUNCE_CHANNEL_ID:
            ch = bot.get_channel(ANNOUNCE_CHANNEL_ID)
            if ch:
                await ch.send(catify(
                    f"🎉 **{pseudo}** vient de terminer les **4 défis** de la {wk_label} !\n"
                    f"😼 Mikasa valide le carnet VIP. **BONUS ACCORDÉ** 🐾",
                    chance=0.10
                ))


@bot.command(name="defistatus")
async def defistatus(ctx, code_vip: str = None):
    """
    - !defistatus           -> VIP (public) voit ses défis de la semaine
    - !defistatus CODE      -> employé/HG peut checker un VIP
    """

    # 1) déterminer le code
    if code_vip:
        if not has_employee_role(ctx.author) and not has_hg_role(ctx.author):
            await ctx.send(catify("⛔ Réservé aux employés/HG pour consulter un autre VIP."))
            return
        code = normalize_code(code_vip)
    else:
        if not await anti_spam_vip(ctx, "defistatus_public"):
            return

        row_i, vip = find_vip_row_by_discord_id(ctx.author.id)

        if not row_i:
            await ctx.send(catify("❌ Aucun VIP lié à ton Discord."))
            return
        code = normalize_code(str(vip.get("code_vip", "")))

    # 2) semaine actuelle
    wk_start, wk_end, wk = get_week_window()
    if wk == 0:
        await ctx.send(catify("😺 Les défis ne sont pas encore lancés."))
        return

    wk_key = week_key_for(wk)         # ✅ 1 seul argument
    wk_label = week_label_for(wk)

    # 3) récupérer la ligne DEFIS (sans créer si tu veux “lecture only”, mais ici on peut créer)
    row_i, row = ensure_defis_row(code, wk_key, wk_label)

    # 4) afficher 1..4
    tasks = WEEKLY_CHALLENGES.get(wk, [])
    done = 0
    lines = []

    if wk == 12:
        # semaine 12 on simplifie
        done = defis_done_count(row)
        lines.append("🎭 **Semaine 12 (Freestyle)**")
        lines.append(f"➡️ Progression: **{done}/4**")
    else:
        for i in range(1, 5):
            stamp = str(row.get(f"d{i}", "")).strip()
            ok = bool(stamp)
            if ok:
                done += 1
            label = tasks[i-1] if len(tasks) >= i else f"Défi {i}"
            icon = "✅" if ok else "❌"
            lines.append(f"{icon} **{label}**")

        lines.append(f"\n➡️ Progression: **{done}/4**")

    await ctx.send(catify(
        f"📸 **Défis de la semaine ({wk_label})**\n" + "\n".join(lines),
        chance=0.12
    ))

@bot.command(name="defitop")
async def defitop(ctx, n: str = "10"):
    if not (has_employee_role(ctx.author) or has_hg_role(ctx.author)):
        await ctx.send(catify("⛔ Réservé staff (employés/HG)."))
        return

    try:
        limit = max(3, min(25, int(n)))
    except:
        limit = 10

    start, end, wk = get_current_week_window()
    if wk == 0:
        await ctx.send(catify("😺 Les défis ne sont pas encore lancés."))
        return
    
    wk_key = week_key_for(wk)
    wk_label = week_label_for(wk)

    rows = ws_defis.get_all_records()
    pack = []
    for r in rows:
        if str(r.get("week_key", "")).strip() != wk_key:
            continue
        code = str(r.get("code_vip", "")).strip().upper()
        if not code:
            continue

        done = defis_done_count(r)
        completed_at = str(r.get("completed_at", "")).strip()  # vide si pas fini

        # récup pseudo depuis VIP sheet
        _, vip = find_vip_row_by_code(code)
        pseudo = display_name(vip.get("pseudo", code)) if vip else code

        pack.append((done, completed_at, pseudo, code))

    if not pack:
        await ctx.send(catify("📭 Aucun défi enregistré pour cette semaine."))
        return

    # tri: d'abord le + de défis, puis ceux qui finissent en premier, sinon pseudo
    pack.sort(key=lambda x: (-x[0], x[1] or "9999", x[2].lower()))
    pack = pack[:limit]

    lines = []
    for i, (done, comp, pseudo, code) in enumerate(pack, start=1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "🏁"
        lines.append(f"{medal} **#{i}** {pseudo} — **{done}/4** (`{code}`)")

    await ctx.send(catify(
        f"🏆 **Classement Défis** — {wk_label}\n" + "\n".join(lines),
        chance=0.12
    ))


@bot.command(name="defiweek")
async def defiweek(ctx):
    if not has_hg_role(ctx.author):
        await ctx.send(catify("😾 Seuls les HG peuvent annoncer les défis de la semaine."))
        return

    if not ANNOUNCE_CHANNEL_ID:
        await ctx.send(catify("⚠️ `ANNOUNCE_CHANNEL_ID` n'est pas configuré."))
        return

    start, end, wk = get_current_week_window()
    if wk == 0:
        await ctx.send(catify(
            "😺 Les défis VIP ne sont pas encore lancés.\n"
            "Rendez-vous le **02/01 à 17:00** (heure FR)."
        ))
        return

    tasks = WEEKLY_CHALLENGES.get(wk, [])
    title = f"📸 Défis VIP SubUrban, en tenue complète SubUrban #DEFISUBURBAN | Semaine {wk}/12"

    lines = []
    if wk == 12:
        lines.append("🎭 **SEMAINE FINALE – FREESTYLE**")
        lines.append("Les clients choisissent **4 défis au choix** parmi :")
        if not tasks:
            lines.append("• (Aucun défi configuré pour la semaine 12)")
        else:
            for t in tasks:
                lines.append(f"• {t}")
    else:
        if not tasks:
            lines.append("⚠️ Aucun défi configuré pour cette semaine.")
        else:
            lines.append("Voici les **4 défis** à valider cette semaine :")
            for i, t in enumerate(tasks, start=1):
                lines.append(f"**{i}.** {t}")

    lines.append("")
    lines.append(f"🗓️ Période: **{fmt_fr(start)} → {fmt_fr(end - timedelta(minutes=1))}** (heure FR)")
    lines.append("✅ Validation des défis: **HG uniquement**")
    lines.append("😼 Mikasa surveille… et garde les meilleurs clichés dans son album. 🐾")

    msg = f"**{title}**\n" + "\n".join(lines)

    ch = bot.get_channel(int(ANNOUNCE_CHANNEL_ID))
    if not ch:
        await ctx.send(catify("❌ Impossible de trouver le salon d'annonce. Vérifie `ANNOUNCE_CHANNEL_ID`."))
        return

    await ch.send(catify(msg, chance=0.12))
    await ctx.send(catify("✅ Annonce postée. Mikasa ronronne fièrement. prrr 🐾", chance=0.15))

@bot.command(name="vipforce")
async def vipforce(ctx, code_vip: str, action_key: str, qty: int, *, reason: str = ""):
    if not has_hg_role(ctx.author):
        await ctx.send(catify("😾 Seuls les HG peuvent forcer une validation."))
        return
    if STAFF_CHANNEL_ID and ctx.channel.id != int(STAFF_CHANNEL_ID):
        await ctx.send(catify("😾 Uniquement dans le salon staff."))
        return

    reason = (reason or "").strip()
    if not reason:
        reason = "HG_FORCE"

    ok, res = add_points_by_action(code_vip.strip().upper(), action_key.strip().upper(), qty, ctx.author.id, reason, author_is_hg=True)
    if not ok:
        await ctx.send(catify(f"❌ {res}"))
        return
    await ctx.send(catify(f"✅ Forcé (HG). {res}", chance=0.18))

@bot.command(name="cave")
@hg_only()
async def cave(ctx, action: str = None, *, rest: str = ""):
    """
    HG only.
    Usages:
    - !cave
    - !cave add PSEUDO | alias1, alias2
    - !cave remove TERME (pseudo_ref ou alias)
    """

    action = (action or "").strip().lower()
    rest = (rest or "").strip()

    # =========================
    # RÉACTIONS MIKASA
    # =========================
    ADD_REACTIONS = [
        "😾 *Hssss…*",
        "🐾 **Le carnet VIP se referme d’un coup sec.**",
        "🕯️ **La cave de Mikasa accueille un nouveau nom.**",
        "😼 **Un coup de patte efface le nom.**",
        "🐱 **Le silence retombe. Le nom est scellé.**",
    ]

    REMOVE_REACTIONS = [
        "🐱 *Hmm…*",
        "🐾 **La porte grince lentement.**",
        "😼 **Mikasa raye le nom avec prudence.**",
        "🕯️ **La chaîne est retirée, mais le regard reste vigilant.**",
        "🐱 **Une chance de plus. Pas une promesse.**",
    ]

    REPEAT_REACTIONS = [
        "😾 *Tsssk…*",
        "🐱 **Le carnet ne s’ouvre même pas.**",
        "🐾 **La décision est ancienne. Et définitive.**",
        "🕯️ **La cave n’a pas besoin de doublons.**",
        "😼 **Mikasa ne répète pas ses décisions.**",
    ]

    # =========================
    # 1) LISTE
    # =========================
    if not action:
        rows = ws_ban_create.get_all_records()
        if not rows:
            await ctx.send(catify("🐱 La cave de Mikasa est vide… pour l’instant.", chance=0.35))
            return

        lines = []
        for r in rows:
            pseudo_ref_raw = str(r.get("pseudo_ref", "")).strip()
            if not pseudo_ref_raw:
                continue

            aliases_raw = r.get("aliases", "")
            aliases_list_norm = split_aliases(aliases_raw)  # retourne des alias normalisés
            aliases_display = ", ".join(display_name(a) for a in aliases_list_norm) if aliases_list_norm else ""

            pseudo_display = display_name(pseudo_ref_raw)

            if aliases_display:
                lines.append(f"🔒 **{pseudo_display}** _(alias: {aliases_display})_")
            else:
                lines.append(f"🔒 **{pseudo_display}**")

        await ctx.send(catify("🕯️ **La cave de Mikasa**", chance=0.30) + "\n" + "\n".join(lines))
        return

    # =========================
    # 2) ADD
    # =========================
    if action == "add":
        if not rest:
            await ctx.send(catify("❌ Utilisation: `!cave add PSEUDO | alias1, alias2`"))
            return
    
        if "|" in rest:
            pseudo_ref_raw, aliases_raw = rest.split("|", 1)
        else:
            pseudo_ref_raw, aliases_raw = rest, ""
    
        pseudo_ref_raw = pseudo_ref_raw.strip()
        aliases_raw = aliases_raw.strip()
    
        if not pseudo_ref_raw:
            await ctx.send(catify("❌ Il me faut au moins un pseudo."))
            return
    
        pseudo_norm = normalize_name(pseudo_ref_raw)
        aliases_list_norm = split_aliases(aliases_raw)
    
        # 🔍 Vérification doublon (PAS d'append ici)
        rows = ws_ban_create.get_all_records()
        for r in rows:
            existing_pseudo = normalize_name(r.get("pseudo_ref", ""))
            existing_aliases = split_aliases(r.get("aliases", ""))
    
            if pseudo_norm == existing_pseudo or pseudo_norm in existing_aliases:
                await ctx.send(catify("😾 Ce nom est déjà dans la cave."))
                return
    
        # ✅ Append UNE SEULE FOIS (hors boucle)
        ws_ban_create.append_row([
            pseudo_ref_raw,
            ", ".join(aliases_list_norm),
            "",                    # discord_id
            "BAN_CREATE",
            str(ctx.author.id),
            now_iso(),
            ""
        ])
    
        await ctx.send(catify(
            f"🔒 **{display_name(pseudo_ref_raw)}** est enfermé dans la cave de Mikasa.",
            chance=0.4
        ))
        return

            
    # =========================
    # 3) REMOVE (par pseudo OU alias)
    # =========================
    if action == "remove":
        if not rest:
            await ctx.send(catify("❌ Utilisation: `!cave remove PSEUDO|ALIAS`"))
            return

        term_norm = normalize_name(rest)

        values = ws_ban_create.get_all_values()
        if not values or len(values) < 2:
            await ctx.send(catify("🐾 Rien à libérer… la cave est vide."))
            return

        header = [h.strip() for h in values[0]]
        data = values[1:]

        if "pseudo_ref" not in header:
            await ctx.send(catify("❌ Colonne `pseudo_ref` introuvable dans VIP_BAN_CREATE."))
            return

        col_pseudo = header.index("pseudo_ref")
        col_aliases = header.index("aliases") if "aliases" in header else None

        for idx, row in enumerate(data, start=2):  # start=2 car ligne 1 = header
            pseudo_ref_raw = row[col_pseudo] if col_pseudo < len(row) else ""
            pseudo_ref_norm = normalize_name(pseudo_ref_raw)

            aliases_norm = []
            if col_aliases is not None and col_aliases < len(row):
                aliases_norm = split_aliases(row[col_aliases])

            if term_norm == pseudo_ref_norm or (aliases_norm and term_norm in aliases_norm):
                ws_ban_create.delete_rows(idx)

                await ctx.send(catify(
                    f"🔓 **{display_name(pseudo_ref_raw)}** est retiré de la cave.\n"
                    + random.choice(REMOVE_REACTIONS),
                    chance=0.45
                ))
                return

        await ctx.send(catify("😾 **Mikasa ne trouve aucun nom correspondant dans la cave.**"))
        return
    # =========================
    # 4) INFO (par pseudo OU alias)
    # =========================
    if action == "info":
        if not rest:
            await ctx.send(catify("❌ Utilisation: `!cave info PSEUDO|ALIAS`"))
            return

        term_norm = normalize_name(rest)

        rows = ws_ban_create.get_all_records()
        for r in rows:
            pseudo_ref_raw = str(r.get("pseudo_ref", "")).strip()
            pseudo_ref_norm = normalize_name(pseudo_ref_raw)

            aliases_norm = split_aliases(r.get("aliases", ""))  # déjà normalisés via normalize_name()
            if term_norm == pseudo_ref_norm or (aliases_norm and term_norm in aliases_norm):
                # Champs
                reason = str(r.get("reason", "—")).strip() or "—"
                added_by = str(r.get("added_by", "—")).strip() or "—"
                added_at = str(r.get("added_at", "—")).strip() or "—"
                notes = str(r.get("notes", "—")).strip() or "—"
                discord_id = str(r.get("discord_id", "—")).strip() or "—"

                # joli affichage
                pseudo_display = display_name(pseudo_ref_raw)
                aliases_display = ", ".join(display_name(a) for a in aliases_norm) if aliases_norm else "—"

                # mention staff si possible
                staff_mention = f"<@{added_by}>" if added_by.isdigit() else added_by

                msg = (
                    f"🕯️ **Dossier cave Mikasa**\n"
                    f"🔒 Nom: **{pseudo_display}**\n"
                    f"🏷️ Alias: {aliases_display}\n"
                    f"📌 Reason: `{reason}`\n"
                    f"👤 Ajouté par: {staff_mention}\n"
                    f"📅 Ajouté le: `{added_at}`\n"
                    f"🪪 discord_id (si renseigné): `{discord_id}`\n"
                    f"📝 Notes: {notes}"
                )
                await ctx.send(catify(msg, chance=0.25))
                return

        await ctx.send(catify("😾 Aucun dossier trouvé dans la cave pour ce terme."))
        return

    await ctx.send(catify("❌ Action inconnue. Utilise `!cave`, `!cave add`, ou `!cave remove`."))

# ============================================================
# 11) Run
# ============================================================
bot.run(DISCORD_TOKEN)
