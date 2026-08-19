from __future__ import annotations

from argparse import ArgumentParser

from django.core.management.base import BaseCommand

from server.pg.schema import ensure_schema
from server.pg.schema_security import assert_security_schema
from server.pg.uow import admin_transaction, warmup_pool
from server.services.local_dev_seed import seed_local_dev_identities


class Command(BaseCommand):
    help = "Prepare the database schema and verify security invariants."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--seed-local-dev",
            action="store_true",
            help="Seed local-only default identities after schema preparation.",
        )

    def handle(self, *args: object, **options: object) -> None:
        ensure_schema()
        with admin_transaction() as session:
            assert_security_schema(session)
        if bool(options.get("seed_local_dev", False)):
            for message in seed_local_dev_identities():
                self.stdout.write(message)
        warmup_pool()
        self.stdout.write(self.style.SUCCESS("Database prepared and verified."))
