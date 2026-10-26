// extern.js – Einstellungen für die externe Trainingsressource (z. B. ein Mac mit dem mac_worker-Dienst).

"use strict";

const externFelder = {
  aktiv: document.getElementById("extern-aktiv"),
  name: document.getElementById("extern-name"),
  host: document.getElementById("extern-host"),
  port: document.getElementById("extern-port"),
  token: document.getElementById("extern-token"),
};
const externErgebnis = document.getElementById("extern-ergebnis");

// Was im Formular steht. Ein leeres Token-Feld heißt: das gespeicherte Token behalten.
function externEingaben() {
  return {
    aktiv: externFelder.aktiv.checked,
    name: externFelder.name.value,
    host: externFelder.host.value,
    port: Number(externFelder.port.value),
    token: externFelder.token.value,
  };
}

function externAnzeigen(einstellung) {
  externFelder.aktiv.checked = einstellung.aktiv;
  externFelder.name.value = einstellung.name;
  externFelder.host.value = einstellung.host;
  externFelder.port.value = einstellung.port;
  externFelder.token.value = "";
  externFelder.token.placeholder = einstellung.token_gesetzt ? "gespeichert – leer lassen zum Behalten" : "aus mac_worker/config.json";

  // Auswahl „Wo trainieren?“ im Trainingsfeld
  const ortExtern = document.getElementById("ort-extern");
  ortExtern.disabled = !einstellung.aktiv;
  if (!einstellung.aktiv && ortExtern.checked) document.querySelector("input[name=ort][value=pi]").checked = true;
  document.getElementById("ort-extern-name").textContent = einstellung.aktiv
    ? `– ${einstellung.name || einstellung.host}` : "(nicht eingerichtet – siehe unten)";
}

function meldungZeigen(text, art) {
  externErgebnis.textContent = text;
  externErgebnis.className = "hinweis " + (art || "");
}

async function externLaden() {
  const einstellung = await senden("/api/extern");
  if (einstellung) externAnzeigen(einstellung);
}

document.getElementById("extern-speichern").addEventListener("click", async () => {
  const einstellung = await senden("/api/extern", externEingaben());
  if (einstellung) {
    externAnzeigen(einstellung);
    meldungZeigen("Gespeichert.", "erfolg");
  }
});

document.getElementById("extern-testen").addEventListener("click", async () => {
  meldungZeigen("Teste die Verbindung ...");
  const ergebnis = await senden("/api/extern/testen", externEingaben());
  if (!ergebnis) return;
  if (!ergebnis.erreichbar) {
    meldungZeigen("Nicht erreichbar: " + ergebnis.meldung, "misserfolg");
    return;
  }
  const info = ergebnis.info;
  if (!externFelder.name.value) externFelder.name.value = info.name;
  const messung = Object.entries(info.messung || {}).map(([g, wert]) => `${g.toUpperCase()} ${wert} Bilder/s`).join(", ");
  let text = `Erreichbar: „${info.name}“ – trainiert mit ${info.geraet.toUpperCase()}` +
             (messung ? ` (gemessen: ${messung})` : "") + `, Code-Version ${info.version}` +
             (info.beschaeftigt ? ". Trainiert gerade etwas anderes." : ".");
  if (ergebnis.warnung) {
    meldungZeigen(text + " " + ergebnis.warnung, "warnhinweis");
  } else {
    meldungZeigen(text + " Gleiche Version wie auf dem Pi.", "erfolg");
  }
});

document.getElementById("extern-suchen").addEventListener("click", async () => {
  const ziel = document.getElementById("extern-gefunden");
  ziel.textContent = "Suche im Netz (3 Sekunden) ...";
  const liste = await senden("/api/extern/suchen", {});
  if (!liste) return;
  if (liste.length === 0) {
    ziel.textContent = "Nichts gefunden. Läuft der Dienst auf dem Mac? Sonst Adresse von Hand eintragen.";
    return;
  }
  ziel.innerHTML = "<span class='hinweis'>Gefunden – zum Übernehmen anklicken:</span><br>";
  for (const dienst of liste) {
    const knopf = document.createElement("button");
    knopf.textContent = `${dienst.name} (${dienst.host}:${dienst.port})`;
    knopf.addEventListener("click", () => {
      externFelder.name.value = dienst.name;
      externFelder.host.value = dienst.host;
      externFelder.port.value = dienst.port;
      externFelder.aktiv.checked = true;
      meldungZeigen("Übernommen – jetzt Token eintragen, „Verbindung testen“ und „Speichern“.");
    });
    ziel.appendChild(knopf);
  }
});

externLaden();
