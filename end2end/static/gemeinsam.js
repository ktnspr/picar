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

// Akku: Batteriesymbol mit Füllstand, Prozent und (klein) die gemessene Spannung.
// Farbe: grün über 50 %, gelb 20–50 %, rot unter 20 % – dann blinkt zusätzlich eine Warnung.
const AKKU_GELB = 50;
const AKKU_ROT = 20;

function akkuAnzeigen(prozent, volt) {
  if (prozent === null || prozent === undefined) return;
  const farbe = prozent < AKKU_ROT ? "rot" : prozent <= AKKU_GELB ? "gelb" : "gruen";
  document.getElementById("akku").className = farbe;
  document.getElementById("akku-fuellung").style.width = prozent + "%";
  document.getElementById("akku-prozent").textContent = prozent + " %";
  document.getElementById("akku-volt").textContent = volt.toFixed(2) + " V";
  document.getElementById("akku-warnung").classList.toggle("versteckt", farbe !== "rot");
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
  akkuAnzeigen(zustand.akku_prozent, zustand.akku_volt);
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
