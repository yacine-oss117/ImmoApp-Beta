"""
Algerian Administrative Divisions - Wilayas and Communes

Wilayas: FIXED list (58 total) - for standardized analytics
Format: "Name - Code" (e.g., "Algiers - 16")

Communes: User-customizable, stored in DB
Format: "Commune Name, Wilaya Name" (e.g., "Bab Ezzouar, Algiers - 16")
"""

# All 58 Algerian wilayas - NORMALIZED format: "Name - Code"
ALGERIAN_WILAYAS = [
    "Adrar - 01",
    "Chlef - 02",
    "Laghouat - 03",
    "Oum El Bouaghi - 04",
    "Batna - 05",
    "Béjaïa - 06",
    "Biskra - 07",
    "Béchar - 08",
    "Blida - 09",
    "Bouira - 10",
    "Tamanrasset - 11",
    "Tébessa - 12",
    "Tlemcen - 13",
    "Tiaret - 14",
    "Tizi Ouzou - 15",
    "Algiers - 16",
    "Djelfa - 17",
    "Jijel - 18",
    "Sétif - 19",
    "Saïda - 20",
    "Skikda - 21",
    "Sidi Bel Abbès - 22",
    "Annaba - 23",
    "Guelma - 24",
    "Constantine - 25",
    "Médéa - 26",
    "Mostaganem - 27",
    "M'Sila - 28",
    "Mascara - 29",
    "Ouargla - 30",
    "Oran - 31",
    "El Bayadh - 32",
    "Illizi - 33",
    "Bordj Bou Arréridj - 34",
    "Boumerdès - 35",
    "El Tarf - 36",
    "Tindouf - 37",
    "Tissemsilt - 38",
    "El Oued - 39",
    "Khenchela - 40",
    "Souk Ahras - 41",
    "Tipaza - 42",
    "Mila - 43",
    "Aïn Defla - 44",
    "Naâma - 45",
    "Aïn Témouchent - 46",
    "Ghardaïa - 47",
    "Relizane - 48",
    "El M'Ghair - 49",
    "El Meniaa - 50",
    "Ouled Djellal - 51",
    "Bordj Badji Mokhtar - 52",
    "Béni Abbès - 53",
    "Timimoun - 54",
    "Touggourt - 55",
    "Djanet - 56",
    "In Salah - 57",
    "In Guezzam - 58",
]

# Default communes - Format: "Commune, Wilaya Name - Code"
ALGERIAN_LOCATIONS = [
    # Algiers - 16
    "Bab El Oued, Algiers - 16",
    "Bab Ezzouar, Algiers - 16",
    "Bir Mourad Raïs, Algiers - 16",
    "Bordj El Kiffan, Algiers - 16",
    "Cheraga, Algiers - 16",
    "Dar El Beïda, Algiers - 16",
    "Dély Ibrahim, Algiers - 16",
    "Draria, Algiers - 16",
    "El Biar, Algiers - 16",
    "El Harrach, Algiers - 16",
    "Hussein Dey, Algiers - 16",
    "Hydra, Algiers - 16",
    "Kouba, Algiers - 16",
    "Mohammadia, Algiers - 16",
    "Rouiba, Algiers - 16",
    "Sidi M'Hamed, Algiers - 16",
    "Zeralda, Algiers - 16",
    # Oran - 31
    "Oran Centre, Oran - 31",
    "Bir El Djir, Oran - 31",
    "Es Sénia, Oran - 31",
    "Arzew, Oran - 31",
    "Aïn El Türk, Oran - 31",
    "Gdyel, Oran - 31",
    "Bethioua, Oran - 31",
    # Constantine - 25
    "Constantine Centre, Constantine - 25",
    "El Khroub, Constantine - 25",
    "Aïn Smara, Constantine - 25",
    "Didouche Mourad, Constantine - 25",
    "Hamma Bouziane, Constantine - 25",
    # Annaba - 23
    "Annaba Centre, Annaba - 23",
    "El Bouni, Annaba - 23",
    "Sidi Amar, Annaba - 23",
    "El Hadjar, Annaba - 23",
    # Blida - 09
    "Blida Centre, Blida - 09",
    "Boufarik, Blida - 09",
    "Oued El Alleug, Blida - 09",
    "Mouzaïa, Blida - 09",
    # Sétif - 19
    "Sétif Centre, Sétif - 19",
    "El Eulma, Sétif - 19",
    "Aïn Oulmene, Sétif - 19",
    # Batna - 05
    "Batna Centre, Batna - 05",
    "Barika, Batna - 05",
    "Aïn Touta, Batna - 05",
    # Béjaïa - 06
    "Béjaïa Centre, Béjaïa - 06",
    "Akbou, Béjaïa - 06",
    "El Kseur, Béjaïa - 06",
    # Tizi Ouzou - 15
    "Tizi Ouzou Centre, Tizi Ouzou - 15",
    "Azazga, Tizi Ouzou - 15",
    "Draa Ben Khedda, Tizi Ouzou - 15",
    # Boumerdès - 35
    "Boumerdès Centre, Boumerdès - 35",
    "Bordj Menaïel, Boumerdès - 35",
    "Dellys, Boumerdès - 35",
    "Naciria, Boumerdès - 35",
    "Khemis El Khechna, Boumerdès - 35",
    # Tipaza - 42
    "Tipaza Centre, Tipaza - 42",
    "Koléa, Tipaza - 42",
    "Hadjout, Tipaza - 42",
    "Fouka, Tipaza - 42",
    # Chlef - 02
    "Chlef Centre, Chlef - 02",
    "Ténès, Chlef - 02",
    # Mostaganem - 27
    "Mostaganem Centre, Mostaganem - 27",
    # Tlemcen - 13
    "Tlemcen Centre, Tlemcen - 13",
    "Maghnia, Tlemcen - 13",
    # Médéa - 26
    "Médéa Centre, Médéa - 26",
    "Berrouaghia, Médéa - 26",
    # Biskra - 07
    "Biskra Centre, Biskra - 07",
    "Tolga, Biskra - 07",
    # M'Sila - 28
    "M'Sila Centre, M'Sila - 28",
    "Bou Saâda, M'Sila - 28",
    # Djelfa - 17
    "Djelfa Centre, Djelfa - 17",
    "Aïn Oussera, Djelfa - 17",
    # Ouargla - 30
    "Ouargla Centre, Ouargla - 30",
    "Hassi Messaoud, Ouargla - 30",
    # Skikda - 21
    "Skikda Centre, Skikda - 21",
    # Sidi Bel Abbès - 22
    "Sidi Bel Abbès Centre, Sidi Bel Abbès - 22",
    # Ghardaïa - 47
    "Ghardaïa Centre, Ghardaïa - 47",
]


def normalize_for_lookup(text: str) -> str:
    """Normalize text for lookup: lowercase, remove accents, remove dashes."""
    import unicodedata

    text = text.lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = text.replace("-", " ").replace("'", " ")
    return text


def extract_wilaya_from_location(location: str) -> str:
    """Extract wilaya from location format 'Commune, Wilaya - Code'."""
    if ", " in location:
        return location.split(", ", 1)[1]
    return ""


def filter_locations_by_wilaya(locations: list[str], wilaya: str) -> list[str]:
    """Filter locations to only those matching the wilaya."""
    if not wilaya:
        return locations

    # Extract wilaya name for comparison
    wilaya_norm = normalize_for_lookup(wilaya)

    return [
        loc
        for loc in locations
        if normalize_for_lookup(extract_wilaya_from_location(loc)) == wilaya_norm
    ]
