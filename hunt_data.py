# hunt_data.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import random

# ==========================================================
# CONFIG
# ==========================================================

HUNT_CAMPAIGN_MAX_WEEK = 12

# Format affichage: "NomJoueur [MAI]"
def format_player_title(player_name: str, avatar_tag: str) -> str:
    player_name = (player_name or "").strip() or "Joueur"
    avatar_tag = (avatar_tag or "").strip().upper()
    if not avatar_tag:
        return player_name
    return f"{player_name} [{avatar_tag}]"

# Mets ton raw github ici (ou charge depuis env)
ASSET_BASE_URL = "https://raw.githubusercontent.com/immaimashiro/mikasa2-bot/main/"

@dataclass(frozen=True)
class AvatarDef:
    tag: str
    name: str
    image: str
    short: str

def asset(path: str) -> str:
    return ASSET_BASE_URL + path

# Avatars jouables (direction)
AVATARS: List[AvatarDef] = [
    AvatarDef(tag="MAI",   name="Mai Mashiro",  image=asset("Mai.png"),   short="Froide, efficace. Bonus ATK."),
    AvatarDef(tag="ROXY",  name="Roxy",         image=asset("Roxy.png"),  short="Agressive. Gros dégâts, +heat possible."),
    AvatarDef(tag="DRACO", name="Draco",        image=asset("Draco.png"), short="Tank. Prend les coups à ta place."),
    AvatarDef(tag="LYA",   name="Lya",          image=asset("Lya.png"),   short="Support. Heal, bonus loot/perception."),
    AvatarDef(tag="ZACKO", name="Zacko",        image=asset("Zacko.png"), short="Assassin. Critiques, bonus vol."),
]

AVATAR_BY_TAG: Dict[str, AvatarDef] = {a.tag: a for a in AVATARS}

def get_avatar(tag: str) -> Optional[AvatarDef]:
    return AVATAR_BY_TAG.get((tag or "").strip().upper())

# ==========================================================
# AVATARS (Direction SubUrban)
# ==========================================================

DIRECTION_TAGS = ["MAI", "ROXY", "LYA", "ZACKO", "DRACO"]

DIRECTION_LABELS = {
    "MAI": "Mai",
    "ROXY": "Roxy",
    "LYA": "Lya",
    "ZACKO": "Zacko",
    "DRACO": "Draco",
}

def avatar_label(tag: str) -> str:
    tag = (tag or "").strip().upper()
    return DIRECTION_LABELS.get(tag, tag or "Inconnu")

def pick_random_avatar_tag() -> str:
    return random.choice(DIRECTION_TAGS)

# ==========================================================
# ALLIÉS (rencontres direction)
# ==========================================================

def pick_direction_ally(exclude_tags: List[str]) -> str:
    """
    Choisit un allié parmi la direction, en excluant:
    - le perso du joueur
    - l'allié déjà actif
    """
    ex = set()
    for x in (exclude_tags or []):
        x = (x or "").strip().upper()
        if x:
            ex.add(x)

    pool = [t for t in DIRECTION_TAGS if t not in ex]
    if not pool:
        pool = DIRECTION_TAGS[:]
    return random.choice(pool)

ALLY_LINES = {
    "MAI": [
        "Mai ajuste ses gants. « Je te couvre. »",
        "Mai jauge l’ennemi. « On termine ça proprement. »",
    ],
    "ROXY": [
        "Roxy sourit. « Tu vas pas tomber aujourd’hui. »",
        "Roxy claque ses phalanges. « Laisse-moi lui parler. »",
    ],
    "LYA": [
        "Lya murmure. « Respire. Je gère la suite. »",
        "Lya trace un plan. « On bouge au bon moment. »",
    ],
    "ZACKO": [
        "Zacko ricane. « Ça fait longtemps que j’ai pas frappé quelqu’un. »",
        "Zacko pose une main sur ton épaule. « Vas-y, j’suis là. »",
    ],
    "DRACO": [
        "Draco fixe l’ennemi. « Je déteste perdre. »",
        "Draco hoche la tête. « Focus. Une ouverture. »",
    ],
}

def ally_intro_line(tag: str) -> str:
    tag = (tag or "").upper().strip()
    arr = ALLY_LINES.get(tag) or ["Un allié surgit, silencieux."]
    return random.choice(arr)

# ==========================================================
# DÉS / RNG
# ==========================================================

def roll_d20() -> int:
    return random.randint(1, 20)

def coinflip() -> bool:
    return random.random() < 0.5

# ==========================================================
# ENNEMIS / PNJ ICONIQUES (base)
# ==========================================================

COMMON_ENEMIES = [
    "Chien errant",
    "Bandit de ruelle",
    "Pickpocket nerveux",
    "Rôdeur masqué",
    "Coyote affamé",
]

RARE_ENEMIES = [
    "Gangster sous stéroïdes",
    "Chasseur nocturne",
    "Maniaque au regard vide",
]

ICONIC_CAMEOS = [
    "Trevor (caméo)",
    "Michael (caméo)",
]

BAYLIFE_NPCS = [
    "Shakir",
    "Luxus Dreyar",
    "Dodo Lasaumure",
]

