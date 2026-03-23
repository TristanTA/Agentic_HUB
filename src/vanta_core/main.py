from __future__ import annotations

import typer

from shared.settings import AppSettings
from vanta_core.guardian import VantaGuardian
from vanta_core.service import VantaCoreService
from vanta_core.telegram_bot import build_bot

cli = typer.Typer(help="Ultra-robust Vanta supervisor")


@cli.command()
def run() -> None:
    settings = AppSettings.load()
    settings.ensure_directories()
    VantaGuardian(settings.root_dir).run_forever()


@cli.command("run-bot")
def run_bot() -> None:
    settings = AppSettings.load()
    settings.ensure_directories()
    build_bot(settings.root_dir).run_forever()


@cli.command()
def status() -> None:
    settings = AppSettings.load()
    typer.echo(VantaCoreService(settings.root_dir).status())


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
