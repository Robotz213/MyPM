"""Interface de linha de comando e servidor daemon do MyPM."""

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Annotated, cast

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .application import ProcessManager, Request, Response
from .common.exceptions import (
    DaemonAlreadyRunningError,
    DaemonStartupError,
    InvalidApplicationNameError,
    InvalidDaemonRequestError,
    MyPMError,
)
from .domain import ApplicationName
from .infrastructure import (
    InMemoryApplicationRepository,
    SubprocessRuntime,
    UnixSocketClient,
)

BASE: Path = Path.home() / ".mypm"
SOCK: Path = BASE / "daemon.sock"
LOGS: Path = BASE / "logs"
cli = typer.Typer(
    name="mypm",
    help="Gerenciador de processos Python.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
console = Console()


class DaemonService:
    """Hospeda o gerenciador de processos em um socket Unix."""

    def __init__(
        self,
        socket_path: Path = SOCK,
        logs_directory: Path = LOGS,
    ) -> None:
        """Configura os caminhos utilizados pelo daemon."""
        self._socket_path = socket_path
        self._logs_directory = logs_directory

    def run(self) -> None:
        """Executa o servidor até receber um pedido de desligamento."""
        BASE.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._logs_directory.mkdir(mode=0o700, exist_ok=True)
        client = UnixSocketClient(self._socket_path)
        if self._socket_path.exists():
            if self._is_alive(client):
                message = "Daemon já está em execução"
                raise DaemonAlreadyRunningError(message)
            self._socket_path.unlink()

        repository = InMemoryApplicationRepository()
        runtime = SubprocessRuntime(self._logs_directory)
        manager = ProcessManager(repository, runtime)
        server = self._create_server()
        try:
            while not manager.stopping:
                manager.reconcile()
                try:
                    connection, _ = server.accept()
                except TimeoutError:
                    continue
                self._serve_connection(connection, manager)
        finally:
            manager.stop_all()
            server.close()
            self._socket_path.unlink(missing_ok=True)

    def _create_server(self) -> socket.socket:
        old_umask = os.umask(0o077)
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            server.bind(str(self._socket_path))
            server.listen(10)
            server.settimeout(0.5)
        finally:
            os.umask(old_umask)
        return server

    @staticmethod
    def _serve_connection(
        connection: socket.socket,
        manager: ProcessManager,
    ) -> None:
        with connection:
            try:
                request = DaemonService._read_request(connection)
                result = manager.handle(request)
            except (MyPMError, KeyError, OSError) as error:
                result = Response(ok=False, error=str(error))
            connection.sendall((json.dumps(result) + "\n").encode())

    @staticmethod
    def _read_request(connection: socket.socket) -> Request:
        raw = b""
        while not raw.endswith(b"\n") and len(raw) < 65536:
            chunk = connection.recv(4096)
            if not chunk:
                break
            raw += chunk
        decoded = json.loads(raw)
        if not isinstance(decoded, dict):
            message = "Requisição inválida"
            raise InvalidDaemonRequestError(message)
        return cast("Request", decoded)

    @staticmethod
    def _is_alive(client: UnixSocketClient) -> bool:
        try:
            return client.request({"cmd": "ping"}).get("ok", False)
        except OSError, MyPMError:
            return False


class CommandLineApplication:
    """Traduz comandos do terminal em solicitações ao daemon."""

    def __init__(
        self,
        client: UnixSocketClient | None = None,
        daemon: DaemonService | None = None,
        output: Console | None = None,
    ) -> None:
        """Cria a interface com dependências substituíveis em testes."""
        self._client = client or UnixSocketClient(SOCK)
        self._daemon = daemon or DaemonService()
        self._console = output or console

    def execute(self, request: Request) -> None:
        """Envia um comando ao daemon e apresenta seu resultado."""
        command = request["cmd"]
        if command == "shutdown" and not self._is_daemon_alive():
            self._show_message("Daemon já está parado", "yellow")
            return

        self._ensure_daemon()
        response = self._client.request(request)
        if not response.get("ok", False):
            self._show_message(
                response.get("error", "Erro desconhecido"),
                "red",
            )
            raise typer.Exit(code=1)
        if command == "list":
            self._print_applications(response)
        else:
            pid = response.get("pid")
            detail = f"PID [bold]{pid}[/]" if pid is not None else None
            self._show_message(detail or "Comando concluído", "green")

    def _ensure_daemon(self) -> None:
        if self._is_daemon_alive():
            return
        BASE.mkdir(mode=0o700, parents=True, exist_ok=True)
        with (
            Path(os.devnull).open("rb") as stdin,
            (BASE / "daemon.log").open("ab") as log,
        ):
            subprocess.Popen(
                [sys.executable, "-m", "mypm.main", "_daemon"],
                stdin=stdin,
                stdout=log,
                stderr=log,
                start_new_session=True,
                close_fds=True,
            )
        for _ in range(40):
            if self._is_daemon_alive():
                return
            time.sleep(0.1)
        message = f"Daemon não iniciou. Veja {BASE / 'daemon.log'}"
        raise DaemonStartupError(message)

    def _is_daemon_alive(self) -> bool:
        try:
            return self._client.request({"cmd": "ping"}).get(
                "ok", False
            )
        except OSError, MyPMError:
            return False

    def show_logs(self, raw_name: str) -> None:
        """Acompanha o arquivo de log de uma aplicação."""
        try:
            name = ApplicationName(raw_name)
        except InvalidApplicationNameError as error:
            self._show_message(str(error), "red")
            raise typer.Exit(code=2) from error
        path = LOGS / f"{name.value}.log"
        if not path.exists():
            self._show_message("Log não encontrado", "red")
            raise typer.Exit(code=2)
        subprocess.run(
            ["tail", "-n", "50", "-f", str(path)],
            check=False,
        )

    def _print_applications(self, response: Response) -> None:
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Nome", style="bold")
        table.add_column("Status")
        table.add_column("PID", justify="right")
        table.add_column("Reinícios", justify="right")
        for application in response.get("apps", []):
            pid = str(application["pid"] or "-")
            state = application["state"]
            color = "green" if state == "online" else "yellow"
            table.add_row(
                application["name"],
                f"[{color}]{state}[/]",
                pid,
                str(application["restarts"]),
            )
        self._console.print(
            Panel(
                table,
                title="[bold]Processos gerenciados[/]",
                border_style="cyan",
            )
        )

    def _show_message(self, message: str, color: str) -> None:
        self._console.print(
            Panel(message, border_style=color, title="[bold]MyPM[/]")
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


def main() -> None:
    """Inicia a interface de linha de comando."""
    cli()


if __name__ == "__main__":
    main()
