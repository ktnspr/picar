// steuerung.js – Die Fernbedienung im Browser.
//
// Die Webseite schickt Befehle an den Server auf dem Auto (z. B. „fahr vorwärts“)
// und sendet 5-mal pro Sekunde ein Lebenszeichen (Herzschlag). Bleibt der
// Herzschlag aus, hält das Auto von selbst an (Totmannschaltung, siehe auto.py).

"use strict";

const HERZSCHLAG_PAUSE_MS = 200;    // so oft sagt die Seite „ich bin noch da“
const VERBINDUNG_TIMEOUT_MS = 500;  // länger als das ohne Antwort = Verbindung weg
const REGLER_PAUSE_MS = 50;         // so oft werden geänderte Regler ans Auto geschickt
const AKKU_PAUSE_MS = 5000;         // so oft wird der Akkustand abgefragt

// Die Elemente der Seite, die wir brauchen
const lenkungRegler = document.getElementById("lenkung");
const tempoRegler = document.getElementById("tempo");
const schwenkenRegler = document.getElementById("schwenken");
const neigenRegler = document.getElementById("neigen");
const fahrknoepfe = {
  vor: document.getElementById("vor"),
  stopp: document.getElementById("stopp"),
  zurueck: document.getElementById("zurueck"),
};


// ---------------------------------------------------------------------
// Nachrichten an den Server
// ---------------------------------------------------------------------

// Schickt eine Anfrage an den Server und gibt seine Antwort zurück.
// Ohne „daten“ ist es eine GET-Anfrage (nur abfragen), sonst POST (Befehl).
// Kommt keine Antwort (rechtzeitig), ist das Ergebnis null.
async function senden(pfad, daten) {
  const abbruch = new AbortController();
  const zeitschaltuhr = setTimeout(() => abbruch.abort(), VERBINDUNG_TIMEOUT_MS);
  try {
    const antwort = await fetch(pfad, {
      method: daten === undefined ? "GET" : "POST",
      headers: { "Content-Type": "application/json" },
      body: daten === undefined ? undefined : JSON.stringify(daten),
      signal: abbruch.signal,
    });
    return antwort.ok ? await antwort.json() : null;
  } catch (fehler) {
    return null;
  } finally {
    clearTimeout(zeitschaltuhr);
  }
}

function warten(millisekunden) {
  return new Promise((fertig) => setTimeout(fertig, millisekunden));
}


// ---------------------------------------------------------------------
// Fahren: Vorwärts, STOP, Rückwärts
// ---------------------------------------------------------------------

// Hebt den Knopf der aktuellen Fahrtrichtung hervor.
function richtungAnzeigen(richtung) {
  for (const [name, knopf] of Object.entries(fahrknoepfe)) {
    knopf.classList.toggle("aktiv", name === richtung);
  }
}

async function fahren(richtung) {
  richtungAnzeigen(richtung);  // sofort anzeigen, damit es sich flott anfühlt
  const status = await senden("/api/fahren", { richtung: richtung });
  if (status) richtungAnzeigen(status.richtung);
}

for (const [richtung, knopf] of Object.entries(fahrknoepfe)) {
  // „pointerdown“ reagiert schon beim Antippen, nicht erst beim Loslassen.
  knopf.addEventListener("pointerdown", (ereignis) => {
    ereignis.preventDefault();
    fahren(richtung);
  });
}


// ---------------------------------------------------------------------
// Schieberegler: Lenkung, Tempo, Kamera
// ---------------------------------------------------------------------

// Die Lenkung springt beim Loslassen zurück in die Mitte.
function lenkungZurMitte() {
  lenkungRegler.value = 0;
}
for (const ereignis of ["change", "pointerup", "touchend", "touchcancel"]) {
  lenkungRegler.addEventListener(ereignis, lenkungZurMitte);
}

tempoRegler.addEventListener("input", () => {
  document.getElementById("tempo-anzeige").textContent = tempoRegler.value + " %";
});

// Feinjustierung: Jeder Tipp verschiebt die Mitte der Lenkung um 1 Grad.
function lenkungMitteAnzeigen(status) {
  document.getElementById("lenkung-mitte").textContent = status.lenkung_mitte + "°";
}

async function lenkungJustieren(aenderung) {
  const status = await senden("/api/lenkung_justieren", { aenderung: aenderung });
  if (status) lenkungMitteAnzeigen(status);
}

document.getElementById("justieren-links").addEventListener("click", () => lenkungJustieren(-1));
document.getElementById("justieren-rechts").addEventListener("click", () => lenkungJustieren(1));

// Kamera justieren: verschiebt die Mitte der Kamera um je 1 Grad (wird dauerhaft gespeichert).
function kameraMitteAnzeigen(status) {
  const mitVorzeichen = (wert) => (wert > 0 ? "+" : "") + wert + "°";
  document.getElementById("kamera-mitte-schwenken").textContent = mitVorzeichen(status.kamera_mitte_schwenken);
  document.getElementById("kamera-mitte-neigen").textContent = mitVorzeichen(status.kamera_mitte_neigen);
}

