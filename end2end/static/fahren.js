// fahren.js – Die Hauptseite: Umschalten zwischen den Modi und Bedienung der Modi.

"use strict";

// ---------------------------------------------------------------------
// Modi umschalten
// ---------------------------------------------------------------------

const reiterKnoepfe = document.querySelectorAll(".reiter button");

function modusAnzeigen(modus) {
  for (const knopf of reiterKnoepfe) {
    knopf.classList.toggle("aktiv", knopf.dataset.modus === modus);
    document.getElementById("modus-" + knopf.dataset.modus).classList.toggle("versteckt", knopf.dataset.modus !== modus);
  }
}

for (const knopf of reiterKnoepfe) {
  knopf.addEventListener("click", async () => {
    const zustand = await senden("/api/modus", { modus: knopf.dataset.modus });
    if (zustand) modusAnzeigen(zustand.modus);
  });
}

// ---------------------------------------------------------------------
// Geschwindigkeit und Kamera
// ---------------------------------------------------------------------

// Es gibt mehrere Tempo-Regler (Aufnahme, Autonom) – alle zeigen denselben Wert.
const tempoRegler = document.querySelectorAll(".tempo-regler");
let tempoWirdGezogen = false;

for (const regler of tempoRegler) {
  regler.addEventListener("input", () => {
    tempoWirdGezogen = true;
    for (const ausgabe of document.querySelectorAll(".tempo-wert")) ausgabe.textContent = regler.value + " %";
  });
  regler.addEventListener("change", async () => {
    await senden("/api/tempo", { tempo: Number(regler.value) });
    tempoWirdGezogen = false;
  });
}

const schwenkenRegler = document.getElementById("schwenken");
const neigenRegler = document.getElementById("neigen");
let kameraWirdGezogen = false;

for (const regler of [schwenkenRegler, neigenRegler]) {
  regler.addEventListener("input", () => {
    kameraWirdGezogen = true;
    document.getElementById(regler.id + "-wert").textContent = regler.value + "°";
  });
  regler.addEventListener("change", async () => {
    await senden("/api/kamera", { schwenken: Number(schwenkenRegler.value), neigen: Number(neigenRegler.value) });
    kameraWirdGezogen = false;
  });
}

// Bildausschnitt: ab welcher Bildhöhe (in Prozent) das Netz das Bild sieht
const ausschnittRegler = document.getElementById("ausschnitt");
let ausschnittWirdGezogen = false;

ausschnittRegler.addEventListener("input", () => {
  ausschnittWirdGezogen = true;
  document.getElementById("ausschnitt-wert").textContent = ausschnittRegler.value + " %";
});
ausschnittRegler.addEventListener("change", async () => {
  await senden("/api/ausschnitt", { ausschnitt_oben: Number(ausschnittRegler.value) / 100 });
  ausschnittWirdGezogen = false;
});

// Die Vorschau „So sieht das Netz das Bild“ zweimal pro Sekunde neu laden
setInterval(() => {
  if (!document.getElementById("modus-aufnahme").classList.contains("versteckt")) {
    document.getElementById("netzbild").src = "/netzbild.jpg?" + Date.now();
  }
}, 500);

// ---------------------------------------------------------------------
// Modus 1: Daten aufnehmen
// ---------------------------------------------------------------------

document.getElementById("aufnahme-knopf").addEventListener("click",
  () => senden("/api/aufnahme", { aktion: "umschalten" }).then(() => setTimeout(fahrtenLaden, 300)));
document.getElementById("pause-knopf").addEventListener("click",
  () => senden("/api/aufnahme", { aktion: "pause" }));

function aufnahmeAnzeigen(zustand) {
  const controller = document.getElementById("controller-status");
  controller.textContent = zustand.controller_verbunden ? "Controller verbunden" : "Controller nicht verbunden";
  controller.className = zustand.controller_verbunden ? "gut" : "schlecht";

  const a = zustand.aufnahme;
  const status = document.getElementById("aufnahme-status");
  if (!a.laeuft) status.textContent = "Aufnahme: aus";
  else status.textContent = `${a.pausiert ? "PAUSE" : "● Aufnahme"} – ${a.bilder} Bilder, ${a.dauer_s} s`;
  status.className = a.laeuft && !a.pausiert ? "schlecht" : "";

  const knopf = document.getElementById("aufnahme-knopf");
  knopf.textContent = a.laeuft ? "■ Aufnahme stoppen" : "● Aufnahme starten";
  knopf.classList.toggle("laeuft", a.laeuft);
  const pause = document.getElementById("pause-knopf");
  pause.disabled = !a.laeuft;
  pause.classList.toggle("aktiv", a.pausiert);
  pause.textContent = a.pausiert ? "Weiter" : "Pause";

  // Während der Aufnahme bleiben Kamerawinkel und Bildausschnitt fest
  schwenkenRegler.disabled = a.laeuft;
  neigenRegler.disabled = a.laeuft;
  ausschnittRegler.disabled = a.laeuft;

  // Wurde die Aufnahme am Controller gestoppt, die Liste neu laden
  if (vorherLief && !a.laeuft) setTimeout(fahrtenLaden, 300);
  vorherLief = a.laeuft;
}
let vorherLief = false;

