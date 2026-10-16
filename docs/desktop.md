# Deck desktop release plan

Deck is a personal desktop app for Windows x64, macOS Intel and Apple Silicon,
and Linux x64. Each installation owns its local watchlist, tracker and downloaded
research. There is no shared server, account approval system, or dependency on
Vegas. The source repository remains **timcocuzza/kal-deck**.

The app and release workflow are implemented locally. The Linux AppImage and its
bundled service have been built and the service has passed integration checks.
Windows and Mac packaging, graphical launch, and a real signed update cycle still
need verification on their target platforms. The Linux preview has also been
installed and launched on the development machine; visual inspection remains
pending. No release has been published.

## Installation and everyday use

| Platform | Distribution | Launch and updates |
| --- | --- | --- |
| Windows x64 | NSIS installer | Install per user, then open Deck from Start or the desktop. Signed releases download updates and offer a restart. |
| macOS Apple Silicon | ARM64 DMG plus ZIP for updates | Drag Deck to Applications. Production builds require Developer ID signing and notarization. |
| macOS Intel | x64 DMG plus ZIP for updates | Same experience, using the Intel package. |
| Linux x64 | AppImage | Keep the executable in a writable user directory and launch it from an app shortcut. Released AppImages support updates. |

Users do not install Git, Node, Python, or run a startup script. The app starts one
private local service and shuts it down when Deck closes. Saved content loads
first; source refresh still runs once on opening, with manual refresh available.
Opening Deck twice focuses the existing instance.

The current local AppImage is a preview with automatic updates disabled. Official
Linux packages are built on Ubuntu 24.04; the locally built Arch package is for
testing on this machine and must not be advertised as compatible with older
distributions. Linux needs working AppImage/FUSE support and the Chromium sandbox;
do not use `--no-sandbox` as an installation workaround. Older OS compatibility,
Windows ARM and Linux ARM are not validated targets.

## Test the installer on a Mac

The simplest test uses GitHub's Mac runners; the Mac does not need Python, Node,
or a source checkout. First push the desktop commit to the source repository's
default branch. Then:

1. Open `timcocuzza/kal-deck` on GitHub, choose **Actions → Deck Desktop → Run
   workflow**, select `main`, and leave the signed-release checkbox unchecked
   (`release=false`). No signing secrets or public release repository are needed
   for this preview. [GitHub workflow instructions](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow).
2. After the Mac build succeeds, open the workflow run and download its artifact:
   `deck-mac-arm64-…` for Apple Silicon (M1/M2/M3/M4 or later), or `deck-mac-x64-…`
   for Intel. **Apple menu → About This Mac** identifies the chip. Artifacts require
   a GitHub login with repository access and are retained for 14 days.
   [GitHub artifact instructions](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/download-workflow-artifacts).
3. Unzip the downloaded artifact, open its `Deck-0.1.0-mac-arm64.dmg` or
   `Deck-0.1.0-mac-x64.dmg`, and drag **Deck** into **Applications**. Open Deck there.
