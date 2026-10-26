// lernkurve.js – Zeichnet die Lernkurve: Fehler in Grad pro Epoche, als SVG-Liniendiagramm.
//
// Die Farben folgen der Bedeutung, nicht der Reihenfolge: „Lernen“ ist immer blau,
// „Prüfen“ immer orange, „Finales Modell“ immer türkis.

"use strict";

const KURVEN_FARBEN = { lernen: "#3987e5", pruefen: "#d95926", final: "#199e70" };
const SVG_NS = "http://www.w3.org/2000/svg";

// Aus allen Kurven eines Trainings die zeigen, die man vergleichen will:
// das (letzte) Probetraining mit Lernen und Prüfen, dazu das finale Modell.
function kurvenAuswaehlen(kurven) {
  const namen = Object.keys(kurven || {});
  const proben = namen.filter((n) => n.startsWith("Probetraining") && n.endsWith(": Prüfen") && kurven[n].length);
  const probe = proben.length ? proben[proben.length - 1].replace(": Prüfen", "") : null;
  const auswahl = [];
  if (probe) {
    auswahl.push({ name: "Lernen", werte: kurven[probe + ": Lernen"] || [], farbe: KURVEN_FARBEN.lernen });
    auswahl.push({ name: "Prüfen", werte: kurven[probe + ": Prüfen"], farbe: KURVEN_FARBEN.pruefen });
  }
  if (kurven && kurven["Finales Modell: Lernen"] && kurven["Finales Modell: Lernen"].length) {
    auswahl.push({ name: "Finales Modell (alle Daten)", werte: kurven["Finales Modell: Lernen"], farbe: KURVEN_FARBEN.final });
  }
  return { probe: probe, reihen: auswahl.filter((r) => r.werte.length) };
}

function svgElement(name, eigenschaften) {
  const element = document.createElementNS(SVG_NS, name);
  for (const [schluessel, wert] of Object.entries(eigenschaften)) element.setAttribute(schluessel, wert);
  return element;
}

// Ein „schöner“ Schritt für die Achsenbeschriftung (1, 2 oder 5 mal Zehnerpotenz)
function schoenerSchritt(spanne, anzahl) {
  const roh = spanne / anzahl;
  const potenz = Math.pow(10, Math.floor(Math.log10(roh)));
  for (const faktor of [1, 2, 5, 10]) if (faktor * potenz >= roh) return faktor * potenz;
}

