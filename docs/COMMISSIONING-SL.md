# Jabuka — kartica za skiperja (tablica na krmilu)

*Statut : brouillon, à relire par un locuteur slovène.* Osnutek: prosim, popravite jezik.
Podrobnosti v francoščini: [COMMISSIONING.md](COMMISSIONING.md).

## Tablica

- Wi-Fi omrežje **`jabuka`**, letalski način z vključenim Wi-Fi.
- Naslov v Chromu: **http://10.42.0.1** (zavihek **Barre** = krmilo).
- Tablica je vedno na polnilcu. Zaslon ne sme ugasniti (oznaka `ÉCRAN: verrou`).

## Velika številka: kaj krmariti

- **`TWA ROUTE ↑ 42° tribord`**: krmari ta kot proti pravemu vetru na tem halzu.
  ↑ = v orco (proti vetru), ↓ = s krmo (z vetrom). tribord = desni bok, bâbord = levi bok.
- **`CAP ROUTE 114°M`**: krmari ta kompasni kurz (magnetni).
- **`TWA CIBLE`** / **`CAP À SUIVRE`**: ni izračunane poti; to so laylines (mejne črte). Krmari
  po njih, je v redu.
- Pod številko: **`LOFER`** = orcaj (bolj v veter), **`ABATTRE`** = odpadi (bolj od vetra),
  **`◄ BÂBORD`** / **`TRIBORD ►`** = levo / desno.

## Slovar zaslona (francosko → slovensko)

| Na zaslonu | Pomen |
|---|---|
| `VIREZ` | Obrni zdaj (obrat). Ostane na zaslonu 2 min. |
| `Virement dans 08:30` | Obrat čez 8 min 30 s. |
| `ON RESTE` | Gumb: ostanemo na tem halzu, zdaj ne obračamo. |
| `ANNULER ON RESTE` | Gumb: prekliči »ostanemo«. |
| `Ne pas virer : +4 min` | Če ne obrnemo, izgubimo 4 min. |
| `CAP À SUIVRE` | Kurz, ki mu sledimo (°M). |
| `Route mise à jour…` | Obrat zamujen, pot se preračunava. Ne obračaj po starem nasvetu. |
| `Marque suivante : Jabuka — Annuler` | Naslednja oznaka je Jabuka. »Annuler« = prekliči, če je napačno. |
| `LIVE` | Veter iz instrumentov B&G. Najboljše. |
| `GRIB` | Instrumenti ne delujejo: veter iz vremenske napovedi. Preveri z očmi. |
| `MANUEL` | Veter, vnesen na roko (iz zaslona B&G). Popravi ga vsakih 30 min. |
| `PÉRIMÉ` | Podatki o vetru so stari. Ne zaupaj številkam. |
| `PERTE DONNÉES` | Ni povezave s Pi: vse številke so sive. |

## ON RESTE

Pritisni, ko zdaj ne želiš obrniti (sunek vetra, promet, posadka ni pripravljena). Pi
preračuna pot na tem halzu. `Virement imposé (terre)`: obrni pred koncem odštevanja (kopno!).

## Noč in zaklep

- Gumb **`☾ Nuit`**: rdeče na črnem. Drsnik zmanjša svetlost.
- **Ključavnica** (zaklep): dotik nič ne spremeni (pršec, mokri prsti).
  Odklepanje: drži ključavnico **2 sekundi**.

## Siv ali prazen zaslon

1. Sive številke (`PERTE DONNÉES`): preveri Wi-Fi `jabuka`, nato ponovno naloži stran.
2. Ni poti: zaslon kaže laylines (`TWA CIBLE`). Krmari po njih.
3. Nič ne dela: instrumenti B&G in papirna karta (Plan C), ali prenosnik z OpenCPN (Plan B).
4. Pokliči lastnika (Pi, Wi-Fi, prenosnik).
