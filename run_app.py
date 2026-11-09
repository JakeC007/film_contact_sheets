"""Entry point for PyInstaller and for double-click launching."""

import sys

from contact_sheet.gui.main_window import main

if __name__ == "__main__":
    sys.exit(main())
