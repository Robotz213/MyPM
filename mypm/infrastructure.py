"""Adaptadores de persistência, processos e comunicação local."""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, cast

from .common.exceptions import (
    ApplicationAlreadyExistsError,
    ApplicationNotFoundError,
    InvalidDaemonResponseError,
)
from .domain import (
    ApplicationName,
    ApplicationState,
    ManagedApplication,
)

if TYPE_CHECKING:
    from .application import Request, Response


class InMemoryApplicationRepository:
    """Mantém em memória as aplicações conhecidas pelo daemon."""

    def __init__(self) -> None:
        """Cria um repositório vazio."""
        self._applications: dict[str, ManagedApplication] = {}

    def add(self, application: ManagedApplication) -> None:
        """Armazena uma aplicação ainda não cadastrada."""
        if application.name in self._applications:
            message = "Nome já existe"
            raise ApplicationAlreadyExistsError(message)
        self._applications[application.name] = application

    def get(self, name: ApplicationName) -> ManagedApplication:
        """Retorna a aplicação identificada pelo nome."""
        try:
            return self._applications[name.value]
        except KeyError as error:
            message = "Aplicação não encontrada"
            raise ApplicationNotFoundError(message) from error

    def list(self) -> tuple[ManagedApplication, ...]:
        """Retorna uma visão imutável das aplicações."""
        return tuple(self._applications.values())

    def remove(self, name: ApplicationName) -> None:
        """Exclui uma aplicação do repositório."""
        del self._applications[name.value]

    def save(self) -> None:
        """Não realiza persistência para o repositório em memória."""


class JsonApplicationRepository(InMemoryApplicationRepository):
    """Persiste aplicações em um arquivo JSON local."""

    def __init__(self, database_path: Path) -> None:
        """Carrega as aplicações existentes no arquivo informado."""
        super().__init__()
        self._database_path = database_path
        self._load()

    def add(self, application: ManagedApplication) -> None:
        """Adiciona e persiste uma aplicação."""
        super().add(application)
        self.save()

    def remove(self, name: ApplicationName) -> None:
        """Remove e persiste a exclusão de uma aplicação."""
        super().remove(name)
        self.save()

    def save(self) -> None:
        """Grava o estado atual de forma atômica."""
        self._database_path.parent.mkdir(
            mode=0o700, parents=True, exist_ok=True
        )
        data = [
            {
                "name": application.name,
                "script": str(application.script),
                "state": application.state.value,
                "restarts": application.restarts,
            }
            for application in self.list()
        ]
        temporary_path = self._database_path.with_suffix(".tmp")
        temporary_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        temporary_path.replace(self._database_path)

    def _load(self) -> None:
        if not self._database_path.exists():
            return
        records = json.loads(
            self._database_path.read_text(encoding="utf-8")
        )
        if not isinstance(records, list):
            message = "Banco de aplicações inválido"
            raise InvalidDaemonResponseError(message)
        for record in records:
            if not isinstance(record, dict):
                message = "Registro de aplicação inválido"
                raise InvalidDaemonResponseError(message)
            application = ManagedApplication(
                name=str(record["name"]),
                script=Path(str(record["script"])),
                state=ApplicationState(str(record["state"])),
                restarts=int(str(record.get("restarts", 0))),
            )
            self._applications[application.name] = application


class SubprocessRuntime:
    """Controla aplicações usando subprocessos do sistema."""

    def __init__(self, logs_directory: Path) -> None:
        """Configura o diretório que receberá os logs."""
        self._logs_directory = logs_directory
        self._processes: dict[str, subprocess.Popen[bytes]] = {}
        self._next_starts: dict[str, float] = {}

    def launch(self, application: ManagedApplication) -> None:
        """Inicia uma aplicação e registra seu PID."""
        log_path = self._logs_directory / f"{application.name}.log"
        with log_path.open("ab", buffering=0) as output:
            process = subprocess.Popen(
                [sys.executable, "-u", str(application.script)],
                cwd=application.script.parent,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        self._processes[application.name] = process
        application.pid = process.pid
        application.state = ApplicationState.ONLINE

    def stop(self, application: ManagedApplication) -> None:
        """Encerra uma aplicação e limpa seu estado de execução."""
        process = self._processes.get(application.name)
        if process is not None and process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
        self._processes.pop(application.name, None)
        self._next_starts.pop(application.name, None)
        application.pid = None
        application.state = ApplicationState.STOPPED

    def reconcile(
        self,
        applications: tuple[ManagedApplication, ...],
    ) -> None:
        """Detecta falhas e executa os reinícios agendados."""
        now = time.monotonic()
        for application in applications:
            process = self._processes.get(application.name)
            if (
                application.state is ApplicationState.ONLINE
                and process is not None
                and process.poll() is not None
            ):
                self._processes.pop(application.name, None)
                application.pid = None
                application.state = ApplicationState.WAITING
                self._next_starts[application.name] = now + 2
            if (
                application.state is ApplicationState.WAITING
                and now >= self._next_starts[application.name]
            ):
                try:
                    self.launch(application)
                    application.restarts += 1
                except OSError:
                    self._next_starts[application.name] = now + 5


class UnixSocketClient:
    """Envia solicitações JSON ao daemon por socket Unix."""

    def __init__(self, socket_path: Path) -> None:
        """Configura o caminho do socket usado pelo daemon."""
        self._socket_path = socket_path

    def request(self, payload: Request) -> Response:
        """Envia uma solicitação e devolve a resposta decodificada."""
        with socket.socket(
            socket.AF_UNIX, socket.SOCK_STREAM
        ) as connection:
            connection.settimeout(5)
            connection.connect(str(self._socket_path))
            connection.sendall((json.dumps(payload) + "\n").encode())
            data = b""
            while not data.endswith(b"\n"):
                chunk = connection.recv(65536)
                if not chunk:
                    break
                data += chunk
        response = json.loads(data.decode())
        if not isinstance(response, dict):
            message = "Resposta inválida do daemon"
            raise InvalidDaemonResponseError(message)
        return cast("Response", response)
