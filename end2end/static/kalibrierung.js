// kalibrierung.js – Die Kalibrierseite: Regler bewegen die Servos sofort (Vorschau),
// „Speichern“ übernimmt die Werte dauerhaft.

"use strict";

const regler = ["lenkung", "schwenken", "neigen"].map((name) => document.getElementById(name));

function werte() {
  return {
    lenkung: Number(regler[0].value),
    schwenken: Number(regler[1].value),
    neigen: Number(regler[2].value),
  };
}

function werteAnzeigen() {
  for (const r of regler) {
    document.getElementById(r.id + "-wert").textContent = (r.value > 0 ? "+" : "") + r.value + "°";
  }
}

async function gespeicherteWerteLaden() {
  const kalibrierung = await senden("/api/kalibrierung");
  if (!kalibrierung) return;
  regler[0].value = kalibrierung.lenkung;
  regler[1].value = kalibrierung.schwenken;
  regler[2].value = kalibrierung.neigen;
  werteAnzeigen();
  senden("/api/kalibrierung/vorschau", werte());
}

// Beim Ziehen die Servos gleich mitbewegen (höchstens alle 100 ms eine Nachricht)
let wartet = false;
for (const r of regler) {
  r.addEventListener("input", () => {
    werteAnzeigen();
    if (wartet) return;
    wartet = true;
    setTimeout(() => {
      wartet = false;
      senden("/api/kalibrierung/vorschau", werte());
    }, 100);
  });
}

document.getElementById("speichern").addEventListener("click", async () => {
  const ergebnis = await senden("/api/kalibrierung/speichern", werte());
  if (ergebnis) {
    document.getElementById("meldung").textContent =
      `Gespeichert: Lenkung ${ergebnis.lenkung}°, Kamera schwenken ${ergebnis.schwenken}°, ` +
      `neigen ${ergebnis.neigen}°.`;
  }
});
document.getElementById("zuruecksetzen").addEventListener("click", gespeicherteWerteLaden);

// Beim Öffnen der Seite in den Kalibriermodus wechseln (Auto hält an) und Werte laden
senden("/api/modus", { modus: "kalibrierung" }).then(gespeicherteWerteLaden);
