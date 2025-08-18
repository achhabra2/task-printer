"""
Printing subsystem for Task Printer.

This package groups printing-related functionality:

- render: Text rendering to Pillow images suitable for ESC/POS printers
- worker: Background job queue, job registry, and print orchestration

For convenience, common functions are re-exported for easy import.
"""

from .render import *
from .emoji import *
from .worker import *
