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

class SaleCategorySelect(discord.ui.Select):
    def __init__(self):
        options = [discord.SelectOption(label=label, value=value) for label, value in CATEGORIES]
        super().__init__(placeholder="Choisir une catégorie d’articles…", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        view: SaleWindowView = self.view  # type: ignore
        view.category = self.values[0]
        await view.refresh(interaction)

class SaleWindowView(discord.ui.View):
    """
    Une seule UI pour saisir:
    - ACHAT (articles normaux)
    - ACHAT_LIMITEE (articles VIP/limités)
    Avec + / - et un Valider.
    """
    def __init__(
        self,
        *,
        author: discord.Member,
        services,
        code_vip: str,
        vip_pseudo: str,
        author_is_hg: bool
    ):
        super().__init__(timeout=180)
        self.author = author
        self.s = services
        self.code = domain.normalize_code(code_vip)
        self.vip_pseudo = vip_pseudo
        self.author_is_hg = author_is_hg

        self.qty_normal = 0
        self.qty_limited = 0
        self.category = "TSHIRT"
        self.note = ""

        self.add_item(SaleCategorySelect())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(catify("😾 Pas touche. Ouvre ta propre fenêtre de vente."), ephemeral=True)
            return False
        return True

    def embed(self) -> discord.Embed:
        desc = (
            f"👤 **{self.vip_pseudo}** • `{self.code}`\n"
            f"🏷️ Catégorie: **{self.category}**\n\n"
            f"🛍️ **ACHAT (normal)**: **{self.qty_normal}**\n"
            f"🎟️ **ACHAT_LIMITEE**: **{self.qty_limited}**\n\n"
            f"📝 Note: {self.note or '_aucune_'}\n"
            f"Quand c’est bon: clique **VALIDER**."
        )
        e = discord.Embed(title="🧾 Fenêtre de vente SubUrban", description=desc, color=discord.Color.blurple())
        e.set_footer(text="Astuce: tu peux faire + / - au fur et à mesure que tu sors les vêtements.")
        return e

    async def refresh(self, interaction: discord.Interaction):
        # met à jour l’affichage sans recréer le message
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    def _sync_buttons(self):
        # désactive valider si rien
        for item in self.children:
            if isinstance(item, SaleValidateButton):
                item.disabled = (self.qty_normal <= 0 and self.qty_limited <= 0)

    @discord.ui.button(label="➕ Normal", style=discord.ButtonStyle.secondary)
    async def plus_normal(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.qty_normal += 1
        await self.refresh(interaction)

    @discord.ui.button(label="➖ Normal", style=discord.ButtonStyle.secondary)
    async def minus_normal(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.qty_normal = max(0, self.qty_normal - 1)
        await self.refresh(interaction)

    @discord.ui.button(label="➕ Limitée", style=discord.ButtonStyle.secondary)
    async def plus_limited(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.qty_limited += 1
        await self.refresh(interaction)

    @discord.ui.button(label="➖ Limitée", style=discord.ButtonStyle.secondary)
    async def minus_limited(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.qty_limited = max(0, self.qty_limited - 1)
        await self.refresh(interaction)

    @discord.ui.button(label="✍️ Note", style=discord.ButtonStyle.primary)
    async def set_note(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = SaleNoteModal(view=self)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="✅ VALIDER", style=discord.ButtonStyle.success)
    async def validate(self, interaction: discord.Interaction, button: discord.ui.Button):
        # remplacé par bouton dédié pour le type-check
        pass

    async def finalize(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        # reason uniforme pour les 2 actions
        # (tu peux filtrer plus tard via tag vente:)
        reason = f"vente:{self.category}"
        if self.note:
            reason += f" note:{self.note.replace(' ', '_')[:40]}"

        results = []
        lvl_up = None

        if self.qty_normal > 0:
            ok, res = domain.add_points_by_action(
                self.s, self.code, "ACHAT", self.qty_normal,
                interaction.user.id, reason, author_is_hg=self.author_is_hg
            )
            if not ok:
                return await interaction.followup.send(f"❌ ACHAT: {res}", ephemeral=True)
            results.append(("ACHAT", res))

        if self.qty_limited > 0:
            ok, res = domain.add_points_by_action(
                self.s, self.code, "ACHAT_LIMITEE", self.qty_limited,
                interaction.user.id, reason, author_is_hg=self.author_is_hg
            )
            if not ok:
                return await interaction.followup.send(f"❌ ACHAT_LIMITEE: {res}", ephemeral=True)
            results.append(("ACHAT_LIMITEE", res))

        # calcul simple du niveau up: on regarde le dernier res
        # (si les deux ont été appliqués, le second reflète le total final)
        last = results[-1][1] if results else None
        if last:
            delta, new_points, old_level, new_level = last
            if new_level > old_level:
                lvl_up = (old_level, new_level)

        # verrouille l’UI
        for item in self.children:
            item.disabled = True

        # message recap
        lines = [f"✅ Vente enregistrée pour **{self.vip_pseudo}** (`{self.code}`)"]
        for name, res in results:
            delta, new_points, old_level, new_level = res
            lines.append(f"• **{name}**: **+{delta} pts** → total **{new_points}** (niv {new_level})")

        if lvl_up:
            lines.append(f"🎊 Level up: **{lvl_up[0]} → {lvl_up[1]}**")

        await interaction.message.edit(embed=self.embed(), view=self)
        await interaction.followup.send("\n".join(lines), ephemeral=True)

class SaleValidateButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="✅ VALIDER", style=discord.ButtonStyle.success)

    async def callback(self, interaction: discord.Interaction):
        view: SaleWindowView = self.view  # type: ignore
        await view.finalize(interaction)

class SaleNoteModal(discord.ui.Modal, title="Note de vente"):
    note = discord.ui.TextInput(label="Note (optionnel)", required=False, max_length=80)

    def __init__(self, view: SaleWindowView):
        super().__init__()
        self._view = view

    async def on_submit(self, interaction: discord.Interaction):
        self._view.note = str(self.note.value or "").strip()
        await self._view.refresh(interaction)


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
