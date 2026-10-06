# Oprava 2.1.1.bugfix

Sťahovanie už neukazuje iba počet dokončených súborov (napríklad 3/5).
Každú sekundu zobrazí fyzickú veľkosť cache modelu, prírastok od spustenia,
rýchlosť zápisu pri zmene veľkosti a čas bez nových dát. Staršie dáta v cache
sa nezapočítavajú do nového prenosu. Ide o zápis na disk, nie meranie sieťovej
rýchlosti; knižnica zapisuje vo väčších blokoch, preto sú krátke pauzy bežné.

Animovaný indikátor odlišuje sťahovanie od samotného prepisu. Nepredstiera
percentuálny podiel celého modelu. Po dokončení alebo chybe sa animácia zastaví.
Pri zastavení aplikácia naďalej čaká na aktuálny krok knižnice a zachová cache.
Oprava platí pri spustení prepisu aj v správcovi modelov.

Overenie: 65 zo 66 automatických testov prešlo vrátane ôsmich nových kontrol.
Jeden existujúci test dostupnosti prvkov pri 200 % zlyháva na obrazovke 1536 × 864;
rovnaké zlyhanie bolo potvrdené aj na nezmenenej verzii 2.1.0. Táto oprava nemení
rozloženie hlavného okna a uvedené obmedzenie malého displeja zostáva.

Skutočné stiahnutie modelu Tiny do prázdnej testovacej cache úspešne zobrazovalo
rast veľkosti počas nezmeneného počtu hotových súborov. Large v3 sa znova
nesťahoval; používa rovnakú cestu sťahovania a monitorovania.

Zostavené EXE úspešne prepísalo lokálny syntetický slovenský zvuk cez Tiny na CPU
a vytvorilo SQLite/TXT/SRT. Skontrolované sú tiež pribalené natívne knižnice.
