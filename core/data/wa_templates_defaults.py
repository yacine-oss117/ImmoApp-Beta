"""Default WhatsApp template definitions."""

LEGACY_TEMPLATE_NAMES = {
    "Nouvelle Offre": "New Listing",
    "Rappel de Visite": "Visit Reminder",
    "Suivi Client": "Client Follow-up",
    "Confirmation Contrat": "Contract Ready",
}

DEFAULT_TEMPLATES = [
    {
        "name": "New Listing",
        "template": (
            "Hello {client_name},\n\n"
            "I have a {type} in {location} for {price} DZD.\n\n"
            "Are you interested?\n\n"
            "Best regards,\n{agency_name}"
        ),
        "is_default": 1,
    },
    {
        "name": "Visit Reminder",
        "template": (
            "Hello {client_name},\n\n"
            "Reminder for your visit tomorrow at {time}.\n\n"
            "Address: {location}\n\n"
            "See you tomorrow!"
        ),
        "is_default": 1,
    },
    {
        "name": "Client Follow-up",
        "template": (
            "Hello {client_name},\n\n"
            "Have you thought about the offer at {location}?\n\n"
            "I am available if you have any questions.\n\n"
            "Best regards,\n{agency_name}"
        ),
        "is_default": 1,
    },
    {
        "name": "Contract Ready",
        "template": (
            "Hello {client_name},\n\n"
            "Your contract for {location} is ready.\n\n"
            "Monthly amount: {price} DZD\n"
            "Start date: {date}\n\n"
            "Please come to the agency to sign."
        ),
        "is_default": 1,
    },
]

DEFAULT_TEMPLATE_BY_NAME = {tpl["name"]: tpl for tpl in DEFAULT_TEMPLATES}
