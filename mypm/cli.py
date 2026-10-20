"""Comandos da interface de linha de comando do MyPM."""

from __future__ import annotations

from typing import Annotated

from typer import Argument, Option, Typer

from .main import CommandLineApplication, DaemonService

__lazy_modules__ = ["pathlib"]

from pathlib import Path

cli = Typer(
    name="mypm",
    help="Gerenciador de processos Python.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
startup_cli = Typer(help="Gerencia a inicialização após o login.")
cli.add_typer(startup_cli, name="startup")


def _application() -> CommandLineApplication:
    return CommandLineApplication()


@cli.command()
def start(
    script: Annotated[
        Path,
        Argument(help="Script Python a executar."),
    ],
    name: Annotated[
        str | None,
        Option("--name", "-n", help="Nome do processo."),
    ] = None,
    executable: Annotated[
        Path | None,
        Option(
            "--executable",
            "-e",
            help="Interpretador ou executável usado para iniciar o script.",
        ),
    ] = None,
    working_directory: Annotated[
        Path | None,
        Option(
            "--cwd",
            help="Diretório de trabalho do processo.",
        ),
    ] = None,
    arguments: Annotated[
        list[str] | None,
        Option(
            "--argument",
            "-a",
            help="Argumento repassado ao script; pode ser repetido.",
        ),
    ] = None,
) -> None:
    """Inicia e monitora um script Python."""
    resolved_script = script.resolve()
    _application().execute({
        "cmd": "start",
        "script": str(resolved_script),
        "name": name or script.stem,
        "arguments": arguments or [],
        "executable": str(executable.resolve()) if executable else "",
        "working_directory": (
            str(working_directory.resolve())
            if working_directory
            else ""
        ),
    })


@cli.command()
def stop(
    name: Annotated[str, Argument(help="Nome do processo.")],
) -> None:
    """Interrompe um processo gerenciado."""
    _application().execute({"cmd": "stop", "name": name})


@cli.command()
def restart(
    name: Annotated[str, Argument(help="Nome do processo.")],
) -> None:
    """Reinicia um processo gerenciado."""
    _application().execute({"cmd": "restart", "name": name})


@cli.command()
def delete(
    name: Annotated[str, Argument(help="Nome do processo.")],
) -> None:
    """Remove um processo do gerenciamento."""
    _application().execute({"cmd": "delete", "name": name})


@cli.command("list")
def list_processes() -> None:
    """Exibe os processos gerenciados."""
    _application().execute({"cmd": "list"})


@cli.command()
def logs(
    name: Annotated[str, Argument(help="Nome do processo.")],
) -> None:
    """Acompanha os logs de um processo."""
    _application().show_logs(name)


@cli.command()
def shutdown() -> None:
    """Encerra o daemon e todos os processos."""
    _application().execute({"cmd": "shutdown"})


@startup_cli.command("install")
def install_startup() -> None:
    """Ativa o MyPM automaticamente após o login."""
    _application().install_startup()


@startup_cli.command("remove")
def remove_startup() -> None:
    """Remove a inicialização automática do MyPM."""
    _application().remove_startup()


@cli.command("_daemon", hidden=True)
def run_daemon() -> None:
    """Executa o serviço interno do daemon."""
    DaemonService().run()
