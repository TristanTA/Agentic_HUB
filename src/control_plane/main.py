from __future__ import annotations

import typer
import uvicorn

from control_plane.service import ControlPlaneService, build_app
from shared.settings import AppSettings

cli = typer.Typer(help="Personal AI Hub control plane")


@cli.command()
def serve() -> None:
    settings = AppSettings.load()
    settings.ensure_directories()
    app = build_app(settings.root_dir)
    uvicorn.run(app, host=settings.control_plane_host, port=settings.control_plane_port)


@cli.command()
def status() -> None:
    settings = AppSettings.load()
    typer.echo(ControlPlaneService(settings.root_dir).status())


@cli.command()
def pause_hub() -> None:
    settings = AppSettings.load()
    typer.echo(ControlPlaneService(settings.root_dir).pause_hub())


@cli.command()
def resume_hub() -> None:
    settings = AppSettings.load()
    typer.echo(ControlPlaneService(settings.root_dir).resume_hub())


@cli.command()
def restart_hub() -> None:
    settings = AppSettings.load()
    typer.echo(ControlPlaneService(settings.root_dir).restart_hub())


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