# ==========================================================
# BOSS: ATTENIN
# ==========================================================

ATTENIN_TAUNTS = [
    "« Regarde-toi… même la rue a pitié de toi. »",
    "« Tu veux être un héros? Tu n’es même pas un figurant. »",
    "« Tu trembles. Je le vois. »",
    "« Continue. J’adore quand tu t’illusionnes. »",
]

ATTENIN_FLEE_LINE_1 = "Attenin recule, essuie une goutte de sang, puis disparaît dans l’ombre."
ATTENIN_FLEE_LINE_2 = "Attenin ricane, et au moment où tu frappes… elle n’est déjà plus là."
ATTENIN_SAVE_LINE = "« Le SubUrban sera toujours de ton côté. »"

ATTENIN_EXEC_FAIL = "Tes mains tremblent. « Finalement… je ne peux pas l’achever… » Attenin s’échappe, blessée mais vivante."
ATTENIN_EXEC_SUCCESS = "Le dernier coup part. Attenin s’effondre. Le silence dure une seconde. Mikasa laisse échapper un petit *prrr*."

# ==========================================================
# ÉCONOMIE / ITEMS / CLÉS
# ==========================================================
# NOTE: en Sheets (HUNT_KEYS.key_type), on utilisera plutôt "NORMAL" ou "GOLD"
KEY_NORMAL = "NORMAL"
KEY_GOLD = "GOLD"

RARITY_COMMON = "COMMON"
RARITY_RARE = "RARE"
RARITY_EPIC = "EPIC"
RARITY_LEGENDARY = "LEGENDARY"

@dataclass
class LootItem:
    item_id: str
    name: str
    rarity: str
    price_dollars: int
    expires_days: int = 0  # 0 = ne périme pas
    desc: str = ""

LOOT_POOL: List[LootItem] = [
    LootItem("BANDAGE", "Bandages", RARITY_COMMON, price_dollars=120, desc="Soigne un peu. Simple, efficace."),
    LootItem("MEDKIT", "Kit de soin", RARITY_RARE, price_dollars=420, desc="Soigne beaucoup. Tu respires mieux."),
    LootItem("KNIFE", "Couteau", RARITY_RARE, price_dollars=550, expires_days=7, desc="Lame rapide. 7 jours d’usage."),
    LootItem("PISTOL", "Pistolet", RARITY_EPIC, price_dollars=1800, expires_days=7, desc="Bim. 7 jours d’usage."),
    LootItem("LUCILLE", "Lucille", RARITY_LEGENDARY, price_dollars=9999, expires_days=7,
             desc="Arme légendaire, très chère. Une batte entourée de barbelés. 7 jours d’usage."),
]

def _weighted_choice(items: List[Tuple[str, int]]) -> str:
    total = sum(int(w) for _, w in items)
    r = random.randint(1, max(1, total))
    upto = 0
    for v, w in items:
        upto += int(w)
        if r <= upto:
            return v
    return items[-1][0]

def roll_key_rarity(key_type: str) -> str:
    """
    Clé or = meilleures chances.
    """
    kt = (key_type or "").upper().strip()
    if kt == KEY_GOLD:
        return _weighted_choice([
            (RARITY_COMMON, 30),
            (RARITY_RARE, 35),
            (RARITY_EPIC, 25),
            (RARITY_LEGENDARY, 10),
        ])
    return _weighted_choice([
        (RARITY_COMMON, 55),
        (RARITY_RARE, 30),
        (RARITY_EPIC, 13),
        (RARITY_LEGENDARY, 2),
    ])

def roll_loot_from_rarity(rarity: str) -> LootItem:
    rarity = (rarity or "").upper().strip()
    pool = [x for x in LOOT_POOL if x.rarity == rarity]
    if not pool:
        pool = [x for x in LOOT_POOL if x.rarity == RARITY_COMMON] or LOOT_POOL[:]
    return random.choice(pool)

# ==========================================================
# JETS JOURNALIERS
# ==========================================================

DAILY_ROLL_TYPES = [
    ("COMBAT", "⚔️ Jet Combat"),
    ("EXPLO", "🧭 Jet Exploration"),
    ("SURVIE", "🩹 Jet Survie"),
    ("CHANCE", "🍀 Jet Chance"),
    ("DIRECTION", "✨ Jet de la Direction"),
]

def build_daily_roll_menu(is_employee: bool) -> List[str]:
    """
    Retourne une liste de types de jets proposés aujourd'hui.
    Base: 3 jets parmi [COMBAT, EXPLO, SURVIE, CHANCE]
    Employé: +50% chance d'ajouter "DIRECTION" (bonus).
    """
    base = ["COMBAT", "EXPLO", "SURVIE", "CHANCE"]
    picks = random.sample(base, k=3)

    if is_employee and random.random() < 0.50:
        picks.append("DIRECTION")

    return picks

def roll_direction_bonus_event() -> bool:
    """
    Bonus interne pour le Jet de la Direction.
    Ex: chance de rencontrer un allié, loot amélioré, etc.
    """
    return random.random() < 0.50