// ---------- Liste der gespeicherten Fahrten ----------

function sekundenText(s) {
  return s < 60 ? `${Math.round(s)} s` : `${Math.floor(s / 60)} min ${Math.round(s % 60)} s`;
}

async function fahrtenLaden() {
  const liste = await senden("/api/fahrten");
  if (!liste) return;
  const ziel = document.getElementById("fahrten-liste");
  if (liste.length === 0) {
    ziel.textContent = "Noch keine Fahrten.";
    return;
  }
  ziel.innerHTML = "";
  for (const fahrt of liste) {
    const eintrag = document.createElement("div");
    eintrag.className = "eintrag";
    eintrag.innerHTML = `
      <img src="/fahrten/${fahrt.id}/vorschau.jpg" alt="">
      <div>
        <div class="name"></div>
        <div class="details">
          ${fahrt.id} · ${sekundenText(fahrt.dauer_s)} · ${fahrt.frames} Bilder<br>
          Tempo ${fahrt.tempo} % · Kamera ${fahrt.kamera.schwenken}° / ${fahrt.kamera.neigen}°
        </div>
      </div>
      <div class="aktionen">
        <button class="umbenennen">Umbenennen</button>
        <button class="loeschen gefahr">Löschen</button>
      </div>`;
    eintrag.querySelector(".name").textContent = fahrt.anzeigename;  // als Text, nicht als HTML
    eintrag.querySelector(".umbenennen").addEventListener("click", async () => {
      const name = prompt("Neuer Name für die Fahrt:", fahrt.anzeigename);
      if (name !== null) {
        await senden(`/api/fahrten/${fahrt.id}/umbenennen`, { name: name });
        fahrtenLaden();
      }
    });
    eintrag.querySelector(".loeschen").addEventListener("click", async () => {
      if (confirm(`Fahrt „${fahrt.anzeigename}“ mit ${fahrt.frames} Bildern wirklich löschen?`)) {
        await senden(`/api/fahrten/${fahrt.id}/loeschen`, {});
        fahrtenLaden();
      }
    });
    ziel.appendChild(eintrag);
  }
}

// ---------------------------------------------------------------------
// Regelmäßige Aktualisierung (wird von gemeinsam.js zweimal pro Sekunde aufgerufen)
// ---------------------------------------------------------------------

let ersterZustand = true;
zustandAnzeigen = (zustand) => {
  // Wer von der Kalibrierseite kommt, landet wieder im Aufnahmemodus.
  if (ersterZustand && zustand.modus === "kalibrierung") {
    ersterZustand = false;
    senden("/api/modus", { modus: "aufnahme" }).then((z) => z && modusAnzeigen(z.modus));
    return;
  }
  if (ersterZustand) {
    // Regler beim ersten Mal auf die Werte des Autos stellen
    schwenkenRegler.value = zustand.schwenken;
    neigenRegler.value = zustand.neigen;
    schwenkenRegler.dispatchEvent(new Event("input"));
    neigenRegler.dispatchEvent(new Event("input"));
    kameraWirdGezogen = false;
  }
  ersterZustand = false;
  modusAnzeigen(zustand.modus);

  if (!ausschnittWirdGezogen) {
    ausschnittRegler.value = Math.round(zustand.ausschnitt_oben * 100);
    document.getElementById("ausschnitt-wert").textContent = ausschnittRegler.value + " %";
  }
  if (!tempoWirdGezogen) {
    for (const regler of tempoRegler) regler.value = zustand.tempo;
    for (const ausgabe of document.querySelectorAll(".tempo-wert")) ausgabe.textContent = zustand.tempo + " %";
  }
  aufnahmeAnzeigen(zustand);
  autonomAnzeigen(zustand);   // steht in autonom.js
};

fahrtenLaden();
