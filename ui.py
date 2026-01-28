# ui.py
# -*- coding: utf-8 -*-

from __future__ import annotations
from typing import Dict, List, Tuple, Optional

import discord
from discord import ui

import domain
from services import (
    catify,
    now_fr,
    now_iso,
    normalize_code,
    display_name,
    extract_tag,
    challenge_week_window,
)

import asyncio

# ==========================================================
# Constantes
# ==========================================================
LETTERS = ["A", "B", "C", "D"]

# ---------------------------------------
# Catégories (si tu veux aussi les exposer depuis ui)
# ---------------------------------------
CATEGORIES: List[Tuple[str, str]] = [
    ("Haut", "TSHIRT/HOODIES"),
    ("Bas", "PANTS"),
    ("Chaussures", "SHOES"),
    ("Masque", "MASKS"),
    ("Accessoire", "ACCESSORY"),
    ("Autre", "OTHER"),
]


def _sale_cat(cat: str) -> str:
    """Normalise la catégorie pour le tag vente: (évite '/' etc)."""
    return (cat or "").replace("/", "_").strip().upper()


# ---------------------------------------
# Panier de vente multi-catégories
# ---------------------------------------
class SaleCartView(ui.View):
    """
    Fenêtre "panier" pour une vente:
    - stockage des quantités par catégorie
    - on peut changer de catégorie, revenir, corriger
    - on valide une seule fois à la fin
    """
    def __init__(
        self,
        *,
        author_id: int,
        categories: List[Tuple[str, str]],
        services,
        code_vip: str,
        vip_pseudo: str,
        author_is_hg: bool,
    ):
        super().__init__(timeout=15 * 60)

        self.author_id = int(author_id)
        self.categories = categories
        self.services = services

        self.code_vip = normalize_code(code_vip)
        self.vip_pseudo = display_name(vip_pseudo or self.code_vip)
        self.author_is_hg = bool(author_is_hg)

        # cart: {category_value: {"normal": int, "limitee": int}}
        self.cart: Dict[str, Dict[str, int]] = {}
        self.current_category: str = categories[0][1] if categories else "OTHER"
        self.note: str = ""

        # UI
        self.add_item(SaleCategorySelect(self))
        self._add_controls()

    # --------- checks ---------
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                catify("😾 Pas touche. Ouvre ta propre fenêtre de vente."),
                ephemeral=True
            )
            return False
        return True

    # --------- state helpers ---------
    def ensure_category(self) -> None:
        if self.current_category not in self.cart:
            self.cart[self.current_category] = {"normal": 0, "limitee": 0}

    def bump(self, field: str, delta: int) -> None:
        self.ensure_category()
        v = self.cart[self.current_category]
        v[field] = max(0, int(v.get(field, 0)) + int(delta))

    def total_lines(self) -> List[str]:
        lines: List[str] = []
        for cat, v in self.cart.items():
            n = int(v.get("normal", 0))
            l = int(v.get("limitee", 0))
            if n > 0 or l > 0:
                lines.append(f"• `{cat}` → Normal **{n}** | Limitée **{l}**")
        return lines

    # --------- render ---------
    def build_embed(self) -> discord.Embed:
        self.ensure_category()
        c = self.cart[self.current_category]

        emb = discord.Embed(
            title="🧾 Fenêtre de vente SubUrban",
            description=(
                f"👤 **Vendeur** : <@{self.author_id}>\n"
                f"🧍 **Client VIP** : **{self.vip_pseudo}** (`{self.code_vip}`)\n"
                f"🏷️ **Catégorie** : `{self.current_category}`\n\n"
                f"🛍️ **Catégorie actuelle**\n"
                f"• ACHAT (normal) : **{c['normal']}**\n"
                f"• ACHAT_LIMITEE : **{c['limitee']}**\n"
            ),
            color=discord.Color.blurple()
        )

        lines = self.total_lines()
        emb.add_field(name="🛒 Panier total", value=("\n".join(lines) if lines else "*Vide*"), inline=False)
        emb.add_field(name="📝 Note", value=(self.note or "*Aucune*"), inline=False)
        emb.set_footer(text="Astuce: change de catégorie et reviens corriger avant de valider.")
        return emb

    async def refresh(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    def _add_controls(self) -> None:
        self.add_item(SaleAdjustButton("➕ Normal", "normal", +1, self))
        self.add_item(SaleAdjustButton("➖ Normal", "normal", -1, self))
        self.add_item(SaleAdjustButton("➕ Limitée", "limitee", +1, self))
        self.add_item(SaleAdjustButton("➖ Limitée", "limitee", -1, self))
        self.add_item(SaleNoteButton(self))
        self.add_item(SaleValidateButton(self))

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        # Optionnel: on pourrait éditer le message ici si on gardait une ref au message.


# ---------------------------------------
# Select catégorie
# ---------------------------------------
class SaleCategorySelect(ui.Select):
    def __init__(self, view: SaleCartView):
        options = [discord.SelectOption(label=label, value=value) for label, value in view.categories]
        super().__init__(
            placeholder="Choisir une catégorie d’articles...",
            options=options,
            min_values=1,
            max_values=1
        )
        self.sale_view = view

    async def callback(self, interaction: discord.Interaction):
        self.sale_view.current_category = self.values[0]
        self.sale_view.ensure_category()
        await self.sale_view.refresh(interaction)


# ---------------------------------------
# Boutons + / -
# ---------------------------------------
class SaleAdjustButton(ui.Button):
    def __init__(self, label: str, field: str, delta: int, view: SaleCartView):
        super().__init__(label=label, style=discord.ButtonStyle.secondary)
        self.field = field
        self.delta = int(delta)
        self.sale_view = view

    async def callback(self, interaction: discord.Interaction):
        self.sale_view.bump(self.field, self.delta)
        await self.sale_view.refresh(interaction)


# ---------------------------------------
# Note modal
# ---------------------------------------
class SaleNoteButton(ui.Button):
    def __init__(self, view: SaleCartView):
        super().__init__(label="📝 Note", style=discord.ButtonStyle.primary)
        self.sale_view = view

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(SaleNoteModal(self.sale_view))


class SaleNoteModal(ui.Modal, title="Note de vente"):
    note = ui.TextInput(label="Note (optionnel)", required=False, max_length=200)

    def __init__(self, view: SaleCartView):
        super().__init__()
        self.sale_view = view

    async def on_submit(self, interaction: discord.Interaction):
        self.sale_view.note = (self.note.value or "").strip()
        await interaction.response.edit_message(embed=self.sale_view.build_embed(), view=self.sale_view)


# ---------------------------------------
# Valider: écrit en Sheets via domain.add_points_by_action
# ---------------------------------------
class SaleValidateButton(ui.Button):
    def __init__(self, view: SaleCartView):
        super().__init__(label="✅ VALIDER", style=discord.ButtonStyle.success)
        self.sale_view = view

    async def callback(self, interaction: discord.Interaction):
        # évite le double-clic
        await interaction.response.defer(ephemeral=True)

        errors: List[str] = []
        applied: List[str] = []

        for cat, v in self.sale_view.cart.items():
            n = int(v.get("normal", 0))
            l = int(v.get("limitee", 0))
            if n <= 0 and l <= 0:
                continue

            base_reason = f"vente:{_sale_cat(cat)}"
            if self.sale_view.note:
                base_reason += f" | note:{self.sale_view.note}"

            if n > 0:
                ok, res = domain.add_points_by_action(
                    self.sale_view.services,
                    self.sale_view.code_vip,
                    "ACHAT",
                    n,
                    interaction.user.id,
                    base_reason,
                    author_is_hg=self.sale_view.author_is_hg
                )
                if ok:
                    delta, new_points, old_level, new_level = res
                    applied.append(f"`{cat}` ACHAT x{n} (**+{delta} pts**, total {new_points})")
                else:
                    errors.append(f"`{cat}` ACHAT: {res}")

            if l > 0:
                ok, res = domain.add_points_by_action(
                    self.sale_view.services,
                    self.sale_view.code_vip,
                    "ACHAT_LIMITEE",
                    l,
                    interaction.user.id,
                    base_reason,
                    author_is_hg=self.sale_view.author_is_hg
                )
                if ok:
                    delta, new_points, old_level, new_level = res
                    applied.append(f"`{cat}` LIMITEE x{l} (**+{delta} pts**, total {new_points})")
                else:
                    errors.append(f"`{cat}` LIMITEE: {res}")

        if not applied and errors:
            return await interaction.followup.send(
                "❌ Vente non enregistrée:\n" + "\n".join(errors),
                ephemeral=True
            )

        for item in self.sale_view.children:
            item.disabled = True

        try:
            await interaction.message.edit(embed=None, view=self.sale_view)
        except Exception:
            pass

        receipt = "✅ **Vente enregistrée**\n" + ("\n".join(applied) if applied else "")
        if errors:
            receipt += "\n\n⚠️ **Erreurs partielles**\n" + "\n".join(errors)

        await interaction.followup.send(receipt, ephemeral=True)


# ==========================================================
# VIP UI (public)
# ==========================================================
class VipHubView(discord.ui.View):
    def __init__(self, *, services, code_vip: str, vip_pseudo: str):
        super().__init__(timeout=5 * 60)
        self.s = services
        self.code = normalize_code(code_vip)
        self.vip_pseudo = display_name(vip_pseudo or self.code)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True

    def hub_embed(self) -> discord.Embed:
        e = discord.Embed(
            title="🎟️ Espace VIP SubUrban",
            description=(
                f"👤 **{self.vip_pseudo}** • `{self.code}`\n\n"
                "Choisis ce que tu veux voir :"
            ),
            color=discord.Color.dark_purple()
        )
        e.add_field(name="📈 Niveau", value="Voir ton niveau, tes points, tes avantages.", inline=False)
        e.add_field(name="📸 Défis", value="Voir ton avancement des défis de la semaine.", inline=False)
        e.set_footer(text="Mikasa ouvre le carnet VIP. 🐾")
        return e

    @discord.ui.button(label="📈 Niveau", style=discord.ButtonStyle.primary)
    async def btn_level(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("❌ Impossible ici.", ephemeral=True)

        row_i, vip = domain.find_vip_row_by_discord_id(self.s, interaction.user.id)
        if not row_i or not vip:
            return await interaction.response.send_message("😾 Ton profil VIP n’est pas lié à ton Discord.", ephemeral=True)

        code = normalize_code(str(vip.get("code_vip", "")))
        if code != self.code:
            return await interaction.response.send_message("😾 Ce panneau ne correspond pas à ton VIP.", ephemeral=True)

        emb = build_vip_level_embed(self.s, vip)
        await interaction.response.send_message(embed=emb, ephemeral=True)

    @discord.ui.button(label="📸 Défis", style=discord.ButtonStyle.secondary)
    async def btn_defis(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("❌ Impossible ici.", ephemeral=True)

        row_i, vip = domain.find_vip_row_by_discord_id(self.s, interaction.user.id)
        if not row_i or not vip:
            return await interaction.response.send_message("😾 Ton profil VIP n’est pas lié à ton Discord.", ephemeral=True)

        code = normalize_code(str(vip.get("code_vip", "")))
        if code != self.code:
            return await interaction.response.send_message("😾 Ce panneau ne correspond pas à ton VIP.", ephemeral=True)

        emb = build_defi_status_embed(self.s, code, vip)
        await interaction.response.send_message(embed=emb, ephemeral=True)


def build_vip_level_embed(s, vip: dict) -> discord.Embed:
    code = normalize_code(str(vip.get("code_vip", "")))
    pseudo = display_name(vip.get("pseudo", code))
    bleeter = str(vip.get("bleeter", "")).strip()
    created_at = str(vip.get("created_at", "")).strip()

    try:
        points = int(vip.get("points", 0) or 0)
    except Exception:
        points = 0
    try:
        lvl = int(vip.get("niveau", 1) or 1)
    except Exception:
        lvl = 1

    rank, total = domain.get_rank_among_active(s, code)
    unlocked = domain.get_all_unlocked_advantages(s, lvl)

    nxt = domain.get_next_level(s, lvl)
    if nxt:
        nxt_lvl, nxt_min, _ = nxt
        remaining = max(0, int(nxt_min) - points)
        prog = int((points / max(1, int(nxt_min))) * 100)
        next_line = f"Prochain: **Niveau {nxt_lvl}** à **{nxt_min}** pts\nProgression: **{prog}%** (reste {remaining} pts)"
    else:
        next_line = "🔥 Niveau max atteint."

    e = discord.Embed(
        title="🎫 VIP SubUrban",
        description=(
            f"👤 **{pseudo}**\n"
            + (f"🐦 Bleeter: **{bleeter}**\n" if bleeter else "")
            + f"🎴 Code: `{code}`\n"
            + (f"📅 VIP depuis: `{created_at}`\n" if created_at else "")
            + (f"🏁 Rang: **#{rank}** sur **{total}** VIP actifs\n" if total else "")
            + f"\n📈 **Niveau {lvl}** | ⭐ **{points} points**\n"
        ),
        color=discord.Color.gold()
    )
    e.add_field(name="🎁 Avantages débloqués", value=unlocked, inline=False)
    e.add_field(name="⬆️ Progression", value=next_line, inline=False)
    e.set_footer(text="Mikasa montre le registre VIP. 🐾")
    return e


# ==========================================================
# VIP Pick (HG) - sélection rapide
# ==========================================================
class VipPickSelect(discord.ui.Select):
    def __init__(self, view: "VipPickView", options: List[discord.SelectOption]):
        super().__init__(
            placeholder="Choisir un VIP…",
            options=options[:25],
            min_values=1,
            max_values=1
        )
        self.pick_view = view

    async def callback(self, interaction: discord.Interaction):
        code = self.values[0]
        self.pick_view.selected_code = normalize_code(code)
        await interaction.response.edit_message(embed=self.pick_view.build_embed(), view=self.pick_view)


class VipPickView(discord.ui.View):
    """
    View HG: choisir un VIP, puis:
      - ouvrir Hub VIP (pour montrer au VIP)
      - ouvrir Edition (HG)
    """
    def __init__(self, *, services, author_id: int, vip_rows: List[dict]):
        super().__init__(timeout=5 * 60)
        self.s = services
        self.author_id = int(author_id)
        self.vip_rows = vip_rows or []
        self.selected_code: Optional[str] = None

        options: List[discord.SelectOption] = []
        for r in self.vip_rows[:25]:
            code = normalize_code(str(r.get("code_vip", "")))
            pseudo = display_name(r.get("pseudo", code))
            if not code:
                continue
            options.append(discord.SelectOption(label=f"{pseudo}", value=code, description=code))

        self.add_item(VipPickSelect(self, options))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(catify("😾 Pas touche. Lance ta propre commande."), ephemeral=True)
            return False
        return True

    def build_embed(self) -> discord.Embed:
        e = discord.Embed(
            title="🎯 VIP Pick (HG)",
            description="Choisis un VIP dans la liste, puis une action.",
            color=discord.Color.dark_purple()
        )
        if self.selected_code:
            e.add_field(name="Sélection", value=f"`{self.selected_code}`", inline=False)
        return e

    @discord.ui.button(label="📌 Ouvrir Hub VIP", style=discord.ButtonStyle.primary)
    async def open_hub(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.selected_code:
            return await interaction.response.send_message("😾 Sélectionne d’abord un VIP.", ephemeral=True)

        row_i, vip = domain.find_vip_row_by_code(self.s, self.selected_code)
        if not row_i or not vip:
            return await interaction.response.send_message("❌ VIP introuvable.", ephemeral=True)

        code = normalize_code(str(vip.get("code_vip", "")))
        pseudo = display_name(vip.get("pseudo", code))

        view = VipHubView(services=self.s, code_vip=code, vip_pseudo=pseudo)
        await interaction.response.send_message(embed=view.hub_embed(), view=view, ephemeral=True)

    @discord.ui.button(label="🛠️ Edit VIP", style=discord.ButtonStyle.secondary)
    async def edit_vip(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.selected_code:
            return await interaction.response.send_message("😾 Sélectionne d’abord un VIP.", ephemeral=True)

        row_i, vip = domain.find_vip_row_by_code(self.s, self.selected_code)
        if not row_i or not vip:
            return await interaction.response.send_message("❌ VIP introuvable.", ephemeral=True)

        await interaction.response.send_modal(VipEditModal(services=self.s, row_i=row_i, vip=vip))


class VipEditModal(discord.ui.Modal, title="VIP Edit (HG)"):
    pseudo = discord.ui.TextInput(label="Pseudo VIP", required=False, max_length=40)
    bleeter = discord.ui.TextInput(label="Bleeter (@...)", required=False, max_length=40)
    discord_id = discord.ui.TextInput(label="Discord ID (chiffres)", required=False, max_length=25)

    def __init__(self, *, services, row_i: int, vip: dict):
        super().__init__()
        self.s = services
        self.row_i = int(row_i)

        code = normalize_code(str(vip.get("code_vip", "")))
        self.pseudo.default = str(vip.get("pseudo", "") or code)
        self.bleeter.default = str(vip.get("bleeter", "") or "")
        self.discord_id.default = str(vip.get("discord_id", "") or "")

    async def on_submit(self, interaction: discord.Interaction):
        updates = {}
        if self.pseudo.value.strip():
            updates["pseudo"] = self.pseudo.value.strip()
        # bleeter: accepte vide => retirer
        if self.bleeter.value.strip() or self.bleeter.value == "":
            updates["bleeter"] = self.bleeter.value.strip()
        if self.discord_id.value.strip():
            digits = "".join([c for c in self.discord_id.value.strip() if c.isdigit()])
            updates["discord_id"] = digits

        if not updates:
            return await interaction.response.send_message("😾 Rien à modifier.", ephemeral=True)

        for header, val in updates.items():
            self.s.update_cell_by_header("VIP", self.row_i, header, val)

        await interaction.response.send_message("✅ VIP mis à jour.", ephemeral=True)


def build_defi_status_embed(s, code: str, vip: dict) -> discord.Embed:
    wk = domain.current_challenge_week_number()
    wk_key = domain.week_key_for(wk)
    wk_label = domain.week_label_for(wk)

    row_i, row = domain.ensure_defis_row(s, code, wk_key, wk_label)
    done = domain.defis_done_count(row)

    tasks = domain.get_week_tasks_for_view(wk)
    lines = []
    if wk == 12:
        lines.append("🎭 Semaine finale: freestyle (4 choix).")
    else:
        for i in range(1, 5):
            ok = bool(str(row.get(f"d{i}", "")).strip())
            mark = "✅" if ok else "❌"
            lines.append(f"{mark} {tasks[i-1]}")

    start, end = challenge_week_window()
    pseudo = display_name(vip.get("pseudo", code))

    e = discord.Embed(
        title=f"📸 Défis de la semaine ({wk_label})",
        description=(
            f"👤 **{pseudo}** • `{code}`\n"
            f"🗓️ **{start.strftime('%d/%m %H:%M')} → {end.strftime('%d/%m %H:%M')}** (FR)\n\n"
            + "\n".join(lines)
            + f"\n\n➡️ Progression: **{done}/4**"
        ),
        color=discord.Color.dark_purple()
    )
    e.set_footer(text="Mikasa coche les cases. 🐾")
    return e


# ==========================================================
# Défis (HG)
# ==========================================================
def yn_emoji(flag: bool) -> str:
    return "✔️" if flag else "❌"

def col_letter_for_defi(n: int) -> str:
    # DEFIS: d1..d4 = colonnes C..F
    return chr(ord("C") + (n - 1))


class DefiValidateView(discord.ui.View):
    def __init__(self, *, author: discord.Member, services, code: str, wk: int, wk_key: str, wk_label: str,
                 row_i: int, row: dict, tasks: List[str], vip_pseudo: str):
        super().__init__(timeout=180)
        self.author = author
        self.s = services
        self.code = code
        self.wk = wk
        self.wk_key = wk_key
        self.wk_label = wk_label
        self.row_i = row_i
        self.row = row
        self.tasks = tasks
        self.vip_pseudo = vip_pseudo

        self.state = {
            1: bool(str(row.get("d1", "")).strip()),
            2: bool(str(row.get("d2", "")).strip()),
            3: bool(str(row.get("d3", "")).strip()),
            4: bool(str(row.get("d4", "")).strip()),
        }
        self.locked = {n: self.state[n] for n in range(1, 5)}
        self._refresh_buttons()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(catify("😾 Pas touche. Lance ta propre commande."), ephemeral=True)
            return False
        return True

    def _build_embed(self) -> discord.Embed:
        start, end = challenge_week_window()
        lines = []
        for i in range(1, 5):
            lines.append(f"{yn_emoji(self.state[i])} {self.tasks[i-1]}")
        desc = (
            f"👤 **{self.vip_pseudo}** • `{self.code}`\n"
            f"📌 {self.wk_label}\n"
            f"🗓️ **{start.strftime('%d/%m %H:%M')} → {end.strftime('%d/%m %H:%M')}** (FR)\n\n"
            + "\n".join(lines)
            + "\n\nClique pour cocher. Les ✔️ déjà tamponnés sont verrouillés."
        )
        embed = discord.Embed(title="📸 Validation des défis (HG)", description=desc, color=discord.Color.dark_purple())
        embed.set_footer(text="Tampon Mikasa: une fois posé, il ne s’efface pas. 🐾")
        return embed

    def _refresh_buttons(self):
        for child in self.children:
            if isinstance(child, discord.ui.Button) and child.custom_id and child.custom_id.startswith("defi_toggle_"):
                n = int(child.custom_id.split("_")[-1])
                child.label = f"{yn_emoji(self.state[n])} Défi {n}"
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
        await interaction.response.defer(ephemeral=True)

        row_i2, row2 = domain.get_defis_row(self.s, self.code, self.wk_key)
        if not row_i2:
            return await interaction.followup.send(catify("❌ Ligne DEFIS introuvable. Relance."), ephemeral=True)

        done_before = domain.defis_done_count(row2)
        stamp = now_fr().strftime("%Y-%m-%d %H:%M:%S")

        updates = []
        for n in range(1, 5):
            if self.state.get(n) and not str(row2.get(f"d{n}", "")).strip():
                col = col_letter_for_defi(n)
                updates.append({"range": f"{col}{row_i2}", "values": [[stamp]]})

        if updates:
            self.s.batch_update("DEFIS", updates)

        row_i3, row3 = domain.get_defis_row(self.s, self.code, self.wk_key)
        done_after = domain.defis_done_count(row3 or {})
        awarded = False

        if done_before == 0 and done_after > 0:
            ok1, _ = domain.add_points_by_action(self.s, self.code, "BLEETER", 1, interaction.user.id, f"1er défi validé ({self.wk_key})", author_is_hg=True)
            ok2, _ = domain.add_points_by_action(self.s, self.code, "DEFI_HEBDO", 1, interaction.user.id, f"1er défi validé ({self.wk_key})", author_is_hg=True)
            awarded = bool(ok1 and ok2)

        if done_after >= 4 and row3 and str(row3.get("completed_at", "")).strip() == "":
            comp_stamp = now_fr().strftime("%Y-%m-%d %H:%M:%S")
            self.s.batch_update("DEFIS", [
                {"range": f"G{row_i3}", "values": [[comp_stamp]]},
                {"range": f"H{row_i3}", "values": [[str(interaction.user.id)]]},
            ])
            domain.add_points_by_action(self.s, self.code, "TOUS_DEFIS_HEBDO", 1, interaction.user.id, f"4/4 défis complétés ({self.wk_key})", author_is_hg=True)

        for item in self.children:
            item.disabled = True

        final_embed = self._build_embed()
        extra = "🎁 Récompense donnée (1er défi de la semaine)." if awarded else "🧾 Récompense déjà prise cette semaine (ou aucune case nouvelle)."
        final_embed.add_field(name="✅ Enregistré", value=f"Progression: **{done_after}/4**\n{extra}", inline=False)
        final_embed.set_footer(text="Tampon posé. Mikasa referme le carnet. 🐾")

        await interaction.message.edit(embed=final_embed, view=self)
        await interaction.followup.send("✅ Défis enregistrés.", ephemeral=True)


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
                return await interaction.response.send_message(catify("😾 Max **4** choix en semaine 12."), ephemeral=True)
            view.selected.add(self.idx)
        await view._edit(interaction)


class Week12ValidateButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="✅ VALIDER", style=discord.ButtonStyle.success, custom_id="w12_commit")

    async def callback(self, interaction: discord.Interaction):
        view: DefiWeek12View = self.view  # type: ignore
        await view.commit_selected(interaction)


class DefiWeek12View(discord.ui.View):
    def __init__(self, *, author: discord.Member, services, code: str, wk: int, wk_key: str, wk_label: str,
                 row_i: int, row: dict, choices: List[str], vip_pseudo: str):
        super().__init__(timeout=180)
        self.author = author
        self.s = services
        self.code = code
        self.wk = wk
        self.wk_key = wk_key
        self.wk_label = wk_label
        self.row_i = row_i
        self.row = row
        self.choices = choices
        self.vip_pseudo = vip_pseudo

        self.selected = set()

        for i in range(12):
            self.add_item(Week12ChoiceButton(i))
        self.add_item(Week12ValidateButton())
        self._refresh_all()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(catify("😾 Pas touche. Lance ta propre commande."), ephemeral=True)
            return False
        return True

    def selected_count(self) -> int:
        return len(self.selected)

    def _build_embed(self) -> discord.Embed:
        start, end = challenge_week_window()
        done = domain.defis_done_count(self.row)
        lines = []
        for idx, txt in enumerate(self.choices):
            mark = "✔️" if idx in self.selected else "❌"
            lines.append(f"{mark} {txt}")

        desc = (
            f"👤 **{self.vip_pseudo}** • `{self.code}`\n"
            f"📌 {self.wk_label} (Freestyle)\n"
            f"🗓️ **{start.strftime('%d/%m %H:%M')} → {end.strftime('%d/%m %H:%M')}** (FR)\n\n"
            f"✅ Slots déjà validés: **{done}/4**\n"
            f"🧩 Sélection en cours: **{self.selected_count()}/4**\n\n"
            + "\n".join(lines)
            + "\n\nChoisis jusqu’à 4 défis, puis **VALIDER**."
        )
        embed = discord.Embed(title="🎭 Semaine 12 Freestyle (HG)", description=desc, color=discord.Color.purple())
        embed.set_footer(text="Freestyle: Mikasa compte exactement 4 preuves. 🐾")
        return embed

    def _refresh_all(self):
        for item in self.children:
            if isinstance(item, Week12ChoiceButton):
                idx = item.idx
                item.label = f"{'✔️' if idx in self.selected else '❌'} {idx+1}"
                item.disabled = (self.selected_count() >= 4 and idx not in self.selected)

            if isinstance(item, Week12ValidateButton):
                item.disabled = (self.selected_count() == 0)

    async def _edit(self, interaction: discord.Interaction):
        self._refresh_all()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    async def commit_selected(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        row_i2, row2 = domain.get_defis_row(self.s, self.code, self.wk_key)
        if not row_i2 or not row2:
            return await interaction.followup.send(catify("❌ Ligne DEFIS introuvable."), ephemeral=True)

        done_before = domain.defis_done_count(row2)
        stamp = now_fr().strftime("%Y-%m-%d %H:%M:%S")

        empty_slots = [n for n in range(1, 5) if not str(row2.get(f"d{n}", "")).strip()]
        to_write = list(self.selected)[:len(empty_slots)]
        updates = []
        notes = str(row2.get("d_notes", "") or "").strip()

        for k, choice_idx in enumerate(to_write):
            slot_n = empty_slots[k]
            col = col_letter_for_defi(slot_n)
            updates.append({"range": f"{col}{row_i2}", "values": [[stamp]]})
            picked_txt = self.choices[choice_idx]
            notes = (notes + " | " if notes else "") + f"W12:{slot_n}:{picked_txt}"

        if updates:
            self.s.batch_update("DEFIS", updates)
            self.s.update_cell_by_header("DEFIS", row_i2, "d_notes", notes)

        row_i3, row3 = domain.get_defis_row(self.s, self.code, self.wk_key)
        done_after = domain.defis_done_count(row3 or {})

        awarded = False
        if done_before == 0 and done_after > 0:
            ok1, _ = domain.add_points_by_action(self.s, self.code, "BLEETER", 1, interaction.user.id, f"1er défi validé ({self.wk_key})", author_is_hg=True)
            ok2, _ = domain.add_points_by_action(self.s, self.code, "DEFI_HEBDO", 1, interaction.user.id, f"1er défi validé ({self.wk_key})", author_is_hg=True)
            awarded = bool(ok1 and ok2)

        if done_after >= 4 and row3 and str(row3.get("completed_at", "")).strip() == "":
            comp_stamp = now_fr().strftime("%Y-%m-%d %H:%M:%S")
            self.s.batch_update("DEFIS", [
                {"range": f"G{row_i3}", "values": [[comp_stamp]]},
                {"range": f"H{row_i3}", "values": [[str(interaction.user.id)]]},
            ])
            domain.add_points_by_action(self.s, self.code, "TOUS_DEFIS_HEBDO", 1, interaction.user.id, f"4/4 défis complétés ({self.wk_key})", author_is_hg=True)

        for item in self.children:
            item.disabled = True

        emb = self._build_embed()
        extra = "🎁 Récompense donnée (1er défi de la semaine)." if awarded else "🧾 Récompense déjà prise cette semaine."
        emb.add_field(name="✅ Enregistré", value=f"Progression: **{done_after}/4**\n{extra}", inline=False)
        emb.set_footer(text="Freestyle enregistré. Mikasa range les preuves. 🐾")

        await interaction.message.edit(embed=emb, view=self)
        await interaction.followup.send("✅ Freestyle enregistré.", ephemeral=True)


# ==========================================================
# QCM (Daily)
# - pas de double interaction.response
# - pas de doublons
# ==========================================================
class QcmDailyView(discord.ui.View):
    def __init__(
        self,
        *,
        services,
        discord_id: int,
        code_vip: str,
        vip_pseudo: str,
        chrono_limit_sec: int = 12
    ):
        super().__init__(timeout=6 * 60)
        self.s = services
        self.discord_id = int(discord_id)
        self.code_vip = normalize_code(code_vip)
        self.vip_pseudo = display_name(vip_pseudo or self.code_vip)
        self.chrono_limit_sec = int(chrono_limit_sec)

        self.questions = domain.qcm_pick_daily_set(self.s)
        self.date_key, self.answers = domain.qcm_today_progress(self.s, self.code_vip, self.discord_id)

        self.current_index = len(self.answers)  # 0..4
        self.sent_at = now_fr()

        self._rebuild_items()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.discord_id:
            await interaction.response.send_message(catify("😾 Pas touche. Lance ton propre QCM."), ephemeral=True)
            return False
        return True

    def _rebuild_items(self):
        self.clear_items()
        if self.current_index >= len(self.questions):
            self.add_item(QcmCloseButton())
            return

        for opt in LETTERS:
            self.add_item(QcmAnswerButton(opt))
        self.add_item(QcmCloseButton())

    def build_embed(self) -> discord.Embed:
        done = self.current_index
        total = len(self.questions)

        if done >= total:
            return discord.Embed(
                title="✅ QCM terminé (aujourd’hui)",
                description=f"Tu as répondu aux **{total}/5** questions.\nReviens demain pour le prochain QCM. 🐾",
                color=discord.Color.green()
            )

        q = self.questions[self.current_index]
        e = discord.Embed(
            title=f"🧠 QCM Los Santos du {self.date_key}",
            description=(
                f"👤 **{self.vip_pseudo}**\n"
                f"📌 Question **{done+1}/{total}**\n"
                f"⏱️ Chrono: **{self.chrono_limit_sec}s**\n\n"
                f"**{q['question']}**\n\n"
                f"**A)** {q['A']}\n"
                f"**B)** {q['B']}\n"
                f"**C)** {q['C']}\n"
                f"**D)** {q['D']}\n"
            ),
            color=discord.Color.blurple()
        )
        e.set_footer(text="Chaque réponse est enregistrée immédiatement. Aucun retour arrière.")
        return e

    async def render_from_response(self, interaction: discord.Interaction):
        self._rebuild_items()
        self.sent_at = now_fr()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def render_from_message_edit(self, message: discord.Message):
        self._rebuild_items()
        self.sent_at = now_fr()
        await message.edit(embed=self.build_embed(), view=self)

    async def submit_choice(self, interaction: discord.Interaction, choice: str):
        elapsed = int((now_fr() - self.sent_at).total_seconds())
        q = self.questions[self.current_index]

        ok, mark, pts, is_correct = domain.qcm_submit_answer(
            self.s,
            discord_id=self.discord_id,
            code_vip=self.code_vip,
            q=q,
            q_index=self.current_index + 1,
            choice=choice,
            elapsed_sec=elapsed,
            chrono_limit_sec=self.chrono_limit_sec
        )

        if not ok:
            return await interaction.followup.send(catify(str(mark)), ephemeral=True)

        note = f"{mark} Réponse enregistrée."
        if elapsed > self.chrono_limit_sec:
            note += " ⏱️ Trop lent: **0 point**."
        elif is_correct and pts > 0:
            note += f" ✅ **+{pts} pts**"
        elif is_correct and pts == 0:
            note += " ✅ Correct mais **cap hebdo** atteint (0 point)."
        else:
            note += " 0 point."

        self.current_index += 1

        try:
            await self.render_from_message_edit(interaction.message)
        except Exception:
            pass

        await interaction.followup.send(note, ephemeral=True)


class QcmAnswerButton(discord.ui.Button):
    def __init__(self, choice: str):
        super().__init__(label=choice, style=discord.ButtonStyle.secondary)
        self.choice = choice

    async def callback(self, interaction: discord.Interaction):
        view: QcmDailyView = self.view  # type: ignore

        # lock visuel immédiat
        for item in view.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

        # ACK 1 seule fois: response.edit_message
        await view.render_from_response(interaction)

        # puis logique: followup + message.edit
        await view.submit_choice(interaction, self.choice)


class QcmCloseButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="✅ Fermer", style=discord.ButtonStyle.success)

    async def callback(self, interaction: discord.Interaction):
        for item in self.view.children:
            item.disabled = True
        await interaction.response.edit_message(content="✅ QCM fermé.", embed=None, view=self.view)
