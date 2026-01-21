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

# ==========================================================
# AVATARS (Direction SubUrban)
# ==========================================================

DIRECTION_TAGS = ["MAI", "ROXY", "LYA", "ZACKO", "DRACO"]

# Pour affichage (si tu veux joli dans l'UI)
DIRECTION_LABELS = {
    "MAI": "Mai",
    "ROXY": "Roxy",
    "LYA": "Lya",
    "ZACKO": "Zacko",
    "DRACO": "Draco",
}

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
    pool = [t for t in DIRECTION_TAGS if t not in set([x.upper() for x in exclude_tags if x])]
    if not pool:
        # fallback: si tout exclu (rare), on autorise n'importe qui
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
    tag = (tag or "").upper()
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
    "Chass

