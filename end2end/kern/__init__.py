"""
kern – Der gemeinsame Kern des End-to-End-Projekts.

Dieses Paket benutzen BEIDE Seiten:
  - die App auf dem Raspberry Pi (Aufnehmen, Trainieren, autonom Fahren)
  - der Trainings-Dienst auf dem Mac (mac_worker)

Weil beide denselben Code verwenden, passen die Modelle garantiert zusammen:
Ein auf dem Mac trainiertes Netz sieht genau so aus und bekommt die Bilder genau
so vorbereitet wie auf dem Pi.

Wichtig: Hier darf nichts stehen, was nur auf dem Pi läuft (picarx, robot_hat,
vilib, picamera2) – sonst ließe sich der Kern auf dem Mac nicht importieren.

    konstanten.py       Bildgröße fürs Netz, größter Lenkwinkel
    vorverarbeitung.py  Ausschnitt aus dem Kamerabild → Bild fürs Netz
    netz.py             das neuronale Netz (PilotNet, verkleinert)
    datensatz.py        Fahrten von der Festplatte lesen
    training.py         das Training (Validierung, Early Stopping, Augmentierung)
    version.py          Code-Version (Git-Commit)
"""
