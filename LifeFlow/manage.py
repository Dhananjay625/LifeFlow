#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys
import pathlib
import dotenv


def main():
    """Run administrative tasks."""

    BASE_DIR = pathlib.Path(__file__).resolve().parent
    dotenv.load_dotenv(BASE_DIR / ".env")

    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'LifeFlow.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
