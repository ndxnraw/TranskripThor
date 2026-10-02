# Overenie CZ/SK na skutočnom zvuku

Zatiaľ nemáme oprávnenú zmiešanú nahrávku s ručne skontrolovanou referenciou.
Automatické testy používajú mocky; slovenský zvuk Microsoft Filip je syntetický.
Tieto výsledky nie sú meraním presnosti na reálnom zmiešanom zvuku.

Potrebné ukážky (aspoň dve nezávislé nahrávky pre každý scenár):

1. Čistá čeština a čistá slovenčina, každá 30–60 s.
2. Dvaja hovoriaci CZ → SK → CZ a SK → CZ → SK, 1–3 minúty, s pauzami.
3. Krátke odpovede „áno“, „jo“, „dobre“, „ještě ne“, 0,5–2 s, v kontexte rozhovoru.
4. Dialóg s ruchom kancelárie/skladu a odlišnou hlasitosťou, 1–3 minúty.
5. Mená osôb, firiem, obcí a čísla, 30–60 s.
6. Zmena jazyka uprostred vety bez pauzy, najmenej 10 prechodov.
7. Pre rozlíšenie hlasov navyše 2–4 hovoriaci, vrátane podobných hlasov a prekryvu.

Použite vlastné nahrávky so súhlasom účastníkov alebo nahrávky s vhodnou licenciou.
Označte presné jazykové hranice (aj uprostred vety), bez normalizovania jazyka.
Referenciu ručne skontrolujte počúvaním a vyplňte `reviewed_by`, oprávnenie a scenáre.
Skopírujte štruktúru ukážky do `recordings`; dodaný príklad nie je skutočná referencia.

```powershell
python evaluate_mixed.py eval/manifest.json --cache "$env:LOCALAPPDATA/LokalnyPrepis/models" --models small medium large-v3 --output eval/merania.json
```

Nástroj beží offline, používa rovnaký zmiešaný režim a meria WER (malé písmená,
bez interpunkcie), časovo váženú správnosť jazyka, čas prepisu a pomer času
spracovania k dĺžke zvuku. Načítanie modelu je vykázané osobitne. Neprítomný text
alebo nesprávny jazyk sa nesmie považovať za správny prechod. Na posúdenie mien
a interpunkcie skontrolujte aj uložený doslovný výstup. Výsledky porovnávajte na
rovnakom hardvéri, v rovnakom režime CPU/GPU a opakujte aspoň trikrát.
