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
| `settings.grib_wind_fallback` | Vent GRIB sans instruments | GRIB wind without instruments | Veter GRIB brez instrumentov |
| `settings.bias_enabled` | Correction du GRIB (biais) | GRIB correction (bias) | Popravek GRIB |
| `settings.bias_tau_decay_h` | Biais : décroissance (h) | Bias: decay (h) | Popravek: upadanje (h) |
| `settings.race_start_local` | Fenêtre météo : début | Weather window: start | Vremensko okno: začetek |
| `settings.race_end_local` | Fenêtre météo : fin | Weather window: end | Vremensko okno: konec |

## Lock

| key | fr | en (reference) | sl (to proofread) |
|---|---|---|---|
| `lock.lockAria` | Verrouiller l'écran | Lock the screen | Zakleni zaslon |
| `lock.unlockAria` | Appui 2 s pour déverrouiller | Hold 2 s to unlock | Pridrži 2 s za odklep |
| `lock.hint` | VERROUILLÉ · appui 2 s | LOCKED · hold 2 s | ZAKLENJENO · pridrži 2 s |

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
| `srv.courseUnreadable` | Parcours illisible : Parcours A par défaut | Course unreadable: Course A used | Proga neberljiva: privzeta proga A |
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
| `srv.rOutMissed` | virement manqué : nouvelle route impossible | missed tack: no new route | zamujen obrat: nove poti ni |
| `srv.rOutMissedWhy` | virement manqué : nouvelle route impossible ({r}) | missed tack: no new route ({r}) | zamujen obrat: nove poti ni ({r}) |
| `srv.rOutAge` | route périmée | route outdated | pot zastarela |
| `srv.rOutAgeWhy` | route périmée ({n} min) : {r} | route outdated ({n} min): {r} | pot zastarela ({n} min): {r} |
| `srv.rOutFail` | le routeur échoue | the router keeps failing | izračun poti ne uspeva |
| `srv.rOutFailWhy` | le routeur échoue : {r} | the router keeps failing: {r} | izračun poti ne uspeva: {r} |
| `srv.rOutRestored` | route sauvegardée : vérification en cours | saved route: being checked | shranjena pot: preverjanje |
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
