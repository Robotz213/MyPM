"""Apresentação de resultados no terminal usando Rich."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

if TYPE_CHECKING:
    from .application import Response


class ConsolePresenter:
    """Formata mensagens e listas exibidas no terminal."""

    def __init__(self, console: Console | None = None) -> None:
        """Configura o console utilizado para renderizar as saídas."""
        self._console = console or Console()

    def show_success(self, message: str = "Comando concluído") -> None:
        """Exibe uma confirmação de sucesso."""
        self._show_message(message, "green")

    def show_warning(self, message: str) -> None:
        """Exibe uma mensagem de atenção."""
        self._show_message(message, "yellow")

    def show_error(self, message: str) -> None:
        """Exibe uma mensagem de erro."""
        self._show_message(message, "red")

    def show_applications(self, response: Response) -> None:
        """Exibe os processos gerenciados em uma tabela."""
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Nome", style="bold")
        table.add_column("Status")
        table.add_column("PID", justify="right")
        table.add_column("Reinícios", justify="right")

        for application in response.get("apps", []):
            state = application["state"]
            color = "green" if state == "online" else "yellow"
            table.add_row(
                application["name"],
                f"[{color}]{state}[/]",
                str(application["pid"] or "-"),
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
