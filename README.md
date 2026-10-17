# Wizard of Wor – C64 játékszoba

Az eredeti Commodore 64 játékkép központi emulációja a NUC-on, két független böngészős kontrollerrel. A játékot egy sessionhöz tartozó **egyetlen** VICE Libretro emulátorfolyamat futtatja; két böngésző ugyanazt a képet és SID-hangot kapja. Az inputok (öt gomb / játékos) a szerverre érkeznek.

## Állapot: integrációs prototípus

- Megvalósítva: ötjegyű szobák, egy host / egy vendég, JWT helyett véletlen 256 bites szobatoken, WebSocket kép/hang/vezérlés, 25 Hz JPEG-képek, eredeti C64 audio PCM, mobil joystick és tűz, desktop nyilak + Space, rövid TTL, per-session izolált VICE worker, rate limit, alap HTTP/API tesztek, docker és k3s manifest.
- Még ellenőrizendő: VICE core valódi Docker-buildje, a feltöltött D64 játékindulása és két joystick portja, SID-hang Firefox/Android böngészőben, 2 eszközös késleltetés és WAN-sávszélesség, mobil landscape.
- Ez még **nem teljesen igazolt, kész játék**. Az éles ingress/landing integrációt csak sikeres helyi E2E után szabad alkalmazni.

A ROM/D64 fájlt **nem terjesztjük** a nyilvános GitHubon. A régi játékok is szerzői jogvédelem alatt állhatnak; a letölthetőség / „abandonware” nem automatikus nyilvános terjesztési engedély. A játékosok saját, jogszerűen használt lemezképpel telepítsék a szolgáltatást.

### A megadott D64 ellenőrzése

Az ismert, feltöltött `Wizard of Wor.d64` 174 848 bájtos szabványos D64 lemezkép. A könyvtárban `WIZ.O.WOR+3H/REM`, `W.O.W.SCORES/REM` és `WIZOFWAR` nevű fájlok vannak. Az első egy módosított traineres változat; induláskor ellenőrizni kell, hogy a játékmenet automatikusan elindul-e, vagy a második fájlt kell kifejezetten kiválasztani. A worker jelenleg a teljes D64-et automatikusan indítja.

## Telepítés a NUC-ra – első próba (még ingress nélkül)

A forráskódot az alábbi PR fejlesztői ágából szerezd be, ne a jelenlegi üres `main`-ből.

```bash
cd ~/codes
git clone https://github.com/Nicqx/wizard-of-wor.git
cd wizard-of-wor
git switch feat/server-c64-mvp
mkdir -p local-roms
```

Másold be saját `Wizard of Wor.d64` fájlodat `local-roms/game.d64` néven. Például Windowsról SCP/SFTP-vel (vagy helyileg `cp '/elérési/út/Wizard of Wor.d64' local-roms/game.d64`). Ezt a fájlt **ne commitold**.

A Docker-próbához:

```bash
docker compose build
docker compose up -d
docker compose logs -f --tail=100
curl -fsS http://127.0.0.1:8107/healthz
```

A konténer a NUC-on kizárólag `127.0.0.1:8107`-en publikál; az internetről addig nem érhető el. SSH tunnellel nyisd meg:

```bash
ssh -L 8107:127.0.0.1:8107 nicqx@nuc
```

Ezután böngészőben: `http://127.0.0.1:8107/wizard-of-wor/`. A második böngészőt egy későbbi, TLS-es ingress-integráció után érdemes kipróbálni.

Leállítás:

```bash
docker compose down
```

### K3s – elkülönített telepítés

A script előzetes ellenőrzése (nem módosít semmit):

```bash
bash scripts/update.sh --dry-run
```

Sikeres Docker/ROM teszt után, manuális jóváhagyással:

```bash
bash scripts/update.sh --apply
```

Ez a NUC-on helyben Dockerrel építi a képet, importálja a k3s/containerd `k8s.io` namespace-be, létrehozza/frissíti a `wizard-of-wor-game` Secretet a helyi D64-ből, majd csak a `wizard-of-wor` Deploymentet és Service-t telepíti. Nem módosít más játékot vagy ingresseket. A régi Deployment/Service YAML-mentése `~/.local/state/nicqx-infra/nuc/wizard-of-wor/` alatt készül, ha már léteztek. A Kubernetes Secret-et **nem** exportáljuk a backupba.

