# ND TranskripThor 2.1.2.bugfix

## Zistenia

Kontrola nainštalovaného Hugging Face Hub 0.36.2 potvrdila, že pôvodný počet dokončených súborov neukazoval prenos veľkého rozpracovaného súboru. Sledovanie veľkosti cieľovej cache navyše nemeralo sieťový prenos: knižnica zapisuje po blokoch a Xet môže používať vlastnú cache a medzipamäť. Hodnota 0 MB sama osebe nedokazuje nulový prenos.

Pôvodné sťahovanie nemalo ohraničené čakanie na zámok cache. Vnútorný HTTP mechanizmus obnovoval rozpočet opakovaní po prijatí dát a aplikačné zastavenie nedokázalo prerušiť zablokovanú operáciu knižnice. To sú potvrdené nedostatky spoločnej cesty pre modely.

V dostupnej používateľskej cache zostalo 16 prázdnych `.incomplete` súborov a dva prázdne súbory zámkov. Samotná existencia súboru zámku neznamená, že ho drží proces. Pôvodný proces už nebežal a nebol dostupný diagnostický záznam prenosu. Konkrétny sieťový spúšťač pôvodného niekoľkohodinového zaseknutia ani vtedajšie používanie Xet preto nemožno spätne potvrdiť. Používateľská cache nebola zmazaná ani upravená testami.

## Oprava

- Všetky modely Whisper, KInIT a WeSpeaker používajú spoločný sledovaný proces sťahovania. Aplikácia môže proces zastaviť aj pri zablokovaní knižnice; model ani prepis sa tým nenahrávajú na externú službu.
- Tento proces používa HTTP prenos cez Hub, pričom Xet a hf_transfer vypína pred importom knižnice. TLS ostáva zapnuté. Hub je pevne viazaný na verziu 0.36.2, pretože izolované meranie využíva jeho interné prenosové rozhranie.
- Priebeh rozlišuje spojenie, zámok cache, prenos, overovanie kontrolného súčtu a dokončovanie. Ukazuje aktuálny súbor a skutočné bajty prenosu alebo overovania; nevytvára odhadované percentá modelu.
- Spojenie má limit 10 s, čítanie zo siete 20 s a zámok 30 s. Nečinnosť má limit 90 s, pri overovaní/dokončovaní 180 s. Postupujúce overovanie sa nepovažuje za zaseknutú sieť. Jedna fáza jedného súboru má horný limit 6 hodín. Najviac tri pokusy majú odstupy 2 a 4 s; zastavenie funguje aj počas odstupu.
- Hotové súbory sa používajú z cache, čiastočné prenosy sa obnovujú pomocou HTTP Range. Poškodený dokončený súbor sa odloží pod názov `.invalid-*`, neopravuje sa vymazaním celej cache. Neodstraňujú sa cudzie zámky.
- Stiahnuté súbory sa overujú podľa veľkosti a SHA-256 alebo Git SHA-1 z metadát konkrétnej revízie. Stav pripravenosti vyžaduje kompletnú štruktúru a dokončený overovací záznam vrátane všetkých častí delených váh. Staršie cache bez tohto záznamu ostávajú použiteľné offline po kontrole štruktúry; opätovné stiahnutie cez správcu doplní kontrolné súčty bez opakovania platných prenosov.
- Diagnostika sa zapisuje do `%LOCALAPPDATA%\LokalnyPrepis\models\model-download.log`. Obsahuje fázu, súbor, pokus, časový limit a bezpečný kód príčiny. Neukladá tokeny, podpisované URL ani surové sieťové výnimky.

## Overenie

Automatická sada: **77 testov, 76 úspešných**. Jediný neúspešný test je už na nezmenenej verzii 2.1.0 reprodukované skrytie tlačidla pri 200 % škálovaní na obrazovke 1536 × 864. Táto oprava sťahovania tento nesúvisiaci problém nemení.

Testy prenosu používajú lokálny HTTP server, skutočné streamovanie knižnice, malé modelové súbory a samostatné procesy. Overujú úspešný prenos všetkých podporovaných modelov, prerušené spojenie, obnovenie čiastočnej cache, zastavenie a pokračovanie, konečný počet pokusov bez nových dát, držaný zámok, poškodený súbor, delené váhy KInIT, overovanie bez sieťovej aktivity a ochranu diagnostiky pred citlivými URL. Opakované nezmenené hlásenie neobnovuje časový limit.

Reálne boli stiahnuté a overené Tiny a WeSpeaker do oddelených testovacích cache. Pri KInIT boli overené tri skutočné konfiguračné JSON súbory a správne odmietnutie neúplného modelu. Celé váhy KInIT, Medium a Large-v3 sa nesťahovali; ich prenosové vetvy pokrývajú malé simulácie. To nie je meranie úspešného stiahnutia ich plných váh.

Zostavené Windows EXE úspešne stiahlo a overilo WeSpeaker v novej cache. Prešiel aj lokálny prepis testovacieho zvuku cez Tiny CPU int8, vytvorenie výsledkov SQLite/TXT/SRT a načítanie komponentov Tk/tkdnd, PortAudio a kaldi. CUDA nebola dostupná. Vizuálne overenie všetkých fáz nového hlásenia človekom nebolo vykonané; priebeh bol skontrolovaný v udalostiach reálneho EXE.

## Ako pokračovať v zaseknutom sťahovaní

1. Ukončite starú verziu. Ak nereaguje, ukončite jej proces ND TranskripThor v Správcovi úloh.
2. Rozbaľte celý nový Windows ZIP a spustite `ND TranskripThor.exe`; priečinok `_internal` musí zostať vedľa EXE. Pôvodnú cache ponechajte.
3. Vypnite režim offline, v Modeloch vyberte príslušný model a zvoľte Stiahnuť, prípadne opakujte prerušenú položku fronty. Platné súbory sa znovu nesťahujú. Pri ďalšej chybe sa riaďte konkrétnym hlásením a priložte `model-download.log`.

## Zostavenie

Použite existujúci Windows postup zostavenia a závislosti z `outputs/zdroj/requirements-models.txt`, vrátane `huggingface-hub==0.36.2`. Neaktualizujte túto knižnicu samostatne bez testov prenosu. Nové moduly `download_transport.py` a `download_worker.py` PyInstaller zahrnie cez importy; spúšťací bod už obsahuje `multiprocessing.freeze_support()` potrebný pre Windows EXE.
