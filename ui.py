# ui.py
# -*- coding: utf-8 -*-

from __future__ import annotations
from typing import Optional, List, Set

import discord

from services import catify, now_fr
import domain


def yn_emoji(flag: bool) -> str:
    return "✔️" if flag else "❌"

def col_letter_for_defi(n: int) -> str:
    # DEFIS: d1..d4 = colonnes C..F
    return chr(ord("C") + (n - 1))


# ---------------------------------------
# Fenêtre de vente: + / - puis Valider
# ---------------------------------------
CATEGORIES = [
    ("Haut", "TSHIRT/HOODIES"),
    ("Bas", "PANTS"),
    ("Chaussures", "SHOES"),
    ("Masque", "MASKS"),
    ("Accessoire", "ACCESSORY"),
    ("Autre", "OTHER"),
]

import discord
from discord import ui

import discord
from discord import ui

class SaleCartView(ui.View):
    def __init__(self, *, author_id: int, categories: list, services, code_vip: str, vip_pseudo: str, author_is_hg: bool):
        super().__init__(timeout=15 * 60)

        self.author_id = author_id
        self.categories = categories
        self.services = services

        self.code_vip = code_vip
        self.vip_pseudo = vip_pseudo
        self.author_is_hg = author_is_hg

        self.cart = {}
        self.current_category = categories[0][1]
        self.note = ""

        self.add_item(CategorySelect(self))
        self._add_controls()

    def ensure_category(self):
        if self.current_category not in self.cart:
            self.cart[self.current_category] = {"normal": 0, "limitee": 0}

    def build_embed(self):
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

        # panier global
        lines = []
        for cat, v in self.cart.items():
            if v["normal"] > 0 or v["limitee"] > 0:
                lines.append(f"• `{cat}` → Normal **{v['normal']}** | Limitée **{v['limitee']}**")

        emb.add_field(name="🛒 Panier total", value=("\n".join(lines) if lines else "*Vide*"), inline=False)
        emb.add_field(name="📝 Note", value=(self.note or "*Aucune*"), inline=False)

        emb.set_footer(text="Astuce: change de catégorie et reviens pour corriger avant de valider.")
        return emb

    async def refresh(self, interaction: discord.Interaction):
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    def _add_controls(self):
        # boutons
        self.add_item(AdjustButton("+ Normal", "normal", +1, self))
        self.add_item(AdjustButton("− Normal", "normal", -1, self))
        self.add_item(AdjustButton("+ Limitée", "limitee", +1, self))
        self.add_item(AdjustButton("− Limitée", "limitee", -1, self))
        self.add_item(NoteButton(self))
        self.add_item(ValidateButton(self))

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class CategorySelect(ui.Select):
    def __init__(self, view: SaleCartView):
        options = [discord.SelectOption(label=label, value=value) for label, value in view.categories]
        super().__init__(placeholder="Choisir une catégorie d’articles...", options=options)
        self.sale_view = view

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.sale_view.author_id:
            return await interaction.response.send_message("❌ Ce n’est pas ta vente.", ephemeral=True)

        self.sale_view.current_category = self.values[0]
        self.sale_view.ensure_category()
        await self.sale_view.refresh(interaction)


class AdjustButton(ui.Button):
    def __init__(self, label, field, delta, view: SaleCartView):
        super().__init__(label=label, style=discord.ButtonStyle.secondary)
        self.field = field
        self.delta = delta
        self.sale_view = view

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.sale_view.author_id:
            return await interaction.response.send_message("❌ Ce n’est pas ta vente.", ephemeral=True)

        self.sale_view.ensure_category()
        v = self.sale_view.cart[self.sale_view.current_category]
        v[self.field] = max(0, v[self.field] + self.delta)
        await self.sale_view.refresh(interaction)


class NoteButton(ui.Button):
    def __init__(self, view: SaleCartView):
        super().__init__(label="📝 Note", style=discord.ButtonStyle.primary)
        self.sale_view = view

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.sale_view.author_id:
            return await interaction.response.send_message("❌ Ce n’est pas ta vente.", ephemeral=True)

        modal = NoteModal(self.sale_view)
        await interaction.response.send_modal(modal)


class NoteModal(ui.Modal, title="Note de vente"):
    note = ui.TextInput(label="Note (optionnel)", required=False, max_length=200)

    def __init__(self, view: SaleCartView):
        super().__init__()
        self.sale_view = view

    async def on_submit(self, interaction: discord.Interaction):
        self.sale_view.note = self.note.value.strip()
        await interaction.response.edit_message(embed=self.sale_view.build_embed(), view=self.sale_view)


class ValidateButton(ui.Button):
    def __init__(self, view: SaleCartView):
        super().__init__(label="✅ VALIDER", style=discord.ButtonStyle.success)
        self.sale_view = view

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.sale_view.author_id:
            return await interaction.response.send_message("❌ Ce n’est pas ta vente.", ephemeral=True)

        # Empêche double clic
        await interaction.response.defer()

        # ✅ ICI ON APPELLE LA LOGIQUE EXISTANTE

        errors = []
        applied = []

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

        # Fin: on fige l’UI
        for item in self.sale_view.children:
            item.disabled = True

        if errors and not applied:
            await interaction.followup.send("❌ Vente non enregistrée:\n" + "\n".join(errors), ephemeral=True)
            return

        receipt = "✅ **Vente enregistrée**\n" + ("\n".join(applied) if applied else "")
        if errors:
            receipt += "\n\n⚠️ **Erreurs partielles**\n" + "\n".join(errors)

        await interaction.message.edit(embed=None, view=self.sale_view)
        await interaction.followup.send(receipt, ephemeral=True)

# ---------------------------------------
# Défis: View standard (semaines 1..11)
# ---------------------------------------
class DefiValidateView(discord.ui.View):
    def __init__(self, *, author: discord.Member, services, code: str, wk: int, wk_key: str, wk_label: str,
                 row_i: int, row: dict, tasks: list[str], vip_pseudo: str):
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
        self.message: discord.Message | None = None
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

        # récompense uniquement au 1er défi validé
        if done_before == 0 and done_after > 0:
            ok1, _ = domain.add_points_by_action(self.s, self.code, "BLEETER", 1, interaction.user.id, f"1er défi validé ({self.wk_key})", author_is_hg=True)
            ok2, _ = domain.add_points_by_action(self.s, self.code, "DEFI_HEBDO", 1, interaction.user.id, f"1er défi validé ({self.wk_key})", author_is_hg=True)
            awarded = bool(ok1 and ok2)

        # si 4/4 -> completed + bonus
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


# ---------------------------------------
# Défis: View semaine 12 (12 choix max 4)
# ---------------------------------------
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
                 row_i: int, row: dict, choices: list[str], vip_pseudo: str):
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

        self.selected: Set[int] = set()
        self.message: discord.Message | None = None

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

