# Windows support in LivePaste 4

The release includes `livepaste-windows-x86_64.exe` and
`livepaste-windows-x86_64-setup.exe` for Windows 10/11 x64. Setup bundles the
runtime, installs for the current user, adds shortcuts, enables sign-in startup
and launches the background server. There is no Python prerequisite or
administrator service account.

The Windows executable is currently unsigned; Windows may show its standard
publisher/security prompt when opening a new download.

## Lifecycle

`livepaste background` launches a detached monitor. A standard-library OS file
lock admits one monitor per user. It starts the server, checks health after a
startup grace period, retries failed processes with bounded backoff and retains
the persistent database. `stop` asks the monitor to stop before stopping its
server, so a deliberate stop does not cause an automatic restart. `restart`
keeps an existing monitor in charge of the replacement process.

Windows process records include the creation time and an unguessable control
token. Stop requests use a per-process local file; the server can finish its
SQLite and WebSocket cleanup. No process is stopped just because it occupies a
port. Windows receives a socket object directly instead of Unix-only `fromfd`.

Sign-in startup uses the current user's
[`Run` registry key](https://learn.microsoft.com/en-us/windows/win32/setupapi/run-and-runonce-registry-keys)
and a quoted UTF-16 Windows Script Host launcher, which hides the console.
`autostart disable` removes that entry and launcher. It does not delete data.

The [Inno Setup installer](https://jrsoftware.org/ishelp/topic_setup_privilegesrequired.htm)
uses `PrivilegesRequired=lowest`. Upgrades stop the existing monitor before
replacing the locked Windows executable, then start the new version. Uninstall
disables startup and stops the app; user data remains for recovery or reinstall.

## Paths and troubleshooting

- Application: `%LOCALAPPDATA%\Programs\LivePaste`.
- Default data/settings: `%USERPROFILE%\.livepaste`.
- Logs: `server.log` and `background.log` in that settings directory.
- Default browser URL: `http://localhost:8090`; `config port` overrides it.
- The computer must be awake and the user signed in. Startup is not a system
  service and does not run while the computer is powered off.
- The installer leaves Windows Firewall rules unchanged. LAN clients need
  connectivity to the selected port on the intended private network.

## Release checks

The Windows runner exercises the real backend suite, frontend build and clean
wheel install. Native binary tests verify file integrity, page state, restart,
duplicate launches, a deliberately crashed process, automatic recovery and
explicit stop. Installer tests cover silent install, reinstall while running,
retained text/binary data, the registered sign-in launcher, uninstall and data
retention. These checks run before publication of the setup asset.
