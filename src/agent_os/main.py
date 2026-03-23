from __future__ import annotations

from pathlib import Path

import typer

from agent_os.runtime import AgentOSRuntime
from shared.settings import AppSettings

cli = typer.Typer(help="Minimal Agent OS runtime")


@cli.command()
def run() -> None:
    settings = AppSettings.load()
    settings.ensure_directories()
    AgentOSRuntime(settings.root_dir).run_forever()


@cli.command()
def status() -> None:
    settings = AppSettings.load()
    typer.echo(AgentOSRuntime(settings.root_dir).status())


@cli.command()
def execute(agent_id: str, text: str) -> None:
    settings = AppSettings.load()
    typer.echo(AgentOSRuntime(settings.root_dir).execute(agent_id, text))


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
