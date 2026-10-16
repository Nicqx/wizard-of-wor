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
