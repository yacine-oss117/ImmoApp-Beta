from __future__ import annotations

from argparse import ArgumentParser

from django.core.management.base import BaseCommand

from server.services.discovery_beacon import discovery_enabled, run_beacon_loop


class Command(BaseCommand):
    help = "Broadcast ImmoApp LAN discovery beacons."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--seconds",
            type=float,
            default=None,
            help="Optional duration to run beacon loop before exiting.",
        )

    def handle(self, *args: object, **options: object) -> None:
        if not discovery_enabled():
            self.stdout.write("Discovery beacon disabled (IMMOAPP_DISCOVERY_ENABLED not set).")
            return
        seconds_option = options.get("seconds")
        seconds = float(seconds_option) if isinstance(seconds_option, int | float) else None
        run_beacon_loop(stop_after_seconds=seconds)
