# ND TranskripThor

Jednoduchá aplikácia pre Windows na lokálny prepis zvukových nahrávok do textu a titulkov. Bez minútových kvót a bez odosielania nahrávok na externú službu.

## Stiahnutie

**[Stiahnuť verziu 1.5.1 pre Windows x64](https://github.com/ndxnraw/TranskripThor/releases/download/v1.5.1/ND-TranskripThor-1.5.1-Windows.zip)** · [Všetky vydania](https://github.com/ndxnraw/TranskripThor/releases)

Rozbaľte celý ZIP a spustite **ND TranskripThor.exe**. Priečinok `_internal` musí zostať vedľa EXE. Python netreba inštalovať.

## Funkcie

- Slovenčina, čeština, angličtina, maďarčina a automatické rozpoznanie jazyka.
- Výber modelov Whisper Tiny, Small, Medium, Large v3 a slovenského **KInIT Large v3**.
- Export do **TXT a SRT**, dávkové spracovanie a zachovanie rozpracovaného prepisu.
- Tmavý a svetlý režim.

Modely sa sťahujú pri prvom použití, potom fungujú offline. KInIT je voliteľný, určený iba pre slovenčinu a vyžaduje približne 6,2 GB na stiahnutie; v tejto zostave používa CPU. Modely nie sú súčasťou ZIP balíka.

## Zo zdrojového kódu

Zdroje sú v [`outputs/zdroj`](outputs/zdroj). Vo Windows s 64-bitovým Pythonom 3.12:

```powershell
cd outputs/zdroj
python -m pip install -r requirements.txt PyInstaller==6.22.3
python -m unittest discover -s . -p "test*.py"
.\zostavit.cmd
```

Created by Daniel Návojský using Codex | 2026
