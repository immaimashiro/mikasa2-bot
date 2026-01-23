# ui.py
# -*- coding: utf-8 -*-

from __future__ import annotations
from typing import Dict, List, Tuple, Optional

import discord
from discord import ui

import domain
from services import catify, now_fr, now_iso

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

# --- VIP UI (public) ---
# (inchangé en dessous, je n'y touche pas)


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
# Défis (HG) - inchangé (tu peux garder tout ce que tu avais)
# ==========================================================
# ... (je laisse tout ton code défi / edit / help identique)
# ==========================================================


# ==========================================================
# QCM
# - FIXES IMPORTANTES:
#   1) plus de build_qcm_embed cassée (indentation)
#   2) pas de double "interaction.response" (sinon crash "already responded")
#   3) on édite le message via interaction.message.edit
# ==========================================================
class QcmDailyView(discord.ui.View):
    def __init__(self, *, services, discord_id: int, code_vip: str, vip_pseudo: str, chrono_limit_sec: int = 16):
        super().__init__(timeout=6 * 60)
        self.s = services
        self.discord_id = discord_id
        self.code_vip = domain.normalize_code(code_vip)
        self.vip_pseudo = domain.display_name(vip_pseudo or self.code_vip)

        self.chrono_limit_sec = int(chrono_limit_sec)

        # questions du jour
        self.questions = domain.qcm_pick_daily_set(self.s)
        self.date_key, self.answers = domain.qcm_today_progress(self.s, self.code_vip, self.discord_id)

        self.current_index = len(self.answers)  # 0..4
        self.sent_at = now_fr()

        self._add_buttons()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.discord_id:
            await interaction.response.send_message(catify("😾 Pas touche. Lance ton propre QCM."), ephemeral=True)
            return False
        return True

    def _add_buttons(self):
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
            e = discord.Embed(
                title="✅ QCM terminé (aujourd’hui)",
                description=f"Tu as répondu aux **{total}/5** questions.\nReviens demain pour le prochain QCM. 🐾",
                color=discord.Color.green()
            )
            return e

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

    async def refresh(self, interaction: discord.Interaction):
        self._add_buttons()
        self.sent_at = now_fr()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def start_tick_15s(self, message: discord.Message):
        # petit clin d’œil: edit après 1s (pas toutes les secondes)
        try:
            await asyncio.sleep(1)
            if self.current_index >= len(self.questions):
                return
            await message.edit(embed=self.build_embed(), view=self)
        except Exception:
            pass

    async def submit(self, interaction: discord.Interaction, choice: str):
        elapsed = int((now_fr() - self.sent_at).total_seconds())
        q = self.questions[self.current_index]

        ok, mark, pts, correct = domain.qcm_submit_answer(
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
            return await interaction.followup.send(f"😾 {mark}", ephemeral=True)

        # feedback
        note = f"{mark} Réponse enregistrée."
        if elapsed > self.chrono_limit_sec:
            note += " ⏱️ Trop lent: **0 point**."
        elif correct and pts > 0:
            note += f" ✅ **+{pts} pts**"
        elif correct and pts == 0:
            note += " ✅ Correct mais **cap hebdo** atteint (0 point)."
        else:
            note += " 0 point."

        # avancer + edit message
        self.current_index += 1
        self._add_buttons()
        self.sent_at = now_fr()

        try:
            await interaction.message.edit(embed=self.build_embed(), view=self)
        except Exception:
            pass

        await interaction.followup.send(note, ephemeral=True)


class QcmAnswerButton(discord.ui.Button):
    def __init__(self, choice: str):
        super().__init__(label=choice, style=discord.ButtonStyle.secondary)
        self.choice = choice

    async def callback(self, interaction: discord.Interaction):
        view: QcmDailyView = self.view  # type: ignore

        # verrouille instantanément côté UI
        for item in view.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

        # on ACK l'interaction (sinon Discord râle)
        await interaction.response.edit_message(embed=view.build_embed(), view=view)

        # puis on traite via followups + message.edit
        await view.submit(interaction, self.choice)


class QcmCloseButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="✅ Fermer", style=discord.ButtonStyle.success)

    async def callback(self, interaction: discord.Interaction):
        for item in self.view.children:
            item.disabled = True
        await interaction.response.edit_message(content="✅ QCM fermé.", embed=None, view=self.view)


# ==========================================================
# (Optionnel) équilibrage des positions A/B/C/D
# Si tu veux t’en servir ailleurs sans NameError:
# ==========================================================
class QcmSession:
    def __init__(self):
        self.correct_pos_counts = [0, 0, 0, 0]  # A,B,C,D


def build_shuffled_question_from_sheet(row: dict) -> dict:
    """
    Wrapper: si tu as une fonction dans domain, utilise-la.
    Sinon, garde ce wrapper, mais il faut l’implémenter côté domain.
    """
    fn = getattr(domain, "qcm_build_shuffled_question", None)
    if callable(fn):
        return fn(row)
    raise RuntimeError("domain.qcm_build_shuffled_question(row) est manquante.")


def shuffle_balanced(row: dict, session: QcmSession, max_same: int = 2) -> dict:
    for _ in range(8):
        q = build_shuffled_question_from_sheet(row)
        idx = LETTERS.index(q["correct_letter"])
        if session.correct_pos_counts[idx] < max_same:
            session.correct_pos_counts[idx] += 1
            return q

    q = build_shuffled_question_from_sheet(row)
    session.correct_pos_counts[LETTERS.index(q["correct_letter"])] += 1
    return q
