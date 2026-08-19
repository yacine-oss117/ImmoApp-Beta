import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
django.setup()

from server.services.local_dev_seed import seed_local_dev_identities  # noqa: E402


def seed() -> None:
    for message in seed_local_dev_identities():
        print(message)


if __name__ == "__main__":
    seed()
