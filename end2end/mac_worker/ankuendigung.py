"""
ankuendigung.py – Meldet den Dienst per mDNS (Zeroconf) im lokalen Netz an.

So findet der Pi den Mac automatisch, ohne dass man eine IP-Adresse abtippen muss –
genauso, wie ein Drucker im Netz von selbst auftaucht.
"""

import socket

from zeroconf import ServiceInfo, Zeroconf

DIENST_TYP = "_picar-training._tcp.local."

_zeroconf = None
_info = None


def eigene_ip():
    """Die IP-Adresse, unter der dieser Rechner im lokalen Netz erreichbar ist."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        # Es wird nichts gesendet – das Betriebssystem wählt nur die passende Netzwerkkarte aus.
        s.connect(("192.168.0.1", 1))
        return s.getsockname()[0]


def starten(name, port, version, protokoll):
    """Kündigt den Dienst an. Ergebnis: True, wenn es geklappt hat."""
    global _zeroconf, _info
    try:
        rechner = socket.gethostname().split(".")[0]
        _info = ServiceInfo(
            DIENST_TYP,
            f"{name}.{DIENST_TYP}",
            addresses=[socket.inet_aton(eigene_ip())],
            port=port,
            properties={"version": version, "protokoll": str(protokoll)},
            server=f"{rechner}.local.",
        )
        _zeroconf = Zeroconf()
        _zeroconf.register_service(_info)
        return True
    except Exception as fehler:   # ohne Ankündigung geht es auch – dann eben IP von Hand eingeben
        print("mDNS-Ankündigung hat nicht geklappt:", repr(fehler))
        return False


def beenden():
    if _zeroconf:
        _zeroconf.unregister_service(_info)
        _zeroconf.close()
