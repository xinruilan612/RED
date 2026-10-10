"""Interpreter locations only; never substitute another environment on failure."""
import os
from pathlib import Path


def venv_python(directory, *, windows=None):
    """Return the native Python entry point in a declared virtual environment."""
    windows = os.name == 'nt' if windows is None else windows
    return Path(directory) / ('Scripts/python.exe' if windows else 'bin/python')


def is_venv_python(interpreter, directory):
    """Recognize either layout for the existing website-environment guard."""
    candidate = Path(interpreter).absolute()
    return candidate in {venv_python(directory, windows=flag).absolute() for flag in (False, True)}


def module_command(module):
    """Re-enter the frozen launcher only for the bounded document parsers."""
    import sys
    services = {'backend.document_parser': 'document-parser', 'backend.word_parser': 'word-parser'}
    if module not in services:
        raise ValueError('Unsupported subprocess module.')
    if getattr(sys, 'frozen', False):
        return [sys.executable, '--service', services[module]]
    return [sys.executable, '-m', module]
