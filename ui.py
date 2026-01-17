# ui.py
# -*- coding: utf-8 -*-

from __future__ import annotations
import discord
from typing import Optional, Any, Dict

from services import catify, normalize_code, display_name
from domain import add_points_by_action, find_vip_row_by_code_or_pseudo


class SaleView(discord.ui.View):
    def __init__(
        self,
        *,
        author: discord.Member,
        sheets,
        tz,
        employee_allowed_actions: set[str],
        code_or_pseudo: str,
        author_is_hg: bool
    ):
        super().__init__(timeout=180)
        self.author = author
        self.sheets = sheets
        self.tz = tz
        self.employee_allowed_actions = employee_allowed_actions
        self.author_is_hg = author_is_hg

        self.query = code_or_pseudo
        self.code: Optional[str] = None
        self.pseudo: str = "VIP"

        self.qty_normal = 0
        self.qty_limited = 0
        self.reason = ""

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(catify("😾 Lance ta propre fenêtre de vente."), ephemeral=True)
            return False
        return True

    async def init_resolve(self):
        row_i, vip = await find_vip_row_by_code_or_pseudo(self.sheets, self.query)
        if not row_i or not vip:
            raise RuntimeError("VIP introuvable.")
        self.code = normalize_code(str(vip.get("code_vip", "")))
        self.pseudo = display_name(vip.get("pseudo", "VIP"))

    def embed(self) -> discord.Embed:
        code = self.code or "—"
        e = discord.Embed(
            title="🧾 Fenêtre de vente",
            description=(
                f"👤 **{self.pseudo}** (`{code}`)\n\n"
                f"🛍️ **ACHAT (normal)**: **{self.qty_normal}**\n"
                f"✨ **ACHAT_LIMITEE**: **{self.qty_limited}**\n\n"
                f"📝 Note: {self.reason if self.reason else '_aucune_'}\n\n"
                f"Valide quand tu es prêt. Mikasa compte les cintres. 🐾"
            )
        )
        return e

    async def refresh(self, interaction: discord.Interaction):
        # activer/désactiver VALIDATE si 0/0
        for item in self.children:
            if isinstance(item, discord.ui.Button) and item.custom_id == "sale_validate":
                item.disabled = (self.qty_normal <= 0 and self.qty_limited <= 0)
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="+ Normal", style=discord.ButtonStyle.success, custom_id="sale_plus_normal")
    async def plus_normal(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.qty_normal += 1
        await self.refresh(interaction)

    @discord.ui.button(label="- Normal", style=discord.ButtonStyle.secondary, custom_id="sale_minus_normal")
    async def minus_normal(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.qty_normal = max(0, self.qty_normal - 1)
        await self.refresh(interaction)

    @discord.ui.button(label="+ Limitée", style=discord.ButtonStyle.success, custom_id="sale_plus_limited")
    async def plus_limited(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.qty_limited += 1
        await self.refresh(interaction)

    @discord.ui.button(label="- Limitée", style=discord.ButtonStyle.secondary, custom_id="sale_minus_limited")
    async def minus_limited(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.qty_limited = max(0, self.qty_limited - 1)
        await self.refresh(interaction)

    @discord.ui.button(label="📝 Note", style=discord.ButtonStyle.primary, custom_id="sale_note")
    async def note(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = SaleNoteModal(view=self)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="✅ VALIDER", style=discord.ButtonStyle.danger, custom_id="sale_validate")
    async def validate(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        if not self.code:
            return await interaction.followup.send("❌ VIP introuvable (code).", ephemeral=True)

        reason = self.reason.strip()
        # petite convention: tu peux mettre event:xxx ici, ou “vente:pull” etc
        if reason and not reason.lower().startswith(("event:", "poche:")):
            reason = f"vente:{reason.replace(' ', '_')}"

        results = []
        # applique les 2 actions si besoin
        if self.qty_normal > 0:
            ok, res = await add_points_by_action(
                self.sheets, self.code, "ACHAT", self.qty_normal,
                interaction.user.id, reason, self.author_is_hg, self.employee_allowed_actions, self.tz
            )
            results.append(("ACHAT", ok, res))

        if self.qty_limited > 0:
            ok, res = await add_points_by_action(
                self.sheets, self.code, "ACHAT_LIMITEE", self.qty_limited,
                interaction.user.id, reason, self.author_is_hg, self.employee_allowed_actions, self.tz
            )
            results.append(("ACHAT_LIMITEE", ok, res))

        # build message
        lines = [f"✅ Vente enregistrée pour **{self.pseudo}** (`{self.code}`)"]
        for action, ok, res in results:
            if ok:
                delta, new_points, old_level, new_level = res
                lines.append(f"• **{action}** x{self.qty_normal if action=='ACHAT' else self.qty_limited} → **+{delta} pts** (total {new_points}, lvl {new_level})")
            else:
                lines.append(f"• ❌ **{action}**: {res}")

        # disable view
        for item in self.children:
            item.disabled = True

        await interaction.message.edit(embed=self.embed(), view=self)
        await interaction.followup.send("\n".join(lines), ephemeral=True)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class SaleNoteModal(discord
