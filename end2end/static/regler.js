// regler.js – Einstellungen der Kameraregelung. Das Feld steht in mehreren Reitern,
// alle zeigen dieselben Werte.

"use strict";

const REGLER_EINHEITEN = {
  totzone: "°", max_geschwindigkeit: "°/s", such_geschwindigkeit: "°/s", schwenk_max: "°", verlust_zeit: " s",
};
const REGLER_ZUSTAENDE = { folgt: "– folgt der Linie", sucht: "– sucht die Linie", verloren: "– Linie verloren" };

function reglerAnzeigen(einstellungen) {
  // Kurzfassung (Reiter „Daten aufnehmen“)
  for (const ziel of document.querySelectorAll(".regler-kurz")) {
    ziel.textContent = `Kp ${einstellungen.kp}, Kd ${einstellungen.kd}, Totzone ${einstellungen.totzone}°, ` +
      `bis ${einstellungen.max_geschwindigkeit}°/s, Schwenkbereich ±${einstellungen.schwenk_max}°` +
      (einstellungen.richtung === -1 ? ", Richtung umgekehrt" : "");
  }
  for (const feld of document.querySelectorAll("[data-regler]")) {
    const name = feld.dataset.regler;
    if (feld.type === "checkbox") {
      feld.checked = einstellungen.richtung === -1;   // „umkehren“ angehakt = Richtung −1
    } else {
      feld.value = einstellungen[name];
      feld.nextElementSibling.textContent = einstellungen[name] + (REGLER_EINHEITEN[name] || "");
    }
  }
}

async function reglerSpeichern(daten) {
  const einstellungen = await senden("/api/regler", daten);
  if (einstellungen) reglerAnzeigen(einstellungen);
}

for (const feld of document.querySelectorAll("[data-regler]")) {
  const name = feld.dataset.regler;
  if (feld.type === "checkbox") {
    feld.addEventListener("change", () => reglerSpeichern({ richtung: feld.checked ? -1 : 1 }));
  } else {
    feld.addEventListener("input", () => {
      feld.nextElementSibling.textContent = feld.value + (REGLER_EINHEITEN[name] || "");
    });
    feld.addEventListener("change", () => reglerSpeichern({ [name]: Number(feld.value) }));
  }
}

// Zustand der Regelung neben der Überschrift anzeigen
function reglerZustandAnzeigen(zustand) {
  for (const ziel of document.querySelectorAll(".regler-zustand")) {
    ziel.textContent = zustand.regler_zustand ? REGLER_ZUSTAENDE[zustand.regler_zustand] : "(aus)";
  }
}

// ---------- Regler einmessen ----------

function einmessenAnzeigen(status) {
  for (const balken of document.querySelectorAll(".einmessen-balken")) balken.style.width = (status.fortschritt * 100) + "%";
  for (const text of document.querySelectorAll(".einmessen-text")) {
    text.textContent = status.text;
    text.className = "hinweis einmessen-text " + (status.fehler ? "misserfolg" : "");
  }
  for (const knopf of document.querySelectorAll(".einmessen-start")) knopf.disabled = status.laeuft;
  for (const knopf of document.querySelectorAll(".einmessen-abbrechen")) knopf.disabled = !status.laeuft;
  for (const ziel of document.querySelectorAll(".einmessen-tabelle")) ziel.innerHTML = einmessenTabelle(status);
}

// Tabelle aller Versuche; die beste Zeile ist hervorgehoben
function einmessenTabelle(status) {
  if (!status.ergebnisse.length) return "";
  const zahl = (wert, einheit) => (wert === null ? "–" : wert + einheit);
  let html = `<p class="hinweis">Profil: <b>${status.profil}</b></p>` +
             "<table class='tabelle'><tr><th>Kp</th><th>Kd</th><th>Einschwingzeit</th><th>Überschwingen</th>" +
             "<th>Unruhe</th><th>Ruckeln</th><th>Note</th><th></th></tr>";
  for (const e of status.ergebnisse) {
    const beste = status.beste && e.kp === status.beste.kp && e.kd === status.beste.kd;
    html += `<tr class="${beste ? "beste" : ""}"><td>${e.kp}</td><td>${e.kd}</td>` +
            `<td>${zahl(e.einschwingzeit, " s")}</td><td>${zahl(e.ueberschwingen, "°")}</td>` +
            `<td>${zahl(e.unruhe, "°")}</td><td>${zahl(e.ruckeln, "")}</td><td>${e.note.toFixed(2)}${e.verloren ? " ⚠" : ""}</td>` +
            `<td>${beste ? "<b>beste</b> " : ""}<button class="klein einmessen-uebernehmen" data-kp="${e.kp}" data-kd="${e.kd}">übernehmen</button></td></tr>`;
  }
  return html + "</table><p class='hinweis'>⚠ = Linie zwischendurch verloren.</p>";
}

document.addEventListener("click", async (ereignis) => {
  const knopf = ereignis.target;
  if (knopf.classList.contains("einmessen-start")) {
    const status = await senden("/api/regler/einmessen", { profil: knopf.dataset.profil });
    if (status) { einmessenAnzeigen(status); einmessenBeobachten(); }
  } else if (knopf.classList.contains("einmessen-abbrechen")) {
    senden("/api/regler/einmessen/abbrechen", {});
  } else if (knopf.classList.contains("einmessen-uebernehmen")) {
    await reglerSpeichern({ kp: Number(knopf.dataset.kp), kd: Number(knopf.dataset.kd) });
    knopf.textContent = "übernommen ✓";
  }
});

// Während des Einmessens jede Sekunde den Stand abfragen
async function einmessenBeobachten() {
  const status = await senden("/api/regler/einmessen");
  if (!status) return;
  einmessenAnzeigen(status);
  if (status.laeuft) setTimeout(einmessenBeobachten, 1000);
}

senden("/api/regler/einmessen").then((status) => {
  if (status) { einmessenAnzeigen(status); if (status.laeuft) einmessenBeobachten(); }
});

// Test-Schalter auf der Kalibrierseite: Kamera folgt der Linie
const regeltest = document.getElementById("regeltest");
if (regeltest) {
  regeltest.addEventListener("change", async () => {
    await senden("/api/regeltest", { an: regeltest.checked });
    if (!regeltest.checked) gespeicherteWerteLaden();   // Servos wieder auf die Kalibrier-Vorschau (kalibrierung.js)
  });
}

senden("/api/regler").then((einstellungen) => einstellungen && reglerAnzeigen(einstellungen));
