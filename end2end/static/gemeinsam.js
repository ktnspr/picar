// gemeinsam.js – Was alle Seiten brauchen: Nachrichten an den Server, Kopfzeile, Motorschalter.

"use strict";

// Schickt eine Anfrage an den Server. Ohne „daten“ ist es eine GET-Anfrage, sonst POST.
async function senden(pfad, daten) {
  try {
    const antwort = await fetch(pfad, {
      method: daten === undefined ? "GET" : "POST",
      headers: { "Content-Type": "application/json" },
      body: daten === undefined ? undefined : JSON.stringify(daten),
    });
    const inhalt = await antwort.json();
    if (!antwort.ok) {
      alert(inhalt.fehler || "Fehler " + antwort.status);
      return null;
    }
    return inhalt;
  } catch (fehler) {
    return null;
  }
}

// Ab diesen Temperaturen (°C) wechselt die Farbe der Anzeige.
// Der Pi 5 beginnt bei etwa 80 °C, seinen Takt zu senken (zu drosseln).
const TEMPERATUR_WARM = 70;
const TEMPERATUR_HEISS = 80;

function temperaturAnzeigen(temperatur, drosselt) {
  const anzeige = document.getElementById("temperatur");
  if (temperatur === null) return;
  anzeige.textContent = `CPU ${Math.round(temperatur)} °C` + (drosselt ? " – drosselt!" : "");
  anzeige.className = temperatur >= TEMPERATUR_HEISS ? "heiss" : temperatur >= TEMPERATUR_WARM ? "warm" : "kuehl";
}

// Wird von jeder Seite überschrieben, um ihre eigenen Anzeigen zu aktualisieren.
let zustandAnzeigen = (zustand) => {};
let letzterZustand = null;

// Zweimal pro Sekunde den Zustand abfragen. Das ist zugleich das Lebenszeichen der
// Seite: Bleibt es aus, schaltet der Server die Motoren ab.
async function zustandAbfragen() {
  const zustand = await senden("/api/zustand");
  const verbindung = document.getElementById("verbindung");
  if (!zustand) {
    verbindung.textContent = "Keine Verbindung zum Auto!";
    verbindung.className = "weg";
    return;
  }
  letzterZustand = zustand;
  verbindung.textContent = "";
  verbindung.className = "";
  document.getElementById("akku").textContent =
    zustand.akku_volt ? `Akku ${zustand.akku_volt.toFixed(2)} V` : "Akku –";
  temperaturAnzeigen(zustand.temperatur, zustand.drosselt);

  const schalter = document.getElementById("motorschalter");
  schalter.className = zustand.motoren_gesperrt ? "gesperrt" : (zustand.motoren_frei ? "an" : "");
  schalter.textContent = zustand.motoren_gesperrt ? "Motoren gesperrt"
                       : (zustand.motoren_frei ? "Motoren: EIN" : "Motoren: AUS");
  zustandAnzeigen(zustand);
}

document.getElementById("motorschalter").addEventListener("click", () => {
  if (!letzterZustand || letzterZustand.motoren_gesperrt) return;
  senden("/api/motoren", { frei: !letzterZustand.motoren_frei }).then(zustandAbfragen);
});

zustandAbfragen();
setInterval(zustandAbfragen, 500);
