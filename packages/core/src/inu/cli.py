"""`inu` command-line entry point."""

import argparse
import sys
from collections.abc import Sequence

import structlog
import yaml

from inu.config import ConfigError, Settings, load_settings
from inu.observability import init_observability, stage, turn

EXIT_CONFIG_ERROR = 2
DIAG_STAGES = ("stt", "route", "llm", "tts")


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        settings = load_settings(profile=args.profile)
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return EXIT_CONFIG_ERROR

    if args.command == "diag":
        _emit_diagnostic_turn(settings)
    elif args.action == "show":
        # mode="json" renders secrets as "**********".
        print(yaml.safe_dump(settings.model_dump(mode="json"), sort_keys=False), end="")
    else:
        print(f"Configuration OK (profile: {settings.profile})")
    return 0


def _emit_diagnostic_turn(settings: Settings) -> None:
    """Send one synthetic turn through logging and telemetry, to check the pipeline."""
    telemetry = init_observability(settings)
    log = structlog.get_logger("inu.diag")
    try:
        with turn() as turn_id:
            for name in DIAG_STAGES:
                with stage(name):
                    log.info("diag.stage", stage=name)
    finally:
        telemetry.shutdown()
    print(f"Emitted diagnostic turn {turn_id}")


def _build_parser() -> argparse.ArgumentParser:
    profile = argparse.ArgumentParser(add_help=False)
    profile.add_argument("--profile", help="Override INU_PROFILE")

    parser = argparse.ArgumentParser(prog="inu")
    commands = parser.add_subparsers(dest="command", required=True)

    config = commands.add_parser("config", parents=[profile], help="Inspect configuration")
    config.add_argument("action", choices=["show", "check"])

    commands.add_parser(
        "diag", parents=[profile], help="Emit a synthetic turn to test logs and telemetry"
    )
    return parser


if __name__ == "__main__":
    sys.exit(main())
