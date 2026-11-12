# Projektzusammenfassung für ein Poster: „Ein Auto lernt, einer Linie zu folgen“

> **Für die Claude-Instanz, die das Poster gestaltet:** Diese Datei enthält alles Inhaltliche.
> Anlass ist ein **Studieninformationstag**. Das Publikum sind Schülerinnen und Schüler der Oberstufe
> und ihre Eltern, also interessierte Laien ohne Vorwissen in KI. Das Auto steht als Live-Demo
> neben dem Poster. Bitte keine Code-Details aufs Poster, sondern Ideen, Bilder und Zahlen.
> Alle Zahlen unten sind auf dem echten Fahrzeug gemessen. Bitte keine Werte erfinden oder
> aufrunden. Wo etwas fehlt, steht **[Platzhalter]**.

---

## 1. Worum geht es? (Kernbotschaft)

Ein kleines Roboterauto (SunFounder PiCar-X auf einem Raspberry Pi 5) soll einer Klebebandlinie auf
dem Boden folgen, **ohne dass jemand eine einzige Lenkregel programmiert hat**.

Stattdessen zeigt ein Mensch dem Auto, wie man fährt: Er steuert es ein paar Minuten mit einem
Gamepad die Strecke entlang. Das Auto speichert dabei Kamerabilder und die zugehörigen Lenkwinkel.
Ein **neuronales Netz** lernt daraus selbst, aus einem Kamerabild den richtigen Lenkwinkel
abzuleiten. Danach fährt das Auto allein.

**Vorschläge für den Titel bzw. Slogan:**
- „Vom Zuschauen zum Selberfahren: Ein Auto lernt Lenken“
- „Kamerabild rein, Lenkwinkel raus: End-to-End-Lernen auf einem Mini-Auto“
- „Keine Regeln, nur Beispiele: Wie ein neuronales Netz Autofahren lernt“

**Drei Botschaften, die hängen bleiben sollen:**
1. **Lernen aus Beispielen statt Programmieren von Regeln.** Das Auto ahmt nach, was ein Mensch vormacht.
   Der Fachbegriff dafür ist *Imitation Learning* oder *Behavioral Cloning*.
2. **Ein Gedächtnis hilft.** Wenn die Linie aus dem Bild verschwindet, „erinnert“ sich das Auto, wo
   sie zuletzt war, und lenkt zurück.
3. **Daten sind entscheidend.** Was das Netz lernen soll, muss in den Trainingsfahrten vorkommen.
   Deshalb haben wir dem Auto absichtlich auch Fehler und deren Korrektur gezeigt („Driftfahrten“).

---

## 2. Die Hardware

| Bauteil | Details |
|---|---|
| Fahrzeug | SunFounder PiCar-X V2.0, etwa 22 × 14 cm, Vorderradlenkung (±30°), zwei angetriebene Hinterräder |
| Rechner | Raspberry Pi 5, sitzt direkt auf dem Auto. Das Netz rechnet **auf dem Auto selbst**, nicht in der Cloud |
| Sensor | **Eine einzige Frontkamera** (5 MP, wir nutzen 320 × 240 Pixel bei 30 Bildern/s), auf einer schwenk- und neigbaren Halterung |
| Steuerung | Nintendo Switch Pro Controller per Bluetooth (zum Vorfahren und als Not-Aus) |
| Bedienung | Weboberfläche im Browser (Handy oder Laptop): Livebild, Aufnehmen, Trainieren, Autonom fahren |
| Training | Auf dem Pi selbst oder viel schneller auf einem Mac im selben WLAN (siehe Abschnitt 7) |

Erwähnenswert für technisch Interessierte: Ein **elektronisches Differential** regelt in Kurven die
beiden Hinterräder unterschiedlich schnell, wie bei einem echten Auto, wo das äußere Rad einen
längeren Weg hat.

---

## 3. Was heißt „End-to-End“?

**Klassischer Ansatz** (viele Einzelschritte, alle von Menschen programmiert):
Kamerabild → Linie suchen (Kanten, Farben) → Position und Richtung berechnen → Regel „Linie links → links lenken“ → Lenkwinkel

**End-to-End-Ansatz** (unser Weg):
Kamerabild → **ein neuronales Netz** → Lenkwinkel

