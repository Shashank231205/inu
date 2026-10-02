"""`inu` command-line entry point."""

import argparse
import sys
from collections.abc import Sequence

import yaml

from inu.config import ConfigError, load_settings

EXIT_CONFIG_ERROR = 2


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        settings = load_settings(profile=args.profile)
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return EXIT_CONFIG_ERROR

    if args.action == "show":
        # mode="json" renders secrets as "**********".
        print(yaml.safe_dump(settings.model_dump(mode="json"), sort_keys=False), end="")
    else:
        print(f"Configuration OK (profile: {settings.profile})")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="inu")
    commands = parser.add_subparsers(dest="command", required=True)

    config = commands.add_parser("config", help="Inspect configuration")
    config.add_argument("action", choices=["show", "check"])
    config.add_argument("--profile", help="Override INU_PROFILE")
    return parser


if __name__ == "__main__":
    sys.exit(main())
