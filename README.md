# ND TranskripThor 2.0.2

Pri spustení sa okno vždy otvorí v aktuálnej minimálnej veľkosti podľa mierky
rozhrania. Predtým uložená veľkosť sa neobnovuje; jazyk, model, vzhľad a ostatné
nastavenia zostávajú zachované. Po spustení možno okno normálne zväčšiť.

Oprava orezaných častí textu, loga a tlačidiel: odstránené experimentálne prepínanie
WS_EX_COMPOSITED z 2.0.0.bugfix. Obsah opäť vykresľuje samotné Tk bez zásahov
do štýlov podokien pri zmene veľkosti. Nezmenený priebeh sa zbytočne neprekresľuje.
Funkcie prepisu a uložené projekty zostávajú kompatibilné.
Animácia minimalizácie a obnovy je vypnutá iba pre okná aplikácie, aby Windows
nezobrazoval snímku ešte nedokreslených prvkov. Systémové nastavenia sa nemenia.

Windows aplikácia na **lokálny prepis zvuku do textu a titulkov**, bez minútových
kvót. Nahrávky ani prepisy sa neposielajú na externé služby. Internet slúži iba
na stiahnutie vybraných modelov. Po stiahnutí je dostupný režim Iba offline.

## Spustenie

Rozbaľte celý Windows ZIP a spustite **ND TranskripThor.exe**. Priečinok
`_internal` musí zostať vedľa EXE. Python netreba inštalovať. Modely nie sú
pribalené. Lokálna zostava tejto verzie je v `outputs/release202/ND TranskripThor`.
[Stiahnuť Windows ZIP 2.0.2](https://github.com/ndxnraw/TranskripThor/releases/download/v2.0.2/ND-TranskripThor-2.0.2-Windows.zip)
· [Poznámky k vydaniu](https://github.com/ndxnraw/TranskripThor/releases/tag/v2.0.2)

## Funkcie

- Slovenčina, čeština, angličtina, maďarčina, automatický jazyk a zmiešané CZ/SK.
- Pôvodný faster-whisper: Tiny, Small, Medium, Large v3; voliteľný slovenský
  KInIT Large v3 cez Transformers. CPU/GPU a cache zostávajú zachované.
- Trvalá fronta, pretiahnutie súborov, zmena poradia čakajúcich položiek,
  samostatné stavy, opakovanie chýb a pokračovanie po prerušení.
- Editor celého prepisu s časmi, vyhľadávaním, úpravou textu, lokálnym prehrávaním,
  pauzou a posunom. Kliknutím na úsek sa prehrá jeho zvuk.
- TXT/SRT, nastaviteľné titulky, samostatné prevádzkové správy.
- Zapamätanie nastavení, svetlý/tmavý vzhľad a obnova predvolených hodnôt.
- Správca modelov: dostupnosť, miesto, sťahovanie a potvrdené odstránenie.
- Voliteľné lokálne zoskupenie hlasov a ručná oprava/priradenie mien.

## Bežný postup

1. Pridajte alebo pretiahnite nahrávky, vyberte jazyk, model a výstupný priečinok.
2. **Spustiť prepis** spracuje čakajúce položky. **Opakovať / pokračovať** vyberie
   iba chybné a prerušené položky; pri platnom projekte pokračuje od checkpointu.
3. **Nový od začiatku** spracuje označené položky (bez označenia všetky) do nových
   priečinkov. Predchádzajúce výsledky neprepíše.
4. Označte výsledok a zvoľte **Editor výsledku**. Úpravy ukladajte cez
   **Uložiť TXT/SRT**; vzniknú `prepis.opravene.txt` a `titulky.opravene.srt`.
   Pôvodný dokončený export zostáva zachovaný. Editor pri zatvorení upozorní na
   neuložené zmeny. Vyhľadávanie prehľadáva celý prepis, zobrazenie je stránkované.

Hlavná karta obsahuje frontu a spracovanie, druhá náhľad a prevádzkové správy.
Náhľad má obmedzenú históriu; editor používa všetky uložené úseky bez tohto limitu.

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

Automatické testy zahŕňajú pôvodné funkcie, checkpointy a pád procesu,
obnovu fronty/nastavení, chyby, editor nad 1 501 úsekmi, export a timestampy.
Natívny Windows test preveril Small na CPU, prerušenie po prvom úseku,
reštart aplikácie a dokončenie zvyšných úsekov bez zdvojenia uložených dát.
WeSpeaker bol spustený na syntetickom zvuku; nejde o meranie presnosti diarizácie.

Chýba oprávnený reálny CZ/SK korpus s ručne skontrolovanou referenciou.
Pripravený je [vyhodnocovací nástroj a presný zoznam ukážok](outputs/zdroj/eval/README.md).
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
Nové základné závislosti: sounddevice 0.5.3 (prehrávanie), tkinterdnd2 0.4.3
(pretiahnutie súborov). Nepribaľujú sa váhy modelov.

Debug CZ/SK: pred spustením nastavte `$env:ND_TRANSKRIPTHOR_DEBUG='1'`.
Rotovaný log je `%LOCALAPPDATA%\LokalnyPrepis\asr-debug.log`; neobsahuje zvuk ani text prepisu.

Created by Daniel Návojský using Codex | 2026
