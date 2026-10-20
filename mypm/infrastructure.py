"""Adaptadores de persistência, processos e comunicação local."""

import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import cast

from .application import Request, Response
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
