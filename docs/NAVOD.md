# ND TranskripThor 2.1.0

Aktualizácia rozhrania podľa návrhu Studio, pri zachovaní lokálneho prepisu.
Samostatné karty **Nahrávky, Editor, Modely, Nastavenia a Podrobnosti spracovania**
udržujú ovládanie dostupné aj v minimálnom okne. Tmavý aj svetlý vzhľad používajú
pokojnejšie farby a jednotné písmo; značka a logo zostávajú zachované.
Okno sa naďalej spúšťa v minimálnej veľkosti podľa mierky rozhrania.

Windows aplikácia na **lokálny prepis zvuku do textu a titulkov**, bez minútových
kvót. Nahrávky ani prepisy sa neposielajú na externé služby. Internet slúži iba
na stiahnutie vybraných modelov. Po stiahnutí je dostupný režim Iba offline.

## Spustenie

Rozbaľte celý Windows ZIP a spustite **ND TranskripThor.exe**. Priečinok
`_internal` musí zostať vedľa EXE. Python netreba inštalovať. Modely nie sú
pribalené. Lokálna zostava tejto verzie je v `outputs/release210/ND TranskripThor`.
[Windows ZIP 2.1.0](https://github.com/ndxnraw/TranskripThor/releases/download/v2.1.0/ND-TranskripThor-2.1.0-Windows.zip)
· [Poznámky k vydaniu](https://github.com/ndxnraw/TranskripThor/releases/tag/v2.1.0)

## Funkcie

- Slovenčina, čeština, angličtina, maďarčina, automatický jazyk a zmiešané CZ/SK.
- Pôvodný faster-whisper: Tiny, Small, Medium, Large v3; voliteľný slovenský
  KInIT Large v3 cez Transformers. CPU/GPU a cache zostávajú zachované.
- Trvalá fronta, pretiahnutie súborov, zmena poradia čakajúcich položiek,
  samostatné stavy, opakovanie chýb a pokračovanie po prerušení.
- Editor celého prepisu s časmi, vyhľadávaním, úpravou textu, lokálnym prehrávaním,
  pauzou a posunom. Text sa upravuje priamo vo vybranom bloku. Výber úseku
  nespúšťa zvuk; automatické prehrávanie možno zapnúť v Nastaveniach.
- TXT/SRT, nastaviteľné titulky, samostatné prevádzkové správy.
- Zapamätanie nastavení, svetlý/tmavý vzhľad a obnova predvolených hodnôt.
- Správca modelov: dostupnosť, miesto, sťahovanie a potvrdené odstránenie.
- Voliteľné lokálne zoskupenie hlasov a ručná oprava/priradenie mien.

## Bežný postup

1. Pridajte alebo pretiahnite nahrávky, vyberte jazyk, model a výstupný priečinok.
2. **Spustiť čakajúce** spracuje čakajúce položky. Vyberte prerušenú/chybnú
   nahrávku a zvoľte **Pokračovať / Skúsiť znova**. Platný projekt obnoví svoj
   uložený model, jazyk a nastavenia bez zmeny nastavení pre nové nahrávky.
3. **Nový prepis** vyžaduje výber položiek a vytvorí nové priečinky.
   Predchádzajúce výsledky neprepíše. **Podrobnosti** zobrazia zdroj, chybu
   a uložené nastavenia; čakajúce položky možno presúvať šípkami.
4. **Otvoriť prepis / Editor** otvorí výsledok na karte Editor. Kliknutím vyberte
   blok a upravte text priamo v ňom. **▶ Úsek** prehrá vybraný interval.
   **Hľadať** prehľadáva celý prepis; **Ďalší výskyt** prejde na ďalší zhodný úsek.
   Hovoriaci a nastavenia titulkov sú pod tlačidlom **Úsek, hovoriaci a titulky**.
5. **Uložiť TXT/SRT** vytvorí `prepis.opravene.txt` a `titulky.opravene.srt`.
   Pôvodný dokončený export zostáva zachovaný. Neuložené úpravy sú viditeľne
   označené; pri zatvorení editor upozorní na ich uloženie.

Karta Podrobnosti spracovania oddeľuje náhľad od prevádzkových správ. Náhľad má
obmedzenú históriu; editor používa všetky uložené úseky. Zobrazuje najviac 40
blokov na stránku, aby dlhé prepisy zbytočne nespomaľovali rozhranie.
Karta Modely oddeľuje modely prepisu od voliteľného rozlíšenia hlasov. Chýbajúci
model sa v režime offline oznámi ešte pred spustením prepisu.

## Ukladanie a pokračovanie

Každá úloha má `projekt.sqlite3`: zdroj a SHA-256 obsahu, nastavenia a revíziu
modelu, plán úsekov, dokončené úseky, časy slov, jazyk a bod pokračovania.
Checkpoint sa zapíše transakčne až po dokončení celého rečového úseku. Pri páde
alebo zastavení sa rozpracovaný úsek zopakuje celý. Bezpečne uložené úseky sa
nespracujú znova. Overuje sa obsah nahrávky aj zhoda nastavení; pri nezhode treba
obnoviť nastavenia alebo spustiť nový prepis.

SQLite projekt je autoritatívny zdroj. TXT/SRT sú exporty, ktoré možno znovu
vytvoriť; pri páde počas exportu otvorte projekt vo fronte a zopakujte uloženie.
Staré samotné TXT/SRT z verzie 1.x nemajú checkpoint a nemožno z nich bezpečne
pokračovať. Zachovajte celý výstupný priečinok aj pôvodnú nahrávku.

Nastavenia/fronta sú atómovo uložené v `%LOCALAPPDATA%\LokalnyPrepis`.
Poškodený JSON sa podľa možnosti odloží s príponou `.damaged-*`; aplikácia
sa spustí s predvolenými hodnotami. Stav „spracúva sa“ sa po reštarte obnoví
ako „prerušené“. Modelová cache zostáva v podpriečinku `models`.

## CZ/SK a titulky

Režim **Čeština + slovenčina** používa Silero VAD a samostatné porovnanie `cs`
a `sk` pre každý úsek. Typicky 5–25 s, krátke susedné úseky sa spájajú, dlhé
delia. Confidence pod 0,60 alebo rozdiel pod 0,15 spustí dvojitý prepis; výber
porovná tokenovo vážené `avg_logprob`. Prah remízy je 0,03. Model sa nenačítava
znova a úseky sa explicitne transkribujú, neprekladajú. KInIT je iba pre SK.

Titulky používajú vety a časové značky slov; predvolene 42 znakov, dva riadky,
1–7 sekúnd. Po ručnej zmene textu sa staré zarovnanie slov zneplatní. Bez časov
slov zostane úsek v pôvodnom intervale; limity sú vtedy mäkké a zobrazí sa
upozornenie. Slová sa nevynechávajú ani neduplikujú. Neplatné intervaly sa
odmietnu. Mená hovoriacich sa uchovávajú v projekte; čistý TXT/SRT ich nepridáva.

## Voliteľné hlasy

V Správcovi modelov stiahnite **WeSpeaker ResNet34-LM**, potom v editore použite
**Rozlíšiť hlasy**. Funkcia je štandardne vypnutá; bežný prepis model nenačítava.
Model [WeSpeaker](https://huggingface.co/Wespeaker/wespeaker-voxceleb-resnet34-LM)
má licenciu **CC BY 4.0**, autorstvo tím WeSpeaker; používa sa pôvodný ONNX súbor
bez úpravy váh, revízia `f0c48c298fd835726c27956a5d617bad7115627e`.
Nie je gated a nevyžaduje token ani samostatné prijatie podmienok na portáli.
[Licencia CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

Výpočet beží na CPU cez ONNX Runtime a voliteľný kaldi-native-fbank (Apache 2.0).
Váhy majú približne 27 MB; ďalšiu RAM potrebuje runtime a dekódovaný zvuk.
Hlasy sa zoskupujú podľa podobnosti zvuku úsekov, nezávisle od jazyka. Nie je to
identifikácia osoby ani presná diarizácia prekrývajúcich sa hlasov. Podsekundové
úseky zostanú neurčené, viac hlasov v jednom ASR úseku môže byť zlúčených.
Priradenia skontrolujte a ručne opravte; názov možno zmeniť aj v celom prepise.

## Overenie a obmedzenia

Vo verzii 2.1.0 prešlo 58 automatických testov. Zahŕňajú pôvodné funkcie, checkpointy a pád procesu,
obnovu fronty/nastavení, chyby, editor nad 1 501 úsekmi, export a timestampy.
Natívny Windows test preveril Small na CPU, prerušenie po prvom úseku,
reštart aplikácie a dokončenie zvyšných úsekov bez zdvojenia uložených dát.
Overené je aj obnovenie pôvodného modelu/jazyka projektu pri odlišných nastaveniach
pre nové úlohy. Zostavené EXE 2.1.0 úspešne vytvorilo SQLite/TXT/SRT z lokálneho
syntetického slovenského zvuku; skontrolované sú pribalené natívne knižnice.
WeSpeaker bol vo verzii 2.0.0 spustený na syntetickom zvuku; nejde o meranie presnosti diarizácie.

Chýba oprávnený reálny CZ/SK korpus s ručne skontrolovanou referenciou.
Pripravený je [vyhodnocovací nástroj a presný zoznam ukážok](../outputs/zdroj/eval/README.md).
Mock testy, syntetický zvuk a reálne merania sú oddelené. Presnosť pri hluku,
menách a zmene jazyka uprostred vety zatiaľ nie je odmeraná. Zmena jazyka bez
pauzy môže zostať v rámci jedného úseku nerozpoznaná.

Rozmery loga a tlačidiel boli kontrolované v oboch vzhľadoch pri mierkach Tk 100/125/150/175/200 % na
Windows; nejde o úplné testovanie všetkých monitorov a zmien systémového DPI.
GPU nie je na tomto testovacom stroji dostupné. Audio sa dekóduje raz celé do
RAM; dlhé nahrávky a Large/KInIT potrebujú viac pamäte. Zastavenie počká na
aktuálny dekódovací/inferenčný krok alebo prenos súboru modelu. ETA je hrubý
odhad z dokončeného postupu, nie sľúbený čas dokončenia.

## Vývoj a zostavenie

Windows x64, Python 3.12:

```powershell
cd outputs/zdroj
python -m pip install -r requirements.txt PyInstaller==6.22.3
# Voliteľné rozlíšenie hlasov:
python -m pip install -r requirements-speakers.txt
python -m unittest discover -s . -p "test*.py"
python prepis.py
.\zostavit.cmd
```

Zostavenie kontroluje runtime a testy; výsledok je `dist/ND TranskripThor`.
Zachované sú torch 2.8.0, transformers 4.55.4 a faster-whisper 1.2.1.
Existujúce základné závislosti: sounddevice 0.5.3 (prehrávanie), tkinterdnd2 0.4.3
(pretiahnutie súborov). Nepribaľujú sa váhy modelov.

Verzia 2.1.0 nepridáva nový framework ani závislosti; zostáva pri Tk/ttk.

Debug CZ/SK: pred spustením nastavte `$env:ND_TRANSKRIPTHOR_DEBUG='1'`.
Rotovaný log je `%LOCALAPPDATA%\LokalnyPrepis\asr-debug.log`; neobsahuje zvuk ani text prepisu.

Created by Daniel Návojský using Codex | 2026
