"""Entrypoint when running `python -m envoyr`."""

import sys
from envoyr.cli import main

if __name__ == "__main__":
    sys.exit(main())