Dazwischen programmiert niemand etwas. Das Netz findet selbst heraus, worauf es im Bild ankommt.
Vorbild ist NVIDIAs „PilotNet“, mit dem 2016 ein echtes Auto End-to-End gelenkt wurde. Unser Netz
ist eine stark verkleinerte Version davon, damit es auf einem Raspberry Pi läuft.

**Grafikvorschlag:** zwei Abläufe übereinander, oben der klassische mit vielen Kästchen, unten
End-to-End mit einem einzigen großen Kasten „Neuronales Netz“.

---

## 4. Der Ablauf in vier Schritten

Das ist das Herzstück des Posters, am besten als nummerierte Bildleiste von links nach rechts.

1. **Kalibrieren.** Lenkung und Kamera so einstellen, dass „geradeaus“ wirklich geradeaus ist.
2. **Vorfahren und Daten aufnehmen.** Ein Mensch lenkt das Auto mit dem Gamepad die Linie entlang.
   Das Auto speichert **10 Bilder pro Sekunde**, jedes zusammen mit dem Lenkwinkel, den der Mensch
   in dem Moment eingestellt hat. Eine Fahrt von knapp 3 Minuten ergibt etwa 1700 Bilder.
3. **Trainieren.** Das neuronale Netz sieht sich alle Bilder an und versucht immer wieder, den
   Lenkwinkel des Menschen vorherzusagen. Nach jedem Fehler werden seine Gewichte ein wenig
   verbessert. Das geschieht auf einem Mac in **unter einer Minute**.
4. **Autonom fahren.** Das Netz bekommt jetzt **30-mal pro Sekunde** das aktuelle Kamerabild und
   lenkt selbst. Gas gibt das Auto mit konstanter Geschwindigkeit.

---

## 5. Das neuronale Netz (CNN): Wie „sieht“ das Auto?

### Was das Netz bekommt

Das Netz bekommt nicht das ganze Kamerabild, sondern nur den **unteren Teil, also den Boden vor dem
Auto**. Der Ausschnitt ist auf **160 × 48 Pixel** verkleinert und farbig. Himmel, Möbel und Wände
lenken so nicht ab, und das Netz kann klein und schnell bleiben.

**Grafikvorschlag:** Ein Kamerabild mit einem farbigen Rahmen um den unteren Teil, daneben der
verkleinerte Streifen, „so sieht das Netz die Welt“. Ein echtes Foto aus der Fahrt lässt sich
liefern **[Platzhalter: Bild aus der Weboberfläche]**.

### Aufbau: ein *Convolutional Neural Network* (CNN, „faltendes neuronales Netz“)

```
Bild 160 × 48 Pixel, 3 Farbkanäle
   │
   ▼  Faltungsschicht 1: 12 Filter (5×5)   → 12 Merkmalskarten, 78 × 22
   ▼  Faltungsschicht 2: 18 Filter (5×5)   → 18 Karten, 37 × 9
   ▼  Faltungsschicht 3: 24 Filter (5×5)   → 24 Karten, 17 × 3
   ▼  Faltungsschicht 4: 32 Filter (3×3)   → 32 Karten, 15 × 1
   │      (= 480 Zahlen, die das Bild beschreiben)
   ▼  Dense-Schicht: 480 → 64
   ▼  Dense-Schicht:  64 → 16
   ▼  Dense-Schicht:  16 →  1
   │
Lenkwinkel (−30° … +30°)
```

**Anschaulich erklärt:**
- Eine **Faltung** ist ein kleines Fenster, zum Beispiel 5 × 5 Pixel, das über das Bild wandert und
  nach einem Muster sucht. Die ersten Schichten finden einfache Dinge wie **Kanten und helle Flächen**.
  Spätere Schichten setzen daraus **Linienstücke** und schließlich **den Verlauf der Linie**
  zusammen: Wo liegt sie, wie schräg ist sie?
- Mit jeder Schicht wird das Bild kleiner und abstrakter. Aus 23.040 Pixelwerten werden am Ende
  480 Zahlen, die das Wesentliche beschreiben.
- Die **Dense-Schichten** entscheiden aus diesen Zahlen den Lenkwinkel.
- Das ganze Netz hat **rund 56.000 lernbare Zahlen (Gewichte)**. Zum Vergleich: Große Sprachmodelle
  haben Milliarden davon. Unser Netz ist so klein, dass es auf dem Raspberry Pi **etwa 1 ms pro Bild**
  braucht.

