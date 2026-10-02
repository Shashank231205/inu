"""`inu` command-line entry point.

Subcommands are plugins. Built-in ones live here; other packages add theirs through
the `inu.commands` entry-point group, so `inu-voice` contributes `inu audio` without
core depending on it.
"""

import argparse
import sys
from collections.abc import Sequence
from importlib.metadata import entry_points
from typing import Protocol

import structlog
import yaml

from inu.config import ConfigError, Settings, load_settings
from inu.observability import init_observability, stage, turn

COMMAND_GROUP = "inu.commands"
EXIT_CONFIG_ERROR = 2
DIAG_STAGES = ("stt", "route", "llm", "tts")


class Command(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def help(self) -> str: ...

    def configure(self, parser: argparse.ArgumentParser) -> None:
        """Add this command's arguments."""

    def run(self, args: argparse.Namespace, settings: Settings) -> int:
        """Execute and return the process exit code."""


class ConfigCommand:
    name = "config"
    help = "Inspect configuration"

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("action", choices=["show", "check"])

    def run(self, args: argparse.Namespace, settings: Settings) -> int:
        if args.action == "show":
            # mode="json" renders secrets as "**********".
            print(yaml.safe_dump(settings.model_dump(mode="json"), sort_keys=False), end="")
        else:
            print(f"Configuration OK (profile: {settings.profile})")
        return 0


class DiagCommand:
    name = "diag"
    help = "Emit a synthetic turn to test logs and telemetry"

    def configure(self, parser: argparse.ArgumentParser) -> None:
        """Takes no arguments beyond the shared --profile."""

    def run(self, args: argparse.Namespace, settings: Settings) -> int:
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
        return 0


def main(argv: Sequence[str] | None = None) -> int:
    commands = {command.name: command for command in discover_commands()}
    args = _build_parser(commands).parse_args(argv)
    try:
        settings = load_settings(profile=getattr(args, "profile", None))
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return EXIT_CONFIG_ERROR
    return commands[args.command].run(args, settings)


def discover_commands() -> list[Command]:
    commands: list[Command] = [ConfigCommand(), DiagCommand()]
    for entry_point in entry_points(group=COMMAND_GROUP):
        try:
            command: Command = entry_point.load()()
        except Exception as exc:  # noqa: BLE001 - a broken plugin must not disable the CLI
            print(f"warning: skipping command plugin {entry_point.name!r}: {exc}", file=sys.stderr)
            continue
        if any(existing.name == command.name for existing in commands):
            print(f"warning: duplicate command {command.name!r} ignored", file=sys.stderr)
            continue
        commands.append(command)
    return commands


def _build_parser(commands: dict[str, Command]) -> argparse.ArgumentParser:
    # SUPPRESS keeps a missing --profile on one level from erasing it on the other.
    profile = argparse.ArgumentParser(add_help=False)
    profile.add_argument("--profile", default=argparse.SUPPRESS, help="Override INU_PROFILE")

    parser = argparse.ArgumentParser(prog="inu", parents=[profile])
    subcommands = parser.add_subparsers(dest="command", required=True)
    for command in commands.values():
        command.configure(
            subcommands.add_parser(command.name, parents=[profile], help=command.help)
        )
    return parser


if __name__ == "__main__":
    sys.exit(main())
