---
name: console-onboard
description: Use when the user wants to set up the owner console for the current project (onboard, install, connect it to Cloudflare, Tailscale or ZeroTier), or asks how to get the console running. Asks how the console will be reached, then for the project name and the Cloudflare values (or none, with sign-in links), writes the project's non-secret config with the kit's onboard.py, and hands the user the commands only they may run.
---

# Onboard this project onto the owner console

The owner console is a web page, behind Cloudflare Access, where the owner
answers an agent's questions. Onboarding a project means five values, one
script run, and a short list of commands **the user runs themselves**.

## What you must never do here

- **Never open, print or copy** `~/.cloudflared/cert.pem` or any
  `~/.cloudflared/*.json`. They are Cloudflare secrets. The kit only ever
  checks that a credentials file exists.
- **Never run** `deploy/install.sh` (with or without `--start`),
  `agent.py register`, `cloudflared tunnel create`,
  `cloudflared tunnel route dns`, or `systemctl --user enable`/`start`. The
  installer sets up a service that **imports and runs the project's
  `.overture/adapter.py` as Python**. Registering tells every Claude
  session to trust this project's console. The tunnel and DNS make it
  reachable from the internet. They are the user's decisions, so you print
  them and the user runs them. The same goes for `agent.py access`, which
  sets who may decide in the console, and for `agent.py invite` and
  `agent.py server listen` (1.47): a sign-in link signs a browser in as
  someone, and `--listen` decides which network reaches the console. Both
  refuse inside a Claude session anyway.
- **Never pass `--force`** unless the user has seen the file it would replace
  and said to. **Never delete or replace a symbolic link** that `onboard.py`
  refused; tell the user what it points at instead.
- **Show every `REVIEW` line** `onboard.py` prints. It means an adapter or
  page was already in the project, and the server will run it.
- **Never invent a value.** An AUD tag or team domain you did not get from the
  user is a console nobody can log in to.

## 1. Find the kit

The kit ships inside this plugin, at `${CLAUDE_SKILL_DIR}/../../kit`, however the
plugin was installed (from the release zip or straight from the repository).
Call that folder `KIT`.

`KIT/onboard.py` must exist. If it does not, stop and say the plugin is
incomplete.

## 1a. Check the prerequisites (1.53.2)

Run `python3 "KIT/onboard.py" prereqs` first (read-only; it works on native
Windows too). Each `ok:` line is present; each `- NAME (required|optional)`
line is missing, with the command that fixes it on this platform and a link.
The last line counts what is missing.

**On native Windows, stop here, before any question.** The scan lists
"Claude Code inside WSL" there every time, since this session is not in
WSL, so re-running it never clears. Show the user its lines word for word,
then say what to do: install WSL, run the Claude Code CLI inside it, and
onboard there.

On every other platform, when one is missing, show the user its lines word
for word, then ask with AskUserQuestion, never a blank question:

> Some prerequisites are missing. How do you want to go on?
> **A** I install them now, then you re-run the check · **B** go on without the optional ones · **C** stop here

Put ★ on **A** when a required one is missing (onboarding cannot finish
without it; `prereqs` exits 1), else on **B**. Never run a fix command
yourself: each installs software, which is the user's act.

## 1b. Ask how the console will be reached (1.47)

Run `python3 "KIT/onboard.py" detect` first (read-only). It prints one line
per overlay address it finds (`zerotier ztexample0 10.147.17.10/16`,
`tailscale tailscale0 100.x.y.z/32`) and any overlap warning. Then ask, with
AskUserQuestion:

> How will you reach the console?
> **A** Cloudflare (as today) · **B** Tailscale · **C** ZeroTier · **D** this machine only

Put ★ on the one `detect` points at: **C** when it found a `zerotier` line,
else **B** when it found a `tailscale` line, else **A** (or **D** when the user
said they have no Cloudflare account). Show every overlap warning `detect`
printed, word for word: a Docker bridge on the ZeroTier range can take its
route.

- **A**: sections 2 to 4 below, unchanged.
- **B, C, D**: sign-in links, no Cloudflare: section 5.


Ask with AskUserQuestion where it helps, and in plain text otherwise. Offer
these defaults, and let the user change every one:

| Value | Default | Notes |
|---|---|---|
| Project name | the project directory's name, lowercased, spaces to hyphens | 2-32 of a-z, 0-9, hyphen; it names the services and the state folder |
| Team domain | `${user_config.team_domain}` if set | `<team>.cloudflareaccess.com` |
| AUD tag | none; the user pastes it | 64 hex characters, from the Access application (step 3 below) |
| Hostname | `<name>-console.${user_config.zone}` if a zone is set | must be in a zone on their Cloudflare account |
| Port | 4793 | the script checks it is free on 127.0.0.1 |
| Master agent (steward) | `${user_config.steward}` if set | optional; the session that processes the owner's answers. Agent-name shape, e.g. `steward` or `agent-1` |