A `k8s/deployment.yaml` önmagában a GHCR `main` képet tartalmazza, de a helyi telepítő ezt egy egyedi helyi image tagre cseréli. A GHCR image csak a PR merge után épül/publikálódik, és lehet, hogy külön publikusra kell állítani a csomag jogosultságát.

**Nincs még ingress útvonal**. A `/wizard-of-wor` útvonalat majd a `Nicqx/ingress` projektben, a szolgáltatás igazolt működése után kell felvenni; a `Nicqx/landing` oldalt ugyanakkor frissítjük. A Traefik WebSocket támogatása megfelelő; első körben nincs szükség új UDP/portforward szabályra.

### Teszt és fejlesztés

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest -q
```

Az emulátor futtatásához kompatibilis `vice_x64_libretro.so` is szükséges. Enélkül az API és a kontrollerteszt futtatható, de a játék nem.

Az audio 16 bites, sztereó PCM a WebSocketen; a böngésző WebAudio API-ja játssza le, a sample rate a Libretro core-tól érkezik. A képernyő 25 fps JPEG (alap VICE PAL 50 fps képkockákból), a játék maga körülbelül 50 fps-sel fut. Ez a WebSocket/PCM MVP később cserélhető WebRTC/Opus/Vp8-ra, ha a sávszélesség vagy késleltetés indokolja.

A session maximum egy óra, mindkét játékos távozása után 5 perc inaktivitásnál automatikusan záródik. Böngészőfrissítés után ugyanabban a tabban a token `sessionStorage`-ban marad, így a játékos visszaléphet. Második vendéget a rendszer nem enged be.

### Biztonság / korlátok

- A GitHub nem tárol játékképet; a konténer read-only filesystemmel, root nélkül, cap-drop-pal indul.
- A szobakód **nem jogosultsági token**; azonosításhoz külön kriptográfiai token kell. A játékszobák memóriában vannak, a publikus csatlakozások IP-szintű limitet kapnak.
- A jelenlegi kód **egyetlen backend replika** mellett helyes. Több replika Redis és sticky routing nélkül nem támogatott.
- 4 session maximum; terhelésméréssel hangoljuk. A JPEG + PCM nem Opus/WebRTC, ezért a WAN valódi throughputját tesztelni kell.
- Ez az integrációs prototípus nem ígér biztosan hibátlan eredeti C64 game playt a hardveres telepítési próba előtt.

## Licenc / upstream

Emulációs core: [libretro/vice-libretro](https://github.com/libretro/vice-libretro), a VICE és a Libretro licencei szerint. A játék eredeti eszközei és jogai nem tartoznak ide. A projekt saját részei GPL-3.0-or-later licenccel készülnek, hogy az emulációs komponens licencével kompatibilisek legyenek.

## Hibaelhárítás – HEALTHCHECK 503

A szolgáltatás HTTP-szervere **futhat** akkor is, ha a telepített játékkép hiányzik. A `/healthz` válasz `checks.game_d64` és `checks.vice_core` mezői jelzik, melyik komponens hibás. Például `"game_d64":"missing"` esetén nincs vagy nem fájl a csatolt `/games/game.d64`. Ha `"invalid_size"`, a fájl nem ismert D64-méretű. **A healthz zöld állapota még nem bizonyítja, hogy a játék ténylegesen betöltődött.**

Ellenőrzés a NUC-on:

```bash
cd ~/codes/wizard-of-wor
ls -ld local-roms/game.d64
file local-roms/game.d64
docker compose exec wizard-of-wor ls -l /games/game.d64 /opt/vice/vice_x64_libretro.so
curl -i http://127.0.0.1:8107/healthz
```

Ha a `local-roms/game.d64` könyvtár (korábbi rövid Docker-volume szintaxis automatikusan létrehozhatta), **csak akkor** töröld `rmdir local-roms/game.d64` paranccsal, ha üres. Ez nem töröl valódi lemezképet. Másold oda a saját `.d64` fájlodat, majd `docker compose up -d --force-recreate`. Az új Compose konfiguráció `create_host_path: false` beállítással már nem hoz létre látszólagos fájlt hiányzó csatoláskor.

## C64 billentyűzet / RUN-STOP (2026-10)

A képernyő feletti **RUN/STOP** gyorsgomb mindig elérhető. A **⌨ Billentyűzet** gombbal megjeleníthető egy érintésérzékeny C64-kiosztás, majd ugyanitt elrejthető. A panel alapállapotban rejtve van; mobilon az érintőgombok, PC-n a fizikai billentyűzet is használható. A joystick ettől függetlenül változatlanul működik.

- C64 `RUN/STOP` = PC `Esc` (Libretro `RETROK_ESCAPE=27`).
- C64 `RETURN` = `Enter`, `DEL` = `Backspace`, `RESTORE` = `PageUp`.
- A teljesebb panel betűket, számokat, Shift/C=/Ctrl billentyűket, kurzornyilakat és F1/F3/F5/F7-et tartalmaz.
- **Ha a panel csukva van**, a PC nyilak és a Space továbbra is a játékos joystickját kezelik. **Ha nyitva van**, a PC billentyűzet a C64 billentyűzetét vezérli (a képernyős joystick ekkor is aktív).
- A billentyűlenyomás és -felengedés a WebSocketen külön esemény. A worker legalább két emulált képkockáig nyomva tartja a nagyon rövid érintéseket is. Kilépés, kapcsolatvesztés és fókuszvesztés során automatikus felengedés történik.
- Két játékos esetén mindkét résztvevő ugyanazt a virtuális C64-billentyűzetet használja; az azonos gombot párhuzamosan lenyomó játékosok nem tudják egymás gombját idő előtt felengedni.

A módosítás **nem** települ automatikusan a futó NUC-ra. Helyi frissítés (az eredeti lemezkép megtartásával):

```bash
cd ~/codes/wizard-of-wor
git pull --ff-only
bash scripts/update.sh --dry-run
bash scripts/update.sh --apply
```

Végül töltsd újra a `https://pmqxyz.hopto.org/wizard-of-wor/` oldalt.

