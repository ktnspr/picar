"""konstanten.py – Zahlen, die Pi und Mac gleich verwenden müssen."""

NETZ_HOEHE, NETZ_BREITE = 48, 160   # so groß ist das Bild, das ins Netz geht
LENKUNG_MAX = 30                     # Grad; das Netz gibt -1 bis 1 aus, mal LENKUNG_MAX

# Variante „Bildfolge“: Das Netz sieht außer dem aktuellen Bild auch frühere Bilder
GEDAECHTNIS_S = 4.0                  # so weit schaut es zurück (Sekunden)
FOLGE_ABSTAND_S = 0.2                # Abstand der Bilder in der Folge (Sekunden)
FOLGE_LAENGE = round(GEDAECHTNIS_S / FOLGE_ABSTAND_S) + 1   # 21 Bilder: das aktuelle und 20 frühere