async function kameraJustieren(schwenken, neigen) {
  const status = await senden("/api/kamera_justieren", { schwenken: schwenken, neigen: neigen });
  if (status) kameraMitteAnzeigen(status);
}

document.getElementById("kamera-links").addEventListener("click", () => kameraJustieren(-1, 0));
document.getElementById("kamera-rechts").addEventListener("click", () => kameraJustieren(1, 0));
document.getElementById("kamera-hoch").addEventListener("click", () => kameraJustieren(0, 1));
document.getElementById("kamera-runter").addEventListener("click", () => kameraJustieren(0, -1));

document.getElementById("kamera-justieren").addEventListener("click", async () => {
  // Kamera auf ihre Mitte stellen (die Regler schicken das automatisch ans Auto),
  // dann das Feld mit den Pfeilen zeigen.
  schwenkenRegler.value = 0;
  neigenRegler.value = 0;
  document.getElementById("justieren-feld").classList.remove("versteckt");
  const status = await senden("/api/herzschlag", {});
  if (status) kameraMitteAnzeigen(status);
});

document.getElementById("justieren-fertig").addEventListener("click", () => {
  document.getElementById("justieren-feld").classList.add("versteckt");
});

document.getElementById("kamera-zentrieren").addEventListener("click", () => {
  schwenkenRegler.value = 0;
  neigenRegler.value = 0;
});

// Beim Ziehen ändert sich ein Regler sehr oft. Damit wir das Auto nicht mit
// Nachrichten überfluten, schauen wir nur alle 50 ms nach, ob sich etwas
// geändert hat, und schicken dann den neuesten Wert.
const gesendet = {};  // die zuletzt an das Auto geschickten Werte

async function wennGeaendertSenden(name, wert, pfad, daten) {
  if (gesendet[name] === wert) return;
  gesendet[name] = wert;
  const antwort = await senden(pfad, daten);
  // Hat es nicht geklappt, vergessen wir den Wert – dann wird er erneut geschickt.
  if (!antwort) gesendet[name] = undefined;
}

function regler() {
  const lenkung = Number(lenkungRegler.value);
  const tempo = Number(tempoRegler.value);
  const schwenken = Number(schwenkenRegler.value);
  const neigen = Number(neigenRegler.value);

  wennGeaendertSenden("lenkung", lenkung, "/api/lenken", { winkel: lenkung });
  wennGeaendertSenden("tempo", tempo, "/api/tempo", { prozent: tempo });
  wennGeaendertSenden("kamera", schwenken + "/" + neigen, "/api/kamera",
                      { schwenken: schwenken, neigen: neigen });
}

setInterval(regler, REGLER_PAUSE_MS);


// ---------------------------------------------------------------------
// Herzschlag und Verbindungsanzeige
// ---------------------------------------------------------------------

let letzteAntwortZeit = Date.now();  // wann der Server zuletzt geantwortet hat
let warVerbindungWeg = false;

async function herzschlag() {
  while (true) {
    const start = Date.now();
    const status = await senden("/api/herzschlag", {});
    if (status) {
      letzteAntwortZeit = Date.now();
      richtungAnzeigen(status.richtung);
      lenkungMitteAnzeigen(status);
    }
    // Die nächste Nachricht 200 ms nach dem Start dieser schicken
    await warten(Math.max(0, HERZSCHLAG_PAUSE_MS - (Date.now() - start)));
  }
}

function verbindungPruefen() {
  const verbunden = Date.now() - letzteAntwortZeit <= VERBINDUNG_TIMEOUT_MS;

  document.getElementById("verbindung").className = verbunden ? "ok" : "weg";
  document.getElementById("verbindung-text").textContent = verbunden ? "Verbunden" : "Keine Verbindung";
  document.getElementById("verbindung-weg").classList.toggle("versteckt", verbunden);

  if (!verbunden) {
    richtungAnzeigen("stopp");  // das Auto hat von selbst angehalten
    warVerbindungWeg = true;
  } else if (warVerbindungWeg) {
    // Verbindung ist wieder da: Videobild neu laden, es bleibt sonst stehen
    document.getElementById("video").src = "/video?" + Date.now();
    warVerbindungWeg = false;
  }
}

herzschlag();
setInterval(verbindungPruefen, 100);


// ---------------------------------------------------------------------
// Akku-Anzeige
// ---------------------------------------------------------------------

async function akkuAnzeigen() {
  const akku = await senden("/api/akku");
  if (!akku || akku.prozent === null) return;

  let farbe = "gruen";
  if (akku.prozent < 20) farbe = "rot";
  else if (akku.prozent <= 50) farbe = "gelb";

  document.getElementById("akku").className = farbe;
  document.getElementById("akku-fuellung").style.width = akku.prozent + "%";
  document.getElementById("akku-prozent").textContent = akku.prozent + " %";
  document.getElementById("akku-spannung").textContent = akku.spannung.toFixed(2) + " V";
  document.getElementById("akku-warnung").classList.toggle("versteckt", farbe !== "rot");
}

akkuAnzeigen();
setInterval(akkuAnzeigen, AKKU_PAUSE_MS);