## Billentyűzet KB2 – jól látható, önálló panel

A C64-billentyűzet most egy külön `web/assets/c64-keyboard.js` komponens, más C64-játékokhoz is újrahasználható. A játékszoba képernyője felett nagyméretű **⌨ Billentyűzet megnyitása** gomb van; mellette közvetlen RUN/STOP. Telefonon felnyíló, vízszintesen is görgethető panelen, asztali gépen egérrel/kattintással lehet a Commodore 64 billentyűit használni. Bezárás: **✕ Bezárás**, vagy a sötét háttér megnyomása. A játék közben a NUC-on fut tovább. A zárt panel nem változtat a játék nyíl/Space vezérlésén.

A címlapon és a játékszobában megjelenő `C64 UI KB2` marker, továbbá a `/wizard-of-wor/api/version` végpont segít ellenőrizni, hogy valóban az új felület van-e telepítve. A statikus HTML/CSS/JS válaszok már cache-elés nélkül érkeznek, az asset URL-eket `?v=kb2` is védi a régi böngészőcache-től.

**Ha nem látszik a gomb, először a helyi git ágat ellenőrizd** — a csak `git pull` parancs az aktuális branchből frissít, és lehetséges, hogy ez még mindig `main`:

```bash
cd ~/codes/wizard-of-wor
git fetch origin
git switch feat/server-c64-mvp
git pull --ff-only
grep -n 'C64 UI KB2' web/index.html
bash scripts/update.sh --dry-run
bash scripts/update.sh --apply
```

A telepítő ellenőrzi a `KB2` forrását az indítás előtt, majd a ténylegesen elindult k3s konténerben is. Frissítéskor az aktív szobák újraindulnak. A távoli ellenőrzés:

```bash
curl -fsS https://pmqxyz.hopto.org/wizard-of-wor/api/version
```

A válaszban `"ui":"KB2"` jelenik meg, ha a megfelelő verzió fut. Két egymást követő böngészőfrissítésre nincs szükség; az oldal normál újratöltése elegendő.

