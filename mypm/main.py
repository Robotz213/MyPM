"""Interface de linha de comando e servidor daemon do MyPM."""

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import cast

from .application import ProcessManager, Request, Response
from .common.exceptions import (
    DaemonAlreadyRunningError,
    DaemonStartupError,
    InvalidApplicationNameError,
    InvalidDaemonRequestError,
    MyPMError,
)
from .console import ConsolePresenter
from .domain import ApplicationName
from .infrastructure import (
    JsonApplicationRepository,
    SubprocessRuntime,
    UnixSocketClient,
)

BASE: Path = Path.home() / ".mypm"
SOCK: Path = BASE / "daemon.sock"
LOGS: Path = BASE / "logs"
DATABASE: Path = BASE / "applications.json"
AUTOSTART: Path = Path.home() / ".config/autostart/mypm.desktop"


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

        repository = JsonApplicationRepository(DATABASE)
        runtime = SubprocessRuntime(self._logs_directory)
        manager = ProcessManager(repository, runtime)
        manager.restore()
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
        presenter: ConsolePresenter | None = None,
    ) -> None:
        """Cria a interface com dependências substituíveis em testes."""
        self._client = client or UnixSocketClient(SOCK)
        self._daemon = daemon or DaemonService()
        self._presenter = presenter or ConsolePresenter()

    def execute(self, request: Request) -> None:
        """Envia um comando ao daemon e apresenta seu resultado."""
        command = request["cmd"]
        if command == "shutdown" and not self._is_daemon_alive():
            self._presenter.show_warning("Daemon já está parado")
            return

        self._ensure_daemon()
        response = self._client.request(request)
        if not response.get("ok", False):
            self._presenter.show_error(
                response.get("error", "Erro desconhecido")
            )
            return
        if command == "list":
            self._presenter.show_applications(response)
        else:
            pid = response.get("pid")
            detail = f"PID [bold]{pid}[/]" if pid is not None else None
            self._presenter.show_success(detail or "Comando concluído")

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
            self._presenter.show_error(str(error))
            return
        path = LOGS / f"{name.value}.log"
        if not path.exists():
            self._presenter.show_error("Log não encontrado")
            return
        subprocess.run(
            ["tail", "-n", "50", "-f", str(path)],
            check=False,
        )

    def install_startup(self) -> None:
        """Instala a inicialização automática na sessão do usuário."""
        AUTOSTART.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        command = f"{sys.executable} -m mypm.main list"
        content = (
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=MyPM\n"
            "Comment=Inicia o gerenciador de processos MyPM\n"
            f"Exec={command}\n"
            "Terminal=false\n"
            "X-GNOME-Autostart-enabled=true\n"
        )
        AUTOSTART.write_text(content, encoding="utf-8")
        self._presenter.show_success(
            f"Inicialização automática instalada em [bold]{AUTOSTART}[/]"
        )

    def remove_startup(self) -> None:
        """Remove a inicialização automática da sessão do usuário."""
        AUTOSTART.unlink(missing_ok=True)
        self._presenter.show_success(
            "Inicialização automática removida"
        )


def main() -> None:
    """Inicia a interface de linha de comando."""
    from .cli import cli

    cli()


if __name__ == "__main__":
    main()
