# Struktura ISVU-a (pregled podataka)

Za debugiranje kad se ISVU promijeni. Sve putanje su pod `https://www.isvu.hr/visokaucilista/hr/podaci`, `{vu}` je šifra visokog učilišta, a `{g}` početna godina.

| Korak | URL | Oblik |
|---|---|---|
| Popis učilišta | `/visokaucilista/hr/pretrazivanje` | HTML tablica: naziv (link `/podaci/{vu}`), nadređena ustanova, sjedište |
| Razine | `/{vu}/dohvatirazine/{g}` | JSON `[{sifraRazine, nazivRazineIVrste}]` |
| Načini izvedbe | `/{vu}/razina/{r}/dohvatiizvedbe/{g}` | JSON `[{oznaka: "R"/"I", naziv}]` |
| Stablo studija | `/{vu}/razina/{r}/izvedba/{i}/akgodina/{g}` | JSON, rekurzivno `listaPodredjenihStudija`; koristi samo čvorove s `imaNastavniProgram == 1` |
| Nastavni program | `/{vu}/nastavniprogram/{g}/razina/{r}/izvedba/{i}/smjer/{s}` | HTML; `div.tab-pane#semestarN`, redovi s linkom `/predmet/{pid}/`; izborne grupe su u ugniježđenoj `table.panel` |
| Kolegij | `/{vu}/akademskagodina/{g}/predmet/{pid}/razina/{r}/izvedba/{i}/smjer/{s}` | HTML; `h2.card-title` = naziv; `dl.row` parovi dt/dd: Šifra, ECTS bodovi, Opterećenje, Izvođači, Opis predmeta, Ishodi učenja, Jezici izvođenja nastave, Predmet u nastavnom programu (tablica: šifra studija, naziv, razina, semestar, obavezni/izborni) |

Šifre razina viđene 2026.: 1 dodiplomski (stari), 3 sveučilišni prijediplomski, 4 sveučilišni diplomski, 5 integrirani, 6 stručni diplomski, 8 stručni prijediplomski, 9 stručni kratki, 10 doktorski, 11 sveučilišni specijalistički.

Poznate posebnosti: šifra 9996 je samo „Sveučilište u Zagrebu” (sveučilišni studiji, bez nadređene ustanove). PMF se u ISVU-u vodi kao dvije jedinice (37 matematički, 119 prirodoslovni odsjeci). Neke sastavnice (374, 9950) za 2025. i 2026. vraćaju prazan popis razina.
