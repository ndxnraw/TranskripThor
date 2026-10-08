# ND TranskripThor 2.1.3b – pretiahnutie súborov

## Potvrdené zistenia a neistota

V pôvodnom kóde lambda pre `<<Drop>>` vracala výsledok `accept_files()`, teda `None`. Nainštalované tkinterdnd2 0.4.3 a jeho Tcl kód používajú výsledok handlera ako DnD akciu; požadované sú napríklad `copy` a `refuse_drop`. Navyše `accept_files()` počas prepisu skončilo bez vysvetlenia a pôvodné porovnanie ciest nerozlišovalo duplicity podľa pravidiel Windows.

Pôvodne bol registrovaný iba root. Tcl vrstva vie vyhľadávať registrovaných rodičov, preto samotnú registráciu rootu nemožno označiť za dokázanú jedinú príčinu. Nenašiel sa dôkaz chýbajúcej DLL alebo chybného PyInstaller balenia. Tieto dve možnosti sa nezamieňajú s chybou návratovej akcie alebo nedoručením udalosti.

## Zmeny

- `file_drop.py`: bežné spustenie cez verejnú triedu `TkinterDnD.Tk`, zachytenie zlyhania a náhradné obyčajné Tk. Vložené aplikácie/testy s dodaným obyčajným Tk používajú ten istý `_require` loader ako konštruktor verzie 0.4.3.
- Registrovaná je oblasť nahrávok a jej potomkovia: prázdna plocha, jej text, nápoveda, zoznam a posúvač. Root nie je druhým handlerom. Tcl vyberá konkrétny cieľ; jeden dispatch volá príjem raz.
- Explicitné handlery DropEnter, DropPosition a Drop vracajú COPY alebo REFUSE_DROP. Používa sa výhradne `root.tk.splitlist(event.data)`, bez delenia podľa medzier či ručných úprav zátvoriek.
- `prepis.py`: tlačidlo aj drop používajú rovnaký príjem. Podporované formáty ostávajú nezmenené vrátane výberu všetkých súborov. Windows cesty sa normalizujú cez resolve/normcase. Súbory sa iba pridávajú do fronty; nepresúvajú sa, nemažú a prepis sa automaticky nespúšťa.
- Zobrazuje sa počet pridaných a preskočených položiek, počet duplicít a neplatných ciest/priečinkov. Priečinky sa neprechádzajú rekurzívne. Busy stav drop odmietne so zrozumiteľným dôvodom.
- Pri nedostupnom DnD je informácia priamo v oblasti nahrávok aj pri naplnenej fronte. Pridať nahrávky ostáva použiteľné. Nápoveda sľubuje drop iba do tejto oblasti.
- Diagnostika `dnd.log` v priečinku nastavení odlišuje `load`, `register`, `delivered`, `handled`, odmietnutie a technické chyby. Udalosti sú tiež v Podrobnostiach spracovania.
- Manifest zostáva `asInvoker`. Aplikácia kontroluje svoje zvýšené oprávnenia a pri spustení ako správca upozorní, že bežný Prieskumník nemusí môcť doručiť drop. Ochrana Windows sa neobchádza. Rovnaké oprávnenia nie sú dôkazom úspešného dropu.

Necommitnuté zmeny 2.1.3 vrátane manuálneho CPU/GPU zostali zachované. Závislosti a `TranskripTHOR.spec` sa nemenili. Vydanie nebolo publikované.

## Overenie

- Finálna celá sada: **89 testov, 88 úspešných**. Zostáva pôvodný známy test viditeľnosti tlačidla pri 200 % škálovaní na 1536 × 864. Dodatočná výška nápovedy najprv spôsobila regresiu pri 175 %; bola opravená a finálna sada ju už nereprodukuje.
- Všetkých päť nových DnD testov prešlo: viac ciest v Tcl zozname, medzery, diakritika a Unicode, duplicity vrátane veľkosti písmen, neexistujúce cesty/priečinky, chybný vstup, busy, návratové akcie a náhradné spustenie pri zlyhaní načítania.
- Zdrojové testy reálne načítajú tkdnd, kontrolujú Windows registráciu `CF_HDROP` a vykonajú Tcl binding/substitúciu na zamýšľaných cieľoch. Jeden dispatch zavolá príjem raz. To je integračný test Tcl/Python, **nie systémové pretiahnutie z Prieskumníka**.
- Windows EXE reálne načítalo tkdnd 2.9.4 a registrovalo šesť cieľov. Prešiel aj skutočný CPU prepis Tiny s exportom SQLite/TXT/SRT. V oddelenom interaktívnom EXE sa tlačidlom otvoril systémový dialóg výberu súborov; dokončenie výberu cez automatizáciu nebolo potvrdené. Výsledky sú tiež v `OVERENIE.json`. Úspešné načítanie knižnice, registrácia alebo prítomnosť DLL samy o sebe nepotvrdzujú systémový drag and drop.
- Čítanie tokenov procesov potvrdilo `elevated=false` pre testovacie EXE aj bežiaci Prieskumník. Rozdiel zvýšených oprávnení sa pri tomto teste nepotvrdil; nevylučuje to odlišné spustenie aplikácie u používateľa.
- Reálny systémový drop jedného/viacerých súborov do prázdnej/naplnenej oblasti, následný výber tlačidlom a systémové odmietnutie počas prepisu **neboli dokončené**. Nástroj Windows Computer Use pri pokuse o prípravu Prieskumníka stratil okno a neskôr ani opakované zadanie adresy nebolo spoľahlivo viditeľné. Výsledok nie je označený za úspech.

## Krátky manuálny test

1. Rozbaľte celý ZIP. Spustite EXE bežne, nie ako správca. Pre oddelený stav použite argumenty `--dnd-test C:\Testy\TranskripThor-DnD`; tento režim ukladá frontu, cache a výsledky len do zadaného testovacieho priečinka.
2. Z bežného Prieskumníka pretiahnite jeden WAV s medzerami/diakritikou na text prázdnej oblasti. Očakávajte jednu položku, COPY a žiadne spustenie prepisu.
3. Pretiahnite dva ďalšie súbory (jeden s Unicode názvom) na naplnený zoznam. Znova pustite rovnaké súbory: počet položiek sa nezmení a súhrn uvedie duplicity. Zdrojové súbory musia zostať v Prieskumníkovi.
4. V novej prázdnej testovacej fronte zopakujte hromadný drop na prázdnu plochu aj jej text. Potom pridajte ďalší súbor tlačidlom Pridať nahrávky.
5. Spustite prepis dlhšej testovacej nahrávky a skúste ďalší drop: musí byť odmietnutý s vysvetlením, bez zmeny fronty. Po zastavení ho zopakujte: musí byť prijatý.
6. Pri probléme priložte testovací `state\dnd.log`. `load/register` bez `delivered` ukazuje problém pred handlerom (cieľ, systémové doručenie alebo oprávnenia), `delivered` s odmietnutím/chybou ukazuje spracovanie udalosti. Nezapínajte administrátorské spustenie ani výnimky ochrany Windows.
