#!/bin/bash
# Richtet die Python-Umgebung (.venv) für das End-to-End-Projekt ein. Nur einmal nötig.
#
# Warum eine eigene Umgebung?
#  - PyTorch gibt es nicht als System-Paket in passender Version.
#  - Die Umgebung darf die System-Pakete mitbenutzen (--system-site-packages),
#    damit picamera2, picarx und robot_hat weiter funktionieren.
#  - NumPy und OpenCV kommen zusätzlich per pip in die Umgebung: Die System-Versionen
#    laden eine Rechenbibliothek (OpenBLAS), die sich mit der von PyTorch nicht verträgt.
set -e
cd "$(dirname "$0")"
python3 -m venv --system-site-packages .venv
.venv/bin/pip install --upgrade pip
# Die CPU-Variante von PyTorch (die normale Variante bringt 5 GB Grafikkarten-Treiber mit)
.venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu
.venv/bin/pip install --ignore-installed -r requirements.txt
echo "Fertig. Starten mit:  ./start.sh"
