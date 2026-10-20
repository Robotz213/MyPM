"""Objetos e contratos que representam o domínio do MyPM."""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from .common.exceptions import InvalidApplicationNameError


class ApplicationState(StrEnum):
    """Estados possíveis de uma aplicação gerenciada."""

    ONLINE = "online"
    WAITING = "waiting"
    STOPPED = "stopped"


@dataclass(slots=True)
class ManagedApplication:
    """Representa uma aplicação acompanhada pelo daemon."""

    name: str
    script: Path
    state: ApplicationState = ApplicationState.STOPPED
    pid: int | None = None
    restarts: int = 0


@dataclass(frozen=True, slots=True)
class ApplicationName:
    """Nome validado usado para identificar uma aplicação."""

    value: str

    def __post_init__(self) -> None:
        """Garante que o nome possa ser usado com segurança."""
        if not self.value or not all(
            character.isalnum() or character in "_-"
            for character in self.value
        ):
            message = "Nome inválido (use letras, números, _ ou -)"
            raise InvalidApplicationNameError(message)


class ApplicationRepository(Protocol):
    """Contrato para armazenar aplicações gerenciadas."""

    def add(self, application: ManagedApplication) -> None:
        """Adiciona uma aplicação ao repositório."""
        ...

    def get(self, name: ApplicationName) -> ManagedApplication:
        """Obtém uma aplicação pelo nome."""
        ...

    def list(self) -> tuple[ManagedApplication, ...]:
        """Lista as aplicações armazenadas."""
        ...

    def remove(self, name: ApplicationName) -> None:
        """Remove uma aplicação do repositório."""
        ...


class ProcessRuntime(Protocol):
    """Contrato para controlar processos do sistema operacional."""

    def launch(self, application: ManagedApplication) -> None:
        """Inicia o processo de uma aplicação."""
        ...

    def stop(self, application: ManagedApplication) -> None:
        """Encerra o processo de uma aplicação."""
        ...

    def reconcile(
        self, applications: tuple[ManagedApplication, ...]
    ) -> None:
        """Sincroniza o estado do domínio com os processos reais."""
        ...