**Grafikvorschlag:** Schichten als kleiner werdende, gestapelte Quader (klassische CNN-Darstellung),
darunter die Beschriftung „Kanten → Linienstücke → Linienverlauf → Lenkwinkel“.

### Tricks beim Training (für Neugierige, auf dem Poster gern knapp)
- **Spiegeln:** Jedes Bild wird zufällig auch gespiegelt verwendet, mit umgedrehtem Lenkwinkel. So
  gibt es doppelt so viele Beispiele, und Links- und Rechtskurven kommen gleich oft vor.
- **Helligkeit variieren:** Damit das Auto auch bei anderem Licht fährt.
- **Seltene Fälle öfter zeigen:** Meist fährt man fast geradeaus. Scharfe Kurven sind selten und
  werden deshalb beim Lernen häufiger gezeigt.
- **Ehrlich prüfen:** Ein Teil der Fahrt wird beim Lernen weggelassen und nur zum Prüfen benutzt.
  Wir teilen in zusammenhängende Abschnitte von 3 Sekunden, nicht in einzelne Bilder. Benachbarte
  Bilder sind fast identisch, und sonst würde das Netz beim Prüfen „Zwillinge“ von Lernbildern
  sehen und besser aussehen, als es ist.
- **Rechtzeitig aufhören** (*Early Stopping*): Wird das Netz beim Prüfen nicht mehr besser, hört
  das Training auf. Sonst lernt es die Trainingsbilder auswendig (*Overfitting*).

---

## 6. Das Gedächtnis (RNN): Was tun, wenn die Linie weg ist?

### Das Problem
Ein Netz, das immer nur **ein einzelnes Bild** sieht, ist ratlos, sobald die Linie aus dem Bild
verschwindet, etwa in einer engen Kurve oder wenn jemand das Auto wegschiebt. Es sieht nur Boden.
Ob die Linie links oder rechts hinausgelaufen ist, kann es nicht wissen. Es lenkt dann ungefähr
geradeaus weiter und verliert die Linie.

### Die Lösung: Das Auto bekommt ein Gedächtnis
Die Variante **„Bildfolge“** sieht nicht nur das aktuelle Bild, sondern auch die Bilder der
**letzten 4 Sekunden**: 21 Bilder im Abstand von 0,2 s. Daraus kann sie ablesen, dass die Linie
vor einer Sekunde noch am linken Rand war und jetzt weg ist, also lenkt sie links zurück.

### Aufbau: CNN als „Auge“ + GRU als „Gedächtnis“
```
Bild vor 4,0 s ─► Auge (CNN) ─► 64 Merkmale ─┐
Bild vor 3,8 s ─► Auge (CNN) ─► 64 Merkmale ─┤
      …                                      ├─► GRU (Gedächtnis, 32 Zahlen) ─► Lenkwinkel
Bild vor 0,2 s ─► Auge (CNN) ─► 64 Merkmale ─┤
Bild jetzt     ─► Auge (CNN) ─► 64 Merkmale ─┘
```
- Das **Auge** ist dasselbe CNN wie oben. Es beschreibt jedes Bild mit 64 Zahlen.
- Die **GRU** (*Gated Recurrent Unit*) ist ein kleines **rekurrentes neuronales Netz (RNN)**. Sie
  liest die Bilder der Reihe nach, vom ältesten zum neuesten, und führt dabei einen **inneren
  Zustand** von 32 Zahlen mit, ihr „Gedächtnis“. Zwei „Tore“ entscheiden bei jedem Bild, wie viel
  sie davon behält und wie viel sie aus dem neuen Bild übernimmt.
- Das Gedächtnis hat nur rund **9.400 zusätzliche Gewichte**, insgesamt also etwa 65.000.

**Training in zwei Stufen** (anschaulich: „erst sehen lernen, dann erinnern lernen“):
1. **Sehen:** Das Auge lernt wie ein normales Einzelbild-Netz.
2. **Erinnern:** Das Auge bleibt fest, nur die GRU lernt, die Bildfolge auszuwerten.

