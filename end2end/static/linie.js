// linie.js – Einstellungen der Linienerkennung (Kalibrierseite) und Bandfarbe per Klick ins Livebild.

"use strict";

const linieRegler = document.querySelectorAll("[data-linie]");

function einheit(name, wert) {
  if (name === "streifen_y" || name === "streifen2_y") return Math.round(wert * 100) + " %";
  if (name === "bildwinkel") return wert + "°";
  return String(wert);
}

function linieAnzeigen(einstellungen) {
  document.getElementById("linie-modus").value = einstellungen.modus;
  for (const feld of linieRegler) {
    const wert = einstellungen[feld.dataset.linie];
    if (feld.type === "checkbox") feld.checked = wert;
    else {
      feld.value = wert;
      feld.nextElementSibling.textContent = einheit(feld.dataset.linie, wert);
    }
  }
  const farbe = einstellungen.farbe_bgr;
  document.getElementById("linie-farbe").textContent = farbe ? `Blau ${farbe[0]}, Grün ${farbe[1]}, Rot ${farbe[2]}` : "noch nicht gewählt";
  document.getElementById("linie-farbfeld").style.background = farbe ? `rgb(${farbe[2]}, ${farbe[1]}, ${farbe[0]})` : "transparent";
}

async function linieSpeichern(daten) {
  const einstellungen = await senden("/api/linie", daten);
  if (einstellungen) linieAnzeigen(einstellungen);
}

document.getElementById("linie-modus").addEventListener("change", (e) => linieSpeichern({ modus: e.target.value }));
for (const feld of linieRegler) {
  if (feld.type === "checkbox") {
    feld.addEventListener("change", () => linieSpeichern({ [feld.dataset.linie]: feld.checked }));
  } else {
    feld.addEventListener("input", () => { feld.nextElementSibling.textContent = einheit(feld.dataset.linie, feld.value); });
    feld.addEventListener("change", () => linieSpeichern({ [feld.dataset.linie]: Number(feld.value) }));
  }
}

// Klick ins Livebild: Bandfarbe an dieser Stelle übernehmen.
// Das Livebild ist 320 × 240 Pixel groß, wird aber größer angezeigt – deshalb umrechnen.
document.getElementById("livebild").addEventListener("click", async (ereignis) => {
  const bild = ereignis.target;
  const x = ereignis.offsetX / bild.clientWidth * bild.naturalWidth;
  const y = ereignis.offsetY / bild.clientHeight * bild.naturalHeight;
  const einstellungen = await senden("/api/linie/farbe", { x: x, y: y });
  if (einstellungen) linieAnzeigen(einstellungen);
});

// Erkennungsergebnis laufend anzeigen (kommt mit dem Zustand zweimal pro Sekunde)
const bisherigeAnzeige = zustandAnzeigen;
zustandAnzeigen = (zustand) => {
  bisherigeAnzeige(zustand);
  const l = zustand.linie;
  // Die gemessene Helligkeit hilft beim Einstellen der Mindesthelligkeit
  const hell = l && l.helligkeit !== null ? `, Helligkeit des hellsten Teils im Streifen ${l.helligkeit}` : "";
  document.getElementById("linie-status").textContent = !l ? "–"
    : l.sichtbar ? `Linie erkannt: ${l.winkel > 0 ? "+" : ""}${l.winkel}° neben der Bildmitte (Rechenzeit ${l.rechenzeit_ms} ms${hell})`
    : `Linie nicht erkannt (Rechenzeit ${l.rechenzeit_ms} ms${hell})`;
};

// Bildwinkel ausmessen (Kamera schwenkt kurz auf −8° und +8°)
let bildwinkelMessung = null;
document.getElementById("bildwinkel-messen").addEventListener("click", async () => {
  const ausgabe = document.getElementById("bildwinkel-ergebnis");
  ausgabe.textContent = "Messe ... (Kamera schwenkt kurz hin und her)";
  bildwinkelMessung = await senden("/api/bildwinkel_messen", {});
  if (!bildwinkelMessung) { ausgabe.textContent = "Messung fehlgeschlagen."; return; }
  const m = bildwinkelMessung;
  ausgabe.textContent = `Gemessen: Bildwinkel ${m.bildwinkel}° (Brennweite ${m.brennweite_pixel} Pixel; ` +
    `die Linie wanderte ${Math.abs(m.wanderung_pixel)} Pixel). ` +
    (m.regler_richtung === 1 ? "Schwenkrichtung stimmt." : "Achtung: Die Schwenkrichtung ist umgekehrt – „Übernehmen“ stellt den Regler darauf ein.");
  document.getElementById("bildwinkel-uebernehmen").classList.remove("versteckt");
});
document.getElementById("bildwinkel-uebernehmen").addEventListener("click", async () => {
  if (!bildwinkelMessung) return;
  await linieSpeichern({ bildwinkel: bildwinkelMessung.bildwinkel });
  await senden("/api/regler", { richtung: bildwinkelMessung.regler_richtung });
  document.getElementById("bildwinkel-ergebnis").textContent += " Übernommen.";
  document.getElementById("bildwinkel-uebernehmen").classList.add("versteckt");
});

senden("/api/linie").then((einstellungen) => einstellungen && linieAnzeigen(einstellungen));