function lernkurveZeichnen(ziel, legende, titel, kurven) {
  const { probe, reihen } = kurvenAuswaehlen(kurven);
  titel.textContent = probe && probe !== "Probetraining" ? `Lernkurve – ${probe}` : "Lernkurve";
  ziel.innerHTML = "";
  legende.innerHTML = "";
  if (reihen.length === 0) return;

  // Legende (ab zwei Linien)
  if (reihen.length >= 2) {
    for (const reihe of reihen) {
      const eintrag = document.createElement("span");
      eintrag.innerHTML = `<span class="farbe" style="background:${reihe.farbe}"></span>`;
      eintrag.append(reihe.name);
      legende.appendChild(eintrag);
    }
  }

  const breite = ziel.clientWidth, hoehe = ziel.clientHeight;
  const rand = { links: 40, rechts: 70, oben: 12, unten: 28 };
  const epochen = Math.max(5, ...reihen.map((r) => r.werte.length));
  const yMax = Math.max(...reihen.flatMap((r) => r.werte)) * 1.1;
  const schritt = schoenerSchritt(yMax, 4);
  const yOben = Math.ceil(yMax / schritt) * schritt;
  const x = (epoche) => rand.links + (epoche - 1) / (epochen - 1) * (breite - rand.links - rand.rechts);
  const y = (wert) => hoehe - rand.unten - wert / yOben * (hoehe - rand.oben - rand.unten);

  const svg = svgElement("svg", { viewBox: `0 0 ${breite} ${hoehe}` });

  // Gitterlinien und Achsenbeschriftung (zurückhaltend)
  for (let wert = 0; wert <= yOben + 1e-9; wert += schritt) {
    svg.appendChild(svgElement("line", { x1: rand.links, x2: breite - rand.rechts, y1: y(wert), y2: y(wert),
                                          stroke: wert === 0 ? "#55554f" : "#2f2f2c", "stroke-width": 1 }));
    const text = svgElement("text", { x: rand.links - 6, y: y(wert) + 4, "text-anchor": "end", fill: "#9aa0a6", "font-size": 11 });
    text.textContent = wert + "°";
    svg.appendChild(text);
  }
  const xSchritt = schoenerSchritt(epochen, 6);
  for (let epoche = 1; epoche <= epochen; epoche += 1) {
    if (epoche !== 1 && epoche % xSchritt !== 0) continue;
    const text = svgElement("text", { x: x(epoche), y: hoehe - 10, "text-anchor": "middle", fill: "#9aa0a6", "font-size": 11 });
    text.textContent = epoche;
    svg.appendChild(text);
  }
  const achse = svgElement("text", { x: breite - rand.rechts, y: hoehe - 10, "text-anchor": "start", fill: "#9aa0a6", "font-size": 11, dx: 6 });
  achse.textContent = "Epoche";
  svg.appendChild(achse);

  // Die Linien, mit Punkten und Namen am Ende
  const endpunkte = [];
  for (const reihe of reihen) {
    const punkte = reihe.werte.map((wert, i) => `${x(i + 1)},${y(wert)}`).join(" ");
    svg.appendChild(svgElement("polyline", { points: punkte, fill: "none", stroke: reihe.farbe, "stroke-width": 2,
                                              "stroke-linejoin": "round", "stroke-linecap": "round" }));
    reihe.werte.forEach((wert, i) => {
      if (reihe.werte.length <= 25 || i === reihe.werte.length - 1) {
        svg.appendChild(svgElement("circle", { cx: x(i + 1), cy: y(wert), r: 4, fill: reihe.farbe,
                                                stroke: "#1a1a19", "stroke-width": 2 }));
      }
    });
    const letzter = reihe.werte.length;
    endpunkte.push({ reihe: reihe, x: x(letzter), y: y(reihe.werte[letzter - 1]) });
  }
  // Namen am Linienende – so verschieben, dass sie sich nicht überlappen
  endpunkte.sort((a, b) => a.y - b.y);
  for (let i = 1; i < endpunkte.length; i++) {
    endpunkte[i].y = Math.max(endpunkte[i].y, endpunkte[i - 1].y + 14);
  }
  for (const punkt of endpunkte) {
    const text = svgElement("text", { x: punkt.x + 8, y: punkt.y + 4, fill: "#e8eaed", "font-size": 11 });
    text.textContent = punkt.reihe.name.split(" ")[0];
    svg.appendChild(text);
  }

  // Fadenkreuz und Tooltip beim Überfahren mit der Maus
  const linie = svgElement("line", { y1: rand.oben, y2: hoehe - rand.unten, stroke: "#9aa0a6", "stroke-width": 1, visibility: "hidden" });
  svg.appendChild(linie);
  const flaeche = svgElement("rect", { x: rand.links, y: 0, width: breite - rand.links - rand.rechts, height: hoehe, fill: "transparent" });
  svg.appendChild(flaeche);
  ziel.appendChild(svg);

  const tooltip = document.createElement("div");
  tooltip.className = "tooltip versteckt";
  ziel.appendChild(tooltip);

  flaeche.addEventListener("mousemove", (ereignis) => {
    const position = ereignis.offsetX / ziel.clientWidth * breite;
    const epoche = Math.round((position - rand.links) / (breite - rand.links - rand.rechts) * (epochen - 1)) + 1;
    linie.setAttribute("x1", x(epoche));
    linie.setAttribute("x2", x(epoche));
    linie.setAttribute("visibility", "visible");
    tooltip.innerHTML = `<b>Epoche ${epoche}</b>`;
    for (const reihe of reihen) {
      const wert = reihe.werte[epoche - 1];
      if (wert === undefined) continue;
      tooltip.innerHTML += `<br><span class="farbe" style="display:inline-block;width:10px;height:3px;` +
                           `background:${reihe.farbe};vertical-align:middle;margin-right:5px"></span>` +
                           `${reihe.name}: ${wert.toFixed(2)}°`;
    }
    tooltip.classList.remove("versteckt");
    const links = Math.min(x(epoche) + 12, breite - tooltip.offsetWidth - 4);
    tooltip.style.left = links + "px";
    tooltip.style.top = "8px";
  });
  flaeche.addEventListener("mouseleave", () => {
    linie.setAttribute("visibility", "hidden");
    tooltip.classList.add("versteckt");
  });
}