**Beim Fahren:** Das Auge verarbeitet jedes neue Kamerabild nur einmal, die Merkmale der älteren
Bilder liegen im Gedächtnis bereit. Eine Lenkentscheidung mit Gedächtnis dauert auf dem
Raspberry Pi **etwa 7 ms**. Neue Kamerabilder kommen alle 33 ms, es bleibt also viel Luft.

**Grafikvorschlag:** Eine Zeitachse mit Filmstreifen-Bildern. Auf den ersten sieht man die Linie
links, auf den letzten keine Linie mehr. Darunter ein Pfeil „Gedächtnis“ und am Ende das Lenkrad
nach links. Alternativ eine Comic-Sprechblase: „Eben war die Linie doch noch links …“

---

## 7. Driftfahrten: Dem Auto auch Fehler zeigen

Das Gedächtnis kann nur lernen, was in den Daten vorkommt. Ein guter menschlicher Fahrer verliert
die Linie aber fast nie. In unseren längeren Aufnahmen (je 1100–1500 Bilder) war die Linie nur bei
0–2 % der Bilder außer Sicht. Das Netz hätte also kaum Beispiele dafür, wie man zurückfindet.

**Unsere Lösung: „Driftfahrten“ (Rettungsfahrten).**
- Während der Aufnahme hält der Fahrer eine Taste am Gamepad (R oder ZR) und lenkt das Auto
  **absichtlich von der Linie weg**, bis sie aus dem Bild verschwindet.
- Dann lässt er die Taste los und lenkt **zurück zur Linie**.
- Die Bilder bei gehaltener Taste werden gespeichert, aber **besonders markiert**: Sie dienen nur
  als **Vorgeschichte** und werden **nie als Lenkbeispiel gelernt**. Das Netz soll ja nicht
  lernen, von der Linie wegzufahren.
- Gelernt wird nur das Zurücklenken, und zwar mit der Vorgeschichte, wie die Linie verschwunden ist.

So entsteht genau das Wissen, das das Gedächtnis braucht: „Die Linie ist links verschwunden, also
links zurück.“

**Unsere Driftfahrt:** 170 Sekunden, 1701 Bilder, davon 141 als „abgedriftet“ markiert.

**Grafikvorschlag:** Draufsicht auf die Linie mit der gefahrenen Bahn. Ein roter Abschnitt
„abdriften, Taste gehalten, wird nicht gelernt“, dann ein grüner Abschnitt „zurücklenken, wird
gelernt“.

**Schöner Hintergrund für Interessierte:** Dieses Problem ist in der Forschung zum Nachahmungslernen
bekannt. Ein Netz, das nur perfekte Fahrten gesehen hat, weiß nicht, was es tun soll, sobald es
selbst einen kleinen Fehler macht. Die Fehler schaukeln sich dann auf. NVIDIA hat 2016 dafür
seitliche Zusatzkameras benutzt, wir benutzen Driftfahrten.

---

## 8. Training auf dem Mac (Remote-Training)

Training ist Rechenarbeit, für die ein Raspberry Pi eher langsam ist. Deshalb kann das Auto sein
Training an einen **Mac im selben WLAN** abgeben:

1. In der Weboberfläche auf dem Auto wählt man „Wo trainieren? → extern“.
2. Das Auto schickt die ausgewählten Fahrten als Paket zum Mac (bei rund 3800 Bildern etwa 38 MB).
3. Der Mac trainiert auf seiner **Grafikeinheit** (Apple „MPS“). Fortschritt und Lernkurve
   erscheinen live auf der Weboberfläche des Autos.
4. Das fertige Modell, eine Datei mit den gelernten Gewichten, wandert zurück aufs Auto.
5. Das Auto fährt mit dem Modell **ohne Verbindung zum Mac**. Das Netz läuft komplett auf dem Pi.

**Zahlen:**
| | Raspberry Pi 5 | Mac (Grafikeinheit) |
|---|---|---|
| Training, Variante „Einzelbild“, rund 4000 Bilder, Modus „schnell“ | **etwa 6 Minuten** | – |
| Training, Variante „Bildfolge“, 3762 Bilder, Modus „schnell“ | nicht gemessen (Stufe 1 entspricht einem Einzelbild-Training) | **18 Sekunden** |
| Training, Variante „Bildfolge“, 1701 Bilder, Modus „gründlich“ (4-fache Prüfung) | – | **29 Sekunden** |

