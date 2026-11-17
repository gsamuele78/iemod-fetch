# Guida al test reale (Linux, giochi GOG o Steam)

Questa guida serve a provare iemod-fetch 4.1.0 su una macchina vera, con i
giochi veri, su **Debian trixie**, **Ubuntu 24.04 LTS e successive**,
**Bazzite** e **CachyOS**. È scritta per chi ha i giochi da **GOG** o da
**Steam**. Alla fine dice cosa raccogliere e come spedirlo.

Tre cose da sapere prima:

- **Si lavora sempre su copie dei giochi**, mai sulla cartella che Steam,
  GOG Galaxy o Heroic aggiornano: un aggiornamento o una "verifica dei file"
  annullerebbe l'installazione senza dirlo. La procedura guidata fa anche un
  backup, ma una copia pulita resta il punto da cui ricominciare.
- **Quello che non è ancora misurato è scritto come tale.** Le librerie di
  sistema di Qt per ogni distribuzione sono misurate dalla CI (PR #118) sui
  container di Debian, Ubuntu, Fedora e Arch; quello che resta da misurare è
  indicato al suo posto.
- **Limite noto:** mod_installer 16.0.0 mostra solo le domande che contengono
  certe parole ("enter", "choose", "do you want"...). Dalla versione
  successiva alla 4.1.0 la procedura guidata gli passa una configurazione con
  i testi delle domande note (ADR-0057); con la 4.1.0 una domanda senza
  queste parole ferma ancora WeiDU fino al timeout di 3 ore. In entrambi i
  casi il watchdog dopo 10 minuti lo dice nell'output: se succede, annota
  quale mod era, è uno dei dati che servono.

---

## 1. Cosa serve

| | |
|---|---|
| Giochi | **Baldur's Gate: Enhanced Edition** con **Siege of Dragonspear** (obbligatorio per EET) e **Baldur's Gate II: Enhanced Edition**, versione Linux nativa o Windows |
| Spazio | circa **30 GB liberi** sul disco dove lavori (due copie dei giochi, i backup, le mod scaricate, l'installazione) |
| Rete | per scaricare le mod da GitHub e dagli altri siti |
| Tempo | test piccolo: 15-30 minuti; EET completo: ore |

Cartelle usate in tutta la guida (cambiale se vuoi, ma tienile uguali dall'inizio
alla fine):

```bash
mkdir -p ~/iemod-test/{games,project,report}
```

---

## 2. Procurarsi i giochi

### 2a. Da GOG

Scegli **una** delle tre strade.

- **Installer Linux dal sito GOG** (la più semplice): dalla tua libreria su
  gog.com, per ciascun gioco scarica l'installer Linux (`.sh`) e la DLC
  Siege of Dragonspear. Installa in `~/GOG Games/...` (il default), poi copia
  (passo 3).
- **Heroic Games Launcher** (Flatpak, già presente o installabile su Bazzite e
  CachyOS): accedi a GOG in Heroic, installa i due giochi (scegli la versione
  Linux quando c'è). Di solito finiscono in `~/Games/Heroic/`.
- **lgogdownloader** (riga di comando, open source): utile se non hai un
  desktop. `lgogdownloader --login`, poi `--list` e `--download --game ...`.

### 2b. Da Steam

Installa Baldur's Gate: Enhanced Edition (con la DLC Siege of Dragonspear) e
Baldur's Gate II: Enhanced Edition. Steam scarica la versione Linux nativa.
Le cartelle sono:

| Steam | Percorso |
|---|---|
| nativo (Debian, Ubuntu, CachyOS, **Bazzite**) | `~/.local/share/Steam/steamapps/common/` |
| Flatpak | `~/.var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/common/` |

Nelle Proprietà di ogni gioco imposta gli aggiornamenti su "solo quando lo
avvio", così Steam non tocca le copie mentre provi.

> **Avvia ogni gioco una volta** prima di copiarlo (fino al menu, poi esci):
> crea le sue cartelle di impostazioni.

---

## 3. Le copie su cui si lavora

```bash
cd ~/iemod-test/games
# adatta i percorsi di origine a dove li hai installati (passo 2)
cp -a "<cartella di BG:EE>"  bgee
cp -a "<cartella di BG2:EE>" bg2ee
ls bgee/chitin.key bg2ee/chitin.key     # devono esistere entrambi
```

La cartella giusta è quella che contiene `chitin.key`. Con l'installer Linux
di GOG il gioco sta nella sottocartella `game/` (per esempio
`~/GOG Games/Baldur's Gate II Enhanced Edition/game`): copia quella, non la
cartella sopra.

Per EET la cartella `bg2ee` diventa il gioco EET; `bgee` resta la sorgente.

### Nomi in minuscolo: da misurare, non da dare per scontato

Le guide storiche di WeiDU su Linux dicono di portare in minuscolo i nomi dei
file del gioco con lo strumento `tolower`. Sta nello zip di WeiDU per Linux,
ma la procedura guidata tiene solo il programma `weidu` e scarta il resto,
quindi `tolower` va preso a mano (passo 2 qui sotto). Sulle Enhanced Edition questo può
però rinominare anche il programma del gioco (`BaldursGate` →
`baldursgate`) e rompere l'avvio da GOG o Steam. Quindi:

1. **Giro A senza `tolower`.** Se l'installazione va e il gioco parte, non
   serve: annotalo, è un dato prezioso.
2. **Solo se WeiDU si lamenta di file che non trova** (righe con "not found"
   o "cannot open" nell'output), ripeti da copie nuove lanciando `tolower`
   dentro ciascuna copia (rispondi sì alle sue domande), e annota se il gioco
   parte ancora:
   ```bash
   mkdir -p ~/iemod-test/weidu-zip && cd ~/iemod-test/weidu-zip
   curl -LO https://github.com/WeiDUorg/weidu/releases/download/v251.00/WeiDU-Linux-251.zip
   echo "3e1a34ec5d6e934b1d4a34541a1312d0170b120c6efe903a732415acde3bd3c0  WeiDU-Linux-251.zip" | sha256sum --check
   unzip -o WeiDU-Linux-251.zip WeiDU-Linux/tolower
   cd ~/iemod-test/games/bgee  && ~/iemod-test/weidu-zip/WeiDU-Linux/tolower
   cd ~/iemod-test/games/bg2ee && ~/iemod-test/weidu-zip/WeiDU-Linux/tolower
   ```
   (La somma è la stessa che la procedura guidata controlla per questo zip.)

---

## 4. Preparare il sistema

La procedura guidata contiene già Python, mod_installer e quasi tutte le
librerie di Qt. Al sistema servono solo: il **driver grafico** (EGL/GL), le
librerie **xcb** per la finestra su X11 o XWayland (solo con lo zip 4.1.0) e
gli strumenti per aprire archivi RAR e 7z (circa metà delle mod li usa).

Gli elenchi qui sotto sono **misurati in CI su container puliti** di ogni
distribuzione (PR #131, run 43965747309, con il conteggio corretto: le
librerie che il bundle porta già contano come presenti). Un desktop
installato ne ha già la maggior parte, e `apt`/`dnf`/`pacman` salteranno
quelli presenti.

- **Con l'AppImage o lo zip della prossima release** (ADR-0060): le librerie
  xcb sono già dentro; servono solo il driver grafico e gli strumenti per gli
  archivi (la prima e l'ultima riga dei comandi qui sotto).
- **Con lo zip 4.1.0**: servono anche le librerie xcb (la riga in mezzo) per
  la finestra su X11/XWayland, e `wayland-cursor` per Wayland nativo.

### Debian trixie

```bash
sudo apt update
sudo apt install unzip libarchive-tools unar libegl1 libgl1
# solo con lo zip 4.1.0:
sudo apt install libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
  libxcb-render-util0 libxcb-shape0 libxcb-util1 libxcb-xkb1 \
  libxkbcommon-x11-0 libwayland-cursor0
```

### Ubuntu 24.04 LTS e successive

Identico a Debian (misurato su 24.04 e 26.04):

```bash
sudo apt update
sudo apt install unzip libarchive-tools unar libegl1 libgl1
# solo con lo zip 4.1.0:
sudo apt install libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
  libxcb-render-util0 libxcb-shape0 libxcb-util1 libxcb-xkb1 \
  libxkbcommon-x11-0 libwayland-cursor0
```

Ubuntu 22.04 e Debian 12 **non sono supportati**: lo zip è costruito per
Debian trixie e successivi (glibc più recente) e lì molto probabilmente non
parte.

### Bazzite (Fedora Atomic)

**Con l'AppImage** (passo 5) la procedura guidata parte direttamente sul
sistema, che ha già il driver grafico. Gli strumenti per gli archivi però li
cerca **sul sistema dove gira** (`archives.py` non ne include di propri): se
sono installati solo in un contenitore Distrobox, l'AppImage avviata fuori
non li vede e le mod in RAR/7z falliscono. Controlla sul sistema:

```bash
command -v unzip bsdtar unar 7z      # annota quali mancano
```

Se manca `unar` (basta da solo per RAR e 7z), una di queste vie, **non
misurate**:
- `brew install unar` (Homebrew è previsto su Bazzite);
- `rpm-ostree install unar bsdtar`, poi riavvia;
- oppure fai girare anche l'AppImage **dentro** Distrobox, come lo zip qui
  sotto.

**Con lo zip 4.1.0**, la strada pulita è un contenitore **Distrobox**, già
presente in Bazzite, che condivide la tua cartella home e quindi vede i giochi
e le copie; la procedura guidata gira dentro il contenitore insieme agli
strumenti:

```bash
distrobox create --name iemod --image fedora:latest
distrobox enter iemod
sudo dnf install unzip bsdtar unar libglvnd-egl libglvnd-glx
# solo con lo zip 4.1.0:
sudo dnf install xcb-util-cursor xcb-util-wm xcb-util-image xcb-util-keysyms \
  xcb-util-renderutil xcb-util libxkbcommon-x11 libwayland-cursor
```

oppure, con un'immagine Ubuntu, i comandi di Ubuntu qui sopra dopo
`distrobox create --name iemod --image ubuntu:24.04` e `distrobox enter iemod`.

Con lo zip, tutti i passi da qui in poi si fanno **dentro** `distrobox enter
iemod`. La finestra della procedura guidata appare sul tuo desktop
normalmente.

### CachyOS (Arch)

```bash
sudo pacman -S --needed unzip libarchive unarchiver libglvnd
# solo con lo zip 4.1.0:
sudo pacman -S --needed xcb-util-cursor xcb-util-wm xcb-util-image xcb-util-keysyms \
  xcb-util-renderutil xcb-util libxkbcommon-x11
```

(`unarchiver` fornisce `unar`, `libarchive` fornisce `bsdtar`. Le librerie di
Qt sono misurate; i nomi di `unar` e `bsdtar` per Fedora e Arch no.)

Non misurato: una finestra davvero disegnata su un display reale. La
completezza di `ldd` è la misura di riferimento.

---

## 5. Scaricare e verificare iemod-fetch 4.1.0

**Da quando la release lo contiene, la via principale su Linux è l'AppImage**
(ADR-0060): un solo file, niente da estrarre, e le librerie di Qt sono già
dentro. Il sistema deve fornire solo il driver grafico (EGL/GL), che ogni
desktop ha già (misurato sullo zip, che contiene la stessa cartella). Scarica `iemod-fetch-gui-linux-x86_64.AppImage` e
`SHA256SUMS`:

```bash
cd ~/iemod-test
sha256sum --check --ignore-missing SHA256SUMS      # deve dire OK
chmod +x iemod-fetch-gui-linux-x86_64.AppImage
./iemod-fetch-gui-linux-x86_64.AppImage --version
./iemod-fetch-gui-linux-x86_64.AppImage --check    # apre la finestra e la chiude
```

- **FUSE.** L'AppImage si monta con FUSE: Bazzite, Steam Deck, CachyOS e
  Ubuntu desktop ce l'hanno. Se dice `fusermount` / "Cannot mount AppImage",
  avvialo così (si estrae in una cartella temporanea, è un po' più lento):
  `./iemod-fetch-gui-linux-x86_64.AppImage --appimage-extract-and-run --check`.
- **Bazzite (Fedora Atomic).** L'AppImage parte **direttamente sul sistema**,
  senza Distrobox: è il caso principale da provare. Gli strumenti per gli
  archivi devono essere sul sistema stesso (passo 4, Bazzite): `command -v
  bsdtar unar 7z` prima di iniziare.
- Nessuna voce di menu viene creata da sola. Se la vuoi, usa Gear Lever (da
  Flathub, se non c'è già) o AppImageLauncher.
- Copia l'output intero di `--check` se fallisce, e indica se hai usato
  `--appimage-extract-and-run`.

**Con lo zip** (la 4.1.0 ha solo questo, e resta disponibile): dalla pagina della release
<https://github.com/gsamuele78/iemod-fetch/releases/tag/v4.1.0> scarica
`iemod-fetch-gui-linux-x86_64.zip` e `SHA256SUMS`.

```bash
cd ~/iemod-test
sha256sum --check --ignore-missing SHA256SUMS      # deve dire OK
unzip iemod-fetch-gui-linux-x86_64.zip -d gui
./gui/iemod-fetch-gui/iemod-fetch-gui --version    # 4.1.0
./gui/iemod-fetch-gui/iemod-fetch-gui --check      # apre la finestra e la chiude
```

Se hai il comando `gh`, puoi anche verificare da chi è stato costruito:
`gh attestation verify iemod-fetch-gui-linux-x86_64.zip --repo gsamuele78/iemod-fetch`.

Se `--check` fallisce con "could not load the Qt platform plugin xcb" o una
libreria mancante, copia il messaggio intero: ricontrolla il passo 4 per la tua
distribuzione; su Wayland puoi provare anche
`QT_QPA_PLATFORM=wayland ./gui/iemod-fetch-gui/iemod-fetch-gui --check`.

---

## 6. Il test, passo per passo

Avvia la procedura guidata sul progetto di prova:

```bash
./gui/iemod-fetch-gui/iemod-fetch-gui --project ~/iemod-test/project
```

Due giri, nell'ordine: prima piccolo, poi grande.

### Giro A - BG2:EE da solo, poche mod (15-30 minuti)

1. **Fase 1, gioco e cartelle:** scegli **BG2EE**, cartella
   `~/iemod-test/games/bg2ee`, la tua lingua.
2. **Fase 2, mod:** scegli **3-5 mod piccole** che scaricano da GitHub (la
   colonna della sorgente lo dice), almeno una che fa una domanda durante
   l'installazione se la conosci.
3. **Fase 3, ordine:** lascia l'ordine calcolato.
4. **Fase 4, download:** *Download*. Se una mod non si scarica (pagina dietro
   Cloudflare, un pulsante), prova "Open the mod's page" e "Choose the saved
   file..." con il file scaricato dal browser.
5. **Fase 5, installazione:**
   - fai scaricare WeiDU se manca (`tolower` solo se serve, passo 3);
   - fai il **backup** quando lo chiede;
   - *Install*: rispondi al **questionario** se compare;
   - leggi la **conferma**: elenca problemi noti, spazio, WeiDU, domande che
     potrebbero ancora fermarsi. Rispondi sì.
6. Alla fine leggi il riepilogo: quanti componenti installati, con avvisi, non
   installati, non raggiunti.
7. **Avvia il gioco** dalla copia e controlla che arrivi al menu e carichi una
   partita nuova. Lancia il programma **dentro la copia**, non da Steam o GOG
   Galaxy/Heroic, che avvierebbero la cartella originale:
   ```bash
   cd ~/iemod-test/games/bg2ee && ./BaldursGateII     # nome esatto: ls
   ```
   La versione Steam nativa, lanciata così, può riavviarsi tramite Steam e
   aprire la cartella originale. Se succede, crea nella copia un file
   `steam_appid.txt` con l'ID del gioco (BG2:EE `257350`, BG:EE `228280`) e
   riprova; se ancora non basta, annotalo in `note.txt`. Per EET si lancia il
   gioco della cartella `bg2ee`.

### Giro B - EET (ore)

Ripeti con **EET**, cartelle `~/iemod-test/games/bgee` (BG:EE con SoD) e
`~/iemod-test/games/bg2ee` (diventa EET). Parti da **copie nuove** (rifai il
passo 3, con o senza `tolower` come ha detto il giro A), poi scegli il nucleo EET e una decina di mod. Durante le ore di
installazione puoi lasciare la finestra aperta: se una domanda si ferma o il
watchdog avvisa (`!!` nell'output), annota mod e ora.

---

## 7. Cosa raccogliere

Prima scrivi, a mano, `~/iemod-test/report/note.txt` con:

- giro A o B, distribuzione, giochi da GOG o Steam, nativi o Windows;
- il testo dell'output della procedura guidata (selezionalo nella finestra e
  incollalo), soprattutto le righe `!!` e quelle di errore;
- se il gioco parte dopo l'installazione;
- qualunque cosa ti sia sembrata strana.

Su Bazzite scrivi anche che lavori in Distrobox: dentro il contenitore
`/etc/os-release` (in `system.txt`) descrive l'immagine Ubuntu o Fedora, non
Bazzite.

Poi questo script raccoglie il resto e crea l'archivio, **senza** i file dei
giochi:

```bash
cd ~/iemod-test
{
  echo "== sistema"; cat /etc/os-release; uname -r
  echo "== sessione"; echo "$XDG_SESSION_TYPE"
  echo "== iemod-fetch"; ./gui/iemod-fetch-gui/iemod-fetch-gui --version
} > report/system.txt 2>&1
cp -r project/install-plan report/ 2>/dev/null      # results.json, answers.json, i log pianificati
for g in bgee bg2ee; do
  mkdir -p "report/$g"
  cp games/$g/WeiDU.log games/$g/WSETUP.DEBUG "report/$g/" 2>/dev/null
done
tar czf iemod-report.tar.gz report
ls -lh iemod-report.tar.gz
```

Se modifichi `note.txt` dopo, rilancia la riga `tar czf ...`.

Non metterci token, password o il nome utente se non vuoi: `results.json` e
`answers.json` contengono nomi di mod e risposte, non dati personali, ma i
percorsi contengono la tua cartella home.

`install-plan/results.json` contiene anche i **silenzi** più lunghi di ogni
batch: è la misura che serve per tarare il watchdog (oggi provvisorio a 10
minuti).

---

## 8. Farmi raccogliere gli output direttamente (Claude Code sulla macchina di test)

Se installi Claude Code sulla macchina di test, posso leggere e raccogliere
gli output io stesso da questa sessione, con la funzione **Remote Control**:

1. Installa Claude Code (funziona anche su Bazzite, si installa nella tua
   home): segui <https://code.claude.com/docs> per Linux.
2. Apri un terminale **nella cartella di prova** e avvia:
   ```bash
   cd ~/iemod-test
   claude remote-control
   ```
   La cartella compare nell'app di Claude Code.
3. Dimmelo nella sessione: chiedo di collegarmi a quella cartella, e **tu
   approvi ogni volta** sul tuo dispositivo. Da lì posso lanciare i comandi del
   passo 7, leggere `results.json`, `WSETUP.DEBUG` e i log, e anche avviare io
   la riga di comando su un test piccolo.

Limiti da sapere:

- una sessione si collega **a un solo computer**: per provare sia Bazzite sia
  CachyOS servono due sessioni (o uno dopo l'altro in sessioni diverse);
- vedo solo la cartella che scegli (`~/iemod-test`), non il resto del disco;
- la finestra grafica la usi tu: io leggo file e output, non clicco nella
  finestra;
- Bazzite: avvia `claude remote-control` **dentro** `distrobox enter iemod`,
  così i comandi girano dove sono installate le librerie.

---

## 9. Checklist del test

| Cosa | Atteso |
|---|---|
| `--check` | la finestra si apre e si chiude senza errori |
| Finestra vera, X11 | su una sessione X11 (o `QT_QPA_PLATFORM=xcb`) la procedura guidata si apre e si usa: in CI gira solo "offscreen", le librerie xcb del bundle non vengono mai caricate lì |
| Finestra vera, Wayland | su una sessione Wayland (Bazzite, Steam Deck in modalità desktop) si apre; se no, prova `QT_QPA_PLATFORM=xcb` e indica quale funziona |
| AppImage | parte con `chmod +x` e doppio clic o da terminale; indica se è servito `--appimage-extract-and-run` |
| Archivi RAR/7z con l'AppImage | `command -v bsdtar unar 7z` sul sistema dove gira l'AppImage; una mod in RAR e una in 7z si estraggono (su Bazzite: indica come hai installato `unar`) |
| Installer Windows (solo se provi anche su Windows) | `iemod-fetch-gui-windows-x86_64-setup.exe` si installa senza richiesta di amministratore; non è firmato, quindi SmartScreen avvisa ("Ulteriori informazioni", poi "Esegui comunque"): indica cosa dice esattamente; la voce nel menu Start apre la procedura guidata; la disinstallazione da "App installate" lascia i progetti e `%LOCALAPPDATA%\iemod-fetch\data`; con una versione precedente già installata, la nuova la sostituisce senza crearne una seconda |
| Flatpak (sperimentale) | con il remote flathub, `flatpak install --user iemod-fetch-gui-linux-x86_64.flatpak` e `flatpak run io.github.gsamuele78.iemod_fetch` si avvia; la cartella del gioco scelta dal dialogo appare in fase 1 con la nota sul "document portal" |
| Flatpak, WeiDU sul portal | prova un'installazione piccola (1-2 mod) nella cartella scelta dal dialogo: indica se va a buon fine, quanto ci mette rispetto allo zip, e qualsiasi errore di WeiDU o mod_installer - in particolare un errore di `getcwd` / "No such file or directory" sulla cartella di lavoro (xdg-desktop-portal #1812). Poi la stessa con il comando `flatpak override` della nota (selezionalo e copialo dalla fase 1) e confronta |
| Flatpak, progetto | il progetto e le mod scaricate stanno in `~/.var/app/io.github.gsamuele78.iemod_fetch/data/project` e ci sono ancora dopo aver chiuso e riaperto il Flatpak |
| Flatpak, gioco aperto | con il gioco aperto, l'installazione chiede di confermare che è chiuso (non può vederlo): indica che il messaggio compare |
| Download | ogni mod scaricata o, se bloccata, fornita a mano |
| Gioco chiuso | con il gioco aperto, *Install* rifiuta e dice di chiuderlo |
| Questionario | compare per le mod che fanno domande; le risposte vengono date da sole durante l'installazione (`-> ... (by question)` nell'output) |
| Domande non mostrate | se una si ferma: il watchdog lo dice dopo 10 minuti |
| Esiti | il riepilogo conta installati / con avvisi / errori / non raggiunti |
| EEex | se installato: alla fine dice di avviare InfinityLoader.exe (solo versione Windows del gioco) |
| Gioco | parte e carica una partita nuova |
| `tolower` | servito o no, e il gioco parte ancora dopo |
| Ripresa | se annulli a metà e ripeti *Install*: riprende da dove si era fermato |

Ogni riga che non va come atteso è un difetto da correggere: mandami il
pacchetto del passo 7 con la riga della checklist.