4. This preview is not Developer ID signed or notarized. If macOS says the developer
   cannot be verified, first try opening Deck, then use **System Settings → Privacy
   & Security → Open Anyway** for this specific app from your own build. Do not
   disable Gatekeeper globally. A damaged-app or malware warning needs investigation
   rather than this workaround. [Apple's instructions](https://support.apple.com/en-us/102445).
5. Let research refresh, add a watchlist note or test tracker entry, quit with
   **Command-Q**, and reopen Deck to check persistence. Also test game logs, source
   links, and tracker export/import. The Mac starts with its own empty personal
   records; your Linux data is not uploaded or copied into installers.

Preview builds do not receive automatic updates. Replace the app in Applications
with a later preview to test another build; personal data stays in the user profile.
Signed releases will add the normal update flow. The Mac workflow has been prepared
but has not yet been executed remotely or validated on a physical Mac.

## Personal data and recovery

Use **File → Open data folder** to find `deck.sqlite3` and `backups/`.
Default locations are:

| OS | Data directory |
| --- | --- |
| Windows | `%APPDATA%\Deck\data` |
| macOS | `~/Library/Application Support/Deck/data` |
| Linux | `$XDG_CONFIG_HOME/Deck/data`, normally `~/.config/Deck/data` |

Updates replace application files while leaving this directory intact. Before a
different version opens an existing database, Deck makes a full SQLite backup and
checks its integrity. A backup failure stops startup. Backups cover watchlists,
tracker records and source snapshots. They are retained locally; they do not
protect against disk loss. Tracker JSON export remains useful but does not include
watchlists. Unsaved UI drafts still need saving before restart.

To recover, close Deck, preserve a copy of the current data directory, and replace
`deck.sqlite3` with a verified backup. Launch Deck again. For the existing source
checkout, the original database remains `.data/kalshi-deck.sqlite3`. A new desktop
profile does not automatically search the filesystem for it. Migrate it with a
SQLite online backup into the desktop data directory before first use; do not
overwrite an existing desktop profile or copy an actively written database file.
This migration has been performed on the development machine: all four tables
were copied, integrity passed, and the original checkout database was preserved.

Local data is protected by the operating-system user account, not app encryption.
Different OS accounts have different profiles. People sharing the same OS login
also share that login's Deck data. Full-disk encryption and a private login protect
records on a lost computer.

## Security boundary

The backend listens only on a randomly assigned `127.0.0.1` port. Every asset and
API request requires a random per-launch token; the Electron main process adds it
without exposing it to React. Host and Origin checks reject other origins. API
responses are not cached. The packaged API schema and interactive docs are disabled.
This protects against unrelated websites and unauthenticated local HTTP clients;
it cannot protect against malware already running as the same OS user.

The renderer uses Chromium sandboxing, context isolation, disabled Node integration,
denied permissions and a restrictive Content Security Policy. Only explicit HTTPS
source domains can open in the system browser. Node environment/debug switches
are disabled in packaged Electron binaries. Fonts and branding are bundled.
These choices follow [Electron's security guidance](https://www.electronjs.org/docs/latest/tutorial/security).

Production Windows builds require a signing publisher and verify that publisher
on updates. Production Mac builds require signing, hardened runtime, and
notarization. Linux updates use HTTPS and SHA-512 checks from the release manifest;
the current updater does not provide a separately signed Linux manifest. GitHub
release write access therefore permits distributing executable updates. Protect
the release account with strong MFA, limited credentials and a reviewed release
environment. Never put a GitHub access token in the app.

Outstanding risks before broad distribution:

- Source downloads and compressed expansion still need explicit byte/row/page
  limits. Public upstream changes can exhaust memory; keeping the last good
  snapshot helps recovery but does not bound resource use.
- Reports repeatedly decompress and recalculate saved data. The prior local
  partial-season benchmark peaked around 500 MiB for backend work. Full-season
  refresh and simultaneous research still need resource profiling. Bounded caching
  by snapshot revision and narrower source columns are the next performance work.
- The current npm audit reports eight moderate findings in the builder's legacy
  download/proxy dependency chain. They are build-time dependencies; the production
  npm dependency audit reports none. Do not apply an untested builder downgrade to
  silence the report. Recheck before publishing and upgrade compatible tooling.
- Signed install, update, interruption, and rollback tests must pass on all four
  build targets. CI backend smoke tests do not replace those graphical checks.

The archived hosted audit's authentication issues remain relevant if this code is
ever exposed on a public server. The desktop boundary does not make the legacy
browser service a multi-user product.

## Speed and resources

The interface retains the current layout, interactions, fonts and transitions.
The optimized logo is approximately 8 KB. The latest production build contains
about 95 KB gzipped JavaScript and 6 KB gzipped CSS. Desktop packaging adds Chromium
and Python so users need no separate runtimes; the Linux download is about 142 MB.
Onedir Python packaging avoids unpacking the backend on every launch.

Plan for an 8 GB RAM computer with at least 2 GB free disk as an initial testing
target, not a measured minimum. Allow additional space for full-season sources,
multiple database backups and the downloaded update. Disk growth depends on usage.
Automatic update checks run after launch and every four hours; market data is not
polled on that schedule. No EC2 resize, DNS change or server resource allocation
is needed for this architecture.

## GitHub Actions and release ownership

`.github/workflows/ci.yml` runs tests, type checking, bundle budgets, a history
secret scan, and dependency audits. `.github/workflows/desktop.yml` calls those
checks, then uses four native runners: Windows 2025 x64, macOS 15 ARM64,
macOS 15 Intel, and Ubuntu 24.04 x64. Python is frozen separately on each target;
[PyInstaller is not a cross-compiler](https://pyinstaller.org/en/stable/).

Pull requests affecting the app produce unsigned preview artifacts without update
configuration or release credentials. A manual run with `release=false` does the
same. A manual `release=true` run on `main` builds signed Windows/Mac packages and
the Linux AppImage. All four must succeed before the release assembly job proceeds.
The assembly validates file hashes, includes both Mac architectures in the update
feed, writes SHA256SUMS, and uploads a **draft** release. Publishing the reviewed
draft makes its update available to installed release builds. Deck downloads it
and asks the user to save edits and restart; it does not silently quit mid-session.

Use a public release repository so friends can update without a GitHub login or
embedded credentials. Proposed destination: **timcocuzza/deck-releases**, containing
installers and release notes only. This does not transfer or expose the source
repository, although distributed application code can be inspected. If
`timcocuzza/kal-deck` is already public, it can instead host its own releases.
The destination still needs confirmation; neither repository has been changed.

### Configuration after choosing the release destination

In the source repository, create a `desktop-release` environment restricted to
`main`, with an approval gate where the GitHub plan supports it. Keep signing
secrets there. Preview jobs use `desktop-build` and do not receive signing secrets.
Protect `main` with CI requirements and review workflow changes carefully.

| Environment variable | Value |
| --- | --- |
| `DECK_RELEASE_OWNER` | `timcocuzza` |
| `DECK_RELEASE_REPO` | Confirmed public installer repository name |
| `DECK_WINDOWS_PUBLISHER` | Exact signing certificate publisher name |

`DECK_RELEASE_TOKEN` is a fine-grained, expiring token with Contents read/write
permission on the release repository only. It is used only by the draft-upload
job, never packaged. The ordinary workflow token has read-only contents permission.
Actions are pinned by commit and Python packages by artifact hash. The build still
downloads Electron/installer tooling; this is not a fully hermetic build.

### Apple signing

Confirm the existing account has active Apple Developer Program membership and
access to a **Developer ID Application** certificate and private key. An ordinary
Apple Development certificate is insufficient for this distribution. Use a
password-protected exported certificate and GitHub environment secrets:

- `DECK_MAC_CERTIFICATE`: base64-encoded P12 certificate with private key.
- `DECK_MAC_CERTIFICATE_PASSWORD`: P12 export password.
- `DECK_APPLE_ID`, `DECK_APPLE_APP_PASSWORD`, `DECK_APPLE_TEAM_ID`: notarization identity,
  app-specific password and team ID.

The workflow signs and notarizes, then verifies the signature and stapled ticket.
Never send these credentials in chat or commit them. Apple's requirements are in
[Notarizing macOS software before distribution](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution).

### Windows signing

No Windows signing account is currently available. The workflow supports Microsoft's
Azure signing service through the pinned builder's `azureSignOptions`, or an existing
CI-compatible PFX certificate. Unsigned previews remain possible; the production
workflow intentionally fails if signing is unavailable. Both the app and bundled
service executable are signed; a verification step rejects invalid signatures.

For Azure, complete account/identity validation and create a public-trust certificate
profile, then grant a dedicated service principal the Certificate Profile Signer
role on that profile. Set these environment variables:

- `DECK_AZURE_SIGNING_ACCOUNT`, `DECK_AZURE_SIGNING_ENDPOINT`, `DECK_AZURE_SIGNING_PROFILE`.
- `DECK_WINDOWS_PUBLISHER` matching the certificate's publisher exactly.

Store `DECK_AZURE_TENANT_ID`, `DECK_AZURE_CLIENT_ID` and the expiring
`DECK_AZURE_CLIENT_SECRET` as environment secrets. The workflow exposes them only
to the Windows release build. Rotate the secret and scope its signing access.
For an existing PFX instead, leave Azure settings empty and use
`DECK_WINDOWS_CERTIFICATE` (base64 PFX) and `DECK_WINDOWS_CERTIFICATE_PASSWORD`.
Hardware-backed certificates need their vendor's signing integration, not a
promise that the private key can be exported. Details:
[electron-builder v26 Windows signing](https://www.electron.build/v26/docs/features/code-signing/code-signing-win/).

### First release acceptance

1. Run a preview workflow and install on clean Windows, Intel Mac, Apple Silicon
   Mac, and Linux machines. Verify launch without development tools, app icons,
   source refresh, source links, tracker export/import, watchlist saving and clean quit.
2. Configure signing and the public release destination. Increment `package.json`
   and its lockfile together for each release; never replace an existing version.
3. Build a signed candidate from `main`, inspect the draft artifacts and checksums,
   and install those exact files. Test a second version on every platform: download,
   restart prompt, retained notes/tickets, upgrade backup and offline behavior.
4. Publish the reviewed draft only after those checks. Test discovery through
   **Help → Check for updates**. Friends install once and then use that update channel.
5. For a bad published update, withdraw it and release a fixed higher version.
   Automatic downgrades are disabled. Restore an older database only from a backup
   with Deck closed and after preserving the current data directory.

See the pinned-version [update documentation](https://www.electron.build/v26/docs/features/auto-update/)
for platform requirements and release metadata. macOS update ZIPs and both Mac
architectures are essential; distributing only DMGs is insufficient.

## Local maintainer build

Use Node 24 and Python 3.14 with a `.venv`. On each target OS, install the locked
dependencies, build React, freeze Python, then package that native target:

```text
npm ci
npm run desktop:install-runtime
python -m pip install --require-hashes -r requirements-desktop.txt
npm run build
python scripts/build_desktop_backend.py
npm run desktop:dist -- --publish never
```

Use the virtual environment's Python for those commands. `npm run desktop:dev`
launches Electron against that environment for development. Build artifacts go to
`release/desktop/`. Backend integration checks use a disposable profile via
`python scripts/smoke_desktop.py`; pass `--executable` with the bundled service path
to test the frozen service. Users installing Deck do not run these commands.
