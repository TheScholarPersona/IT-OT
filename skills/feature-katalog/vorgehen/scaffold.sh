#!/usr/bin/env bash
# Legt das Feature-Katalog-Gerüst in einem Zielprojekt an. Vorhandene Dateien werden nie überschrieben.
# Aufruf: scaffold.sh <zielverzeichnis>
set -euo pipefail

ziel="${1:-}"
if [[ -z "$ziel" || ! -d "$ziel" ]]; then
  echo "Aufruf: $0 <zielverzeichnis>" >&2
  exit 2
fi

vorlagen="$(cd "$(dirname "${BASH_SOURCE[0]}")/vorlagen" && pwd)"
angelegt=0; uebersprungen=0

kopiere() {  # kopiere <vorlage> <ziel relativ>
  local quelle="$vorlagen/$1" dest="$ziel/$2"
  if [[ -e "$dest" ]]; then
    echo "  übersprungen (existiert): $2"; uebersprungen=$((uebersprungen + 1))
  else
    mkdir -p "$(dirname "$dest")"
    cp "$quelle" "$dest"
    echo "  angelegt: $2"; angelegt=$((angelegt + 1))
  fi
}

echo "Feature-Katalog-Gerüst → $ziel"
kopiere catalog/catalog.yaml             catalog/catalog.yaml
kopiere catalog/review.yaml              catalog/review.yaml
kopiere catalog/features/_beispiel.yaml  catalog/features/_beispiel.yaml
mkdir -p "$ziel/catalog/discovered"
kopiere steckbrief.md                    docs/feature-katalog-steckbrief.md
kopiere feature-katalog.md               docs/feature-katalog.md
kopiere reifegrad-bewertung.md           docs/feature-katalog-reifegrad.md
kopiere pr-nachweis.md                   .github/PULL_REQUEST_TEMPLATE/feature-katalog.md
kopiere ci-feature-katalog.yml           .github/workflows/feature-katalog.yml

echo "Fertig: $angelegt angelegt, $uebersprungen übersprungen."
echo "Nicht automatisch übernommen (bitte von Hand einfügen):"
echo "  - $vorlagen/CODEOWNERS            → .github/CODEOWNERS"
echo "  - $vorlagen/definition-of-done.md → eure Definition of Done"
echo "Weiter mit Schritt 1 (Steckbrief): docs/feature-katalog-steckbrief.md"
