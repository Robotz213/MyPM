"""Comandos da interface de linha de comando do MyPM."""

from pathlib import Path
from typing import Annotated

import typer

from .main import CommandLineApplication, DaemonService

cli = typer.Typer(
    name="mypm",
    help="Gerenciador de processos Python.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)


def _application() -> CommandLineApplication:
    return CommandLineApplication()


@cli.command()
def start(
    script: Annotated[
        Path,
        typer.Argument(help="Script Python a executar."),
    ],
    name: Annotated[
        str | None,
        typer.Option("--name", "-n", help="Nome do processo."),
    ] = None,
) -> None:
    """Inicia e monitora um script Python."""
    resolved_script = script.resolve()
    _application().execute({
        "cmd": "start",
        "script": str(resolved_script),
        "name": name or script.stem,
    })


@cli.command()
def stop(
    name: Annotated[str, typer.Argument(help="Nome do processo.")],
) -> None:
    """Interrompe um processo gerenciado."""
    _application().execute({"cmd": "stop", "name": name})


@cli.command()
def restart(
    name: Annotated[str, typer.Argument(help="Nome do processo.")],
) -> None:
    """Reinicia um processo gerenciado."""
    _application().execute({"cmd": "restart", "name": name})


@cli.command()
def delete(
    name: Annotated[str, typer.Argument(help="Nome do processo.")],
) -> None:
    """Remove um processo do gerenciamento."""
    _application().execute({"cmd": "delete", "name": name})


@cli.command("list")
def list_processes() -> None:
    """Exibe os processos gerenciados."""
    _application().execute({"cmd": "list"})


@cli.command()
def logs(
    name: Annotated[str, typer.Argument(help="Nome do processo.")],
) -> None:
    """Acompanha os logs de um processo."""
    _application().show_logs(name)


@cli.command()
def shutdown() -> None:
    """Encerra o daemon e todos os processos."""
    _application().execute({"cmd": "shutdown"})


@cli.command("_daemon", hidden=True)
def run_daemon() -> None:
    """Executa o serviço interno do daemon."""
    DaemonService().run()
