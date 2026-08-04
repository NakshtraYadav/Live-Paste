"""PyInstaller entry point for the standalone LivePaste binary."""

import multiprocessing

from livepaste.cli import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
