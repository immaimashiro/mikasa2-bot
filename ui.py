# ui.py
# -*- coding: utf-8 -*-

from __future__ import annotations
from typing import Dict, List, Tuple, Optional

import discord
from discord import ui

import domain
from services import catify, now_fr, now_iso


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

        self.author_id = author_id
        self.categories = categories
        self.services = services

        self.code_vip = domain.normalize_code(code_vip)
        self.vip_pseudo = domain.display_name(vip_pseudo or self.code_vip)
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
        v[field] = max(0, int(v.get(field, 0)) + delta)

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
        # 5 boutons max par ligne: discord gère
        self.add_item(SaleAdjustButton("➕ Normal", "normal", +1, self))
        self.add_item(SaleAdjustButton("➖ Normal", "normal", -1, self))
        self.add_item(SaleAdjustButton("➕ Limitée", "limitee", +1, self))
        self.add_item(SaleAdjustButton("➖ Limitée", "limitee", -1, self))
        self.add_item(SaleNoteButton(self))
        self.add_item(SaleValidateButton(self))

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True


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
        self.delta = delta
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
        # On édite le message original de la view
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

            base_reason = f"vente:{cat}"
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

        # si rien n'a été appliqué
        if not applied and errors:
            return await interaction.followup.send(
                "❌ Vente non enregistrée:\n" + "\n".join(errors),
                ephemeral=True
            )

        # on fige l’UI (vente terminée)
        for item in self.sale_view.children:
            item.disabled = True

        # On enlève l’embed pour laisser place au reçu (et éviter confusion)
        try:
            await interaction.message.edit(embed=None, view=self.sale_view)
        except Exception:
            pass

        receipt = "✅ **Vente enregistrée**\n" + ("\n".join(applied) if applied else "")
        if errors:
            receipt += "\n\n⚠️ **Erreurs partielles**\n" + "\n".join(errors)

        await interaction.followup.send(receipt, ephemeral=True)

# --- VIP UI (public) ---

class VipHubView(discord.ui.View):
    def __init__(self, *, services, code_vip: str, vip_pseudo: str):
        super().__init__(timeout=5 * 60)
        self.s = services
        self.code = domain.normalize_code(code_vip)
        self.vip_pseudo = domain.display_name(vip_pseudo or self.code)

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
        # réservé au VIP concerné (sécurité)
        if not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("❌ Impossible ici.", ephemeral=True)

        row_i, vip = domain.find_vip_row_by_discord_id(self.s, interaction.user.id)
        if not row_i or not vip:
            return await interaction.response.send_message("😾 Ton profil VIP n’est pas lié à ton Discord.", ephemeral=True)

        code = domain.normalize_code(str(vip.get("code_vip", "")))
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

        code = domain.normalize_code(str(vip.get("code_vip", "")))
        if code != self.code:
            return await interaction.response.send_message("😾 Ce panneau ne correspond pas à ton VIP.", ephemeral=True)

        emb = build_defi_status_embed(self.s, code, vip)
        await interaction.response.send_message(embed=emb, ephemeral=True)


def build_vip_level_embed(s, vip: dict) -> discord.Embed:
    code = domain.normalize_code(str(vip.get("code_vip", "")))
    pseudo = domain.display_name(vip.get("pseudo", code))
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
    pmin, raw_av = domain.get_level_info(s, lvl)
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


def build_defi_status_embed(s, code: str, vip: dict) -> discord.Embed:
    wk = domain.current_challenge_week_number()
    wk_key = domain.week_key_for(wk)
    wk_label = domain.week_label_for(wk)

    row_i, row = domain.ensure_defis_row(s, code, wk_key, wk_label)
    done = domain.defis_done_count(row)

    tasks = domain.get_week_tasks_for_view(wk)
    lines = []
    if wk == 12:
        # semaine 12 = freestyle: on affiche juste l'info
        lines.append("🎭 Semaine finale: freestyle (4 choix).")
    else:
        for i in range(1, 5):
            ok = bool(str(row.get(f"d{i}", "")).strip())
            mark = "✅" if ok else "❌"
            lines.append(f"{mark} {tasks[i-1]}")

    start, end = domain.challenge_week_window()
    pseudo = domain.display_name(vip.get("pseudo", code))

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
# Défis (HG) - on garde tes views existantes, inchangées
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
        start, end = domain.challenge_week_window()
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
        start, end = domain.challenge_week_window()
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

