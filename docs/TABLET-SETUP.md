# Tablet setup — Réglage de la tablette (helm)

Checklist for the Android tablet at the helm. Do it once at the dock with the Pi powered
(`deploy/PI-SETUP.md`), then check it again on the night before the start. Everything here is
offline: the tablet only talks to the Pi.

## 1. Join the boat network — Rejoindre le réseau

1. On the tablet, forget other Wi-Fi networks and turn mobile data off.
2. Join the Wi-Fi network **`jabuka`** (WPA2, passphrase from `deploy/secrets.env`).
3. Open Chrome at **`http://10.42.0.1`** (port 80: no `:8080` on the boat).
   The helm page opens on the **Barre** tab. Diagnostics are on the **Diag** tab
   (or `http://10.42.0.1/diag.html`).

## 2. Chrome flag for the screen lock — Drapeau Chrome (indispensable)

Wake Lock (keeping the screen on) only works on a "secure" origin. The Pi serves plain HTTP, so
Chrome must be told to treat exactly that origin as secure:

1. Open `chrome://flags/#unsafely-treat-insecure-origin-as-secure`.
2. Set it to **Enabled** and type exactly **`http://10.42.0.1`** in the text box
   (scheme + address, no port, no trailing slash: the flag needs the exact origin, Pitfall 1).
   For development against a laptop, add it after a comma: `http://10.42.0.1,http://<laptop-ip>:8080`.
3. Tap **Relaunch**.
4. Open `http://10.42.0.1`, tap the screen once, and check the top-bar badge reads
   **`ÉCRAN: verrou`**.
   - `ÉCRAN: vidéo`: the flag is not active (wrong origin, or Chrome not relaunched). The page
     falls back to a muted looping video, which usually keeps the screen on; fix the flag anyway.
   - `ÉCRAN: aucun` (shown as an alert): nothing holds the screen (request refused, battery
     saver). Tap the screen again; if it stays, rely on step 3 and recheck the flag.

The flag only names the Pi's own address on a WPA2 network with no internet; Wake Lock is the
only feature the page uses with it.

## 3. Keep the screen on — Écran toujours allumé

1. Settings → About tablet → tap **Build number** 7 times to enable Developer options.
2. Settings → Developer options → **Stay awake** (stay awake while charging): ON.
3. Keep the tablet **on charge** for the whole race (the screen lock is lost if the battery
   saver starts).
4. Settings → Display → Screen timeout: the longest value (belt and braces).
5. Turn off battery optimisation for Chrome (Settings → Apps → Chrome → Battery → Unrestricted).
6. Test: leave the helm view untouched for 30 min on charge; the screen must never sleep.

## 4. Full screen — Plein écran

- Chrome menu → **Add to Home screen**, then open the helm from that icon.
- Switching to night mode also asks Chrome for full screen, which hides the Android status bar
  (its white icons are the last light leak at night). If a system bar comes back, tap
  "Nuit" twice or swipe it away.
- Turn off "auto-rotate" if the tablet mount makes the screen flip; the helm works in landscape
  and portrait.

## 5. Map check (WebGL) — Vérifier la carte

1. Open `chrome://gpu` and check **WebGL: Hardware accelerated** (or at least "Software only,
   hardware acceleration unavailable" without "Disabled").
2. Open the helm: the sea, coast, course, marks, laylines and seamarks are drawn over the
   offline map.
3. If the badge **`CARTE INDISPONIBLE`** shows, the tablet has no usable WebGL: the numbers,
   countdown and badges still work, only the map is missing (a Leaflet fallback is deferred).
   Use the numbers; report the tablet model.

## 6. Night mode — Mode nuit

- Button **`☾ Nuit`** in the top bar: true black background, red only (map, overlays, numbers,
  buttons). **`Jour`** goes back to the day theme. The choice is remembered by this tablet.
- In night mode a **brightness slider** (40–100 %) appears next to the button: it dims every red.
  Also lower the Android brightness to the lowest level that stays readable at arm's length.
- Check in a dark room: no white or green light anywhere (map, controls, banner, status bar).

## 7. Map orientation — Orientation de la carte

- **Nord en haut**: north up (default). **Cap en haut**: the map turns with the boat heading
  (COG when there is no compass heading). **Centrer**: the map follows the boat (zooms in once
  when switched on). All three are remembered by this tablet and only act on the Barre tab.

## 8. Lock mode in spray and rain — Verrouillage

- Tap the **padlock** (top right) before spray, rain or a crowded cockpit: the whole screen
  stops reacting (tabs, map, buttons, pinch, wheel) while the numbers keep updating.
- To unlock, **press and hold the padlock for 2 seconds** (a ring fills up). A short tap, a
  second finger or water on the screen never unlocks.
- The lock is remembered across a reload or a Chrome restart.

## 9. Badges — Signification des badges

| Badge | Meaning |
|---|---|
| `LIVE` | True wind computed from the boat instruments, fresh |
| `LIVE B&G` | True wind taken from the B&G (Hercules) TWD/TWS |
| `MANUEL 12 min` | Wind typed in by hand, 12 min ago |
| `PÉRIMÉ` | The wind in use is too old: treat targets and laylines with suspicion |
| `PAS DE VENT` | No wind at all: no targets, no laylines |
| `CAP NON FIABLE` | Heading not trusted (e.g. the magnetic anomaly near Jabuka): cross-check with COG |
| `COURANT` | Laylines include the current |
| `ANGLES RÉELS` | Laylines use the tacking angles actually sailed, not the polar |
| `PERTE DONNÉES` | No data from the Pi for 3 s: every number is greyed, do not trust them |
| `ÉCRAN: verrou` / `vidéo` / `aucun` | What keeps the screen on (see section 2) |
| `CARTE INDISPONIBLE` | No WebGL: numbers only (see section 5) |

On the Barre view the numbers sit in a column on the left third of the screen in landscape, with
the map on the right two thirds (the boat is centred there). In portrait they sit in one area at
the top, with the map below. The column has three blocks:
1. **Steering.** The big number is the **target TWA** upwind (↑) or downwind (↓), or the
   **course to steer** (°M) on a reach, then the tack. Under it is the deviation with
   **LOFER / ABATTRE** (or **◄ BÂBORD / TRIBORD ►** on a course to steer).
2. **Route and tack.** The tack/gybe countdown, then one line each for the cost of not tacking,
   the route state, the route age, the route heading and the GRIB bias, then the **ON RESTE**
   button.
3. **The rest.** BSP / target, % polar, the next mark with distance and time, its bearing and the
   heading on the other tack. This block scrolls if the screen is short.

## 10. Remote debugging — Débogage à distance

1. Developer options → **USB debugging**: ON; connect the tablet to the laptop by USB.
2. On the laptop, open `chrome://inspect/#devices` in Chrome/Chromium and click **inspect**
   under the helm page: console errors, network and WebSocket frames, and a live screen copy.
3. Typical checks: `window.jabuka.lastNav` (last nav message), `window.jabuka.map`
   (the MapLibre map), `localStorage` keys `jabuka.theme`, `jabuka.brightness`,
   `jabuka.mapMode`, `jabuka.centred`, `jabuka.locked`.

## Night-before checklist — Check-list de la veille

- [ ] `ÉCRAN: verrou` after one tap on `http://10.42.0.1`
- [ ] Stay awake while charging ON, tablet on charge, battery optimisation off for Chrome
- [ ] Map drawn (no `CARTE INDISPONIBLE`), course and marks visible
- [ ] Night mode readable at the lowest usable brightness, no white/green light
- [ ] Lock: water on the screen changes nothing; 2 s press unlocks
