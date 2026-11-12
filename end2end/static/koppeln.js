// koppeln.js – Kalibrierseite: den Nintendo-Controller per Bluetooth koppeln (siehe controller_koppeln.py).

"use strict";

const koppelnStart = document.getElementById("koppeln-start");
const koppelnAbbrechen = document.getElementById("koppeln-abbrechen");
let koppelnAbfrage = null;   // solange gekoppelt wird: jede halbe Sekunde den Fortschritt abfragen

function koppelnAnzeigen(status) {
  const liste = document.getElementById("koppeln-schritte");
  liste.innerHTML = "";
  status.schritte.forEach((text, nummer) => {
    const eintrag = document.createElement("li");
    eintrag.textContent = text;   // als Text, nicht als HTML
    // Der letzte Schritt zeigt das Ergebnis farbig an
    if (!status.laeuft && nummer === status.schritte.length - 1) {
      eintrag.className = status.ergebnis === "ok" ? "gut" : "schlecht";
    }
    liste.appendChild(eintrag);
  });
  koppelnStart.disabled = status.laeuft;
  koppelnAbbrechen.disabled = !status.laeuft;
  if (status.laeuft && !koppelnAbfrage) {
    koppelnAbfrage = setInterval(async () => {
      const neu = await senden("/api/controller/koppeln");
      if (neu) koppelnAnzeigen(neu);
    }, 500);
  } else if (!status.laeuft && koppelnAbfrage) {
    clearInterval(koppelnAbfrage);
    koppelnAbfrage = null;
  }
}

koppelnStart.addEventListener("click", async () => {
  const status = await senden("/api/controller/koppeln", {});
  if (status) koppelnAnzeigen(status);
});
koppelnAbbrechen.addEventListener("click", async () => {
  const status = await senden("/api/controller/koppeln/abbrechen", {});
  if (status) koppelnAnzeigen(status);
});

// Verbunden oder nicht? Kommt mit dem Zustand zweimal pro Sekunde.
const bisherigeZustandsanzeige = zustandAnzeigen;
zustandAnzeigen = (zustand) => {
  bisherigeZustandsanzeige(zustand);
  const anzeige = document.getElementById("controller-status");
  anzeige.textContent = zustand.controller_verbunden ? "Controller verbunden" : "Controller nicht verbunden";
  anzeige.className = zustand.controller_verbunden ? "gut" : "schlecht";
};

// Läuft schon eine Kopplung (z. B. Seite neu geladen)? Dann den Fortschritt gleich zeigen.
senden("/api/controller/koppeln").then((status) => status && koppelnAnzeigen(status));