# --- VIP EDIT UI (staff) ---

EDIT_FIELDS = [
    ("Pseudo", "pseudo"),
    ("Bleeter", "bleeter"),
    ("Téléphone", "phone"),
    ("Date de naissance (dob)", "dob"),
    ("Status (ACTIVE/DISABLED)", "status"),
    ("Discord ID (liaison)", "discord_id"),
]


class VipEditView(ui.View):
    def __init__(self, *, services, author_id: int, code_vip: str, vip_pseudo: str):
        super().__init__(timeout=5 * 60)
        self.s = services
        self.author_id = author_id

        self.code = domain.normalize_code(code_vip)
        self.vip_pseudo = domain.display_name(vip_pseudo or self.code)

        self.selected_field = "bleeter"
        self.add_item(VipEditFieldSelect(self))
        self.add_item(VipEditOpenModalButton(self))
        self.add_item(VipEditCloseButton())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(catify("😾 Pas touche. Ouvre ton /vip edit."), ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True

    def build_embed(self) -> discord.Embed:
        field_label = next((lab for lab, val in EDIT_FIELDS if val == self.selected_field), self.selected_field)
        e = discord.Embed(
            title="🛠️ Édition VIP",
            description=(
                f"👤 **VIP** : {self.vip_pseudo} • `{self.code}`\n\n"
                f"🔧 Champ sélectionné : **{field_label}**\n"
                "Clique **Modifier** pour saisir une nouvelle valeur."
            ),
            color=discord.Color.dark_teal()
        )
        e.set_footer(text="Astuce: laisse vide pour effacer (sauf status).")
        return e

    async def refresh(self, interaction: discord.Interaction):
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def apply_update(self, interaction: discord.Interaction, field: str, new_value: str):
        # retrouve la ligne VIP
        row_i, vip = domain.find_vip_row_by_code(self.s, self.code)
        if not row_i or not vip:
            return await interaction.followup.send("❌ VIP introuvable (ligne).", ephemeral=True)

        field = (field or "").strip()
        val = (new_value or "").strip()

        # règles spécifiques
        if field == "status":
            v = val.upper()
            if v not in ("ACTIVE", "DISABLED"):
                return await interaction.followup.send("❌ Status doit être ACTIVE ou DISABLED.", ephemeral=True)
            val = v

        if field == "discord_id":
            # autorise vide (unlink) ou un int
            if val:
                try:
                    int(val)
                except Exception:
                    return await interaction.followup.send("❌ discord_id doit être un nombre (ID Discord).", ephemeral=True)

        # update sheet
        self.s.update_cell_by_header("VIP", row_i, field, val)

        # log
        self.s.append_by_headers("LOG", {
            "timestamp": now_iso(),
            "staff_id": str(interaction.user.id),
            "code_vip": self.code,
            "action_key": "EDIT_VIP",
            "quantite": 1,
            "points_unite": 0,
            "delta_points": 0,
            "raison": f"{field} -> {val if val else '(vide)'}",
        })

        # petit feedback + refresh message original (la view)
        await interaction.followup.send(f"✅ `{field}` mis à jour pour **{self.vip_pseudo}**.", ephemeral=True)

        # On tente de rafraîchir l'embed du panneau (pas obligatoire)
        try:
            await interaction.message.edit(embed=self.build_embed(), view=self)
        except Exception:
            pass


class VipEditFieldSelect(ui.Select):
    def __init__(self, view: VipEditView):
        options = [discord.SelectOption(label=label, value=value) for label, value in EDIT_FIELDS]
        super().__init__(placeholder="Choisir une info à modifier…", options=options, min_values=1, max_values=1)
        self.v = view

    async def callback(self, interaction: discord.Interaction):
        self.v.selected_field = self.values[0]
        await self.v.refresh(interaction)


class VipEditOpenModalButton(ui.Button):
    def __init__(self, view: VipEditView):
        super().__init__(label="✍️ Modifier", style=discord.ButtonStyle.primary)
        self.v = view

    async def callback(self, interaction: discord.Interaction):
        field = self.v.selected_field
        label = next((lab for lab, val in EDIT_FIELDS if val == field), field)
        await interaction.response.send_modal(VipEditValueModal(self.v, field=field, label=label))


class VipEditValueModal(ui.Modal):
    def __init__(self, view: VipEditView, *, field: str, label: str):
        super().__init__(title=f"Modifier: {label}")
        self.v = view
        self.field = field

        placeholder = "Nouvelle valeur (vide = effacer)" if field != "status" else "ACTIVE ou DISABLED"
        maxlen = 200

        self.value_input = ui.TextInput(
            label=label,
            required=(field == "status"),
            placeholder=placeholder,
            max_length=maxlen
        )
        self.add_item(self.value_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.v.apply_update(interaction, self.field, str(self.value_input.value))


class VipEditCloseButton(ui.Button):
    def __init__(self):
        super().__init__(label="✅ Fermer", style=discord.ButtonStyle.success)

    async def callback(self, interaction: discord.Interaction):
        for item in self.view.children:
            item.disabled = True
        await interaction.response.edit_message(content="✅ Panneau fermé.", embed=None, view=self.view)

# --- HELP UI (staff) ---

HELP_SECTIONS: List[Tuple[str, str]] = [
    ("Tout", "all"),
    ("VIP", "vip"),
    ("Staff", "staff"),
    ("Défis (HG)", "defi"),
]

def _help_pages() -> Dict[str, Dict[str, str]]:
    """
    Retourne un dict:
    section -> {title, body}
    """
    vip = [
        "**Commandes VIP (staff)**",
        "• `/vip create` → Créer un profil VIP",
        "• `/vip add` → Ajouter une action/points à un VIP",
        "• `/vip actions` → Voir la liste des actions disponibles",
        "• `/vip sale` → Fenêtre panier de vente (catégories + normal/limitée)",
        "• `/vip sales_summary` → Résumé ventes (day/week/month + filtre catégorie)",
        "• `/vip card_generate` → Générer la carte VIP (impression)",
        "• `/vip card_show` → Afficher la carte VIP",
        "• `/vip bleeter` → Définir/retirer le bleeter d’un VIP (si tu l’as ajouté)",
        "• `/vip edit` → Panneau d’édition (si tu l’as ajouté)",
        "• `/vipstats` → Stats globales VIP",
        "• `/vipsearch` → Rechercher un VIP",
        "• `/niveau_top` → Top VIP (actifs) par points",
        "• `/niveau <pseudo ou code>` → Voir le niveau VIP d’un client",
    ]

    staff = [
        "**Rappels Staff**",
        "• Les commandes VIP sont staff-only (employés + HG).",
        "• Certaines actions peuvent être HG-only selon l’onglet `ACTIONS`.",
        "• Pour une vente: utilise `/vip sale <code ou pseudo>` puis fais +/− par catégorie, et **VALIDER** à la caisse.",
        "• Les logs sont dans l’onglet `LOG` (utile en cas de litige).",
    ]

    defi = [
        "**Commandes Défis (HG)**",
        "• `/defi panel` → Ouvrir le panneau de validation des défis (HG)",
        "• `/defi week_announce` → Poster l’annonce hebdo (HG)",
        "",
        "**Défis côté VIP**",
        "• (optionnel) `/vipme` ou panneau VIP si tu l’as ajouté (Niveau / Défis).",
        "",
        "_Note:_ les semaines dépendent de `CHALLENGE_START` (Railway).",
    ]

    all_lines = []
    all_lines += vip + [""] + staff + [""] + defi

    return {
        "vip":  {"title": "📘 Aide Mikasa • VIP", "body": "\n".join(vip)},
        "staff":{"title": "📘 Aide Mikasa • Staff", "body": "\n".join(staff)},
        "defi": {"title": "📘 Aide Mikasa • Défis", "body": "\n".join(defi)},
        "all":  {"title": "📘 Aide Mikasa • Tout", "body": "\n".join(all_lines)},
    }


class VipHelpView(ui.View):
    def __init__(self, *, author_id: int, default_section: str = "all"):
        super().__init__(timeout=6 * 60)
        self.author_id = author_id
        self.section = default_section if default_section in ("all", "vip", "staff", "defi") else "all"

        self.add_item(VipHelpSectionSelect(self))
        self.add_item(VipHelpQuickButton("📦 Tout", "all", self))
        self.add_item(VipHelpQuickButton("🎟️ VIP", "vip", self))
        self.add_item(VipHelpQuickButton("🧑‍💼 Staff", "staff", self))
        self.add_item(VipHelpQuickButton("📸 Défis", "defi", self))
        self.add_item(VipHelpCloseButton())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(catify("😾 Pas touche. Ouvre ton propre `/vip help`."), ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True

    def build_embed(self) -> discord.Embed:
        pages = _help_pages()
        page = pages.get(self.section, pages["all"])

        e = discord.Embed(
            title=page["title"],
            description=page["body"],
            color=discord.Color.blurple()
        )
        e.set_footer(text="Astuce: garde ce panneau ouvert pendant que tu bosses. 🐾")
        return e

    async def refresh(self, interaction: discord.Interaction):
        await interaction.response.edit_message(embed=self.build_embed(), view=self)


class VipHelpSectionSelect(ui.Select):
    def __init__(self, view: VipHelpView):
        options = [discord.SelectOption(label=lab, value=val) for lab, val in HELP_SECTIONS]
        super().__init__(placeholder="Choisir une section…", options=options, min_values=1, max_values=1)
        self.v = view

    async def callback(self, interaction: discord.Interaction):
        self.v.section = self.values[0]
        await self.v.refresh(interaction)


class VipHelpQuickButton(ui.Button):
    def __init__(self, label: str, section: str, view: VipHelpView):
        super().__init__(label=label, style=discord.ButtonStyle.secondary)
        self.section = section
        self.v = view

    async def callback(self, interaction: discord.Interaction):
        self.v.section = self.section
        await self.v.refresh(interaction)


class VipHelpCloseButton(ui.Button):
    def __init__(self):
        super().__init__(label="✅ Fermer", style=discord.ButtonStyle.success)

    async def callback(self, interaction: discord.Interaction):
        for item in self.view.children:
            item.disabled = True
        await interaction.response.edit_message(content="✅ Aide fermée.", embed=None, view=self.view)

class VipPickView(ui.View):
    def __init__(self, *, author_id: int, services, matches: list[tuple[str, str]]):
        super().__init__(timeout=3 * 60)
        self.author_id = author_id
        self.s = services
        self.matches = matches
        self.add_item(VipPickSelect(self))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(catify("😾 Pas touche."), ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class VipPickSelect(ui.Select):
    def __init__(self, view: VipPickView):
        options = []
        for pseudo, code in view.matches:
            options.append(discord.SelectOption(label=f"{pseudo}", description=code, value=code))
        super().__init__(
            placeholder="Choisir le VIP…",
            options=options,
            min_values=1,
            max_values=1
        )
        self.v = view

    async def callback(self, interaction: discord.Interaction):
        code = self.values[0]
        row_i, vip = domain.find_vip_row_by_code(self.v.s, code)
        if not row_i or not vip:
            return await interaction.response.send_message("❌ VIP introuvable.", ephemeral=True)

        pseudo = domain.display_name(vip.get("pseudo", code))
        edit_view = VipEditView(
            services=self.v.s,
            author_id=interaction.user.id,
            code_vip=code,
            vip_pseudo=pseudo
        )
        await interaction.response.edit_message(
            content="✅ VIP sélectionné. Panneau d’édition ouvert :",
            embed=edit_view.build_embed(),
            view=edit_view
        )
