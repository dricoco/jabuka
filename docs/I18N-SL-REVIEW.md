# Slovenian UI texts: proofreading sheet

Generated from `src/jabuka/web/static/i18n.js` by `python -m jabuka.tools.i18n_review`. Do not
edit by hand: correct the `sl` column in i18n.js, then regenerate.

**Status: proposed translation, NOT yet proofread by a native speaker.** Please check every
`sl` cell, in particular the sailing terms. Short texts matter: the helm labels and the
countdown must fit on the tablet in big letters.

How to propose corrections: mark the row (key) and write the better Slovenian text next to it,
on paper, in a message or straight in this file. The owner will copy them into i18n.js.

Terms chosen (to confirm first):

| English | French | Proposed Slovenian |
|---|---|---|
| tack (manoeuvre) | virement | obrat ("Obrat čez 08:30", "OBRNI") |
| gybe | empannage | križ ("Križ čez 04:30", "KRIŽAJ") |
| layline | layline | layline |
| mark | marque | boja |
| course (sequence of marks) | parcours | proga |
| route (computed) | route | pot |
| heading / course to steer | cap / cap à suivre | smer / smer krmarjenja |
| true wind | vent réel | pravi veter |
| port / starboard | bâbord / tribord | levo / desno |
| head up / bear away | lofer / abattre | orcaj / odpadi |
| hold the tack | on reste | ostanemo |
| knots | nœuds (nds) | kn |

`{name}` placeholders are filled in by the program: keep them unchanged.


## Shell: tabs, night mode, top-bar badges

| key | fr | en (reference) | sl (to proofread) |
|---|---|---|---|
| `app.title` | Jabuka — Barre | Jabuka — Helm | Jabuka — Krmilo |
| `tab.barre` | Barre | Helm | Krmilo |
| `tab.carte` | Carte | Chart | Karta |
| `tab.reglages` | Réglages | Settings | Nastavitve |
| `tab.diag` | Diag | Diag | Diag |
| `aria.tabs` | Onglets | Tabs | Zavihki |
| `aria.map` | Carte | Chart | Karta |
| `aria.diag` | Diagnostics | Diagnostics | Diagnostika |
| `theme.day` | Jour | Day | Dan |
| `theme.night` | ☾ Nuit | ☾ Night | ☾ Noč |
| `theme.brightAria` | Luminosité nuit | Night brightness | Nočna svetlost |
| `theme.nightAria` | Mode nuit | Night mode | Nočni način |
| `badge.link` | PERTE DONNÉES | DATA LOST | NI PODATKOV |
| `badge.wake` | ÉCRAN: {state} | SCREEN: {state} | ZASLON: {state} |
| `wake.verrou` | verrou | lock | zaklep |
| `wake.video` | vidéo | video | video |
| `wake.aucun` | aucun | none | brez |
| `badge.mapUnavailable` | CARTE INDISPONIBLE | CHART UNAVAILABLE | KARTA NI NA VOLJO |
| `badge.moduleUnavailable` | {name} INDISPONIBLE | {name} UNAVAILABLE | {name} NI NA VOLJO |
| `common.error` | erreur | error | napaka |
| `common.failed` | Échec ({s}) | Failed ({s}) | Napaka ({s}) |
| `common.close` | Fermer | Close | Zapri |
| `common.cancel` | Annuler | Cancel | Prekliči |
| `unit.kn` | nds | kn | kn |
| `badge.noWind` | PAS DE VENT | NO WIND | NI VETRA |
| `badge.stale` | PÉRIMÉ | STALE | ZASTARELO |
| `badge.manual` | MANUEL {n} min | MANUAL {n} min | ROČNO {n} min |
| `badge.manualUnknown` | MANUEL âge ? | MANUAL age ? | ROČNO starost ? |
| `badge.calcError` | ERREUR CALCUL | CALC ERROR | NAPAKA IZRAČUNA |

## Helm (Barre): big numbers, hints, countdown

| key | fr | en (reference) | sl (to proofread) |
|---|---|---|---|
| `helm.deviation` | Écart | Off target | Odstopanje |
| `helm.speedTarget` | Vitesse / cible | Speed / target | Hitrost / cilj |
| `helm.bspTarget` | BSP / cible | BSP / target | BSP / cilj |
| `helm.polar` | Polaire | Polar | Polara |
| `helm.mark` | Marque | Mark | Boja |
| `helm.distance` | Distance | Distance | Razdalja |
| `helm.time` | Temps | Time | Čas |
| `helm.bearing` | Relèvement | Bearing | Azimut |
| `helm.stale` | PERTE DONNÉES | DATA LOST | NI PODATKOV |
| `helm.windStale` | VENT PÉRIMÉ | WIND STALE | VETER ZASTAREL |
| `helm.northUp` | Nord en haut | North up | Sever gor |
| `helm.courseUp` | Cap en haut | Course up | Smer gor |
| `helm.centre` | Centrer | Centre | Centriraj |
| `helm.tackIn` | Virement dans {t} | Tack in {t} | Obrat čez {t} |
| `helm.gybeIn` | Empannage dans {t} | Gybe in {t} | Križ čez {t} |
| `helm.overstood` | DÉPASSÉE +{t} | OVERSTOOD +{t} | PREKORAČENO +{t} |
| `helm.fetching` | ÇA PASSE | LAYING THE MARK | DOSEŽEMO BOJO |
| `helm.twaUp` | TWA CIBLE ↑ | TARGET TWA ↑ | CILJNI TWA ↑ |
| `helm.twaDown` | TWA CIBLE ↓ | TARGET TWA ↓ | CILJNI TWA ↓ |
| `helm.cts` | CAP À SUIVRE | COURSE TO STEER | SMER KRMARJENJA |
| `helm.hintPort` | ◄ BÂBORD | ◄ PORT | ◄ LEVO |
| `helm.hintStbd` | TRIBORD ► | STARBOARD ► | DESNO ► |
| `helm.hintUp` | LOFER | HEAD UP | ORCAJ |
| `helm.hintDown` | ABATTRE | BEAR AWAY | ODPADI |
| `helm.speed` | {bsp} / {tgt} nds | {bsp} / {tgt} kn | {bsp} / {tgt} kn |
| `helm.otherTack` | Autre bord {h} | Other tack {h} | Po obratu {h} |
| `helm.laylineDist` | Layline à {d} | Layline in {d} | Layline čez {d} |
| `flag.cap` | CAP NON FIABLE | HEADING UNRELIABLE | SMER NI ZANESLJIVA |
| `flag.current` | COURANT | CURRENT | TOK |
| `flag.sailed` | ANGLES RÉELS | SAILED ANGLES | DEJANSKI KOTI |
| `flag.noGps` | PAS DE GPS | NO GPS | NI GPS |
| `tack.stbd` | tribord | starboard | desno |
| `tack.port` | bâbord | port | levo |

## Route band and ON RESTE

