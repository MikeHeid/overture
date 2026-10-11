# Join the main Overture server

One Overture server can host every project on your machine. Each project
keeps its own:

- console address (for example `acme-console.example.com`);
- Cloudflare Access application;
- loopback port;
- inbox, rulings and state directory;
- agent token.

They all run in one process, `server.py --all`. That process reads its
project list from `~/.config/overture/server.json`.

This guide has two parts:

- **Part A** sets up the main server, once per machine. Skip it if a main
  server is already running.
- **Part B** joins a project to it. Repeat it for each project.

Every command below was run against the kit, in this order, before it was
written down. **You** run them in a terminal, not a Claude session.
`register`, `steward` and `server` write your user-level registry and
`server.json`, which decide what the plugin trusts. The kit does not block a
session from running them, so keep them out of agents' hands by convention.

## Placeholders

| Placeholder | Meaning | Example |
|---|---|---|
| `<kit>` | the installed kit (`deploy/install.sh` puts it here) | `~/.local/share/overture/kit` |
| `<py>` | the kit's own Python, with PyJWT and cryptography | `~/.local/share/overture/venv/bin/python` |
| `<name>` | the project's name: lowercase letters, digits, single hyphens | `acme` |
| `<project>` | the project's checkout | `~/src/acme` |
| `<state>` | the project's state directory | `~/.local/state/overture/acme` |
| `<host>` | the project's console hostname | `acme-console.example.com` |
| `<aud>` | the Access application's AUD tag | 64 hex characters |
| `<port>` | a free loopback port, different for each project | `47932` |
| `<team>` | your Zero Trust team domain | `yourteam.cloudflareaccess.com` |

---

## Part A: start the main server (once per machine)

**1. Install the kit and its Python.** This uses the same installer as a
single project:

    bash <plugin>/kit/deploy/install.sh --project <first project>

It copies the kit to `~/.local/share/overture/kit` and creates
`~/.local/share/overture/venv`.

**2. Join your first project** with Part B, steps 1 to 3, so `server.json`
exists.

**3. Create the main server's unit.** Write
`~/.config/systemd/user/overture-console.service`:

    [Unit]
    Description=Overture console server (every project in server.json; loopback only)
    After=network-online.target

    [Service]
    Type=simple
    ExecStart=%h/.local/share/overture/venv/bin/python %h/.local/share/overture/kit/server.py --all
    Restart=on-failure
    RestartSec=5

    [Install]
    WantedBy=default.target

**4. Stop every per-project server that the main server now hosts.** While an
old per-project server still listens on `<state>/agent.sock`, that socket
answers without a token. The main server also refuses to open a store
another server holds.

    systemctl --user disable --now <name>-console.service     # each joined project

**5. Start it.**

    systemctl --user daemon-reload
    systemctl --user enable --now overture-console.service
    journalctl --user -u overture-console -n 20
    # console-server: acme: serving on port 47931
    # console-server: agent door ~/.config/overture/server.sock

On WSL, run `loginctl enable-linger $USER` so the server keeps running after
you close your WSL terminal. To try the server without a unit, run
`<py> <kit>/server.py --all` in a terminal and leave it open.

---

## Part B: join a project to the main server

**1. Register the project.** This switches the plugin on for the project.
`--steward` names the master agent: the one session that processes your
answers. Use the name from the plugin's **Master agent name** setting
(`/plugin` → overture → configure), if you set one.

    <py> <kit>/agent.py --state <state> register --project <project> --steward <agent-name>

Then type `/overture:as <agent-name>` in the Claude session that should be
the master. Other sessions are workers: they send their questions to your
inbox instead of asking you directly.

**2. Give the project a console address in Cloudflare.**

- **Zero Trust → Access → Applications:** add a self-hosted application for
  `<host>`. Copy its **AUD tag**.
- **Tunnel:** add an ingress rule to the tunnel your main server's
  cloudflared uses, above its catch-all:

      - hostname: <host>
        service: http://127.0.0.1:<port>

  Then route DNS:

      cloudflared tunnel route dns <tunnel> <host>

  [`plugin/kit/docs/CLOUDFLARE.md`](../plugin/kit/docs/CLOUDFLARE.md) has the
  details.

**3. Add the project to the main server.** This writes the project into
`server.json` and its agents' token into `~/.config/overture/tokens/<name>`
(mode 0600). The token is never printed.

    <py> <kit>/agent.py --state <state> server add <name> \
        --hostname <host> --aud <aud> --port <port> --team-domain <team>

The command refuses, writing nothing, in these cases:

- `register` has not been run for `<state>`;
- another project already uses `<port>`, `<host>` or `<state>`;
- the name or a domain is malformed.

Run it again to change a value. The token is kept, so running agents are
not cut off.

**4. Restart the main server.** It reads the project list when it starts. A
project you join while it runs is refused until the restart.

    systemctl --user restart overture-console.service
    journalctl --user -u overture-console -n 5      # "<name>: serving on port <port>"

A project the server cannot open, for example because an old per-project
server still holds its store, is refused by name, with the reason. Every
other project keeps being served.

**5. Check it from inside the project.** `agent.py` picks the project from
the directory it runs in, and reads the token itself.

    cd <project>
    <py> <kit>/agent.py --state <state> health
    # {"ok":true,"version":"…","register":"ok",…}

Run from another project's checkout, the command is refused and names the
right `--state`. Then open `https://<host>` in a browser. Access asks you to
sign in, then the console loads.

**6. Fill the console.** The steward does this, inside the project:

    <py> <kit>/agent.py --state <state> items-push --adapter .overture/adapter.py
    <py> <kit>/agent.py --state <state> page-snapshot --path docs/console/page.html
    <py> <kit>/agent.py --state <state> prs-push        # needs gh, logged in

Then press **Use this page** in the console.

---

## Day to day

| To | Run |
|---|---|
| Give a project a new agent token; the old one is refused at once, with no restart | `<py> <kit>/agent.py --state <state> server token rotate <name>` |
| See what the main server serves | `journalctl --user -u overture-console -n 20` |
| Upgrade every project at once | re-run `install.sh`, then `systemctl --user restart overture-console` |
| See every project's waiting questions | the **Portfolio** tab and the priority ribbon, once peers are listed in `.overture/portfolio.json` |

**What a token protects.** A project's token stops cross-talk: a wrong
`--state` or a skill bug can't reach another project's console. It does not
isolate agents that run as the same OS user, because such an agent can read
`tokens/` directly. Real isolation needs a sandbox or a separate user.