## Teljesítmény és fekete képernyő – KB3 diagnosztika (2026-10-17)

A Worker most **2 másodpercenként valós képkockaszámból mér**: `fps` / `target_fps` (kb. 50 PAL), tényleges JPEG FPS, a teljes médiafolyam bitrátája, processzor-munkaidő becsült aránya, a C64 képének átlagos fényereje (`luma`, 0–255), valamint a 16×16-ra kicsinyített képen észlelt változások száma. A szerver játékosonként **12 elemű, eldobással szabályozott média-sort** használ: WAN akadozásakor a régi kép/hang csomagokat ejti, nem blokkolhatja a VICE stdout feldolgozását. A böngésző a megérkező FPS-t, kirajzolt FPS-t, mért WebSocket adatátvitelt, képdekódolási időt, ping-pong RTT-t és régi képkockák számát mutatja. A **Mérés másolása** gombbal a teljes egy soros diagnosztika kimásolható.

Értelmezés 5–10 másodperccel a játék indítása után:

- **NUC C64 ≈ 50/50 FPS, bejövő ≈ 25 és kirajzolt ≈ 25 FPS**: az emuláció és a képfolyam időzítése jó. Ha a kép mégis sötét, nézd meg a fényerőt és a változások számát; egy 0/255 és 0 változás a valóban sötét/stagnáló *emulált* képet valószínűsíti, nem a WAN eltűnt képkockáit.
- **NUC C64 jóval 50 alatt**: CPU/VICE betöltési vagy emulációs lassulás a NUC-on; a hálózat önmagában nem magyarázza ezt.
- **NUC ≈ 50, de beérkezett FPS alacsony vagy eldobott csomagok száma nő**: hálózat/WebSocket útvonal torlódása. **Megérkezett FPS ≈ 25, de kirajzolt FPS alacsony**: böngészős dekódolás/megjelenítés.
- **RTT** a WebSocket ping-pong oda-vissza ideje, *nem* teljes joystick→C64→kép reakcióidő. A bitráta a böngészőben ténylegesen beérkezett adat, nem becslés.
- Az automatikus GitHub Actions alapteszt **nullázott próbalemezt** használ, ezért nem igazolja a teljes Wizard of Wor játékmenetét. Ezzel az emulátor 50,6/50,1 FPS, 25,3 JPEG FPS és kb. 2255 kbit/s streamet adott a tesztkörnyezetben. **A NUC valódi sebességét a futó játék mérése mutatja.**

A 48 kHz-es, 16 bites, kétcsatornás tömörítetlen PCM-hang önmagában **1536 kbit/s** játékosonként. A JPEG képek erre jönnek rá, ezért a WebSocketes alapváltozat WAN-adatforgalma jóval nagyobb, mint magának egy 1983-as játékgépnek a joystick-adata; a méréstől függően később érdemes Opus/WebRTC hang-/videokódolásra áttérni.

Mobil landscape (rövid képernyő): **játék képernyője felül, TŰZ bal alsó sarokban, joystick jobb alsó sarokban**. A billentyűzet opcionális és az egész képernyő aljáról nyílik fel. Külön RUN/STOP gyorsgomb nincs, csak a billentyűzeten.

Frissítés (az aktív sessionök megszakadnak):

```bash
cd ~/codes/wizard-of-wor
git fetch origin
git switch feat/server-c64-mvp
git pull --ff-only
bash scripts/update.sh --dry-run
bash scripts/update.sh --apply
curl -fsS https://pmqxyz.hopto.org/wizard-of-wor/api/version
```

Az utolsó kérés `{"ui":"KB3","keyboard":"bottom-sheet"}` JSON-t ad, ha az új NUC-verzió fut. Az első játéknál várj a betöltésre, és másold ki a mérést. A `/healthz` még mindig csak az alkalmazás- és fájlhozzáférést mutatja.

## KB4: teljesen üres videó + 0 kbit/s / nincs RTT

A `C64: — FPS | átvett: 0.0 FPS | RTT: —` **nem nulla emulátor-FPS**, hanem WebSocket-adatfolyam hiánya. A KB4 javításai:

