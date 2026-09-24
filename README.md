# 🎓 Horizontalna mobilnost UNIZG: pretraživač kolegija

Pretraži **19.557 kolegija svih sastavnica Sveučilišta u Zagrebu** koje možeš upisati u sklopu horizontalne mobilnosti, za **ak. god. 2026./2027.** Podaci su preuzeti iz nastavnih programa u [ISVU-u](https://www.isvu.hr/visokaucilista/hr/pocetna).

<!-- Nakon povezivanja s Netlifyjem ovdje upiši link: -->
**▶ Otvori pretraživač:** _(link će biti dodan nakon objave na Netlifyju)_

![Pretraga „poduzetništvo” s filtrom na diplomske studije](docs/snimka.png)

## Što može

- **Pretraga po ključnoj riječi** u nazivu i opisu kolegija. Dijakritici nisu bitni (*poduzetnistvo* = *poduzetništvo*), a pronalaze se i drugi oblici riječi (*poduzetništvo* → *poduzetnički*, *poduzetnik*; *robotika* → *robotski*).
- **Istaknut pogodak** u isječku opisa, uz mogućnost otvaranja cijelog opisa.
- **Filtri:** područje, fakultet, razina studija, semestar (zimski/ljetni), ECTS i jezik nastave. Uz svaki filtar prikazuje se broj kolegija.
- **Opisi sa stranica fakulteta:** gdje fakultet u ISVU nije unio opis, opis se preuzima s njegove stranice (Filozofski, FER, Kineziološki, Agronomski, Pravni). Takav opis je jasno označen i ima link na izvor.
- **Svaki kolegij** ima naziv, fakultet, ECTS, razinu, semestar, opis, popis studija na kojima se izvodi i **službeni link na ISVU**.
- Kolegij koji se izvodi na više studija ili smjerova prikazan je **samo jednom**.
- Radi na mobitelu, s tamnom i svijetlom temom. Sve je u jednoj statičkoj datoteci, bez servera.

<p align="center"><img src="docs/snimka-mobitel.png" width="300" alt="Prikaz na mobitelu"></p>

## Kako se podaci osvježavaju

GitHub Action [`refresh.yml`](.github/workflows/refresh.yml) pokreće se **1. u svakom mjesecu**. Može se pokrenuti i ručno: *Actions → Osvježi kolegije iz ISVU-a → Run workflow*, uz opcionalan unos godine.

1. Prikupi popis sastavnica, sve nastavne programe i stranicu svakog kolegija iz ISVU-a (~40 min).
2. Za kolegije bez opisa u ISVU-u dohvati opise sa stranica fakulteta (vidi dolje).
3. Izgradi novu `site/index.html`.
4. **Provjeri rezultat prema izvoru.** Ponovno dohvati nasumični uzorak kolegija uživo i usporedi naziv, ECTS, opis, jezik i link. Isto napravi i za uzorak opisa sa stranica fakulteta: provjerava se da stranica ili PDF izvora sadrži ISVU šifru kolegija i isti tekst. Zatim na stvarnim podacima testira ponašanje pretrage.
5. Commita novu stranicu **samo ako je provjera prošla**, nakon čega Netlify automatski objavljuje novu verziju. Ako provjera padne, stara stranica ostaje, a izvještaj je u sažetku pokretanja.

Od srpnja nadalje automatski se prelazi na iduću akademsku godinu.

## Opisi sa stranica fakulteta

Koriste se samo izvori koji objavljuju **ISVU šifru kolegija**, pa se spajanje radi po šifri, a ne po nazivu. Opis s fakultetske stranice koristi se samo kad u ISVU-u nema polja „Opis predmeta”.

| Sastavnica | Izvor | Sadržaj opisa |
|---|---|---|
| Filozofski | ECTS katalog `thetha.ffzg.hr/ECTS` (tekuća godina) | cilj, sadržaj, ishodi |
| FER | `fer.unizg.hr/predmet/{kratica}`, podaci za traženu ak. god. | opis, ishodi |
| Kineziološki | PDF „Izvedbeni plan” (popis URL-ova u `s3b_external.py`, `KIF_PDFS`) | ciljevi, ishodi, sadržaj |
| Agronomski | `agr.unizg.hr/hr/course/{broj}` | opis, sadržaj, ishodi |
| Pravni | PDF-ovi `{šifra}-NTJ.pdf` i `{šifra}-IUK.pdf` (WordPress) | nastavne teme, ishodi |

Ako je neki fakultet nedostupan, zadržava se zadnji uspješno preuzeti rezultat (`pipeline/data/external.json.gz`) i izgradnja se nastavlja. Ekonomski fakultet ne objavljuje opise sa šiframa kolegija, pa nije uključen. Kad KIF objavi noviji izvedbeni plan, njegov URL treba dodati na vrh popisa `KIF_PDFS`.

## Struktura repozitorija

| Putanja | Sadržaj |
|---|---|
| `site/index.html` | Gotova stranica s ugrađenim podacima. Netlify objavljuje ovu mapu. |
| `pipeline/scripts/` | `s1`–`s3` prikupljanje iz ISVU-a, `s3b` opisi sa stranica fakulteta, `s4` izgradnja, `s5` provjera prema izvoru |
| `pipeline/data/external.json.gz` | Zadnji uspješni rezultat `s3b` (rezerva kad je stranica fakulteta nedostupna) |
| `pipeline/assets/template.html` | Predložak stranice (izgled, pretraga, filtri) |
| `pipeline/isvu-struktura.md` | Opis ISVU putanja, za slučaj da se izvor promijeni |
| `netlify.toml` | Postavke Netlifyja: objavljuje `site/`, bez build koraka |
| `docs/` | Snimke zaslona za ovaj README |

## Lokalno pokretanje

Potrebni su Python 3.10+ i Node.js (za korak provjere).

```bash
pip install requests beautifulsoup4 pdfplumber
cd pipeline/scripts
A="--year 2026 --workdir ../../work"
python s1_institutions.py $A && python s2_programs.py $A && python s3_details.py $A
python s3b_external.py $A                              # izvještaj: work/external_report.md
python s4_build.py $A --out ../../site/index.html
python s5_verify.py $A --out ../../site/index.html    # izvještaj: work/verification_report.md
```

## Napomene o podacima

- Uključeni su sveučilišni i stručni **prijediplomski, diplomski i integrirani** studiji, redovni i izvanredni. Doktorski i poslijediplomski specijalistički studiji nisu uključeni.
- **Opis:** za 9.479 kolegija (48 %) fakulteti u ISVU nisu unijeli opis. Za 2.167 od njih opis je preuzet sa stranice fakulteta, uz oznaku i link na izvor. Gdje ni toga nema, a postoje ishodi učenja iz ISVU-a, prikazani su ishodi. Bez ikakvog opisa ostaje 7.315 kolegija (37 %), i oni se pronalaze samo po nazivu.
- **Područje** je dodijeljeno prema sastavnici, jer ISVU ne bilježi znanstveno područje po kolegiju.
- **Zimski** semestar obuhvaća neparne, a **ljetni** parne semestre studija.
- Za 2026./2027. Fakultet zdravstvenih studija i Vojni studiji nemaju objavljen nastavni program u ISVU-u, a Farmaceutsko-biokemijski fakultet ima unesena samo prva dva semestra.
- Podaci su snimka stanja ISVU-a na datum naveden na stranici. **Uvjete upisa i dostupnost za studente drugih sastavnica provjerite kod matične i ciljne sastavnice.**

---

Izvor podataka: ISVU, Informacijski sustav visokih učilišta (Ministarstvo znanosti, obrazovanja i mladih / Srce). Ovo **nije službena stranica** Sveučilišta u Zagrebu.
