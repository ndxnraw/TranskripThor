# ND TranskripThor 2.1.3

V časti **Nastavenia čakajúcich nahrávok → Zariadenie** je manuálny výber:

- **CPU – kompatibilný režim** (predvolené aj pri chýbajúcej/neplatnej hodnote),
- **GPU (CUDA) – NVIDIA**.

Voľba sa ukladá do `settings.json` pod kľúčom `device` (`cpu` alebo `cuda`). Počas prepisu je zablokovaná. Zmena v nečinnosti uvoľní predchádzajúci model, ale nový model sa načíta až po spustení prepisu. Identifikátor modelu v pamäti zahŕňa zariadenie. CPU nevyberá CUDA automaticky.

Faster-whisper zachováva CPU int8 a GPU float16; KInIT/PyTorch CPU float32 a GPU float16. Závislosti a spôsob sťahovania modelov sa nemenia.

Pri nedostupnej CUDA, chýbajúcej cuBLAS/cuDNN alebo nedostatku pamäte aplikácia zobrazí: **„GPU sa nepodarilo použiť. Môžete pokračovať na CPU.“** Tlačidlá sú **Pokračovať na CPU** a **Zrušiť**. Zatvorenie okna alebo Escape znamená zrušenie. Až potvrdenie zmení voľbu na CPU, uloží ju a načíta rovnaký model na CPU. Technická príčina zostáva na karte Podrobnosti spracovania. Stav zariadenia sa aktualizuje až podľa skutočne načítaného backendu.

Pri chybe počas prepisu sa najskôr zachovajú dokončené úseky v existujúcom projekte. Aktuálny úsek sa ukladá až po úspešnom vyčerpaní celého výsledkového iterátora. Po potvrdení sa zopakuje iba tento neuložený úsek, vrátane rozpoznávania jazyka v CZ/SK režime. Zrušenie ponechá projekt prerušený; neskoršie Pokračovať umožňuje zvoliť CPU alebo GPU a zachováva uložený model, jazyk a postup. Zariadenie nie je súčasťou nemenných nastavení prepisu, takže jeho zmena neruší checkpoint.

## Overenie

- Celá sada: 84 testov, 83 úspešných. Zostáva už predtým reprodukovaný problém rozhrania pri 200 % škálovaní na obrazovke 1536 × 864; nejde o novú chybu voľby zariadenia.
- Po doplnení testu skutočnej CZ/SK orchestrace prešlo všetkých 18 testov zariadenia/modelov. Testovaný je predvolený CPU, validácia a obnova nastavenia, blokovanie výberu, uvoľnenie a opätovné použitie modelu, úspešný simulovaný GPU backend a výpočtové typy oboch backendov.
- Chýbajúca `cublas64_12.dll` je simulovaná pri načítaní aj po čiastočnom vydaní výsledkov iterátorom. Overené je potvrdenie aj zrušenie, zachovanie dokončeného úseku, následné pokračovanie na CPU, bez duplicitného textu a s pôvodnými časmi. Zmiešaný test používa existujúcu CZ/SK orchestrace s mockovaným modelom, nie skutočnú GPU.
- Reálny beh na NVIDIA GPU nie je potvrdený; výsledok kontroly miestneho hardvéru a testu EXE je uvedený v `OVERENIE.json` Windows balíka. Simulácia GPU nie je meraním kompatibility konkrétnej grafickej karty.

## Spustenie a zostavenie

Rozbaľte celý Windows ZIP a spustite `ND TranskripThor.exe`; `_internal` ponechajte vedľa EXE. Modely nie sú pribalené a existujúca cache sa zachováva. Pri prvom spustení tejto voľby zostane CPU aj na počítači s NVIDIA kartou.

Postup zostavenia a závislosti sa nemenia: nainštalovať existujúce requirements, spustiť `python -m unittest discover -s outputs/zdroj -p "test*.py" -v` a zostaviť `outputs/zdroj/TranskripTHOR.spec` cez PyInstaller. Verzia EXE aj manifestu je 2.1.3. README na GitHube naďalej odkazuje na poslednú publikovanú verziu; 2.1.3 sa automaticky nepublikuje.
