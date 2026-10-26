"""
version.py – Welcher Stand des Codes läuft gerade?

Pi und Mac melden ihren Git-Commit. Weicht er ab, warnt die Weboberfläche:
Dann könnten Pi und Mac verschiedene Versionen des Kerns benutzen.
"""

import subprocess
from pathlib import Path

PROJEKT = Path(__file__).resolve().parent.parent   # der Ordner end2end


def code_version():
    """Kurzer Git-Commit, z. B. "d389bfe". Mit „+geändert“, wenn es lokale Änderungen am Code gibt."""
    try:
        commit = subprocess.run(["git", "-C", str(PROJEKT), "rev-parse", "--short", "HEAD"],
                                capture_output=True, text=True, timeout=5).stdout.strip()
        # Lokale, noch nicht committete Änderungen an Dateien von end2end?
        aenderungen = subprocess.run(["git", "-C", str(PROJEKT), "status", "--porcelain", "--untracked-files=no", "."],
                                     capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return "unbekannt"
    if not commit:
        return "unbekannt"
    return commit + ("+geändert" if aenderungen else "")