Auf Pi und Mac läuft **derselbe Trainings-Code**, die Modelle passen also garantiert zusammen. Der
Mac-Dienst kündigt sich selbst im Netz an, das Auto findet ihn per Knopfdruck. Abgesichert ist er
mit einem gemeinsamen Schlüssel (Token). Ist der Mac nicht erreichbar, trainiert das Auto selbst
und sagt das deutlich.

**Grafikvorschlag:** Auto ↔ WLAN ↔ Laptop, mit Pfeilen „Fahrten (Bilder + Lenkwinkel)“ hin und
„gelerntes Modell“ zurück.

---

## 9. Ergebnisse

### In Zahlen: mittlerer Lenkfehler auf Prüfdaten, die das Netz nie gesehen hat

| Modell | Trainingsdaten | Fehler mit Gedächtnis | dasselbe Auge ohne Gedächtnis | Vergleich: „immer geradeaus“ |
|---|---|---|---|---|
| Bildfolge | normale Fahrt, 3762 Bilder, keine Driftfahrten | 3,1° | 3,1° | 6,7° |
| Bildfolge | **Driftfahrt**, 1701 Bilder, davon 141 Drift | **4,4°** | 4,5° | 8,2° |

**So einordnen:**
- Das Netz lenkt **etwa halb so falsch** wie die einfachste Strategie „immer geradeaus“, und das
  auf Bildern, die es beim Lernen nie gesehen hat.
- Im **Durchschnitt** ist der Unterschied mit und ohne Gedächtnis klein. Das ist zu erwarten: Auf
  den meisten Bildern ist die Linie gut zu sehen, und dafür braucht man kein Gedächtnis. Es hilft
  nur in den wenigen Momenten, in denen die Linie weg ist, und die gehen im Durchschnitt unter.
- **Der eigentliche Test ist das Fahrverhalten:** Das Modell mit Gedächtnis, trainiert mit der
  Driftfahrt, **findet die Linie wieder, wenn man das Auto ein Stück wegschiebt**. Das ist auch
  die Live-Demo am Stand.
- Fehler im Bereich von 3–5° sind auch deshalb normal, weil schon der Mensch beim Vorfahren nicht
  immer exakt gleich lenkt.

### Lernkurve (Daten für ein Diagramm)
Modell „Bildfolge“ auf der Driftfahrt, Stufe „Erinnern“, Prüfdurchgang 4 von 4. Mittlerer Fehler
in Grad pro Epoche (eine Epoche heißt, alle Lernbilder einmal gesehen):

| Epoche | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
|---|---|---|---|---|---|---|---|---|---|---|
| Lernen | 9,16 | 6,28 | 5,73 | 5,81 | 5,13 | 5,13 | 4,72 | 5,07 | 4,77 | 4,71 |
| Prüfen | 5,76 | 4,04 | 3,74 | 4,02 | 3,65 | 3,74 | 3,90 | 3,86 | 3,75 | 3,67 |

Zu erkennen: Der Fehler sinkt schnell und flacht dann ab, also hört das Training auf. Der Fehler
beim „Lernen“ liegt höher als beim „Prüfen“, weil die Lernbilder absichtlich erschwert werden
(gespiegelt, heller oder dunkler, zufällig ausgeblendete Merkmale).

---

## 10. Weitere Ideen im Projekt (optional, für eine Randspalte)

- **Aktive Kamera:** In einer weiteren Variante schwenkt die Kamera selbstständig mit, sodass die
  Linie in der Bildmitte bleibt (klassische Bildverarbeitung plus Regler). Das Netz bekommt dann
  Bild **und** Schwenkwinkel. Der Schwenkwinkel ist auch eine Art Gedächtnis: Die Kamera schaut
  dorthin, wo die Linie zuletzt war.
- **Sicherheit:** Schließt man die Weboberfläche, gehen die Motoren nach 1,5 s von selbst aus. Ist
  der Controller außer Reichweite, hält das Auto an. Beim Programmende werden immer zuerst die
  Motoren abgeschaltet.
- **Alles im Browser:** Kalibrieren, Controller koppeln, Daten aufnehmen, Trainieren, Lernkurven
  ansehen, Modelle vergleichen und autonom fahren gehen über eine Weboberfläche, ohne
  Programmierkenntnisse.

