"""
Standard Algerian Contract Clauses - Pre-defined articles for Bail de Location.

These clauses can be loaded into a contract and customized.
"""

from __future__ import annotations

from typing import TypedDict


class Clause(TypedDict):
    """Represents a single contract article/clause."""

    number: int
    title: str
    content: str
    is_required: bool


STANDARD_CLAUSES: list[Clause] = [
    {
        "number": 1,
        "title": "LES PARTIES",
        "content": """Entre les soussignés:

Le BAILLEUR:
Nom: {owner_name}
Adresse: {owner_address}
Ci-après dénommé "LE BAILLEUR"

Et

Le LOCATAIRE:
Nom: {tenant_name}
Adresse: {tenant_address}
Ci-après dénommé "LE LOCATAIRE"

Il a été convenu et arrêté ce qui suit:""",
        "is_required": True,
    },
    {
        "number": 2,
        "title": "DÉSIGNATION DU BIEN",
        "content": """Le BAILLEUR donne en location au LOCATAIRE qui accepte le bien immobilier suivant:

Type de bien: {property_type}
Adresse: {property_address}
Superficie: {property_surface} m²
Usage: Habitation

Le LOCATAIRE déclare bien connaître les lieux pour les avoir visités et les accepte dans l'état où ils se trouvent.""",
        "is_required": True,
    },
    {
        "number": 3,
        "title": "DURÉE DU BAIL",
        "content": """Le présent bail est consenti et accepté pour une durée de:

Date de début: {lease_start}
Date de fin: {lease_end}

À l'expiration de cette période, le bail pourra être renouvelé par accord mutuel des parties.
En l'absence de préavis de résiliation par le BAILLEUR, le bail sera automatiquement reconduit aux mêmes conditions.""",
        "is_required": True,
    },
    {
        "number": 4,
        "title": "LOYER",
        "content": """Le présent bail est consenti moyennant un loyer mensuel de:

Montant: {monthly_rent} DA (Dinars Algériens)

Ce loyer est payable d'avance le premier de chaque mois.
Le paiement peut être effectué en espèces ou par tout autre moyen convenu entre les parties.

Toute modification du montant du loyer devra faire l'objet d'un préavis de trois (3) mois.""",
        "is_required": True,
    },
    {
        "number": 5,
        "title": "DÉPÔT DE GARANTIE (CAUTION)",
        "content": """Le LOCATAIRE verse au BAILLEUR à la signature des présentes une caution d'un montant de:

Montant: {security_deposit} DA

Cette somme sera restituée au LOCATAIRE dans un délai de deux (2) mois suivant la fin du bail, déduction faite des éventuelles réparations locatives ou loyers impayés.

Le BAILLEUR s'engage à fournir un reçu pour tout versement effectué.""",
        "is_required": True,
    },
    {
        "number": 6,
        "title": "OBLIGATIONS DU LOCATAIRE",
        "content": """Le LOCATAIRE s'engage à:

1. Payer le loyer aux termes convenus
2. User paisiblement des lieux loués
3. Répondre des dégradations et pertes survenant de son fait
4. Maintenir les lieux en bon état d'entretien courant
5. Effectuer les menues réparations locatives
6. Signaler immédiatement au BAILLEUR tout problème ou dégât
7. Ne pas modifier la structure des lieux sans autorisation écrite
8. Restituer les lieux en bon état à la fin du bail""",
        "is_required": True,
    },
    {
        "number": 7,
        "title": "OBLIGATIONS DU BAILLEUR",
        "content": """Le BAILLEUR s'engage à:

1. Délivrer le bien en bon état d'habitation
2. Assurer la jouissance paisible des lieux
3. Effectuer les grosses réparations (toiture, murs porteurs, canalisations principales)
4. Payer les impôts fonciers et taxes liées à la propriété
5. Souscrire une assurance contre les catastrophes naturelles
6. Remettre au LOCATAIRE un exemplaire du présent contrat""",
        "is_required": True,
    },
    {
        "number": 8,
        "title": "INTERDICTION DE SOUS-LOCATION",
        "content": """Sauf autorisation écrite et préalable du BAILLEUR, le LOCATAIRE ne pourra:

1. Sous-louer tout ou partie des lieux loués
2. Céder son droit au bail à un tiers
3. Héberger à titre onéreux des personnes étrangères au foyer

Toute infraction à cette clause entraînera la résiliation immédiate du bail.""",
        "is_required": False,
    },
    {
        "number": 9,
        "title": "RÉSILIATION DU BAIL",
        "content": """Le présent bail pourra être résilié:

Par le LOCATAIRE:
- À tout moment moyennant un préavis de trois (3) mois

Par le BAILLEUR:
- À l'échéance du bail avec préavis de trois (3) mois
- En cas de non-paiement du loyer pendant deux (2) mois consécutifs
- En cas de manquement grave aux obligations contractuelles

La partie qui souhaite résilier le bail doit notifier l'autre partie par lettre recommandée.""",
        "is_required": True,
    },
    {
        "number": 10,
        "title": "ÉTAT DES LIEUX",
        "content": """Un état des lieux contradictoire sera établi:

1. À l'entrée dans les lieux: décrivant l'état du bien et de ses équipements
2. À la sortie des lieux: permettant de constater les éventuelles dégradations

Ces documents seront signés par les deux parties et annexés au présent contrat.
En l'absence d'état des lieux d'entrée, le bien est présumé avoir été remis en bon état.""",
        "is_required": False,
    },
]


def get_standard_clauses() -> list[Clause]:
    """Get all standard clauses for a new contract."""
    return [clause.copy() for clause in STANDARD_CLAUSES]


def render_clause(clause: Clause, context: dict[str, str]) -> Clause:
    """Replace placeholders in a clause with actual values."""
    rendered = clause.copy()
    content = rendered["content"]
    for key, value in context.items():
        placeholder = "{" + key + "}"
        content = content.replace(placeholder, str(value) if value else "________")
    rendered["content"] = content
    return rendered


def render_all_clauses(clauses: list[Clause], context: dict[str, str]) -> list[Clause]:
    """Render all clauses with context values."""
    return [render_clause(clause, context) for clause in clauses]


__all__ = ["Clause", "get_standard_clauses", "render_all_clauses"]
