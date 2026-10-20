"""Casos de uso e contratos de comunicação do gerenciador."""

from pathlib import Path
from typing import TYPE_CHECKING, NotRequired, TypedDict

if TYPE_CHECKING:
    from collections.abc import Callable

from .common.exceptions import (
    ApplicationAlreadyExistsError,
    ApplicationNotFoundError,
    InvalidProcessCommandError,
    MissingRequestDataError,
    ProcessStartedWithoutPidError,
    ScriptNotFoundError,
)
from .domain import (
    ApplicationName,
    ApplicationRepository,
    ManagedApplication,
    ProcessRuntime,
)


class Request(TypedDict):
    """Representa uma solicitação enviada ao daemon."""

    cmd: str
    name: NotRequired[str]
    script: NotRequired[str]


class ApplicationView(TypedDict):
    """Define os dados públicos de um processo gerenciado."""

    name: str
    state: str
    pid: int | None
    restarts: int


class Response(TypedDict, total=False):
    """Representa a resposta devolvida pelo daemon."""

    ok: bool
    error: str
    pid: int
    apps: list[ApplicationView]


class ProcessManager:
    """Orquestra os casos de uso disponíveis para processos."""

    def __init__(
        self,
        repository: ApplicationRepository,
        runtime: ProcessRuntime,
    ) -> None:
        """Inicializa o serviço com suas dependências externas."""
        self._repository = repository
        self._runtime = runtime
        self._stopping = False
        self._handlers: dict[str, Callable[[Request], Response]] = {
            "ping": self._ping,
            "start": self._start,
            "list": self._list,
            "stop": self._stop,
            "restart": self._restart,
            "delete": self._delete,
            "shutdown": self._shutdown,
        }

    @property
    def stopping(self) -> bool:
        """Informa se o encerramento do daemon foi solicitado."""
        return self._stopping

    def reconcile(self) -> None:
        """Atualiza processos encerrados e reinícios pendentes."""
        self._runtime.reconcile(self._repository.list())
        self._repository.save()

    def restore(self) -> None:
        """Restaura processos que estavam ativos antes do daemon parar."""
        for application in self._repository.list():
            if application.state.value in {"online", "waiting"}:
                self._runtime.launch(application)
        self._repository.save()

    def handle(self, request: Request) -> Response:
        """Executa o caso de uso indicado na requisição."""
        try:
            handler = self._handlers[request["cmd"]]
        except KeyError as error:
            message = "Comando inválido"
            raise InvalidProcessCommandError(message) from error
        return handler(request)

    def stop_all(self) -> None:
        """Encerra todos os processos antes de desligar o daemon."""
        for application in self._repository.list():
            self._runtime.stop(application)
        self._repository.save()

    @staticmethod
    def _ping(_: Request) -> Response:
        return {"ok": True}

    def _list(self, _: Request) -> Response:
        return {"ok": True, "apps": self._list_applications()}

    def _shutdown(self, _: Request) -> Response:
        self._stopping = True
        return {"ok": True}

    def _start(self, request: Request) -> Response:
        raw_script = request.get("script")
        raw_name = request.get("name")
        if raw_script is None or raw_name is None:
            message = "Nome e arquivo são obrigatórios"
            raise MissingRequestDataError(message)
        script = Path(raw_script).resolve()
        if not script.is_file():
            message = "Arquivo não existe"
            raise ScriptNotFoundError(message)
        name = ApplicationName(raw_name)
        try:
            self._repository.get(name)
        except ApplicationNotFoundError:
            pass
        else:
            message = "Nome já existe"
            raise ApplicationAlreadyExistsError(message)
        application = ManagedApplication(name.value, script)
        self._runtime.launch(application)
        self._repository.add(application)
        if application.pid is None:
            message = "Processo iniciado sem PID"
            raise ProcessStartedWithoutPidError(message)
        return {"ok": True, "pid": application.pid}

    def _find_application(
        self, request: Request
    ) -> tuple[ApplicationName, ManagedApplication]:
        raw_name = request.get("name")
        if raw_name is None:
            message = "Nome é obrigatório"
            raise MissingRequestDataError(message)
        name = ApplicationName(raw_name)
        return name, self._repository.get(name)

    def _stop(self, request: Request) -> Response:
        _, application = self._find_application(request)
        self._runtime.stop(application)
        self._repository.save()
        return {"ok": True}

    def _restart(self, request: Request) -> Response:
        _, application = self._find_application(request)
        self._runtime.stop(application)
        self._runtime.launch(application)
        self._repository.save()
        return {"ok": True}

    def _delete(self, request: Request) -> Response:
        name, application = self._find_application(request)
        self._runtime.stop(application)
        self._repository.remove(name)
        return {"ok": True}

    def _list_applications(self) -> list[ApplicationView]:
        return [
            {
                "name": application.name,
                "state": application.state.value,
                "pid": application.pid,
                "restarts": application.restarts,
            }
            for application in self._repository.list()
        ]
