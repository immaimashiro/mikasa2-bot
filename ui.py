# ui.py
# -*- coding: utf-8 -*-

from __future__ import annotations
from typing import Dict, List, Tuple, Optional

import discord
from discord import ui

import domain
from services import catify, now_fr


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
    def __init__
