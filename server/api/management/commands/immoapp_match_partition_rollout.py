from __future__ import annotations

from argparse import ArgumentParser

from django.core.management.base import BaseCommand

from server.pg.match_partitions import rollout_match_partitions
from server.pg.uow import admin_transaction


class Command(BaseCommand):
    help = (
        "Convert match_candidates/match_pairs to HASH-partitioned tables. "
        "Run during maintenance windows only."
    )

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--partitions",
            type=int,
            default=16,
            help="Number of hash partitions to create (default: 16).",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Apply the rollout. Without this flag, command is dry-run.",
        )

    def handle(self, *args: object, **options: object) -> None:
        partitions_option = options.get("partitions")
        partitions = int(partitions_option) if isinstance(partitions_option, int) else 16
        apply_rollout = bool(options.get("apply"))
        if not apply_rollout:
            self.stdout.write(self.style.WARNING("Dry-run only. Use --apply to execute."))
            self.stdout.write(f"Planned partitions: {partitions}")
            return

        with admin_transaction() as session:
            result = rollout_match_partitions(session, partitions=partitions)

        self.stdout.write(
            self.style.SUCCESS(
                "Partition rollout complete: "
                f"match_candidates_changed={result.candidates_partitioned}, "
                f"match_pairs_changed={result.pairs_partitioned}"
            )
        )