| key | fr | en (reference) | sl (to proofread) |
|---|---|---|---|
| `route.twaRouteUp` | TWA ROUTE ↑ | ROUTE TWA ↑ | TWA POTI ↑ |
| `route.twaRouteDown` | TWA ROUTE ↓ | ROUTE TWA ↓ | TWA POTI ↓ |
| `route.capRoute` | CAP ROUTE | ROUTE HEADING | SMER POTI |
| `route.tackNow` | VIREZ | TACK | OBRNI |
| `route.gybeNow` | EMPANNEZ | GYBE | KRIŽAJ |
| `route.wrongTack` | MAUVAIS BORD | WRONG TACK | NAPAČEN BOK |
| `route.cueNow` | MAINTENANT | NOW | ZDAJ |
| `route.updating` | Route mise à jour… | Route updating… | Posodabljanje poti… |
| `route.landTackIn` | Virement imposé (terre) dans {t} | Forced tack (land) in {t} | Prisilni obrat (kopno) čez {t} |
| `route.noTack` | Pas de virement prévu | No tack planned | Obrat ni predviden |
| `route.cost` | Ne pas virer : {c} | Not tacking: {c} | Brez obrata: {c} |
| `route.age` | Route : il y a {a} | Route: {a} ago | Pot: pred {a} |
| `route.ageRecent` | < 1 min | < 1 min | < 1 min |
| `route.level` | Route : niveau {l} | Route: level {l} | Pot: raven {l} |
| `route.offRoute` | Hors route | Off route | Izven poti |
| `route.stayOn` | On reste | Holding tack | Ostanemo |
| `route.stayOnTack` | On reste ({w}) | Holding tack ({w}) | Ostanemo ({w}) |
| `route.capRouteLine` | Cap route {h} | Route heading {h} | Smer poti {h} |
| `route.twaRouteLine` | TWA route {a} | Route TWA {a} | TWA poti {a} |
| `route.computing` | Calcul de la route… | Computing the route… | Izračun poti… |
| `route.blockedClock` | Routage bloqué : {r} | Routing blocked: {r} | Izračun poti blokiran: {r} |
| `route.blockedClockDefault` | heure GPS non valide | GPS time not valid | čas GPS ni veljaven |
| `route.noPack` | Pas de pack météo : {r} | No weather pack: {r} | Ni vremenskega paketa: {r} |
| `route.noPackDefault` | pack de course non chargé | race pack not loaded | paket regate ni naložen |
| `route.failed` | Routage en échec : {r} | Routing failed: {r} | Izračun poti ni uspel: {r} |
| `route.failedDefault` | erreur du routeur | router error | napaka izračuna poti |
| `route.disabled` | Routage désactivé (Réglages) | Routing off (Settings) | Izračun poti izklopljen (Nastavitve) |
| `route.outdated` | Route retirée : {r} | Route withdrawn: {r} | Pot umaknjena: {r} |
| `route.outdatedDefault` | route périmée | route outdated | pot zastarela |
| `route.staleFail` | Recalcul en échec : {r} | Recompute failed: {r} | Ponovni izračun ni uspel: {r} |
| `route.routing` | Routage : {s} | Routing: {s} | Izračun poti: {s} |
| `route.stay` | ON RESTE | HOLD TACK | OSTANEMO |
| `route.stayCancel` | ANNULER ON RESTE | CANCEL HOLD TACK | PREKLIČI OSTANEMO |
| `route.stayRefused` | On reste impossible : {r} | Cannot hold tack: {r} | Ostanemo ni mogoče: {r} |
| `route.bias` | Biais GRIB {d} ×{k} | GRIB bias {d} ×{k} | Popravek GRIB {d} ×{k} |
| `route.biasOff` | Biais GRIB désactivé | GRIB bias off | Popravek GRIB izklopljen |
| `route.biasLearning` | Biais GRIB : apprentissage | GRIB bias: learning | Popravek GRIB: učenje |
| `route.biasFrozen` | Biais GRIB : gelé, Jabuka | GRIB bias: frozen, Jabuka | Popravek GRIB: zamrznjen, Jabuka |
| `route.biasFading` |  (s'estompe) |  (fading) |  (pojenja) |
| `route.biasFrozenSuffix` |  (gelé, Jabuka) |  (frozen, Jabuka) |  (zamrznjen, Jabuka) |

## Course (Carte)

| key | fr | en (reference) | sl (to proofread) |
|---|---|---|---|
| `side.port` | Bâbord | Port | Levo |
| `side.stbd` | Tribord | Starboard | Desno |
| `side.none` | Aucun | None | Brez |
| `carte.template` | Parcours {x} | Course {x} | Proga {x} |
| `carte.prev` | Préc. | Prev. | Prejš. |
| `carte.next` | Suiv. | Next | Nasl. |
| `carte.sidesWarn` | Côtés à confirmer (IC) | Sides to confirm (SI) | Potrdi strani (NJ) |
| `carte.sidesOk` | Côtés confirmés | Sides confirmed | Strani potrjene |
| `carte.hint` | Toucher la carte pour ajouter une marque | Tap the chart to add a mark | Tapni karto za dodajanje boje |
| `carte.noMap` | Carte indisponible : édition par la liste | Chart unavailable: edit with the list | Karta ni na voljo: urejaj s seznamom |
| `carte.start` | DÉPART | START | START |
| `carte.finish` | ARRIVÉE | FINISH | CILJ |
| `carte.conflict` | Parcours modifié ailleurs — rechargé | Course changed elsewhere — reloaded | Proga spremenjena drugje — znova naložena |
| `carte.refused` | Valeur refusée | Value refused | Vrednost zavrnjena |
| `carte.alreadyActive` | {tpl} déjà actif | {tpl} already active | {tpl} je že aktivna |
| `carte.confirmTpl` | Confirmer {tpl} | Confirm {tpl} | Potrdi {tpl} |
| `carte.willReset` | Le parcours sera réinitialisé | The course will be reset | Proga bo ponastavljena |
| `carte.keep` | Garder | Keep | Obdrži |
| `carte.landTitle` | Marque à terre ? | Mark on land? | Boja na kopnem? |
| `carte.landText` | Ce point est sur une île ou la côte. | This point is on an island or the coast. | Ta točka je na otoku ali obali. |
| `carte.name` | Nom | Name | Ime |
| `carte.side` | Côté | Side | Stran |
| `carte.radius` | Rayon | Radius | Polmer |
| `carte.position` | Position | Position | Položaj |
| `carte.afterActive` | Après la marque active | After the active mark | Za aktivno bojo |
| `carte.atEnd` | À la fin | At the end | Na konec |
| `carte.add` | Ajouter | Add | Dodaj |
| `carte.newMark` | Nouvelle marque | New mark | Nova boja |
| `carte.rename` | Renommer | Rename | Preimenuj |
| `carte.up` | Monter | Move up | Gor |
| `carte.down` | Descendre | Move down | Dol |
| `carte.fullCourse` | Parcours complet | Full course | Celotna proga |
| `carte.finishHere` | Finir ici | Finish here | Cilj tukaj |
| `carte.makeActive` | Rendre active | Make active | Nastavi aktivno |
| `carte.delete` | Supprimer | Delete | Izbriši |
| `carte.confirmDelete` | Confirmer la suppression | Confirm delete | Potrdi brisanje |
| `carte.markTitle` | {name} (n° {idx}) | {name} (no. {idx}) | {name} (št. {idx}) |
| `carte.coordButton` | ＋ Marque (coordonnées) | ＋ Mark (coordinates) | ＋ Boja (koordinate) |
| `carte.coords` | Coordonnées | Coordinates | Koordinate |
| `carte.lat` | Latitude | Latitude | Zemljepisna širina |
| `carte.lon` | Longitude | Longitude | Zemljepisna dolžina |
| `carte.coordHint` | Degrés et minutes : 43 45,2 ou 43°45,2' N | Degrees and minutes: 43 45.2 or 43°45.2' N | Stopinje in minute: 43 45,2 ali 43°45,2' N |
| `carte.moveHere` | Déplacer ici | Move here | Premakni sem |
| `carte.errEmpty` | À remplir | Required | Obvezno polje |
| `carte.errFormat` | Format non reconnu (ex. 43 45,2) | Format not recognised (e.g. 43 45.2) | Neprepoznana oblika (npr. 43 45,2) |
| `carte.errMinutes` | Minutes : de 0 à 59,999 | Minutes: 0 to 59.999 | Minute: od 0 do 59,999 |
| `carte.errSeconds` | Secondes : de 0 à 59,9 | Seconds: 0 to 59.9 | Sekunde: od 0 do 59,9 |
| `carte.errRange` | Hors limites | Out of range | Izven meja |
| `carte.errHemi` | Lettre attendue : {h} | Expected letter: {h} | Pričakovana črka: {h} |
| `carte.errArea` | Hors zone de course ({s} à {n}, {w} à {e}) | Outside the race area ({s} to {n}, {w} to {e}) | Izven območja regate ({s} do {n}, {w} do {e}) |
| `banner.undo` | Annuler | Undo | Razveljavi |
| `banner.expired` | Annuler expiré | Undo expired | Razveljavitev potekla |

## Settings (Réglages)

| key | fr | en (reference) | sl (to proofread) |
|---|---|---|---|
| `lang.title` | Langue / Language / Jezik | Langue / Language / Jezik | Langue / Language / Jezik |
| `manual.title` | Vent manuel | Manual wind | Ročni veter |
| `manual.twsLabel` | TWS (nds) | TWS (kn) | TWS (kn) |
| `manual.refAria` | Référence TWD | TWD reference | Referenca TWD |
| `manual.ref` | Réf. | Ref. | Ref. |
| `manual.apply` | Appliquer | Apply | Uporabi |
| `manual.clear` | Effacer | Clear | Pobriši |
| `manual.none` | Aucun vent manuel enregistré | No manual wind saved | Ročni veter ni shranjen |
| `manual.stored` | Enregistré : {twd}°{ref} / {tws} nds | Saved: {twd}°{ref} / {tws} kn | Shranjeno: {twd}°{ref} / {tws} kn |
| `manual.entered` |  — saisi {age} |  — entered {age} |  — vneseno {age} |
| `manual.ageUnknown` |  — âge inconnu |  — age unknown |  — starost neznana |
| `manual.stale` |  — PÉRIMÉ |  — STALE |  — ZASTARELO |
| `manual.justNow` | à l'instant | just now | pravkar |
| `manual.ago` | il y a {m} min | {m} min ago | pred {m} min |
| `manual.unavailable` | Vent manuel indisponible ({s}) | Manual wind unavailable ({s}) | Ročni veter ni na voljo ({s}) |
| `manual.refused` | Valeurs refusées (TWD 0-359,9°, TWS 0-80 nds) | Values refused (TWD 0-359.9°, TWS 0-80 kn) | Vrednosti zavrnjene (TWD 0-359,9°, TWS 0-80 kn) |
| `manual.errTwd` | TWD : entre 0 et 359,9° | TWD: between 0 and 359.9° | TWD: med 0 in 359,9° |
| `manual.errTws` | TWS : entre 0 et 80 nds | TWS: between 0 and 80 kn | TWS: med 0 in 80 kn |
| `src.LIVE` | Vent instruments (LIVE) | Instrument wind (LIVE) | Veter z instrumentov (LIVE) |
| `src.LIVE_BG` | Vent B&G (LIVE B&G) | B&G wind (LIVE B&G) | Veter B&G (LIVE B&G) |
| `src.MANUEL` | Vent manuel utilisé (MANUEL) | Manual wind in use (MANUAL) | Uporablja se ročni veter (ROČNO) |
| `src.GRIB` | Vent GRIB, pas d'instruments (GRIB) | GRIB wind, no instruments (GRIB) | Veter GRIB, brez instrumentov (GRIB) |
| `reglages.invalid` | Valeur invalide | Invalid value | Neveljavna vrednost |
| `reglages.saved` | Enregistré | Saved | Shranjeno |
| `reglages.conflict` | Modifié sur une autre tablette : rechargé, recommencez | Changed on another tablet: reloaded, try again | Spremenjeno na drugi tablici: znova naloženo, poskusi ponovno |
| `reglages.outOfRange` | Valeur hors limites | Value out of range | Vrednost izven meja |
| `reglages.noSchema` | Schéma indisponible ({s}) | Schema unavailable ({s}) | Shema ni na voljo ({s}) |
| `reglages.helpAria` | Aide : {label} | Help: {label} | Pomoč: {label} |
| `reglages.helpRange` | Plage : {min} à {max} | Range: {min} to {max} | Obseg: {min} do {max} |
| `reglages.helpDefault` | Défaut : {v} | Default: {v} | Privzeto: {v} |
| `reglages.helpEmpty` | vide | empty | prazno |
| `reglages.yes` | oui | yes | da |
| `reglages.no` | non | no | ne |
| `opt.computed` | calculé | computed | izračunan |
| `opt.instrument` | instruments | instruments | instrumenti |
| `opt.polar` | polaire | polar | polara |
| `opt.sailed` | angles réels | sailed angles | dejanski koti |
| `settings.variation_deg` | Déclinaison (°E) | Variation (°E) | Deklinacija (°E) |
| `settings.heading_offset_deg` | Décalage compas (°) | Compass offset (°) | Popravek kompasa (°) |
| `settings.heading_ref_unknown` | Cap de référence inconnue traité comme | Heading of unknown reference taken as | Smer z neznano referenco obravnavaj kot |
| `settings.heading_display` | Affichage des caps | Headings shown in | Prikaz smeri |
| `settings.true_wind_source` | Source du vent réel | True wind source | Vir pravega vetra |
| `settings.efficiency` | Efficacité polaire | Polar efficiency | Izkoristek polare |
| `settings.efficiency_up` | Efficacité au près (optionnel) | Upwind efficiency (optional) | Izkoristek v orcu (neobvezno) |
| `settings.efficiency_down` | Efficacité au portant (optionnel) | Downwind efficiency (optional) | Izkoristek v krmo (neobvezno) |
| `settings.heavy_wind_start_kn` | Vent fort : début de réduction (nds) | Heavy wind: reduction starts at (kn) | Močan veter: začetek zmanjšanja (kn) |
| `settings.heavy_wind_full_kn` | Vent fort : réduction complète (nds) | Heavy wind: full reduction at (kn) | Močan veter: polno zmanjšanje (kn) |
| `settings.heavy_wind_reduction` | Vent fort : réduction | Heavy wind: reduction | Močan veter: zmanjšanje |
| `settings.layline_source` | Angles des lay-lines | Layline angles | Koti laylinov |
| `settings.use_current` | Courant sur les lay-lines | Current on the laylines | Tok na laylinih |
| `settings.leeway_deg` | Dérive (°) | Leeway (°) | Zanos (°) |
| `settings.tau_helm_s` | Amortissement barre (s) | Helm damping (s) | Glajenje krmila (s) |
| `settings.tau_layline_s` | Amortissement lay-lines (s) | Layline damping (s) | Glajenje laylinov (s) |
| `settings.zone_lat` | Zone magnétique : latitude | Magnetic zone: latitude | Magnetno območje: širina |
| `settings.zone_lon` | Zone magnétique : longitude | Magnetic zone: longitude | Magnetno območje: dolžina |
| `settings.zone_radius_nm` | Zone magnétique : rayon (nm) | Magnetic zone: radius (nm) | Magnetno območje: polmer (nm) |
| `settings.manual_wind_max_age_min` | Vent manuel périmé après (min) | Manual wind stale after (min) | Ročni veter zastari po (min) |
| `settings.routing_enabled` | Routage actif | Routing on | Izračun poti vklopljen |
| `settings.route_level` | Niveau de routage (banc Pi) | Routing level (Pi bench) | Raven izračuna poti (test Pi) |
| `settings.route_cadence_min` | Recalcul toutes les (min) | Recompute every (min) | Ponovni izračun vsakih (min) |
| `settings.tack_penalty_s` | Pénalité de virement (s) | Tack penalty (s) | Izguba pri obratu (s) |
| `settings.stay_extra_min` | On reste : marge (min) | Hold tack: margin (min) | Ostanemo: rezerva (min) |
| `settings.route_waves` | Vagues dans le routage | Waves in the routing | Valovi v izračunu poti |
| `settings.route_current` | Courant dans le routage | Current in the routing | Tok v izračunu poti |
| `settings.start_tack_s` | Départ : durée d'un virement (s) | Start: tack duration (s) | Start: trajanje obrata (s) |
| `settings.grib_wind_fallback` | Vent GRIB sans instruments | GRIB wind without instruments | Veter GRIB brez instrumentov |
| `settings.bias_enabled` | Correction du GRIB (biais) | GRIB correction (bias) | Popravek GRIB |
| `settings.bias_tau_decay_h` | Biais : décroissance (h) | Bias: decay (h) | Popravek: upadanje (h) |
| `settings.race_start_local` | Fenêtre météo : début | Weather window: start | Vremensko okno: začetek |
| `settings.race_end_local` | Fenêtre météo : fin | Weather window: end | Vremensko okno: konec |

## Settings help (Réglages ? buttons)

| key | fr | en (reference) | sl (to proofread) |
|---|---|---|---|
| `help.variation_deg` | Déclinaison magnétique de la zone : cap vrai = cap magnétique + déclinaison. Est positif, Ouest négatif (environ +4,5 à +5° E vers Šibenik en 2026). Source : rose du compas de la carte (corrigée de la variation annuelle) ou calculateur NOAA/WMM. Contrôle à quai (décalage compas à 0) : Diag navigation.heading + déclinaison = nav.heading.true, à 1° près. Sert aussi au vent manuel en °M et aux caps affichés en °M. | Magnetic variation of the area: true heading = magnetic heading + variation. East positive, West negative (about +4.5 to +5° E near Šibenik in 2026). Source: the chart's compass rose (corrected for the annual change) or the NOAA/WMM calculator. Dock check (compass offset at 0): Diag navigation.heading + variation = nav.heading.true, within 1°. Also used for manual wind in °M and headings shown in °M. | Magnetna deklinacija območja: prava smer = magnetna smer + deklinacija. Vzhod pozitivno, zahod negativno (okoli +4,5 do +5° E pri Šibeniku leta 2026). Vir: kompasna roža na karti (popravljena za letno spremembo) ali kalkulator NOAA/WMM. Preverjanje ob pomolu (popravek kompasa 0): Diag navigation.heading + deklinacija = nav.heading.true, na 1° natančno. Velja tudi za ročni veter v °M in smeri, prikazane v °M. |
| `help.heading_offset_deg` | Correction ajoutée au cap du compas B&G et aux directions B&G qui en dérivent (TWD instruments, courant), avant la déclinaison. Laisser 0 si l'écart reste sous 3°. Au moteur, eau calme sans courant, cap stable 2 min : comparer nav.heading.true (Diag) au COG GPS ; à quai, à l'orientation du ponton sur la carte. Nouvelle valeur = valeur actuelle + (référence − cap affiché). Ex. : 115° lu, COG 120° → +5. | Correction added to the B&G compass heading and to the B&G directions derived from it (instrument TWD, current), before the variation. Leave 0 if the error stays under 3°. Under engine, calm water, no current, steady heading 2 min: compare nav.heading.true (Diag) with GPS COG; at the dock, with the pontoon's bearing on the chart. New value = current value + (reference − displayed heading). E.g. 115° read, COG 120° → +5. | Popravek, prištet smeri kompasa B&G in smerem B&G, ki iz nje izhajajo (TWD instrumentov, tok), pred deklinacijo. Pusti 0, če je odstopanje pod 3°. Na motor, mirna voda brez toka, stalna smer 2 min: primerjaj nav.heading.true (Diag) s COG GPS; ob pomolu z usmeritvijo pomola na karti. Nova vrednost = trenutna vrednost + (referenca − prikazana smer). Npr.: odčitano 115°, COG 120° → +5. |
| `help.heading_ref_unknown` | Quand le bus B&G ne dit pas si un cap ou une direction est magnétique ou vrai (Diag : référence « ? » et une ligne bandg.layoutRecord), elle est traitée comme ceci. Pour choisir, au moteur : cap du bus + déclinaison ≈ COG → M ; cap du bus ≈ COG → T. Sans effet quand le bus donne la référence. | When the B&G bus does not say whether a heading or direction is magnetic or true (Diag: reference “?” and a bandg.layoutRecord line), it is taken as this. To choose, under engine: bus heading + variation ≈ COG → M; bus heading ≈ COG → T. No effect when the bus gives the reference. | Ko vodilo B&G ne pove, ali je smer magnetna ali prava (Diag: referenca „?“ in vrstica bandg.layoutRecord), se obravnava tako. Za izbiro, na motor: smer z vodila + deklinacija ≈ COG → M; smer z vodila ≈ COG → T. Brez učinka, ko vodilo poda referenco. |
| `help.heading_display` | Affichage seulement : les caps de la tablette en magnétique (°M, comme le compas et le B&G) ou en vrai (°T). Tous les calculs restent en vrai ; °M = vrai − déclinaison. | Display only: the tablet's headings in magnetic (°M, like the compass and the B&G) or true (°T). All computations stay in true; °M = true − variation. | Samo prikaz: smeri na tablici v magnetnih (°M, kot kompas in B&G) ali pravih stopinjah (°T). Vsi izračuni ostanejo v pravih; °M = prava − deklinacija. |
| `help.true_wind_source` | calculé : le Pi calcule le vent réel depuis AWA, AWS, BSP et le cap (dérive comprise). instruments : TWD/TWS du Hercules. Sous voiles, 5 min sur chaque bord : garder celui dont le TWD saute le moins d'un bord à l'autre (Diag). Si la source choisie manque, l'autre prend le relais. | computed: the Pi computes the true wind from AWA, AWS, BSP and the heading (leeway included). instruments: the Hercules TWD/TWS. Under sail, 5 min on each tack: keep the one whose TWD jumps least from one tack to the other (Diag). If the chosen source is missing, the other takes over. | izračunan: Pi izračuna pravi veter iz AWA, AWS, BSP in smeri (z zanosom). instrumenti: TWD/TWS iz Herculesa. Pod jadri 5 min na vsakem boku: obdrži tistega, katerega TWD najmanj skoči z boka na bok (Diag). Če izbrani vir manjka, ga nadomesti drugi. |
| `help.efficiency` | Multiplie les vitesses de la polaire (cibles, % polaire, lay-lines, routage) ; les angles ne changent pas. 0,92 = 92 % de la polaire. Mesure : plusieurs minutes de navigation régulière et bien réglée, lire le % polaire de la Barre ; nouvelle valeur = valeur actuelle × % / 100 (ex. 0,92 × 95 % → 0,87). | Multiplies the polar speeds (targets, polar %, laylines, routing); the angles do not change. 0.92 = 92% of the polar. Measure: several minutes of steady, well-trimmed sailing, read the polar % on the Helm tab; new value = current value × % / 100 (e.g. 0.92 × 95% → 0.87). | Pomnoži hitrosti polare (cilji, % polare, laylini, izračun poti); koti se ne spremenijo. 0,92 = 92 % polare. Merjenje: nekaj minut enakomerne, dobro trimane plovbe, odčitaj % polare na Krmilu; nova vrednost = trenutna vrednost × % / 100 (npr. 0,92 × 95 % → 0,87). |
| `help.efficiency_up` | Comme l'efficacité polaire, mais seulement au près. Vide = efficacité polaire. Même mesure, en lisant le % polaire au près uniquement. | Like the polar efficiency, but upwind only. Empty = polar efficiency. Same measure, reading the polar % upwind only. | Kot izkoristek polare, a samo v orcu. Prazno = izkoristek polare. Enako merjenje, z odčitkom % polare samo v orcu. |
| `help.efficiency_down` | Comme l'efficacité polaire, mais seulement au portant. Vide = efficacité polaire. Même mesure, en lisant le % polaire au portant uniquement. | Like the polar efficiency, but downwind only. Empty = polar efficiency. Same measure, reading the polar % downwind only. | Kot izkoristek polare, a samo v krmo. Prazno = izkoristek polare. Enako merjenje, z odčitkom % polare samo v krmo. |
| `help.heavy_wind_start_kn` | Vent réel (TWS) à partir duquel la polaire est réduite pour le vent fort. La réduction grandit ensuite jusqu'au seuil « réduction complète ». Elle s'applique aux cibles, au % polaire, aux lay-lines et au routage, avant l'efficacité. | True wind (TWS) from which the polar is reduced for heavy wind. The reduction then grows up to the “full reduction” threshold. It applies to the targets, the polar %, the laylines and the routing, before the efficiency. | Pravi veter (TWS), od katerega se polara zmanjša zaradi močnega vetra. Zmanjšanje nato raste do praga „polno zmanjšanje“. Velja za cilje, % polare, layline in izračun poti, pred izkoristkom. |
| `help.heavy_wind_full_kn` | TWS à partir duquel toute la réduction s'applique. Doit être plus grand que le début ; entre les deux, la réduction est progressive. | TWS from which the whole reduction applies. Must be higher than the start; in between, the reduction is gradual. | TWS, od katerega velja celotno zmanjšanje. Mora biti večji od začetka; vmes je zmanjšanje postopno. |
| `help.heavy_wind_reduction` | Part de vitesse retirée à la polaire au-delà du seuil complet : 0,05 = −5 %, 0 = désactivé. À augmenter si, par vent fort et bien réglé, le % polaire reste nettement sous 100. | Share of speed taken off the polar above the full threshold: 0.05 = −5%, 0 = off. Increase it if, in heavy wind and well trimmed, the polar % stays clearly under 100. | Delež hitrosti, odvzet polari nad polnim pragom: 0,05 = −5 %, 0 = izklopljeno. Povečaj, če ob močnem vetru in dobrem trimu % polare ostaja precej pod 100. |
| `help.layline_source` | polaire : angles de virement de la polaire (VMG). angles réels : angles vraiment tenus (route fond contre vent, médiane des 3 derniers bords d'au moins 2 min), courant et dérive compris ; badge ANGLES RÉELS. Un bord sans mesure garde la polaire ; rien n'est appris dans la zone Jabuka. Passer en angles réels après quelques virements si les lay-lines tombent mal. | polar: the polar's tacking angles (VMG). sailed angles: the angles actually held (course over ground vs wind, median of the last 3 legs of at least 2 min), current and leeway included; badge SAILED ANGLES. A tack with no measurement keeps the polar; nothing is learnt in the Jabuka zone. Switch to sailed angles after a few tacks if the laylines are off. | polara: koti obrata iz polare (VMG). dejanski koti: dejansko držani koti (smer nad dnom proti vetru, mediana zadnjih 3 bokov, dolgih vsaj 2 min), s tokom in zanosom; značka DEJANSKI KOTI. Bok brez meritve ohrani polaro; v območju Jabuka se nič ne nauči. Preklopi na dejanske kote po nekaj obratih, če laylini ne ustrezajo. |
| `help.use_current` | Ajoute aux lay-lines le courant mesuré par le B&G (set/drift) ; badge COURANT. Ignoré dans la zone Jabuka et quand les deux bords sont en angles réels (le courant y est déjà). Laisser désactivé tant que compas et loch ne sont pas vérifiés. | Adds the current measured by the B&G (set/drift) to the laylines; badge CURRENT. Ignored in the Jabuka zone and when both tacks use sailed angles (the current is already in them). Leave off until compass and log are checked. | Laylinom doda tok, ki ga meri B&G (set/drift); značka TOK. Prezrt v območju Jabuka in ko oba boka uporabljata dejanske kote (tok je že v njih). Pusti izklopljeno, dokler kompas in log nista preverjena. |
| `help.leeway_deg` | Angle dont le bateau glisse sous le vent. Sert seulement au vent réel calculé par le Pi (source calculé). Mesure : au près, eau sans courant, écart entre cap vrai et COG (Diag). Bien réglée, le TWD calculé saute moins à chaque virement. | Angle the boat slips to leeward. Used only for the true wind computed by the Pi (source computed). Measure: upwind, water without current, gap between true heading and COG (Diag). Well set, the computed TWD jumps less at each tack. | Kot, za katerega čoln drsi v zavetrje. Uporablja se samo za pravi veter, ki ga izračuna Pi (vir izračunan). Merjenje: v orcu, voda brez toka, razlika med pravo smerjo in COG (Diag). Ob dobri nastavitvi izračunani TWD ob vsakem obratu manj skoči. |
| `help.tau_helm_s` | Lissage du vent (TWD, TWS, TWA) affiché à la Barre : gros chiffre et écart LOFER/ABATTRE. Plus grand = chiffres plus calmes mais en retard sur les bascules ; plus petit = plus nerveux. Augmenter par mer formée si les chiffres sautent. | Smoothing of the wind (TWD, TWS, TWA) shown on the Helm tab: big number and HEAD UP/BEAR AWAY gap. Larger = calmer numbers but late on shifts; smaller = more jumpy. Increase in a rough sea if the numbers jump. | Glajenje vetra (TWD, TWS, TWA), prikazanega na Krmilu: velika številka in odmik ORCAJ/ODPADI. Večje = mirnejše številke, a z zamikom ob zasukih vetra; manjše = bolj nemirne. Povečaj ob razburkanem morju, če številke skačejo. |
| `help.tau_layline_s` | Lissage du TWD utilisé par les lay-lines. Plus grand = lay-lines stables mais lentes à suivre une bascule durable ; plus petit = elles bougent à chaque risée. | Smoothing of the TWD used by the laylines. Larger = steady laylines but slow to follow a lasting shift; smaller = they move with every gust. | Glajenje TWD, ki ga uporabljajo laylini. Večje = stabilni laylini, a počasni ob trajnem zasuku vetra; manjše = premikajo se ob vsakem sunku. |
| `help.zone_lat` | Latitude du centre de la zone d'anomalie magnétique (îlot de Jabuka par défaut), en degrés décimaux, pas en degrés-minutes. Dans le cercle, le compas n'est pas fiable : cap = COG GPS (au-dessus de 1 nd), direction et courant B&G ignorés, biais GRIB gelé ; alerte CAP NON FIABLE. | Latitude of the centre of the magnetic anomaly zone (Jabuka islet by default), in decimal degrees, not degrees-minutes. Inside the circle the compass is not trusted: heading = GPS COG (above 1 kn), B&G direction and current ignored, GRIB bias frozen; alert HEADING UNRELIABLE. | Zemljepisna širina središča območja magnetne anomalije (privzeto otoček Jabuka), v decimalnih stopinjah, ne v stopinjah in minutah. V krogu kompas ni zanesljiv: smer = COG GPS (nad 1 kn), smer in tok B&G prezrta, popravek GRIB zamrznjen; opozorilo SMER NI ZANESLJIVA. |
| `help.zone_lon` | Longitude Est du centre de la zone magnétique de Jabuka, en degrés décimaux (pas en degrés-minutes). Le défaut est l'îlot de Jabuka. | East longitude of the centre of the Jabuka magnetic zone, in decimal degrees (not degrees-minutes). The default is the Jabuka islet. | Vzhodna zemljepisna dolžina središča magnetnega območja Jabuka, v decimalnih stopinjah (ne v stopinjah in minutah). Privzeto je otoček Jabuka. |
| `help.zone_radius_nm` | Rayon du cercle où le compas est ignoré (cap = COG GPS, biais GRIB gelé, angles réels non appris). 0 = zone désactivée. Agrandir si le cap B&G part en vrille en approchant Jabuka avant d'entrer dans la zone. | Radius of the circle where the compass is ignored (heading = GPS COG, GRIB bias frozen, sailed angles not learnt). 0 = zone off. Enlarge it if the B&G heading goes wild approaching Jabuka before entering the zone. | Polmer kroga, v katerem je kompas prezrt (smer = COG GPS, popravek GRIB zamrznjen, dejanski koti se ne učijo). 0 = območje izklopljeno. Povečaj, če se smer B&G ob približevanju Jabuki zmeša, preden vstopiš v območje. |
| `help.manual_wind_max_age_min` | Âge au-delà duquel un vent manuel est périmé : badge PÉRIMÉ, cadre VENT PÉRIMÉ, chiffres grisés. Ressaisir alors le vent lu sur le B&G (panneau Vent manuel, plus haut). L'âge demande l'heure GPS ; sans elle il est inconnu. | Age after which a manual wind is stale: badge STALE, WIND STALE frame, greyed numbers. Then enter again the wind read on the B&G (Manual wind panel, above). The age needs GPS time; without it, it is unknown. | Starost, po kateri ročni veter zastari: značka ZASTARELO, okvir VETER ZASTAREL, sive številke. Takrat znova vnesi veter, odčitan na B&G (plošča Ročni veter, zgoraj). Starost potrebuje čas GPS; brez njega je neznana. |
| `help.routing_enabled` | Active le calcul de route sur le Pi. Décoché : plus de route, la Barre affiche les lay-lines et « Routage désactivé (Réglages) ». | Turns route computation on the Pi on. Unchecked: no route, the Helm tab shows the laylines and “Routing off (Settings)”. | Vklopi izračun poti na Pi. Izklopljeno: ni poti, Krmilo prikaže layline in „Izračun poti izklopljen (Nastavitve)“. |
| `help.route_level` | Finesse du routage : L0 = complet ; chaque niveau ajoute un allègement (L1 caps tous les 10°, L2 pas de temps plus longs, L3 marque suivante + une seule, L4 recalcul toutes les 10 min, L5 coût du « ne pas virer » un cycle sur deux). Mettre le NIVEAU RECOMMANDÉ du banc Pi ; monter d'un niveau si la route a souvent plus de 10 min ou si Diag montre des timeouts. | Routing detail: L0 = full; each level adds a lightening (L1 headings every 10°, L2 longer time steps, L3 next mark + one only, L4 recompute every 10 min, L5 cost of “not tacking” every other cycle). Set the Pi bench's NIVEAU RECOMMANDÉ (recommended level); go up one level if the route is often older than 10 min or if Diag shows timeouts. | Natančnost izračuna poti: L0 = polno; vsaka raven doda olajšavo (L1 smeri na 10°, L2 daljši časovni koraki, L3 naslednja boja + samo še ena, L4 ponovni izračun na 10 min, L5 cena „brez obrata“ vsak drugi cikel). Nastavi NIVEAU RECOMMANDÉ (priporočena raven) iz testa Pi; dvigni za eno raven, če je pot pogosto starejša od 10 min ali Diag kaže timeoute. |
| `help.route_cadence_min` | Temps entre deux calculs de route programmés. Plus court = route plus fraîche mais Pi plus chargé. Les niveaux L4 et L5 imposent au moins 10 min. Un changement de parcours ou une sortie de route relance aussi un calcul. | Time between two scheduled route computations. Shorter = fresher route but a busier Pi. Levels L4 and L5 impose at least 10 min. A course change or leaving the route also triggers a computation. | Čas med dvema načrtovanima izračunoma poti. Krajši = svežejša pot, a bolj obremenjen Pi. Ravni L4 in L5 zahtevata vsaj 10 min. Sprememba proge ali odhod s poti prav tako sproži izračun. |
| `help.tack_penalty_s` | Temps perdu à chaque virement ou empannage dans le routage, compté comme du temps sans avancer. Plus grand = route avec moins de virements. Repère : chronométrer du début du virement au retour à la vitesse cible ; la perte vaut à peu près la moitié de ce temps. Pas utilisé par le mode départ. | Time lost at each tack or gybe in the routing, counted as time without progress. Larger = route with fewer tacks. Guide: time from the start of the tack until back at target speed; the loss is about half of that. Not used by start mode. | Čas, izgubljen pri vsakem obratu ali križu v izračunu poti, štet kot čas brez napredovanja. Večje = pot z manj obrati. Napotek: izmeri čas od začetka obrata do vrnitve na ciljno hitrost; izguba je približno polovica tega časa. Način start je ne uporablja. |
| `help.stay_extra_min` | ON RESTE : le Pi recalcule en tenant le bord actuel jusqu'au virement conseillé plus cette marge, puis la route jusqu'à l'arrivée. Plus grand = on reste plus longtemps sur ce bord. | HOLD TACK: the Pi recomputes holding the current tack until the advised tack plus this margin, then the route to the finish. Larger = stay longer on this tack. | OSTANEMO: Pi ponovno izračuna z držanjem trenutnega boka do priporočenega obrata plus ta rezerva, nato pot do cilja. Večje = dlje ostanemo na tem boku. |
| `help.route_waves` | Le routage ralentit le bateau dans les vagues (au plus −30 %), selon la hauteur Hs du pack (EWAM), sinon estimée depuis le vent. Décocher pour router sans pénalité de vagues. | The routing slows the boat in waves (at most −30%), from the pack's wave height Hs (EWAM), otherwise estimated from the wind. Uncheck to route without a wave penalty. | Izračun poti upočasni čoln v valovih (največ −30 %), glede na višino valov Hs iz paketa (EWAM), sicer ocenjeno iz vetra. Izklopi za izračun brez kazni za valove. |
| `help.route_current` | Le routage ajoute le courant du pack de course (Copernicus) quand le pack en contient ; sans effet sinon. Différent de « Courant sur les lay-lines » (courant mesuré par le B&G). | The routing adds the race pack's current (Copernicus) when the pack has one; no effect otherwise. Different from “Current on the laylines” (current measured by the B&G). | Izračun poti doda tok iz paketa regate (Copernicus), ko ga paket vsebuje; sicer brez učinka. Drugače kot „Tok na laylinih“ (tok, ki ga meri B&G). |
| `help.start_tack_s` | Mode départ seulement : durée d'un virement ajoutée au temps « Autre bord » et à la zone de départ. Repère : chronométrer un virement serré, de la mise de barre au bateau stabilisé sur l'autre bord. Le routage utilise la « Pénalité de virement », pas ce réglage. | Start mode only: duration of a tack added to the “Other tack” time and to the start zone. Guide: time a tight tack, from putting the helm over to the boat settled on the other tack. The routing uses the “Tack penalty”, not this setting. | Samo način start: trajanje obrata, prišteto času „Drugi bok“ in startnemu območju. Napotek: izmeri tesen obrat, od zasuka krmila do čolna, umirjenega na drugem boku. Izračun poti uporablja „Izguba pri obratu“, ne te nastavitve. |
| `help.grib_wind_fallback` | Bus B&G muet et pas de vent manuel : le Pi prend le vent du GRIB du pack (corrigé du biais) à la position GPS ; cap = COG, vitesse = SOG ; badge GRIB. Sous 1 nd, pas de TWA ni de lay-lines. Décoché : PAS DE VENT à la place. | B&G bus silent and no manual wind: the Pi takes the wind from the pack's GRIB (bias-corrected) at the GPS position; heading = COG, speed = SOG; badge GRIB. Under 1 kn, no TWA and no laylines. Unchecked: NO WIND instead. | Vodilo B&G tiho in ni ročnega vetra: Pi vzame veter iz GRIB paketa (s popravkom) na položaju GPS; smer = COG, hitrost = SOG; značka GRIB. Pod 1 kn ni TWA ne laylinov. Izklopljeno: namesto tega NI VETRA. |
| `help.bias_enabled` | Le Pi compare le vent mesuré au GRIB (après environ 10 min de mesures stables) et corrige le GRIB du routage : direction + x°, force × k (ligne « Biais GRIB » de la Barre). Décocher si le biais paraît faux (capteur de vent déréglé) : la route suivante utilise le GRIB brut. | The Pi compares the measured wind with the GRIB (after about 10 min of steady measurements) and corrects the routing's GRIB: direction + x°, speed × k (“GRIB bias” line on the Helm tab). Uncheck if the bias looks wrong (wind sensor out of calibration): the next route uses the raw GRIB. | Pi primerja izmerjeni veter z GRIB (po približno 10 min stabilnih meritev) in popravi GRIB za izračun poti: smer + x°, moč × k (vrstica „Popravek GRIB“ na Krmilu). Izklopi, če se popravek zdi napačen (senzor vetra ni umerjen): naslednja pot uporabi surovi GRIB. |
| `help.bias_tau_decay_h` | Sans mesure fiable du vent, la correction du GRIB s'estompe avec ce temps caractéristique. Plus court = retour plus rapide au GRIB brut ; plus long = la correction apprise dure plus longtemps. | Without a reliable wind measurement, the GRIB correction fades with this time constant. Shorter = quicker return to the raw GRIB; longer = the learnt correction lasts longer. | Brez zanesljive meritve vetra popravek GRIB pojenja s to časovno konstanto. Krajše = hitrejša vrnitev na surovi GRIB; daljše = naučeni popravek traja dlje. |
| `help.race_start_local` | Début de la période que le pack météo doit couvrir, en heure locale de Croatie, au format AAAA-MM-JJTHH:MM. Si le pack ne couvre pas la fenêtre ou une marque : alerte MÉTÉO INCOMPLÈTE. Mettre un peu avant le départ (départ 20:00 → 18:00). | Start of the period the weather pack must cover, in Croatian local time, format YYYY-MM-DDTHH:MM. If the pack does not cover the window or a mark: alert WEATHER INCOMPLETE. Set it a bit before the start (start 20:00 → 18:00). | Začetek obdobja, ki ga mora pokriti vremenski paket, po lokalnem času Hrvaške, v obliki LLLL-MM-DDTHH:MM. Če paket ne pokrije okna ali boje: opozorilo VREME NEPOPOLNO. Nastavi malo pred startom (start 20:00 → 18:00). |
| `help.race_end_local` | Fin de la période que le pack météo doit couvrir (heure locale, AAAA-MM-JJTHH:MM), après le début. Mettre l'heure limite ou l'arrivée la plus tardive prévue. | End of the period the weather pack must cover (local time, YYYY-MM-DDTHH:MM), after the start. Set the time limit or the latest expected finish. | Konec obdobja, ki ga mora pokriti vremenski paket (lokalni čas, LLLL-MM-DDTHH:MM), po začetku. Nastavi časovno omejitev ali najkasnejši pričakovani prihod v cilj. |

## Lock

| key | fr | en (reference) | sl (to proofread) |
|---|---|---|---|
| `lock.lockAria` | Verrouiller l'écran | Lock the screen | Zakleni zaslon |
| `lock.unlockAria` | Appui 2 s puis relâcher pour déverrouiller | Hold 2 s then release to unlock | Pridrži 2 s in spusti za odklep |
| `lock.hint` | VERROUILLÉ · appui 2 s puis relâcher | LOCKED · hold 2 s, then release | ZAKLENJENO · pridrži 2 s, nato spusti |

## Diagnostics page

| key | fr | en (reference) | sl (to proofread) |
|---|---|---|---|
| `diag.title` | Diagnostics Jabuka | Jabuka diagnostics | Diagnostika Jabuka |
| `diag.back` | ← Barre | ← Helm | ← Krmilo |
| `diag.connecting` | connexion… | connecting… | povezovanje… |
| `diag.connected` | connecté | connected | povezano |
| `diag.live` | en direct | live | v živo |
| `diag.noDataFor` | pas de données depuis {s} s | no data for {s}s | ni podatkov {s} s |
| `diag.reconnecting` | reconnexion dans {s} s | reconnecting in {s}s | ponovna povezava čez {s} s |
| `diag.labelPh` | libellé (optionnel) | label (optional) | oznaka (neobvezno) |
| `diag.eventBtn` | Marqueur d'événement | Event marker | Oznaka dogodka |
| `diag.markerLogged` | Marqueur n° {n} enregistré à {time}{z} | Marker #{n} logged at {time}{z} | Oznaka št. {n} zapisana ob {time}{z} |
| `diag.localClock` |  (horloge locale) |  (local clock) |  (lokalna ura) |
| `diag.tooFast` | Non enregistré : trop rapide (1 par seconde au plus) | Not logged: too fast (max 1 per second) | Ni zapisano: prehitro (največ 1 na sekundo) |
| `diag.tooLong` | Non enregistré : libellé trop long (200 caractères au plus) | Not logged: label too long (max 200 characters) | Ni zapisano: oznaka predolga (največ 200 znakov) |
| `diag.diskFull` | NON ENREGISTRÉ : le journal des événements ne peut pas être écrit (disque plein ?) | NOT LOGGED: the event log cannot be written (disk full?) | NI ZAPISANO: dnevnika dogodkov ni mogoče pisati (disk poln?) |
| `diag.httpFail` | Non enregistré : HTTP {s} | Not logged: HTTP {s} | Ni zapisano: HTTP {s} |
| `diag.fail` | Non enregistré : {e} | Not logged: {e} | Ni zapisano: {e} |
| `diag.gate` | routage : {g} | routing: {g} | izračun poti: {g} |
| `diag.gateInitial` | routage : bloqué | routing: blocked | izračun poti: blokiran |
| `diag.values` | Valeurs | Values | Vrednosti |
| `diag.health` | Santé | Health | Stanje |
| `diag.core` | Cœur | Core | Jedro |
| `diag.colPath` | chemin | path | pot |
| `diag.colSi` | valeur (SI) | value (SI) | vrednost (SI) |
| `diag.colDisplay` | affichage | display | prikaz |
| `diag.colUnit` | unité | unit | enota |
| `diag.colSrc` | src | src | vir |
| `diag.colRef` | réf | ref | ref |
| `diag.colCh` | ch | ch | ch |
| `diag.colDisp` | disp | disp | disp |
| `diag.colAge` | âge s | age s | starost s |
| `diag.alive` | actif | alive | deluje |
| `diag.silent` | muet | silent | tiho |
| `diag.noData` | pas de données | no data | ni podatkov |
| `diag.diskLow` | espace disque sous la réserve | disk space below the reserve | prostor na disku pod rezervo |
| `diag.diskPruning` | suppression d'anciens journaux pour libérer le disque | deleting old logs to free disk space | brisanje starih dnevnikov za sprostitev diska |
| `diag.diskError` | rétention en échec : {e} | retention failed: {e} | čiščenje ni uspelo: {e} |
| `diag.diskOther` | disque {s} | disk {s} | disk {s} |
| `diag.coreDisk` | Cœur : {what} ({free} libres) | Core: {what} ({free} free) | Jedro: {what} ({free} prosto) |
| `diag.rawFloor` | Cœur : historique brut des 36 h supprimé ({n} fichiers) | Core: raw history inside the 36 h floor was deleted ({n} files) | Jedro: surova zgodovina znotraj 36 h meje izbrisana ({n} datotek) |
| `diag.srcDisk` | {src} : disque {state} ({free} libres) | {src}: disk {state} ({free} free) | {src}: disk {state} ({free} prosto) |
| `diag.errCore` | Cœur : {text} ({n} depuis le démarrage) | Core: {text} ({n} since start) | Jedro: {text} ({n} od zagona) |
| `diag.errSrc` | {src} : {text} ({n} depuis le démarrage) | {src}: {text} ({n} since start) | {src}: {text} ({n} od zagona) |
| `diag.err.derived_errors` | écriture du journal dérivé en échec | derived log write failed | zapis izpeljanega dnevnika ni uspel |
| `diag.err.bus_log_errors` | écriture du journal bus en échec | bus log write failed | zapis dnevnika vodila ni uspel |
| `diag.err.events_errors` | écriture du journal d'événements en échec | event log write failed | zapis dnevnika dogodkov ni uspel |
| `diag.err.flush_errors` | vidage des journaux en échec | log flush failed | praznjenje dnevnikov ni uspelo |
| `diag.err.handler_errors` | traitement d'un message en échec | message handler failed | obdelava sporočila ni uspela |
| `diag.err.nav_errors` | calcul nav en échec | nav computation failed | navigacijski izračun ni uspel |
| `diag.err.raw_errors` | écriture du journal brut en échec | raw log write failed | zapis surovega dnevnika ni uspel |
| `diag.err.send_errors` | envoi UDP vers le cœur en échec | UDP send to the core failed | pošiljanje UDP jedru ni uspelo |

## Start mode (Départ)

| key | fr | en (reference) | sl (to proofread) |
|---|---|---|---|
| `start.open` | DÉPART | START | START |
| `start.title` | Départ | Start | Start |
| `start.go` | 5:00 | 5:00 | 5:00 |
| `start.sync` | SYNC | SYNC | SYNC |
| `start.stop` | STOP | STOP | STOP |
| `start.close` | Fermer le départ | Close start | Zapri start |
| `start.pingCommittee` | Ping comité | Ping committee | Ping ladja odbora |
| `start.pingPin` | Ping bouée | Ping pin | Ping boja |
| `start.committee` | Comité | Committee | Ladja odbora |
| `start.pin` | Bouée | Pin | Boja |
| `start.type` | Saisir | Type | Vnesi |
| `start.formTitle` | {end} : coordonnées | {end}: coordinates | {end}: koordinate |
| `start.srcPing` | ping | ping | ping |
| `start.srcTyped` | saisie | typed | vneseno |
| `start.endUnset` | non défini | not set | ni določeno |
| `start.timerOff` | Chrono arrêté | Timer stopped | Štoparica ustavljena |
| `start.waitClock` | Chrono : en attente de l'heure GPS | Timer: waiting for GPS time | Štoparica: čakam na čas GPS |
| `start.restoredBak` | Ligne restaurée depuis la sauvegarde : vérifier | Line restored from the backup: check it | Črta obnovljena iz varnostne kopije: preveri |
| `start.unreadable` | Ligne de départ illisible : à refaire | Start line unreadable: set it again | Startna črta neberljiva: določi znova |
| `start.error` | Mode départ indisponible | Start mode unavailable | Način start ni na voljo |
| `start.noGps` | Pas de position GPS | No GPS position | Ni položaja GPS |
| `start.noTimer` | Pas de chrono en cours | No timer running | Štoparica ne teče |
| `start.writeFailed` | Écriture impossible | Write failed | Zapis ni mogoč |
| `start.lineInfo` | Ligne {d} · {h} | Line {d} · {h} | Črta {d} · {h} |
| `start.now` | Ligne au cap | Line on heading | Črta po smeri |
| `start.other` | Autre bord | Other tack | Drugi bok |
| `start.timeMargin` | {t} · marge {m} | {t} · margin {m} | {t} · rezerva {m} |
| `start.offLine` | hors ligne | off the line | mimo črte |
| `start.tackNow` | VIREZ POUR LA LIGNE | TACK FOR THE LINE | OBRNI ZA ČRTO |
| `start.rNoLine` | Ligne incomplète | Line incomplete | Črta nepopolna |
| `start.rNoPosition` | Pas de position GPS | No GPS position | Ni položaja GPS |
| `start.rNoHeading` | Cap inconnu | Heading unknown | Smer neznana |
| `start.rNoWind` | Pas de vent | No wind | Ni vetra |
| `start.rCalc` | Erreur de calcul du départ | Start computation error | Napaka izračuna starta |

## Alerts and reasons from the core (translated on the tablet)

| key | fr | en (reference) | sl (to proofread) |
|---|---|---|---|
| `srv.noWind` | PAS DE VENT | NO WIND | NI VETRA |
| `srv.navFailed` | Erreur de calcul nav | Nav computation error | Napaka navigacijskega izračuna |
| `srv.gribWind` | VENT GRIB (pas d'instruments) | GRIB WIND (no instruments) | VETER GRIB (brez instrumentov) |
| `srv.capZone` | CAP NON FIABLE (zone Jabuka) | HEADING UNRELIABLE (Jabuka zone) | SMER NI ZANESLJIVA (območje Jabuka) |
| `srv.twaCheck` | Écart TWA calculé/B&G > 10° | Computed/B&G TWA differ > 10° | Razlika TWA izračun/B&G > 10° |
| `srv.settingsUnreadable` | Réglages illisibles : valeurs par défaut | Settings unreadable: defaults used | Nastavitve neberljive: privzete vrednosti |
| `srv.manualUnreadable` | Vent manuel illisible : ignoré | Manual wind unreadable: ignored | Ročni veter neberljiv: prezrt |
| `srv.settingsFromBak` | Réglages restaurés depuis la sauvegarde : vérifier les réglages | Settings restored from backup: check them | Nastavitve obnovljene iz varnostne kopije: preveri nastavitve |
| `srv.manualFromBak` | Vent manuel restauré depuis la sauvegarde : vérifier le vent | Manual wind restored from backup: check it | Ročni veter obnovljen iz varnostne kopije: preveri veter |
| `srv.courseUnreadable` | Parcours illisible : Parcours A par défaut | Course unreadable: Course A used | Proga neberljiva: privzeta proga A |
| `srv.courseFromBak` | Parcours restauré depuis la sauvegarde : vérifier la marque active | Course restored from backup: check the active mark | Proga obnovljena iz varnostne kopije: preveri aktivno bojo |
| `srv.courseWrite` | Écriture du parcours impossible | Cannot write the course | Proge ni mogoče zapisati |
| `srv.routeRestore` | Route sauvegardée illisible : ignorée | Saved route unreadable: ignored | Shranjena pot neberljiva: prezrta |
| `srv.packChanged` | PACK DE COURSE MODIFIÉ : redémarrer jabuka-core | RACE PACK CHANGED: restart jabuka-core | PAKET REGATE SPREMENJEN: znova zaženi jabuka-core |
| `srv.manualOld` | Vent manuel ancien (> {n} min) | Manual wind old (> {n} min) | Ročni veter star (> {n} min) |
| `srv.routeInvalid` | ROUTE INVALIDE : {r} | INVALID ROUTE: {r} | NEVELJAVNA POT: {r} |
| `srv.routerRestarted` | ROUTEUR RELANCÉ : {r} | ROUTER RESTARTED: {r} | IZRAČUN POTI ZNOVA ZAGNAN: {r} |
| `srv.weatherIncomplete` | MÉTÉO INCOMPLÈTE : {r} | WEATHER INCOMPLETE: {r} | VREME NEPOPOLNO: {r} |
| `srv.nextMark` | Marque suivante : {name} | Next mark: {name} | Naslednja boja: {name} |
| `srv.finish` | ARRIVÉE — {name} | FINISH — {name} | CILJ — {name} |
| `srv.rDisabled` | routage désactivé (Réglages) | routing off (Settings) | izračun poti izklopljen (Nastavitve) |
| `srv.rClock` | heure GPS non valide | GPS time not valid | čas GPS ni veljaven |
| `srv.rNoCourse` | plus de marque à rejoindre | no mark left to sail to | ni več boje za plovbo |
| `srv.rNoPosition` | pas de position GPS | no GPS position | ni položaja GPS |
| `srv.rNotLoaded` | pack de course non chargé | race pack not loaded | paket regate ni naložen |
| `srv.rStayNoTack` | amure inconnue : On reste impossible | unknown tack: cannot hold tack | neznan bok: ostanemo ni mogoče |
| `srv.rOutCourse` | parcours modifié : recalcul en cours | course changed: recomputing | proga spremenjena: ponovni izračun |
| `srv.rOutCourseWhy` | parcours modifié : {r} | course changed: {r} | proga spremenjena: {r} |
| `srv.rOutMissed` | virement manqué : nouvelle route impossible | missed tack: no new route | zamujen obrat: nove poti ni |
| `srv.rOutMissedWhy` | virement manqué : nouvelle route impossible ({r}) | missed tack: no new route ({r}) | zamujen obrat: nove poti ni ({r}) |
| `srv.rOutAge` | route périmée | route outdated | pot zastarela |
| `srv.rOutAgeWhy` | route périmée ({n} min) : {r} | route outdated ({n} min): {r} | pot zastarela ({n} min): {r} |
| `srv.rOutFail` | le routeur échoue | the router keeps failing | izračun poti ne uspeva |
| `srv.rOutFailWhy` | le routeur échoue : {r} | the router keeps failing: {r} | izračun poti ne uspeva: {r} |
| `srv.rOutRestored` | route sauvegardée : vérification en cours | saved route: being checked | shranjena pot: preverjanje |
| `srv.rOutClock` | heure GPS revenue en arrière : recalcul en cours | GPS time stepped back: recomputing | čas GPS se je vrnil nazaj: ponovni izračun |
| `srv.rNoPackDir` | pas de dossier de pack | no pack folder | ni mape paketa |
| `srv.rPackUnreadable` | pack illisible | pack unreadable | paket neberljiv |
| `srv.rNoWind` | vent absent | no wind | ni vetra |
| `srv.rNoWindFile` | fichier vent absent | wind file missing | datoteka vetra manjka |
| `srv.rNoLandmask` | landmask.npz absent du pack {dir} | landmask.npz missing from pack {dir} | landmask.npz manjka v paketu {dir} |
| `srv.rNotValidated` | route non validée | route not validated | pot ni potrjena |
| `srv.rRoutingFailed` | échec du routage | routing failed | izračun poti ni uspel |
| `srv.rRouterError` | erreur du routeur | router error | napaka izračuna poti |
| `srv.rLand` | route invalide (terre) | route invalid (land) | pot neveljavna (kopno) |
| `srv.rFrontBlocked` | aucune expansion valide (front bloqué par la terre) | no valid expansion (front blocked by land) | ni veljavne razširitve (fronto blokira kopno) |
| `srv.rNoMark` | aucune marque à rallier | no mark to sail to | ni boje za plovbo |
| `srv.rRecomputing` | recalcul en cours | recomputing | ponovni izračun |
| `srv.rRestartedWhy` | routeur relancé : {r} | router restarted: {r} | izračun poti znova zagnan: {r} |
| `srv.rEngineError` | erreur du moteur ({x}) | engine error ({x}) | napaka pogona ({x}) |
| `srv.rEngineStuck` | calcul bloqué depuis plus de {n} s | computation stuck for more than {n} s | izračun obtičal več kot {n} s |
| `srv.rEngineCreate` | création du moteur impossible ({x}) | cannot start the engine ({x}) | pogona ni mogoče zagnati ({x}) |
| `srv.rTooManySteps` | trop d'étapes (> {n}) sans atteindre la marque | too many steps (> {n}) without reaching the mark | preveč korakov (> {n}) brez dosega boje |
| `srv.rNotInit` | routeur non initialisé (init_worker non appelé) | router not initialised (init_worker not called) | izračun poti ni inicializiran (init_worker ni klican) |
| `srv.rNotInitWhy` | routeur non initialisé : {x} | router not initialised: {x} | izračun poti ni inicializiran: {x} |
| `srv.rPackChangedWorker` | pack de course modifié depuis le démarrage du cœur : redémarrer jabuka-core | race pack changed since the core started: restart jabuka-core | paket regate spremenjen od zagona jedra: znova zaženi jabuka-core |
| `srv.rPackChangedSince` | pack de course modifié depuis le démarrage du cœur | race pack changed since the core started | paket regate spremenjen od zagona jedra |
| `srv.rBadRequest` | requête invalide : {x} | invalid request: {x} | neveljavna zahteva: {x} |
| `srv.rBadPosition` | requête invalide : position hors limites | invalid request: position out of range | neveljavna zahteva: položaj izven meja |
| `srv.rBadMark` | marque invalide : {x} | invalid mark: {x} | neveljavna boja: {x} |
| `srv.rBadSide` | côté invalide pour {name} : {x} | invalid side for {name}: {x} | neveljavna stran za {name}: {x} |
| `srv.rBadSettings` | réglages invalides : {x} | invalid settings: {x} | neveljavne nastavitve: {x} |
| `srv.rTargetOnLand` | cible dans la terre, aucune eau libre à {n} nm : {name} | target on land, no open water within {n} nm: {name} | cilj na kopnem, ni proste vode v {n} nm: {name} |
| `srv.rCannotRound` | impossible de contourner {name} : aucun point en eau libre à moins de {n} nm au relèvement {b}° | cannot round {name}: no open-water point within {n} nm at bearing {b}° | obplutje {name} ni mogoče: ni točke v prosti vodi v {n} nm pri smeri {b}° |
| `srv.rStartOnLand` | départ dans la terre : aucune eau libre à {n} nm | start on land: no open water within {n} nm | start na kopnem: ni proste vode v {n} nm |
| `srv.wCheckImpossible` | contrôle impossible ({x}) | check impossible ({x}) | preverjanje ni mogoče ({x}) |
| `srv.wNoUsableWind` | pas de vent utilisable ({r}) | no usable wind ({r}) | ni uporabnega vetra ({r}) |
| `srv.wHoles` | vent sans valeur sur {n} cellules de la zone de course (le routeur y verrait du calme : refaire le pack) | wind missing in {n} cells of the race area (the router would see calm there: rebuild the pack) | veter manjka v {n} celicah regatnega območja (izračun bi tam videl brezvetrje: ponovno pripravi paket) |
| `srv.wFrom` | vent à partir du {from} seulement, début requis {need} | wind only from {from}, start needed {need} | veter šele od {from}, potreben začetek {need} |
| `srv.wUntil` | vent jusqu'au {until} seulement, fin requise {need} | wind only until {until}, end needed {need} | veter le do {until}, potreben konec {need} |
| `srv.wAt` | vent {why} à {name} {pos} | wind {why} at {name} {pos} | veter {why} pri {name} {pos} |
| `srv.wLeg` | vent {why} sur le bord {name} {pos} | wind {why} on the leg {name} {pos} | veter {why} na odseku {name} {pos} |
| `srv.wOutside` | hors de la zone couverte | outside the covered area | izven pokritega območja |
| `srv.wNaN` | valeurs manquantes (NaN) | missing values (NaN) | manjkajoče vrednosti (NaN) |