- A korábbi, már nem létező memória-szoba `sessionStorage` tokenje többé nem hagy örökre sötét képet. Sikertelen WebSocket-azonosítás vagy kapcsolatvesztés után a lobby jelenik meg, egyértelmű hibával, és új szoba indítható.
- Ugyanazzal a tokennel a frissen megnyitott WebSocket átveszi a régi kapcsolat helyét (oldalfrissítéskor lehetséges versenyhelyzet).
- A TLS mögötti Traefik eredeti originjét a konfigurált `PUBLIC_ORIGIN=https://pmqxyz.hopto.org` is engedélyezi, miközben a nem engedélyezett origin marad 403.
- A diagnosztikai sor tartalmazza a kapcsolat állapotát, megszakadáskor az alacsony szintű WebSocket zárókódot. A szerver naplózza az elfogadott/elutasított socketet, **titkos token nélkül**.
- CI Docker-integrációs teszt tényleges HTTP POST szobát hoz létre, WebSocketen hitelesít, és ellenőrzi a képkockát, FPS-statisztikát és RTT-t (`server.smoke_stream`).

### Frissítés és elkülönítő vizsgálat a NUC-on

```bash
cd ~/codes/wizard-of-wor
git fetch origin
git switch feat/server-c64-mvp
git pull --ff-only
bash scripts/update.sh --dry-run
bash scripts/update.sh --apply

curl -fsS https://pmqxyz.hopto.org/wizard-of-wor/api/version
# "ui": "KB4" kell

# Valódi NUC-pod, valódi szerver, ideiglenes tesztszoba (jogosult D64):
kubectl -n default exec deployment/wizard-of-wor -c wizard -- python -m server.smoke_stream
# Ennek végén: HTTP+WebSocket C64 streaming E2E: PASS

# Ha a publikus útvonalon továbbra sincs kapcsolat:
kubectl -n default logs deployment/wizard-of-wor --since=5m --tail=120 |
    grep -Ei 'WebSocket|Room|emulator|error|warning|GET /wizard-of-wor'
```

A publikus tesztnél **új szobát** indíts a `https://pmqxyz.hopto.org/wizard-of-wor/` nyitóoldaláról. Régi, lejárt `/wizard-of-wor/12345` címmel nem lehetséges az előző emulátorhoz visszatérni. A k3s Deployment frissítése megszakítja az aktív szobákat. Ha a helyi `smoke_stream` PASS, de a publikus WebSocket továbbra sem, az ingress/WAN/Origin útvonalat kell vizsgálni; ha a helyi teszt sem PASS, akkor a NUC-emuláció vagy a szerveroldali kapcsolódás hibás.

## KB5: helyes C64 joystickport Wizard of Wor egy- és kétjátékos módban

A Wizard of Wor eredeti C64-kézikönyve szerint **1 játékos = joystick az 1-es fizikai portban; 2 játékos = mindkét port, és a 2-es port FIRE gombja választja ki a kétjátékos módot a kezdőképernyőn**. A korábbi VICE-beállítás tévesen `vice_joyport=2` volt: az első böngészős játékos ezért a C64 **2. játékosának** gombját nyomta, és ezzel a játék kétjátékos módot indított még vendég nélkül is.

Most a `VICE_PRIMARY_JOYPORT=1` beállítást használjuk. A VICE két RetroPad portot így térképez:
- **Böngészős 1. játékos (szobagazda) → RetroPad 0 → fizikai C64 joystickport 1.** FIRE ebből a portból indítja az egyjátékos módot.
- **Böngészős 2. játékos (vendég) → RetroPad 1 → fizikai C64 joystickport 2.** A kétjátékos indításhoz a második játékos **a kezdőképernyőn** nyomjon FIRE-t. Futó egyjátékos menetre a második játékos utólagos csatlakozása nem feltétlenül váltja a C64-játék módját.
- A nem csatlakozott játékos joystickja **minden képkockában 0**; hiába maradt korábbi állapot a szerver memóriájában.
- A WebSocket `welcome` most `c64_joystick_port` mezőt ad, így a játékos neve mellett a kijelölt port is megjelenik.
- Más C64-játékhoz a `VICE_PRIMARY_JOYPORT=2` is használható; szigorúan csak `1` vagy `2` elfogadott.

