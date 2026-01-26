# hunt_ui.py
from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple
import discord
from discord import ui

import hunt_services as hs
import hunt_domain as hd
from hunt_data import AVATARS, get_avatar, avatar_image_url, rarity_rank, format_player_title

from services import catify, now_iso

# -------------------------
# petits helpers d’edit safe
# -------------------------

async def _edit(interaction: discord.Interaction, *, content: Optional[str] = None, embed: Optional[discord.Embed] = None, view: Optional[discord.ui.View] = None):
    try:
        if interaction.response.is_done():
            await interaction.message.edit(content=content, embed=embed, view=view)
        else:
            await interaction.response.edit_message(content=content, embed=embed, view=view)
    except Exception:
        pass

def _money(n: int) -> str:
    return f"{int(n)} 💵"

def _rarity_label(r: str) -> str:
    r = (r or "").lower().strip()
    return {
        "common": "Common",
        "uncommon": "Uncommon",
        "rare": "Rare",
        "epic": "Epic",
        "legendary": "Legendary",
    }.get(r, r or "Common")

# ==========================================================
# HUB HUNT (message unique, tout se fait dessus)
# ==========================================================
class HuntHubView(ui.View):
    def __init__(self, *, sheets, discord_id: int, code_vip: str, pseudo: str, is_employee: bool):
        super().__init__(timeout=10 * 60)
        self.sheets = sheets
        self.discord_id = int(discord_id)
        self.code_vip = (code_vip or "").strip()
        self.pseudo = (pseudo or "").strip() or self.code_vip
        self.is_employee = bool(is_employee)

        self.p_row_i, self.player = hs.ensure_player(
            sheets,
            discord_id=self.discord_id,
            vip_code=self.code_vip,
            pseudo=self.pseudo,
            is_employee=self.is_employee
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.discord_id:
            await interaction.response.send_message(catify("😾 Pas touche. Lance ton propre HUNT."), ephemeral=True)
            return False
        return True

    def build_embed(self) -> discord.Embed:
        row_i, row = hs.get_player_row(self.sheets, self.discord_id)
        row = row or self.player
        dollars = hs.player_money_get(row)
        avatar_tag = str(row.get("avatar_tag", "")).strip() or "?"
        ally = str(player.get("ally_tag", "")).strip()
        e.add_field(name="🤝 Allié", value=(ally if ally else "Aucun"), inline=False)

        e = discord.Embed(
            title="🗺️ HUNT",
            description=(
                f"👤 **{self.pseudo}**\n"
                f"🎴 VIP: `{self.code_vip}`\n"
                f"🧍 Avatar: **{avatar_tag}**\n"
                f"💰 Argent: **{_money(dollars)}**\n\n"
                "Choisis une action :"
            ),
            color=discord.Color.dark_purple()
        )
        url = str(row.get("avatar_url", "")).strip()
        if url:
            e.set_thumbnail(url=url)
        e.set_footer(text="Tout se met à jour ici. 🐾")
        return e

    @ui.button(label="🎭 Choisir mon Avatar", style=discord.ButtonStyle.primary)
    async def btn_avatar(self, interaction: discord.Interaction, button: ui.Button):
        view = HuntAvatarView(parent=self)
        await _edit(interaction, embed=view.build_embed(), view=view)

    @ui.button(label="🛒 Shop", style=discord.ButtonStyle.secondary)
    async def btn_shop(self, interaction: discord.Interaction, button: ui.Button):
        view = HuntShopView(parent=self)
        await _edit(interaction, embed=view.build_embed(), view=view)

    @ui.button(label="🎒 Inventory", style=discord.ButtonStyle.secondary)
    async def btn_inv(self, interaction: discord.Interaction, button: ui.Button):
        view = HuntInventoryView(parent=self)
        await _edit(interaction, embed=view.build_embed(), view=view)

    @ui.button(label="✅ Fermer", style=discord.ButtonStyle.success)
    async def btn_close(self, interaction: discord.Interaction, button: ui.Button):
        for it in self.children:
            it.disabled = True
        await _edit(interaction, content="✅ HUNT fermé.", embed=None, view=self)

# ==========================================================
# AVATAR (Select + Confirm + annonce publique)
# ==========================================================
# hunt_ui.py (extrait)

class AvatarSelect(ui.Select):
    def __init__(self, view: "HuntAvatarView"):
        options = []
        for a in AVATARS:
            options.append(discord.SelectOption(
                label=a.name,
                value=a.tag,
                description=a.short[:100],
            ))
        super().__init__(placeholder="Choisis ton avatar…", options=options, min_values=1, max_values=1)
        self.v = view

    async def callback(self, interaction: discord.Interaction):
        self.v.selected_tag = (self.values[0] or "").strip().upper()
        await _edit(interaction, embed=self.v.build_embed(), view=self.v)


class AvatarConfirmButton(ui.Button):
    def __init__(self, view: "HuntAvatarView"):
        super().__init__(label="✅ Confirmer", style=discord.ButtonStyle.success)
        self.v = view

    async def callback(self, interaction: discord.Interaction):
        tag = (self.v.selected_tag or "").strip().upper()
        if not tag:
            return await interaction.response.send_message("😾 Choisis d’abord un avatar.", ephemeral=True)

        # ACK rapide
        await interaction.response.defer(ephemeral=True)

        # --- 1) write Sheets (avatar_tag + avatar_url) ---
        a = get_avatar(tag)
        avatar_url = a.image if a else ""

        # si ton view a player_row_i et services:
        self.v.s.update_cell_by_header("HUNT_PLAYERS", self.v.player_row_i, "avatar_tag", tag)
        self.v.s.update_cell_by_header("HUNT_PLAYERS", self.v.player_row_i, "avatar_url", avatar_url)
        self.v.s.update_cell_by_header("HUNT_PLAYERS", self.v.player_row_i, "updated_at", now_iso())

        # --- 2) annonce publique ---
        title = format_player_title(self.v.pseudo, tag)
        try:
            await interaction.channel.send(f"📣 **{title}** a choisi son avatar : **[{tag}]**")
        except Exception:
            pass

        # --- 3) lock UI + refresh embed ---
        self.v.confirmed = True
        for item in self.v.children:
            item.disabled = True

        try:
            await interaction.message.edit(embed=self.v.build_embed(), view=self.v)
        except Exception:
            pass

        await interaction.followup.send(f"✅ Avatar confirmé : **[{tag}]**", ephemeral=True)


class HuntAvatarView(ui.View):
    def __init__(self, *, parent: "HuntHubView"):
        super().__init__(timeout=10 * 60)
        self.parent = parent
        self.sheets = parent.sheets
        self.discord_id = parent.discord_id
        self.code_vip = parent.code_vip
        self.pseudo = parent.pseudo
        self.selected_tag: Optional[str] = None
        self.confirmed = False

        self.add_item(AvatarSelect(self))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # empêche un autre joueur de cliquer
        if interaction.user.id != self.discord_id:
            await interaction.response.send_message(catify("😾 Pas touche. Lance ton propre /hunt."), ephemeral=True)
            return False
        return True

    def build_embed(self) -> discord.Embed:
        row_i, row = hs.get_player_row(self.sheets, self.discord_id)
        row = row or self.parent.player or {}

        current = str(row.get("avatar_tag", "")).strip().upper() or "?"
        pick = (self.selected_tag or current).strip().upper()

        e = discord.Embed(
            title="🎭 Choix d’Avatar",
            description=(
                f"👤 **{self.pseudo}**\n"
                f"Actuel: **[{current}]**\n"
                f"Sélection: **[{pick}]**\n\n"
                "Choisis dans la liste, puis confirme."
            ),
            color=discord.Color.blurple()
        )

        # image du perso sélectionné (ou actuel)
        img = avatar_image_url(pick)
        if img:
            e.set_image(url=img)

        if self.confirmed:
            e.add_field(name="✅ Confirmé", value=f"Avatar défini sur **[{pick}]**", inline=False)
            e.set_footer(text="Mikasa note ça dans le registre. 🐾")
        else:
            e.set_footer(text="Tu confirmes = c’est gravé. 🐾")

        return e

    @ui.button(label="✅ Confirmer", style=discord.ButtonStyle.success)
    async def btn_confirm(self, interaction: discord.Interaction, button: ui.Button):
        tag = (self.selected_tag or "").strip().upper()
        if not tag:
            return await interaction.response.send_message(catify("😾 Choisis un avatar d’abord."), ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        # player row
        row_i, row = hs.get_player_row(self.sheets, self.discord_id)
        if not row_i or not row:
            row_i, row = hs.ensure_player(
                self.sheets,
                discord_id=self.discord_id,
                vip_code=self.code_vip,
                pseudo=self.pseudo,
                is_employee=self.parent.is_employee
            )

        url = avatar_image_url(tag)

        # write Sheets (avatar_tag + avatar_url)
        hs.player_set_avatar(self.sheets, int(row_i), tag=tag, url=url)

        # annonce publique
        try:
            title = format_player_title(self.pseudo, tag)  # si tu utilises hunt_data.py
            await interaction.channel.send(f"📣 **{title}** a choisi son avatar : **[{tag}]**")
        except Exception:
            try:
                await interaction.channel.send(f"📣 <@{self.discord_id}> a choisi **[{tag}]** pour HUNT.")
            except Exception:
                pass

        # log
        hs.log(
            self.sheets,
            discord_id=self.discord_id,
            code_vip=self.code_vip,
            kind="avatar",
            message=f"avatar set {tag}",
            meta={"tag": tag, "url": url}
        )

        # lock UI
        self.confirmed = True
        for it in self.children:
            it.disabled = True

        # refresh message principal
        try:
            await interaction.message.edit(embed=self.build_embed(), view=self)
        except Exception:
            pass

        await interaction.followup.send(catify(f"✅ Avatar confirmé : **[{tag}]**"), ephemeral=True)

    @ui.button(label="↩️ Retour", style=discord.ButtonStyle.secondary)
    async def btn_back(self, interaction: discord.Interaction, button: ui.Button):
        await _edit(interaction, embed=self.parent.build_embed(), view=self.parent)

# -------------------------
# petites utilitaires
# -------------------------
def _money(n: int) -> str:
    try:
        n = int(n)
    except Exception:
        n = 0
    return f"{n:,}".replace(",", " ")

def _power_lines(power: Dict[str, Any]) -> str:
    if not power:
        return "Aucun bonus."
    parts = []
    for k, v in power.items():
        parts.append(f"• {k}: **{v}**")
    return "\n".join(parts)

def _safe_str(x: Any) -> str:
    return str(x or "").strip()

def _edit(interaction: discord.Interaction, *, content: Optional[str] = None, embed=None, view=None):
    # ton helper existe déjà chez toi normalement
    return interaction.response.edit_message(content=content, embed=embed, view=view)


# ==========================================================
# SHOP
# ==========================================================
class HuntShopItemSelect(ui.Select):
    def __init__(self, view: "HuntShopView"):
        options: List[discord.SelectOption] = []
        for item in view.items[:25]:
            iid = _safe_str(item.get("item_id"))
            name = _safe_str(item.get("name")) or iid
            price = hs.item_price(item)
            rarity = _safe_str(item.get("rarity"))
            typ = _safe_str(item.get("type"))
            label = f"{name}"
            desc = f"{typ} | {rarity} | {price}$"
            options.append(discord.SelectOption(label=label[:100], value=iid, description=desc[:100]))

        super().__init__(placeholder="Choisis un item à acheter…", options=options, min_values=1, max_values=1)
        self.v = view

    async def callback(self, interaction: discord.Interaction):
        iid = (self.values[0] or "").strip()
        self.v.selected_item_id = iid
        self.v.mode = "preview"
        await _edit(interaction, embed=self.v.build_embed(), view=self.v)


class HuntShopView(ui.View):
    def __init__(self, *, parent: "HuntHubView"):
        super().__init__(timeout=10 * 60)
        self.parent = parent
        self.sheets = parent.sheets
        self.discord_id = parent.discord_id
        self.code_vip = parent.code_vip
        self.pseudo = parent.pseudo

        self.mode: str = "list"     # list | preview
        self.selected_item_id: Optional[str] = None

        # charge items
        self.items: List[Dict[str, Any]] = hs.items_all(self.sheets)
        # shop = items avec price > 0
        self.items = [it for it in self.items if hs.item_price(it) > 0]

        self._rebuild()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await self.parent.interaction_check(interaction)

    def _rebuild(self):
        self.clear_items()

        if self.mode == "list":
            # select d'items + back
                self.add_item(HuntShopItemSelect(self))
            self.add_item(HuntBackToHubButton(self.parent))
            return

        # preview
        self.add_item(HuntShopBuyButton(self))
        self.add_item(HuntShopCancelButton(self))
        self.add_item(HuntBackToHubButton(self.parent))


    def build_embed(self) -> discord.Embed:
        row_i, row = hs.get_player_row(self.sheets, self.discord_id)
        row = row or self.parent.player or {}
        dollars = hs.player_money_get(row)

        if self.mode == "list":
            e = discord.Embed(
                title="🛒 HUNT Shop",
                description=(
                    f"👤 **{self.pseudo}**\n"
                    f"💰 Argent: **{_money(dollars)}$**\n\n"
                    "Sélectionne un item pour voir l’aperçu et confirmer l’achat."
                ),
                color=discord.Color.dark_purple()
            )
            e.set_footer(text="Le shop se met à jour ici. 🐾")
            return e

        # preview
        item = hs.item_get(self.sheets, self.selected_item_id or "")
        if not item:
            e = discord.Embed(title="🛒 HUNT Shop", description="😾 Item introuvable.", color=discord.Color.red())
            self.mode = "list"
            self._rebuild()
            return e

        name = _safe_str(item.get("name")) or _safe_str(item.get("item_id"))
        iid = _safe_str(item.get("item_id"))
        price = hs.item_price(item)
        rarity = hs.item_rarity(item)
        typ = _safe_str(item.get("type"))
        desc = _safe_str(item.get("description"))
        power = hs.item_power(item)
        img = _safe_str(item.get("image_url"))

        e = discord.Embed(
            title=f"🛒 Achat: {name}",
            description=(
                f"🆔 `{iid}`\n"
                f"🏷️ Type: **{typ}**\n"
                f"✨ Rareté: **{rarity}**\n"
                f"💸 Prix: **{_money(price)}$**\n\n"
                f"**Effets**\n{_power_lines(power)}\n\n"
                f"{desc if desc else ''}"
            ).strip(),
            color=discord.Color.blurple()
        )
        if img:
            e.set_image(url=img)
        e.set_footer(text="Confirme pour acheter (x1). 🐾")
        return e


class HuntShopBuyButton(ui.Button):
    def __init__(self, view: HuntShopView):
        super().__init__(label="✅ Acheter (x1)", style=discord.ButtonStyle.success)
        self.v = view

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        item = hs.item_get(self.v.sheets, self.v.selected_item_id or "")
        if not item:
            return await interaction.followup.send(catify("😾 Item introuvable."), ephemeral=True)

        price = hs.item_price(item)
        iid = _safe_str(item.get("item_id"))
        name = _safe_str(item.get("name")) or iid

        p_row_i, player = hs.get_player_row(self.v.sheets, self.v.discord_id)
        if not p_row_i or not player:
            p_row_i, player = hs.ensure_player(
                self.v.sheets,
                discord_id=self.v.discord_id,
                vip_code=self.v.code_vip,
                pseudo=self.v.pseudo,
                is_employee=self.v.parent.is_employee
            )

        money = hs.player_money_get(player)
        if money < price:
            return await interaction.followup.send(catify(f"😾 Pas assez d’argent. Il te manque **{_money(price - money)}$**."), ephemeral=True)

        inv = hs.inv_load(str(player.get("inventory_json", "")))
        hs.inv_add(inv, iid, 1)

        new_money = money - price

        self.v.sheets.update_cell_by_header(hs.T_PLAYERS, int(p_row_i), "hunt_dollars", str(int(new_money)))
        self.v.sheets.update_cell_by_header(hs.T_PLAYERS, int(p_row_i), "inventory_json", hs.inv_dump(inv))
        self.v.sheets.update_cell_by_header(hs.T_PLAYERS, int(p_row_i), "updated_at", now_iso())

        hs.log(self.v.sheets, discord_id=self.v.discord_id, code_vip=self.v.code_vip, kind="shop_buy",
               message=f"buy {iid} x1", meta={"item_id": iid, "price": price})

        # UI refresh: on repasse en liste
        self.v.mode = "list"
        self.v.selected_item_id = None
        self.v._rebuild()
        try:
            await interaction.message.edit(embed=self.v.build_embed(), view=self.v)
        except Exception:
            pass

        await interaction.followup.send(catify(f"✅ Acheté: **{name}** (x1)"), ephemeral=True)


class HuntShopCancelButton(ui.Button):
    def __init__(self, view: HuntShopView):
        super().__init__(label="↩️ Retour liste", style=discord.ButtonStyle.secondary)
        self.v = view

    async def callback(self, interaction: discord.Interaction):
        self.v.mode = "list"
        self.v.selected_item_id = None
        self.v._rebuild()
        await _edit(interaction, embed=self.v.build_embed(), view=self.v)


class HuntBackToHubButton(ui.Button):
    def __init__(self, parent: "HuntHubView"):
        super().__init__(label="🏠 Hub", style=discord.ButtonStyle.secondary)
        self.parent = parent

    async def callback(self, interaction: discord.Interaction):
        await _edit(interaction, embed=self.parent.build_embed(), view=self.parent)


# ==========================================================
# INVENTORY + EQUIP
# ==========================================================
class HuntInvOpenKeyButton(ui.Button):
    def __init__(self, view: "HuntInventoryView"):
        super().__init__(label="🔑 Ouvrir une clé", style=discord.ButtonStyle.primary)
        self.v = view

    async def callback(self, interaction: discord.Interaction):
        # on passe en mode confirm (UI full)
        self.v.mode = "key_confirm"
        self.v._rebuild()
        await interaction.response.edit_message(embed=self.v.build_embed(), view=self.v)


class HuntKeyConfirmOpenButton(ui.Button):
    def __init__(self, view: "HuntInventoryView"):
        super().__init__(label="✅ Ouvrir maintenant", style=discord.ButtonStyle.success)
        self.v = view

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        # reload player
        p_row_i, player = hs.get_player_row(self.v.sheets, self.v.discord_id)
        if not p_row_i or not player:
            return await interaction.followup.send(catify("😾 Profil introuvable."), ephemeral=True)

        inv = hs.inv_load(str(player.get("inventory_json", "")))
        n_keys = hs.inv_count(inv, "key")
        g_keys = hs.inv_count(inv, "gold_key")

        if n_keys <= 0 and g_keys <= 0:
            # retour list
            self.v.mode = "list"
            self.v._rebuild()
            try:
                await interaction.message.edit(embed=self.v.build_embed(), view=self.v)
            except Exception:
                pass
            return await interaction.followup.send(catify("😾 Tu n’as aucune clé."), ephemeral=True)

        # choix: gold d’abord
        key_type = "gold_key" if g_keys > 0 else "key"

        # on consomme 1 clé
        ok = hs.inv_remove(inv, key_type, 1)
        if not ok:
            return await interaction.followup.send(catify("😾 Impossible de consommer la clé."), ephemeral=True)

        # loot (depuis HUNT_ITEMS)
        items = hs.items_all(self.v.sheets)
        res = hd.loot_open_key(items, key_type=key_type)

        item_id = str(res.get("item_id", "")).strip()
        item_name = str(res.get("item_name", "")).strip() or item_id
        qty = int(res.get("qty", 0) or 0)
        rarity = str(res.get("rarity", "")).strip()

        if item_id and qty > 0:
            hs.inv_add(inv, item_id, qty)

        # update player
        self.v.sheets.update_cell_by_header(hs.T_PLAYERS, int(p_row_i), "inventory_json", hs.inv_dump(inv))
        self.v.sheets.update_cell_by_header(hs.T_PLAYERS, int(p_row_i), "updated_at", now_iso())

        # log HUNT_KEYS: on essaye de lier à une ligne "claim" non ouverte si elle existe.
        # sinon, on ne bloque pas: on loggue juste HUNT_LOG (le claim staff peut être décalé dans le temps).
        opened_at = now_iso()
        key_rows = hs.keys_find_unopened_for_player(self.v.sheets, discord_id=self.v.discord_id)

        if key_rows:
            key_row_i, key_row = key_rows[0]
            meta = {"opened_via": "inventory_ui", "key_type": key_type}
            try:
                hs.keys_log_open_result(
                    self.v.sheets,
                    key_row_i=key_row_i,
                    opened_at=opened_at,
                    item_id=item_id,
                    qty=qty,
                    rarity=rarity,
                    item_name=item_name,
                    meta=meta
                )
            except Exception:
                pass

        hs.log(
            self.v.sheets,
            discord_id=self.v.discord_id,
            code_vip=self.v.code_vip,
            kind="key_open",
            message=f"open {key_type} -> {item_id} x{qty} ({rarity})",
            meta={"key_type": key_type, "item_id": item_id, "qty": qty, "rarity": rarity}
        )

        # UI: on repasse en list + embed “résultat” en public dans le même message
        self.v.mode = "key_result"
        self.v.last_key_result = {"key_type": key_type, "item_id": item_id, "item_name": item_name, "qty": qty, "rarity": rarity}
        self.v._rebuild()
        try:
            await interaction.message.edit(embed=self.v.build_embed(), view=self.v)
        except Exception:
            pass

        await interaction.followup.send(catify("✅ Clé ouverte."), ephemeral=True)


class HuntKeyCancelOpenButton(ui.Button):
    def __init__(self, view: "HuntInventoryView"):
        super().__init__(label="↩️ Retour inventaire", style=discord.ButtonStyle.secondary)
        self.v = view

    async def callback(self, interaction: discord.Interaction):
        self.v.mode = "list"
        self.v._rebuild()
        await interaction.response.edit_message(embed=self.v.build_embed(), view=self.v)


class HuntInvItemSelect(ui.Select):
    def __init__(self, view: "HuntInventoryView"):
        options: List[discord.SelectOption] = []
        for iid, qty in view.inv_list[:25]:
            item = hs.item_get(view.sheets, iid) or {}
            name = _safe_str(item.get("name")) or iid
            typ = _safe_str(item.get("type")) or "item"
            rarity = _safe_str(item.get("rarity"))
            options.append(discord.SelectOption(
                label=f"{name} x{qty}"[:100],
                value=iid,
                description=f"{typ} | {rarity}"[:100]
            ))

        super().__init__(placeholder="Choisis un item…", options=options or [discord.SelectOption(label="(vide)", value="__empty__", description="")], min_values=1, max_values=1)
        self.v = view
        if not options:
            self.disabled = True

    async def callback(self, interaction: discord.Interaction):
        val = (self.values[0] or "").strip()
        if val == "__empty__":
            return await interaction.response.send_message(catify("😾 Inventaire vide."), ephemeral=True)
        self.v.selected_item_id = val
        self.v.mode = "preview"
        self.v._rebuild()
        await _edit(interaction, embed=self.v.build_embed(), view=self.v)

class HuntInvUseButton(ui.Button):
    def __init__(self, view: "HuntInventoryView"):
        super().__init__(label="🩹 Utiliser", style=discord.ButtonStyle.primary)
        self.v = view

    async def callback(self, interaction: discord.Interaction):
        iid = (self.v.selected_item_id or "").strip()
        item = hs.item_get(self.v.sheets, iid)
        if not item:
            return await interaction.response.send_message(catify("😾 Item introuvable."), ephemeral=True)

        typ = hs.item_type(item)
        if typ != "consumable":
            return await interaction.response.send_message(catify("😾 Cet item ne peut pas être utilisé."), ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        # reload player
        p_row_i, player = hs.get_player_row(self.v.sheets, self.v.discord_id)
        if not p_row_i or not player:
            return await interaction.followup.send(catify("😾 Profil introuvable."), ephemeral=True)

        inv = hs.inv_load(str(player.get("inventory_json", "")))
        if hs.inv_count(inv, iid) <= 0:
            return await interaction.followup.send(catify("😾 Tu ne l’as plus."), ephemeral=True)

        # applique effet
        res = hd.consumable_apply(player, item)
        healed = int(res.get("healed", 0) or 0)
        msg = str(res.get("msg", "")).strip()

        # maj HP
        if healed > 0:
            hp = hs.player_hp_get(player)
            new_hp = max(0, hp + healed)
            hs.player_hp_set(self.v.sheets, int(p_row_i), new_hp)

        # consomme 1 item
        hs.inv_remove(inv, iid, 1)
        self.v.sheets.update_cell_by_header(hs.T_PLAYERS, int(p_row_i), "inventory_json", hs.inv_dump(inv))
        self.v.sheets.update_cell_by_header(hs.T_PLAYERS, int(p_row_i), "updated_at", now_iso())

        name = _safe_str(item.get("name")) or iid
        hs.log(
            self.v.sheets,
            discord_id=self.v.discord_id,
            code_vip=self.v.code_vip,
            kind="use_item",
            message=f"use {iid}",
            meta={"item_id": iid, "healed": healed}
        )

        # refresh UI
        self.v.mode = "list"
        self.v.selected_item_id = None
        self.v._rebuild()
        try:
            await interaction.message.edit(embed=self.v.build_embed(), view=self.v)
        except Exception:
            pass

        await interaction.followup.send(catify(f"🩹 **{name}** utilisé. {msg}"), ephemeral=True)

class HuntInventoryView(ui.View):
    def __init__(self, *, parent: "HuntHubView"):
        super().__init__(timeout=10 * 60)
        self.parent = parent
        self.sheets = parent.sheets
        self.discord_id = parent.discord_id
        self.code_vip = parent.code_vip
        self.pseudo = parent.pseudo

        self.mode: str = "list"  # list | preview | equip_confirm
        self.selected_item_id: Optional[str] = None
        self.last_key_result: Optional[Dict[str, Any]] = None

        self.inv_list: List[Tuple[str, int]] = []
        self._reload_state()
        self._rebuild()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await self.parent.interaction_check(interaction)

    def _reload_state(self):
        p_row_i, player = hs.get_player_row(self.sheets, self.discord_id)
        player = player or self.parent.player or {}
        inv = hs.inv_load(str(player.get("inventory_json", "")))

        # inv dict -> list triée
        items = []
        if isinstance(inv, dict):
            for k, v in inv.items():
                try:
                    q = int(v)
                except Exception:
                    q = 0
                if q > 0:
                    items.append((str(k), q))
        items.sort(key=lambda t: t[0].lower())
        self.inv_list = items

    def _rebuild(self):
        self.clear_items()

        if self.mode == "list":
            self.add_item(HuntInvOpenKeyButton(self))
            self.add_item(HuntInventorySelect(self))  # si tu as un select inventory
            self.add_item(HuntBackToHubButton(self.parent))
            return

        if self.mode == "key_confirm":
            self.add_item(HuntKeyConfirmOpenButton(self))
            self.add_item(HuntKeyCancelOpenButton(self))
            self.add_item(HuntBackToHubButton(self.parent))
            return

        if self.mode == "key_result":
            self.add_item(HuntInvBackButton(self))     # revient au list
            self.add_item(HuntInvOpenKeyButton(self))  # ré-ouvrir
            self.add_item(HuntBackToHubButton(self.parent))
            return

        if self.mode == "preview":
            self.add_item(HuntInvEquipButton(self))
            self.add_item(HuntInvUseButton(self))
            self.add_item(HuntInvUnequipButton(self))
            self.add_item(HuntInvBackButton(self))
            self.add_item(HuntBackToHubButton(self.parent))
            return

        # preview d'un item inventaire (si tu as un mode preview)
        self.add_item(HuntEquipButton(self))
        self.add_item(HuntInvBackButton(self))
        self.add_item(HuntBackToHubButton(self.parent))


    def build_embed(self) -> discord.Embed:
        p_row_i, player = hs.get_player_row(self.sheets, self.discord_id)
        player = player or self.parent.player or {}
        dollars = hs.player_money_get(player)

        equip = hs.equip_load(str(player.get("equipped_json", "")))
        inv = hs.inv_load(str(player.get("inventory_json", "")))
        k1 = hs.inv_count(inv, "key")
        k2 = hs.inv_count(inv, "gold_key")

        wpn = (equip.get("player_weapon") or "").strip()
        arm = (equip.get("player_armor") or "").strip()
        
        if self.mode == "list":
            lines = []
            for iid, qty in self.inv_list[:15]:
                item = hs.item_get(self.sheets, iid) or {}
                name = _safe_str(item.get("name")) or iid
                lines.append(f"• **{name}** x{qty} (`{iid}`)")
            if not lines:
                lines = ["*Vide*"]

            e = discord.Embed(
                title="🎒 HUNT Inventory",
                description=(
                    f"👤 **{self.pseudo}**\n"
                    f"💰 Argent: **{_money(dollars)}$**\n"
                    f"🗡️ Arme équipée: **{wpn or 'Aucune'}**\n"
                    f"🛡️ Armure équipée: **{arm or 'Aucune'}**\n\n"
                    f"🔑 Clés: **{k1}** | 🔑✨ Or: **{k2}**\n\n"
                    "Sélectionne un item pour le voir et l’équiper."
                ),
                color=discord.Color.dark_purple()
            )
            e.add_field(name="Contenu", value="\n".join(lines), inline=False)
            e.set_footer(text="Tout se met à jour ici. 🐾")
            return e
            
        if self.mode == "key_confirm":
            inv = hs.inv_load(str(player.get("inventory_json", "")))
            k1 = hs.inv_count(inv, "key")
            k2 = hs.inv_count(inv, "gold_key")
            e = discord.Embed(
                title="🔑 Ouvrir une clé",
                description=(
                    f"👤 **{self.pseudo}**\n"
                    f"🔑 Clés: **{k1}** | 🔑✨ Or: **{k2}**\n\n"
                    "Tu veux ouvrir **1 clé** maintenant ?\n"
                    "Priorité: **clé or** si tu en as."
                ),
                color=discord.Color.blurple()
            )
            e.set_footer(text="Confirme et le loot tombe. 🐾")
            return e

        if self.mode == "key_result":
            r = self.last_key_result or {}
            key_type = str(r.get("key_type", "")).strip()
            item_name = str(r.get("item_name", "")).strip() or str(r.get("item_id", "")).strip()
            qty = int(r.get("qty", 0) or 0)
            rarity = str(r.get("rarity", "")).strip()

            e = discord.Embed(
                title="🎁 Résultat de la clé",
                description=(
                    f"🔑 Type: **{key_type}**\n"
                    f"✨ Rareté: **{rarity}**\n\n"
                    f"Tu obtiens: **{item_name}** x**{qty}**"
                ),
                color=discord.Color.gold() if key_type == "gold_key" else discord.Color.green()
            )
            e.set_footer(text="Tu peux ré-ouvrir une clé ou revenir à l’inventaire. 🐾")
            return e

        # preview / equip_confirm
        iid = (self.selected_item_id or "").strip()
        item = hs.item_get(self.sheets, iid) or {}
        name = _safe_str(item.get("name")) or iid
        typ = _safe_str(item.get("type")) or "item"
        rarity = _safe_str(item.get("rarity"))
        desc = _safe_str(item.get("description"))
        power = hs.item_power(item)
        img = _safe_str(item.get("image_url"))

        title = "🎒 Item"
        if self.mode == "equip_confirm":
            title = "🧷 Équiper (confirmation)"

        e = discord.Embed(
            title=f"{title}: {name}",
            description=(
                f"🆔 `{iid}`\n"
                f"🏷️ Type: **{typ}**\n"
                f"✨ Rareté: **{rarity}**\n\n"
                f"**Effets**\n{_power_lines(power)}\n\n"
                f"{desc if desc else ''}"
            ).strip(),
            color=discord.Color.blurple()
        )
        if img:
            e.set_image(url=img)

        if self.mode == "preview":
            e.set_footer(text="Équiper uniquement si arme/armure. 🐾")
        else:
            e.set_footer(text="Confirme pour équiper sur ton perso. 🐾")

        return e


class HuntInvBackButton(ui.Button):
    def __init__(self, view: HuntInventoryView):
        super().__init__(label="↩️ Retour inventaire", style=discord.ButtonStyle.secondary)
        self.v = view

    async def callback(self, interaction: discord.Interaction):
        self.v.mode = "list"
        self.v.selected_item_id = None
        self.v._rebuild()
        await _edit(interaction, embed=self.v.build_embed(), view=self.v)


class HuntInvEquipButton(ui.Button):
    def __init__(self, view: HuntInventoryView):
        super().__init__(label="🧷 Équiper", style=discord.ButtonStyle.success)
        self.v = view

    async def callback(self, interaction: discord.Interaction):
        iid = (self.v.selected_item_id or "").strip()
        item = hs.item_get(self.v.sheets, iid)
        if not item:
            return await interaction.response.send_message(catify("😾 Item introuvable."), ephemeral=True)
        
        typ = hs.item_type(item)
        if typ not in ("weapon", "armor"):
            return await interaction.response.send_message(catify("😾 Cet item ne peut pas être équipé."), ephemeral=True)

        self.v.mode = "equip_confirm"
        self.v._rebuild()
        await _edit(interaction, embed=self.v.build_embed(), view=self.v)


class HuntEquipConfirmButton(ui.Button):
    def __init__(self, view: HuntInventoryView):
        super().__init__(label="✅ Confirmer l’équipement", style=discord.ButtonStyle.success)
        self.v = view

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        iid = (self.v.selected_item_id or "").strip()
        item = hs.item_get(self.v.sheets, iid)
        if not item:
            return await interaction.followup.send(catify("😾 Item introuvable."), ephemeral=True)

        typ = hs.item_type(item)
        if typ not in ("weapon", "armor"):
            return await interaction.followup.send(catify("😾 Cet item ne peut pas être équipé."), ephemeral=True)

        p_row_i, player = hs.get_player_row(self.v.sheets, self.v.discord_id)
        if not p_row_i or not player:
            p_row_i, player = hs.ensure_player(
                self.v.sheets,
                discord_id=self.v.discord_id,
                vip_code=self.v.code_vip,
                pseudo=self.v.pseudo,
                is_employee=self.v.parent.is_employee
            )

        inv = hs.inv_load(str(player.get("inventory_json", "")))
        if hs.inv_count(inv, iid) <= 0:
            return await interaction.followup.send(catify("😾 Tu ne l’as plus dans ton inventaire."), ephemeral=True)

        equip = hs.equip_load(str(player.get("equipped_json", "")))
        ally = str(player.get("ally_tag", "")).strip()
        # choix slot
        if ally:
        # priorité joueur, plus tard tu ajouteras un bouton switch
            slot = "player_weapon" if typ == "weapon" else "player_armor"
        else:
            slot = "player_weapon" if typ == "weapon" else "player_armor"

        equip = hs.equip_set_slot(equip, slot, iid)

        self.v.sheets.update_cell_by_header(hs.T_PLAYERS, int(p_row_i), "equipped_json", hs.equip_dump(equip))
        self.v.sheets.update_cell_by_header(hs.T_PLAYERS, int(p_row_i), "updated_at", now_iso())

        name = _safe_str(item.get("name")) or iid
        hs.log(self.v.sheets, discord_id=self.v.discord_id, code_vip=self.v.code_vip, kind="equip",
               message=f"equip {slot}={iid}", meta={"slot": slot, "item_id": iid})

        # refresh UI -> retour inventaire
        self.v.mode = "list"
        self.v.selected_item_id = None
        self.v._rebuild()
        try:
            await interaction.message.edit(embed=self.v.build_embed(), view=self.v)
        except Exception:
            pass

        await interaction.followup.send(catify(f"✅ Équipé: **{name}** → `{slot}`"), ephemeral=True)


class HuntEquipCancelButton(ui.Button):
    def __init__(self, view: HuntInventoryView):
        super().__init__(label="↩️ Annuler", style=discord.ButtonStyle.secondary)
        self.v = view

    async def callback(self, interaction: discord.Interaction):
        self.v.mode = "preview"
        self.v._rebuild()
        await _edit(interaction, embed=self.v.build_embed(), view=self.v)


class HuntInvUnequipButton(ui.Button):
    def __init__(self, view: HuntInventoryView):
        super().__init__(label="🧺 Déséquiper slot", style=discord.ButtonStyle.secondary)
        self.v = view

    async def callback(self, interaction: discord.Interaction):
        # déséquipe selon le type de l’item preview
        iid = (self.v.selected_item_id or "").strip()
        item = hs.item_get(self.v.sheets, iid) or {}
        typ = hs.item_type(item)

        if typ not in ("weapon", "armor"):
            return await interaction.response.send_message(catify("😾 Je ne sais pas quel slot déséquiper pour ça."), ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        p_row_i, player = hs.get_player_row(self.v.sheets, self.v.discord_id)
        if not p_row_i or not player:
            return await interaction.followup.send(catify("😾 Profil introuvable."), ephemeral=True)

        equip = hs.equip_load(str(player.get("equipped_json", "")))
        slot = "player_weapon" if typ == "weapon" else "player_armor"
        equip = hs.equip_set_slot(equip, slot, "")

        self.v.sheets.update_cell_by_header(hs.T_PLAYERS, int(p_row_i), "equipped_json", hs.equip_dump(equip))
        self.v.sheets.update_cell_by_header(hs.T_PLAYERS, int(p_row_i), "updated_at", now_iso())

        hs.log(self.v.sheets, discord_id=self.v.discord_id, code_vip=self.v.code_vip, kind="unequip",
               message=f"unequip {slot}", meta={"slot": slot})

        # refresh preview embed (reste sur preview)
        try:
            await interaction.message.edit(embed=self.v.build_embed(), view=self.v)
        except Exception:
            pass

        await interaction.followup.send(catify(f"✅ Slot vidé: `{slot}`"), ephemeral=True)


# ==========================================================
# SHOP
# ==========================================================
class ShopSelect(ui.Select):
    def __init__(self, view: "HuntShopView"):
        self.v = view
        options = self.v._shop_options()
        super().__init__(placeholder="Choisir un item à acheter…", options=options[:25], min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        self.v.selected_item_id = self.values[0]
        await _edit(interaction, embed=self.v.build_embed(), view=self.v)

class HuntShopView(ui.View):
    def __init__(self, *, parent: HuntHubView):
        super().__init__(timeout=10 * 60)
        self.parent = parent
        self.sheets = parent.sheets
        self.discord_id = parent.discord_id
        self.code_vip = parent.code_vip
        self.pseudo = parent.pseudo

        self.selected_item_id: Optional[str] = None
        self.add_item(ShopSelect(self))

    def _items_for_sale(self) -> List[Dict[str, Any]]:
        items = hs.items_all(self.sheets)
        sale = []
        for it in items:
            try:
                price = int(it.get("price", 0) or 0)
            except Exception:
                price = 0
            if price > 0:
                sale.append(it)
        sale.sort(key=lambda it: (rarity_rank(str(it.get("rarity","common"))), hs.item_price(it), str(it.get("name",""))))
        return sale

    def _shop_options(self) -> List[discord.SelectOption]:
        opts = []
        for it in self._items_for_sale():
            iid = str(it.get("item_id","")).strip()
            name = str(it.get("name", iid)).strip()
            rarity = _rarity_label(str(it.get("rarity","common")))
            price = hs.item_price(it)
            opts.append(discord.SelectOption(
                label=f"{name} ({price}💵)",
                value=iid,
                description=f"{rarity} • {str(it.get('type','')).strip()}"
            ))
        if not opts:
            opts = [discord.SelectOption(label="(Shop vide)", value="__none__", description="Ajoute des items dans HUNT_ITEMS")]
        return opts

    def build_embed(self) -> discord.Embed:
        # refresh money/player
        row_i, row = hs.get_player_row(self.sheets, self.discord_id)
        row = row or self.parent.player
        dollars = hs.player_money_get(row)

        e = discord.Embed(
            title="🛒 HUNT Shop",
            description=(
                f"👤 **{self.pseudo}** | 💰 **{_money(dollars)}**\n\n"
                "Sélectionne un item pour voir le détail, puis achète."
            ),
            color=discord.Color.dark_purple()
        )

        if self.selected_item_id and self.selected_item_id != "__none__":
            it = hs.item_by_id(self.sheets, self.selected_item_id)
            if it:
                price = hs.item_price(it)
                rarity = _rarity_label(str(it.get("rarity","common")))
                desc = str(it.get("description","")).strip() or "*Aucune description*"
                e.add_field(
                    name=f"📦 {it.get('name', self.selected_item_id)}",
                    value=f"Type: `{it.get('type','')}`\nRareté: **{rarity}**\nPrix: **{price}💵**\n\n{desc}",
                    inline=False
                )
                img = str(it.get("image_url","")).strip()
                if img:
                    e.set_thumbnail(url=img)

        e.set_footer(text="Achats instantanés. Inventaire mis à jour en direct. 🐾")
        return e

    async def _buy(self, interaction: discord.Interaction, qty: int):
        if not self.selected_item_id or self.selected_item_id in ("__none__", ""):
            return await interaction.response.send_message(catify("😾 Sélectionne un item."), ephemeral=True)
        it = hs.item_by_id(self.sheets, self.selected_item_id)
        if not it:
            return await interaction.response.send_message(catify("❌ Item introuvable."), ephemeral=True)

        price = hs.item_price(it)
        if price <= 0:
            return await interaction.response.send_message(catify("😾 Cet item n’est pas achetable."), ephemeral=True)

        row_i, row = hs.get_player_row(self.sheets, self.discord_id)
        if not row_i or not row:
            row_i, row = hs.ensure_player(self.sheets, discord_id=self.discord_id, vip_code=self.code_vip, pseudo=self.pseudo, is_employee=self.parent.is_employee)

        dollars = hs.player_money_get(row)
        total_cost = price * int(qty)
        if dollars < total_cost:
            return await interaction.response.send_message(catify(f"😾 Pas assez d’argent. Il te manque **{total_cost - dollars}💵**."), ephemeral=True)

        inv = hs.player_inv_get(row)
        hs.inv_add(inv, str(it.get("item_id","")).strip(), int(qty))
        hs.player_inv_set(self.sheets, int(row_i), inv)
        hs.player_money_set(self.sheets, int(row_i), dollars - total_cost)

        hs.log(self.sheets, discord_id=self.discord_id, code_vip=self.code_vip, kind="shop_buy",
               message=f"buy {it.get('item_id')} x{qty}", meta={"qty": qty, "cost": total_cost})

        await interaction.response.send_message(catify(f"✅ Acheté **{it.get('name')}** x{qty} pour **{total_cost}💵**."), ephemeral=True)
        await _edit(interaction, embed=self.build_embed(), view=self)

    @ui.button(label="🧾 Acheter x1", style=discord.ButtonStyle.success)
    async def btn_buy1(self, interaction: discord.Interaction, button: ui.Button):
        await self._buy(interaction, 1)

    @ui.button(label="🧾 Acheter x5", style=discord.ButtonStyle.success)
    async def btn_buy5(self, interaction: discord.Interaction, button: ui.Button):
        await self._buy(interaction, 5)

    @ui.button(label="↩️ Retour", style=discord.ButtonStyle.secondary)
    async def btn_back(self, interaction: discord.Interaction, button: ui.Button):
        await _edit(interaction, embed=self.parent.build_embed(), view=self.parent)

# ==========================================================
# INVENTORY + EQUIP + KEY OPEN
# ==========================================================
class InvSelect(ui.Select):
    def __init__(self, view: "HuntInventoryView"):
        self.v = view
        options = self.v._inv_options()
        super().__init__(placeholder="Choisir un item…", options=options[:25], min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        self.v.selected_item_id = self.values[0]
        await _edit(interaction, embed=self.v.build_embed(), view=self.v)

class HuntInventoryView(ui.View):
    def __init__(self, *, parent: HuntHubView):
        super().__init__(timeout=10 * 60)
        self.parent = parent
        self.sheets = parent.sheets
        self.discord_id = parent.discord_id
        self.code_vip = parent.code_vip
        self.pseudo = parent.pseudo

        self.selected_item_id: Optional[str] = None
        self.equip_target = "player"  # "player" or "ally"

        self.add_item(InvSelect(self))

    def _player_row(self) -> Tuple[int, Dict[str, Any]]:
        row_i, row = hs.get_player_row(self.sheets, self.discord_id)
        if not row_i or not row:
            row_i, row = hs.ensure_player(self.sheets, discord_id=self.discord_id, vip_code=self.code_vip, pseudo=self.pseudo, is_employee=self.parent.is_employee)
        return int(row_i), row

    def _inv_options(self) -> List[discord.SelectOption]:
        row_i, row = self._player_row()
        inv = hs.player_inv_get(row)
        opts = []
        # tri par name si possible
        for iid, qty in sorted(inv.items(), key=lambda kv: kv[0]):
            it = hs.item_by_id(self.sheets, iid)
            name = (str(it.get("name","")).strip() if it else iid)
            rarity = _rarity_label(str(it.get("rarity","common")) if it else "common")
            typ = str(it.get("type","")).strip() if it else ""
            opts.append(discord.SelectOption(
                label=f"{name} x{qty}",
                value=iid,
                description=f"{rarity} • {typ}" if typ else rarity
            ))
        if not opts:
            opts = [discord.SelectOption(label="(Inventaire vide)", value="__none__", description="Va au shop")]
        return opts

    def _equipped_text(self, row: Dict[str, Any]) -> str:
        eq = hs.player_eq_get(row)
        pw = eq.get("player_weapon") or "-"
        pa = eq.get("player_armor") or "-"
        aw = eq.get("ally_weapon") or "-"
        aa = eq.get("ally_armor") or "-"
        ally_tag = str(row.get("ally_tag","")).strip()
        return (
            f"🧍 Player: weapon **{pw}**, armor **{pa}**\n"
            + (f"🤝 Ally ({ally_tag}): weapon **{aw}**, armor **{aa}**\n" if ally_tag else "🤝 Ally: *(aucun)*\n")
        )

    def build_embed(self) -> discord.Embed:
        row_i, row = self._player_row()
        dollars = hs.player_money_get(row)

        e = discord.Embed(
            title="🎒 Inventory",
            description=(
                f"👤 **{self.pseudo}** | 💰 **{_money(dollars)}**\n\n"
                + self._equipped_text(row)
                + f"\n🎯 Cible equip: **{self.equip_target.upper()}**"
            ),
            color=discord.Color.blurple()
        )

        if self.selected_item_id and self.selected_item_id not in ("__none__", ""):
            it = hs.item_by_id(self.sheets, self.selected_item_id)
            inv = hs.player_inv_get(row)
            qty = hs.inv_count(inv, self.selected_item_id)
            if it:
                rarity = _rarity_label(str(it.get("rarity","common")))
                desc = str(it.get("description","")).strip() or "*Aucune description*"
                e.add_field(
                    name=f"📦 {it.get('name', self.selected_item_id)} x{qty}",
                    value=f"Type: `{it.get('type','')}`\nRareté: **{rarity}**\n\n{desc}",
                    inline=False
                )
                img = str(it.get("image_url","")).strip()
                if img:
                    e.set_thumbnail(url=img)
            else:
                e.add_field(name=f"📦 {self.selected_item_id} x{qty}", value="(item non trouvé dans HUNT_ITEMS)", inline=False)

        e.set_footer(text="Equip/Key open se fait ici. 🐾")
        return e

    def _set_buttons_state(self):
        # Active/désactive boutons selon sélection
        row_i, row = self._player_row()
        inv = hs.player_inv_get(row)
        it = hs.item_by_id(self.sheets, self.selected_item_id or "")
        qty = hs.inv_count(inv, self.selected_item_id or "")

        can_equip = bool(it and qty > 0 and hd.is_equippable(it))
        is_key = bool(it and qty > 0 and str(it.get("type","")).strip().lower() in ("key", "gold_key"))
        ally_exists = bool(str(row.get("ally_tag","")).strip())

        for child in self.children:
            if isinstance(child, ui.Button) and child.custom_id:
                if child.custom_id == "inv_equip":
                    child.disabled = not can_equip
                if child.custom_id == "inv_openkey":
                    child.disabled = not is_key
                if child.custom_id == "inv_target":
                    child.disabled = not ally_exists

    async def _refresh(self, interaction: discord.Interaction):
        # rebuild select options
        self.clear_items()
        self.add_item(InvSelect(self))
        # re-add buttons (they are declared as decorators, Discord keeps them; but after clear_items we must re-add)
        # -> easiest: re-add by iterating original children? not possible after clear. So we avoid clear for buttons.
        # Instead: do NOT clear buttons; only replace the select by removing it first.
        # We'll do a safer approach: don't clear_items here.
        pass

    @ui.button(label="🎯 Cible: Player/Ally", style=discord.ButtonStyle.secondary, custom_id="inv_target")
    async def btn_target(self, interaction: discord.Interaction, button: ui.Button):
        row_i, row = self._player_row()
        if not str(row.get("ally_tag","")).strip():
            return await interaction.response.send_message(catify("😾 Tu n’as pas d’allié."), ephemeral=True)
        self.equip_target = "ally" if self.equip_target == "player" else "player"
        await _edit(interaction, embed=self.build_embed(), view=self)

    @ui.button(label="🗡️ Equip", style=discord.ButtonStyle.success, custom_id="inv_equip")
    async def btn_equip(self, interaction: discord.Interaction, button: ui.Button):
        if not self.selected_item_id or self.selected_item_id in ("__none__", ""):
            return await interaction.response.send_message(catify("😾 Sélectionne un item."), ephemeral=True)

        row_i, row = self._player_row()
        inv = hs.player_inv_get(row)
        if hs.inv_count(inv, self.selected_item_id) <= 0:
            return await interaction.response.send_message(catify("😾 Tu n’en as pas."), ephemeral=True)

        it = hs.item_by_id(self.sheets, self.selected_item_id)
        if not it or not hd.is_equippable(it):
            return await interaction.response.send_message(catify("😾 Cet item n’est pas équipable."), ephemeral=True)

        slot = hd.equip_slot(it)
        if not slot:
            return await interaction.response.send_message(catify("😾 Slot inconnu."), ephemeral=True)

        eq = hs.player_eq_get(row)
        name = str(it.get("name", self.selected_item_id)).strip()

        if self.equip_target == "player":
            if slot == "weapon":
                eq["player_weapon"] = name
                eq["player_weapon_id"] = self.selected_item_id
            else:
                eq["player_armor"] = name
                eq["player_armor_id"] = self.selected_item_id
        else:
            if slot == "weapon":
                eq["ally_weapon"] = name
                eq["ally_weapon_id"] = self.selected_item_id
            else:
                eq["ally_armor"] = name
                eq["ally_armor_id"] = self.selected_item_id

        hs.player_eq_set(self.sheets, row_i, eq)
        hs.log(self.sheets, discord_id=self.discord_id, code_vip=self.code_vip, kind="equip",
               message=f"equip {self.equip_target} {slot} {self.selected_item_id}", meta={"target": self.equip_target, "slot": slot})

        await interaction.response.send_message(catify(f"✅ Equip **{name}** sur **{self.equip_target.upper()}**."), ephemeral=True)
        await _edit(interaction, embed=self.build_embed(), view=self)

    @ui.button(label="🔑 Open Key", style=discord.ButtonStyle.primary, custom_id="inv_openkey")
    async def btn_open_key(self, interaction: discord.Interaction, button: ui.Button):
        if not self.selected_item_id or self.selected_item_id in ("__none__", ""):
            return await interaction.response.send_message(catify("😾 Sélectionne une clé."), ephemeral=True)

        row_i, row = self._player_row()
        inv = hs.player_inv_get(row)
        if hs.inv_count(inv, self.selected_item_id) <= 0:
            return await interaction.response.send_message(catify("😾 Tu n’en as pas."), ephemeral=True)

        it = hs.item_by_id(self.sheets, self.selected_item_id)
        if not it:
            return await interaction.response.send_message(catify("❌ Item clé introuvable."), ephemeral=True)

        key_type = str(it.get("type","")).strip().lower()
        if key_type not in ("key", "gold_key"):
            return await interaction.response.send_message(catify("😾 Ce n’est pas une clé."), ephemeral=True)

        # consume key
        if not hs.inv_remove(inv, self.selected_item_id, 1):
            return await interaction.response.send_message(catify("😾 Impossible de consommer la clé."), ephemeral=True)

        # loot
        all_items = hs.items_all(self.sheets)
        loot_id, loot_qty, loot_rarity, loot_name = hd.loot_pick_from_items(all_items, key_type=key_type)

        if loot_id:
            hs.inv_add(inv, loot_id, loot_qty)

        hs.player_inv_set(self.sheets, row_i, inv)

        # update HUNT_KEYS row (si on en trouve une non ouverte)
        k_row_i, k_row = hs.find_unopened_key_row(self.sheets, self.discord_id, key_type=key_type)
        if k_row_i:
            hs.sheets.update_cell_by_header("HUNT_KEYS", int(k_row_i), "opened_at", now_iso())
            hs.sheets.update_cell_by_header("HUNT_KEYS", int(k_row_i), "open_item_id", loot_id)
            hs.sheets.update_cell_by_header("HUNT_KEYS", int(k_row_i), "open_qty", str(loot_qty))
            hs.sheets.update_cell_by_header("HUNT_KEYS", int(k_row_i), "open_rarity", loot_rarity)
            hs.sheets.update_cell_by_header("HUNT_KEYS", int(k_row_i), "open_item_name", loot_name)

        hs.log(self.sheets, discord_id=self.discord_id, code_vip=self.code_vip, kind="key_open",
               message=f"open {key_type} -> {loot_id} x{loot_qty}", meta={"rarity": loot_rarity})

        await interaction.response.send_message(catify(f"🎁 Tu ouvres ta **{key_type}** → **{loot_name}** x{loot_qty} (**{_rarity_label(loot_rarity)}**)"), ephemeral=True)
        await _edit(interaction, embed=self.build_embed(), view=self)

    @ui.button(label="↩️ Retour", style=discord.ButtonStyle.secondary)
    async def btn_back(self, interaction: discord.Interaction, button: ui.Button):
        await _edit(interaction, embed=self.parent.build_embed(), view=self.parent)

    # NOTE: Discord ne rappelle pas automatiquement _set_buttons_state
    # Donc on le fait dans interaction_check via edit events? simple: on laisse OK,
    # car les boutons protègent aussi côté serveur (checks).
