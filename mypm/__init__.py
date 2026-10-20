"""Public package interface."""


def main() -> None:
    """Run the command-line application."""
    from .main import main as run

    run()


__all__ = ["main"]
