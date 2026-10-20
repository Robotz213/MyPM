"""Exceções específicas das regras e operações do MyPM."""


class MyPMError(Exception):
    """Classe base para erros controlados pelo MyPM."""


class DomainError(MyPMError):
    """Classe base para violações das regras de domínio."""


class InvalidApplicationNameError(DomainError):
    """Indica que o nome informado para a aplicação é inválido."""


class ApplicationAlreadyExistsError(DomainError):
    """Indica que já existe uma aplicação com o mesmo nome."""


class ApplicationNotFoundError(DomainError):
    """Indica que a aplicação solicitada não foi encontrada."""


class ScriptNotFoundError(DomainError):
    """Indica que o script informado não existe."""


class ApplicationError(MyPMError):
    """Classe base para erros dos casos de uso."""


class InvalidProcessCommandError(ApplicationError):
    """Indica que o comando solicitado não é suportado."""


class MissingRequestDataError(ApplicationError):
    """Indica a ausência de dados obrigatórios na solicitação."""


class ProcessStartedWithoutPidError(ApplicationError):
    """Indica que um processo foi iniciado sem fornecer um PID."""


class InfrastructureError(MyPMError):
    """Classe base para falhas de infraestrutura."""


class InvalidDaemonRequestError(InfrastructureError):
    """Indica que o daemon recebeu uma solicitação inválida."""


class InvalidDaemonResponseError(InfrastructureError):
    """Indica que o cliente recebeu uma resposta inválida."""


class DaemonCommunicationError(InfrastructureError):
    """Indica uma falha ao comunicar-se com o daemon."""


class DaemonAlreadyRunningError(InfrastructureError):
    """Indica que já existe uma instância ativa do daemon."""


class DaemonStartupError(InfrastructureError):
    """Indica que o daemon não iniciou no prazo esperado."""
