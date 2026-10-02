"""SpeedTree Raw XML to USDA converter."""

__all__ = ["main"]


def main(argv=None) -> int:
    from .cli import main as cli_main

    return cli_main(argv)
