# Deck desktop setup and Git updates

Deck runs as a normal desktop app on Windows x64, macOS Intel or Apple Silicon,
and Linux x64. Install Git, Node and Python once, run the setup once, then use the
Deck icon. **Data → Update Deck** prepares future updates and **Restart to update**
activates them. No Apple Developer membership, Windows signing account, shared
server, or paid update service is required for this source-based installation.

This replaces the earlier signed-installer plan. The old signing secrets and release
repository are no longer used. Source stays at `timcocuzza/kal-deck`; public HTTPS
access is the intended update channel. The repository's visibility has not been
changed by the agent.

## One-time setup on a Mac

Install Git, Node.js **24 LTS** (26 is also accepted), and Python **3.14**. Use the
[Node installer](https://nodejs.org/en/download) and [Python macOS installer](https://www.python.org/downloads/macos/).
Running `git --version` in Terminal offers Apple's command-line tools if Git is
missing. Reopen Terminal after installation.

Once the current code is pushed and the repository is public:

```bash
git clone https://github.com/timcocuzza/kal-deck.git
cd kal-deck
python3.14 scripts/install_desktop.py
```

Setup downloads the locked dependencies, builds the app, and checks the backend
using temporary data. When it finishes, open **Deck.app** in your home folder's
**Applications** directory (`~/Applications/Deck.app`). Drag it to the Dock if desired.
The app wrapper is created locally and launches the local source installation;
it is not a downloaded Developer ID-signed Deck installer.

If you already cloned the repository, run `git pull --ff-only` there before setup.
Setup requires a clean committed checkout. The managed installation is separate
from this checkout, so you can move or delete the original clone afterward.
Keep the installed Git, Node, and Python tools available. Other people need no GitHub
account once the repository is public.

If `/Applications/Deck.app` is an older installer build, quit it and move that old
application to Trash before using the new `~/Applications/Deck.app`. Keep the Deck
folder in Library/Application Support: that contains your records. Setup refuses
to overwrite an unrelated existing `~/Applications/Deck.app`.

## One-time setup on Windows and Linux

On Windows, install [Git for Windows](https://git-scm.com/downloads/win), Node.js 24,
and Python 3.14, then reopen PowerShell:

```powershell
git clone https://github.com/timcocuzza/kal-deck.git
cd kal-deck
py -3.14 scripts/install_desktop.py
```

Setup creates **Deck** shortcuts on the desktop and in the Start menu. They use
Python's windowless launcher, so normal use does not open a terminal.

On Linux, install Git, Node.js 24 or 26, and Python 3.14 with venv support, then run:

```bash
git clone https://github.com/timcocuzza/kal-deck.git
cd kal-deck
python3.14 scripts/install_desktop.py
```

Deck appears in the app menu. This source launcher does not use AppImage or FUSE.
The desktop environment still needs Electron's normal system libraries and
unprivileged Chromium sandbox support. Never add `--no-sandbox` to fix a launch.

For setup failures, read `setup.log` in the runtime directory below. Setup can be
rerun to repair shortcuts without replacing an existing installed revision or data.
Tool installations must remain at the paths recorded during setup; changing or
removing them can require repairing the runtime. macOS and Windows graphical
launches still require validation on those machines.

## Updating without a terminal

Open **Data → Update Deck**, or use **Help → Update Deck**. Deck checks public `main`
and prepares a newer revision while the current app stays usable. Progress appears
under Data. After it says the update is ready, save your edits and click **Restart
to update**. A confirmation prevents an unnoticed restart during editing.

The update manager fetches the exact commit, rejects backwards or diverging history,
creates a separate Git worktree and Python environment, installs locked dependencies,
builds React and runs the JavaScript/backend checks plus a real backend smoke test.
It switches the installed pointer only after those checks pass and the old app exits.
A failed download or build leaves the working version selected. No-change checks
skip dependency installation and building. Ordinary launches work offline using the
installed revision and saved research.

Closing Deck during preparation can let that preparation finish in the background;
it does not automatically install the candidate. Reopen Deck to see a completed
update and choose when to restart. Another setup or update cannot run concurrently.

**`git pull` alone does not update the managed desktop app.** It updates the original
checkout. The app button handles the build, checks and activation. Developers can
still run a checkout with `npm run desktop:dev` after creating its `.venv`, installing
`requirements.txt`, running `npm ci`, and `npm run desktop:install-runtime`.

## Where code and personal data live

| Platform | Managed runtime | Personal database |
| --- | --- | --- |
| macOS | `~/Library/Application Support/DeckRuntime` | `~/Library/Application Support/Deck/data/deck.sqlite3` |
| Windows | `%LOCALAPPDATA%\DeckRuntime` | `%APPDATA%\Deck\data\deck.sqlite3` |
| Linux | `$XDG_DATA_HOME/deck-source`, normally `~/.local/share/deck-source` | `$XDG_CONFIG_HOME/Deck/data/deck.sqlite3`, normally `~/.config/Deck/data/deck.sqlite3` |

Use **File → Open data folder** for your records and backups, and **File → Open update
log** for a failed update. The runtime contains `state.json` (current and previous
commits), `ready.json` (a checked candidate), `tools.json` (local tool paths), and
`releases/<commit>/` (isolated code and dependencies). Do not edit those worktrees;
keep development changes in your original checkout.

Before each new Git revision opens an existing database, Deck makes a full SQLite
backup and checks its integrity. The backup includes tracker records, watchlists and
source snapshots, even if the app version number was not bumped. A failed backup
stops startup. Existing desktop data is reused; each friend's computer starts with
its own empty records. Unsaved forms still need saving before any restart.

The previous installed code stays available. Older unused managed worktrees are
removed during subsequent update checks; the current, previous and pending revision
are retained. Database backups are not automatically deleted. Backups remain local
and do not protect against a lost disk. To restore a database, close Deck first,
copy the whole data directory somewhere safe, then replace `deck.sqlite3` with a
verified backup. Do not automatically pair an older app with a newer schema: review
the migration and restore the corresponding backup if needed.

## Security and maintenance

A public repository makes its committed source and history readable. The application
contains no GitHub token. Personal databases, runtime files, credentials and generated
builds are ignored by Git. Before changing visibility, scan history and inspect the
files being published. [GitHub visibility documentation](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/managing-repository-settings/setting-repository-visibility).

Git updates execute code on your friends' computers. Protect your GitHub account
with strong MFA and `main` with review and required CI checks. Downloading over HTTPS
and validating Git objects protects transport/integrity, not against a compromised
maintainer account or malicious dependency update. The update manager disables Git
hooks, ignores global/system Git configuration and suppresses credential prompts.
Dependencies use the npm lockfile and hashed Python requirements; candidate checks
run before activation. No untrusted pull-request code receives release credentials.

The renderer retains sandboxing, context isolation and disabled Node integration.
Its new bridge exposes only update status, starting an update and requesting a
restart. Main-process handlers accept requests only from Deck's own main frame.
The renderer never receives a session token, filesystem API, shell command or update
URL. The backend still uses a random loopback port, per-launch token, Host/Origin
validation, private API responses and shutdown when its owning app exits.

The source installation has a larger local dependency footprint than a packaged
installer. Allow at least **4 GB free disk** for setup, multiple revisions and backups;
the updater refuses to build with less than 2 GB free. An 8 GB RAM computer remains
an initial testing target, not a measured minimum. Git/Node/Python are system tools
that need normal security maintenance. Current npm dependency auditing reports no
known vulnerabilities after removing the old installer/updater dependency tree.

Outstanding work before broad distribution remains: GUI acceptance on Windows and
both Mac architectures, the in-app restart flow on each OS, upstream byte/row
limits, and full-season memory profiling. A full cross-revision build and activation
and a managed-source launch passed locally on Linux. Report recalculation and large source
refreshes are still the primary performance risks. Core UI interactions are unchanged.

## CI and publishing an update

There is one workflow, **Deck CI**. Every push to `main` and every pull request runs
tests, build-size checks, dependency vulnerability audits and a repository-history
secret scan once. UI-only and documentation-only changes stop there. Desktop,
backend, dependency, test, script, workflow and unrecognized root-file changes also
run fresh source setups on Windows x64, macOS ARM64, macOS Intel and Linux x64,
including temporary-profile backend smoke checks. Weekly and manually requested
runs check every platform. New commits cancel older runs on the same branch/PR.

The normal verification job skips Electron's binary download because it does not
launch the desktop. Native setup jobs cache npm, Python and Electron downloads but
still create fresh environments and validate the locked dependencies. Failed setup
logs appear directly in the job output and are also saved as diagnostic artifacts.
GitHub's runner queues can still add waiting time, especially on Mac.

Dependabot groups weekly version updates into one PR per ecosystem (npm, Python,
GitHub Actions). Its own dependency-discovery runs are separate GitHub-managed jobs;
the version-update limit does not disable security alerts or security updates.
All project jobs use read-only repository permissions and require no Apple/Windows
certificates, release token or separate release repository. No DMGs are published.

Push reviewed changes to `main` after the required checks pass. Once those commits
are publicly accessible, installed users receive them through **Update Deck**. App
version bumps are useful for display but not required for update detection or backups:
updates are identified by the exact Git commit. Keep source protocol compatibility
(`deckSourceProtocol: 1`); incompatible launcher/tool changes require a new setup.

The first local installation and tests are recorded in `docs/source-desktop-validation.json`.
The old `docs/desktop-validation.json` records the superseded packaged preview.