- If a default in the table above is empty or still reads as a literal
  `${user_config...}`, the user has not set it in the plugin's settings. Just
  ask for it.
- **The AUD tag comes from an Access application that may not exist yet.** If
  the user has none, walk them through `KIT/docs/CLOUDFLARE.md`, section
  "Access application", first. Onboarding can be re-run later with the real
  tag.
- Optional: an **audit seat**, the project's own review, which joins the
  deliberation committee as a fourth seat (the console-fork skill says how).
  Pass it as `--audit-seat NAME --audit-brief "what it checks"`. Skip it
  unless the user has one.

## 3. Write the config

Run from the project root:

    python3 "KIT/onboard.py" write --project . --name NAME --team-domain TEAM \
        --aud AUD --hostname HOST --port PORT [--steward STEWARD]

Pass `--steward` only when the user gave a master agent name. The script
checks the name and prints it into the `register` step. It never writes the
name into the project, because a repository must not be able to name the
steward.

- **Refused (exit 2):** the message names the bad value and says what it
  should be. Ask for that one value again. Never edit the files by hand to
  get past a refusal.
- **"exists and was not written by onboard.py":** show the user the file. Pass
  `--force` only if they say to replace it.
- **Success:** it writes `.overture/console.env`, merges
  `.overture.json`, and adds a starter `.overture/adapter.py` and
  `.overture/page.html` when the project has none. Then it prints the
  next steps.

## 4. Hand over the next steps

Show the user the commands the script printed, **verbatim and in order**, and
say plainly that each is theirs to run:

1. `install.sh --start`: the loopback server;
2. `agent.py register`: trust this project's console and, with
   `--steward`, name the master agent. The user then types
   `/overture:as STEWARD` in that session;
3. create the Access application;
4. create the tunnel, `onboard.py tunnel --id`, route DNS **with `--config`**,
   then start the tunnel unit;
5. check it: 403 on loopback without a token, then an Access login at the
   hostname;
6. make themselves the **administrator**: Team → People → "Make me
   the administrator", which takes the login they are signed in with. Until
   then everyone the Access policy lets in can do everything. After it, they
   add each other person there as a member of their areas, or a viewer.

**Never ask for the administrator's email, and never run `agent.py access`.**
Operator emails stay in the console (the owner's ruling of 2026-10-14): the
console button needs none, and the `access` command the script prints is for
the user's own terminal (it refuses inside a Claude session anyway).

Point them at `KIT/docs/CLOUDFLARE.md` for the Cloudflare screens. Offer to
explain any step. Offer, too, to replace the starter page and adapter with the
project's own (`KIT/docs/ADAPTER.md`).

## 5. Without Cloudflare: sign-in links (1.47)

Ask only for the project name, the port, and (optional) the master agent, as
in section 2. No team domain, AUD tag, hostname or tunnel: `onboard.py`
refuses them with `--auth link`. Then run, from the project root:

    # B, Tailscale: preferred through `tailscale serve` (HTTPS); ask the user for
    #    their machine's tailnet name, never guess it
    python3 "KIT/onboard.py" write --project . --name NAME --auth link \
        --origin https://MACHINE.TAILNET.ts.net --port PORT [--steward STEWARD]
    #    or, on the tailnet address itself (plain http on the tailnet):
    python3 "KIT/onboard.py" write --project . --name NAME --auth link \
        --listen 100.X.Y.Z --port PORT [--steward STEWARD]
    # C, ZeroTier: the zerotier address `detect` printed
    python3 "KIT/onboard.py" write --project . --name NAME --auth link \
        --listen ZT_ADDRESS --port PORT [--steward STEWARD]
    # D, this machine only
    python3 "KIT/onboard.py" write --project . --name NAME --auth link --port PORT [--steward STEWARD]

The refusals and `REVIEW` lines are handled as in section 3. Show any
`warning` or `NOTE` line too: a NOTE means the address is on no interface
yet, and the server will wait for it up to 2 minutes when it starts.

Hand over the printed next steps **verbatim and in order**, each the user's
to run: `install.sh --start`, `agent.py register`, how to reach the console
(the `tailscale serve` line, or `http://ADDR:PORT`), `agent.py invite
YOU@EXAMPLE.COM --origin ...` **in their own terminal** (it prints a link that
works once; a session is refused), `onboard.py verify`, and "Make me the
administrator". Say that a browser signs in once per address it uses.
**Never run `invite` and never ask for the email it takes.**

When they have run step 2, the SessionStart note and the `console-process`
skill work in this project from the next session.