Teszt: `tests/test_joystick.py` ellenőrzi mindkét portrendelést, a vendég nélküli nulla bemenetet és a lecsatlakozást; a `tests/test_websocket.py` ellenőrzi mindkét játékos portját, a Docker `server.smoke_worker` és `server.smoke_stream` pedig az induló VICE-portot és a tényleges WebSocket `welcome` mezőt.

```bash
cd ~/codes/wizard-of-wor
git fetch origin
git switch feat/server-c64-mvp
git pull --ff-only
bash scripts/update.sh --dry-run
bash scripts/update.sh --apply
curl -fsS https://pmqxyz.hopto.org/wizard-of-wor/api/version
# {"ui":"KB5","keyboard":"bottom-sheet"}
```

**A k3s újraindítása a meglévő szobákat törli.** A játékot mindkét módban **új szobából**, a megfelelő játékos tűzgombjával indítsd. Ha a ROM/trainer saját menüje felülírja a standard vezérlést, a játék képernyőjén ellenőrizni kell a tényleges módválasztást. A tesztlemezképes CI önmagában nem tudja ezt a konkrét programváltozatot végigjátszani.


## KB6: folyamatos SID-zene távoli WebSocketen (2026-10-17)

A `KB5`-ös változatban 12 csomagos, típusfüggetlen médiapuffer torlódáskor régi audio-adatokat is eldobott. Már egyetlen hiányzó 20 ms-os, 48 kHz-es sztereó PCM-blokk is hiányzó dallamrészt és recsegést okozhatott. A böngésző WebAudio-kódja ezen felül `audioTime`-ot újraindított, ha a lejátszási sor több mint 400 ms-ra nőtt, ami idővonal-átfedést okozhatott.

A **KB6** ezért:
- Egy játékosonként legfeljebb 32 elemű sort használ. Torlódásnál **először régi JPEG-képkockákat ejt**, a legfrissebb képpel helyettesítve őket. A hangmintákat eredeti sorrendben megőrzi. Csak akkor veszít hangot, ha a kapcsolat már kizárólag hangcsomagokkal is túlterhelt.
- Külön számlálja a kieső *hang* és *kép* csomagokat; a játék alatti diagnosztikában ezek mellett az audio aláfutások és az aktuális hangpuffer hossza is látható.
- A böngésző `audio-stream.js` modulja kb. 220–230 ms-os, WAN-jittert elnyelő előtöltést használ. **Nem tekeri vissza** a már ütemezett hang idővonalát, hanem ±2,5% korlátú finom ütemezési korrekciót alkalmaz a kis órajel-eltérésekhez.
- A WebSocket végponttól végpontig futó konténerteszt a JPEG és az FPS mellett a PCM-blokkokat és azok összes sztereó mintáját is ellenőrzi; a GitHub Actions eredménye 102 PCM-csomag, 97 664 sztereó minta ~2 másodperc alatt.
- A képtovábbítás, az emulátor verziója, a C64 joystickportok, a mobilos elrendezés és a billentyűzet változatlan.

**Telepítés csak a NUC Wizard-konténerére (a régi szobák megszakadnak):**

```bash
cd ~/codes/wizard-of-wor
git fetch origin
git switch feat/server-c64-mvp
git pull --ff-only
bash scripts/update.sh --dry-run
bash scripts/update.sh --apply
curl -fsS https://pmqxyz.hopto.org/wizard-of-wor/api/version
# várt: "ui":"KB6"
```

Ellenőrzés: nyiss új szobát, hallgasd meg a zenét legalább 30–60 másodpercig. A `Mérés másolása` sorában a `hang: 0` szerveroldali audio-vesztés és kevés/nem növekvő `hangkihagyás` a jó jel. Ha a zene továbbra is hiányos, oszd meg a mérés sorát: hangvesztés nélkül a böngésző/hangeszköz pufferét, növekvő `hang` veszteségnél a WAN sávszélességet kell vizsgálni. Az audio továbbra is tömörítetlen 48 kHz sztereó PCM, ~1,54 Mbit/s/játékos, így lassabb uplinkeknél később Opus/WebRTC kodek lehet indokolt.