---

## 11. Was man an diesem Projekt lernen kann (Bezug zum Studium)

Ein Absatz, der zeigt, welche Fächer und Themen dahinterstecken:
- **Informatik / KI:** neuronale Netze, CNNs, RNNs, überwachtes Lernen, Nachahmungslernen,
  Overfitting, Validierung
- **Mathematik:** Matrizen und Faltungen, Ableitungen (wie das Netz aus Fehlern lernt), Statistik
  (mittlerer Fehler, Prüfdaten)
- **Technik / Elektrotechnik:** Kamera, Servos, Motoren, Akku, eingebetteter Rechner, Funk (WLAN,
  Bluetooth)
- **Software-Engineering:** Weboberfläche, verteiltes Rechnen (Auto ↔ Mac), Sicherheit

Projektkontext: **[Platzhalter: z. B. Hochschule, Fachbereich, Studiengang, Ansprechperson,
Kontakt, QR-Code zum Repository]**. Das Projekt dient auch als Testumgebung für ein Schulprojekt
mit einer 9. Klasse, deshalb ist alles bewusst einfach und erklärbar gehalten.

---

## 12. Vorschlag für den Poster-Aufbau

Hochformat (z. B. A0), Lesefluss von oben nach unten:

1. **Kopf:** Titel, Untertitel („Ein Mini-Auto lernt aus Beispielen, einer Linie zu folgen“), Foto des Autos
2. **Links oben:** „Die Idee“: klassisch vs. End-to-End (Abschnitt 3)
3. **Rechts oben:** „In 4 Schritten zum autonomen Auto“, Bildleiste (Abschnitt 4)
4. **Mitte, groß:** „So sieht das Auto: das CNN“ mit Schichtengrafik und Bildausschnitt (Abschnitt 5)
5. **Mitte:** „Ein Gedächtnis für das Auto: das RNN“ mit Zeitachsen-Grafik (Abschnitt 6)
6. **Unten links:** „Fehler zeigen hilft: Driftfahrten“ mit Draufsicht-Grafik (Abschnitt 7)
7. **Unten rechts:** „Training auf dem Mac“ mit Auto↔Laptop-Grafik und Zeitvergleich (Abschnitt 8)
8. **Fuß:** Ergebnisse mit kleiner Tabelle und Lernkurve (Abschnitt 9), Bezug zum Studium (Abschnitt 11), **[Platzhalter: Logo, Kontakt, QR-Code]**

**Stil:** wenig Text, große Grafiken, Zahlen hervorheben (z. B. „18 Sekunden statt 6 Minuten“,
„56.000 Gewichte“, „30 Entscheidungen pro Sekunde“, „1 Kamera, kein Lidar, kein GPS“). Fachbegriffe
einführen, aber immer mit einem Satz in Alltagssprache erklären.

**Hinweis für die Live-Demo am Stand** (gern als kleiner Kasten auf dem Poster): „Probieren Sie es
aus: Schieben Sie das Auto vorsichtig von der Linie weg und schauen Sie, ob es zurückfindet!“

---

## 13. Kleines Glossar (falls Platz ist)

| Begriff | In einem Satz |
|---|---|
| Neuronales Netz | Ein Rechenmodell aus vielen einfachen, verbundenen Einheiten, das aus Beispielen lernt |
| Gewichte | Die Zahlen im Netz, die beim Training angepasst werden. Sie sind das „Wissen“ des Netzes |
| CNN | Ein Netz für Bilder: Kleine Filter wandern über das Bild und erkennen Muster |
| RNN / GRU | Ein Netz mit Gedächtnis: Es verarbeitet eine Folge Schritt für Schritt und merkt sich dabei etwas |
| End-to-End | Ein einziges Netz vom Rohbild bis zur Aktion, ohne handprogrammierte Zwischenschritte |
| Imitation Learning | Lernen durch Nachahmen eines Menschen |
| Epoche | Ein Durchgang, in dem das Netz alle Lernbeispiele einmal gesehen hat |
| Overfitting | Das Netz lernt die Beispiele auswendig, statt das Prinzip zu verstehen |
| Validierung | Prüfen mit Daten, die beim Lernen nicht benutzt wurden: die ehrliche Note |
