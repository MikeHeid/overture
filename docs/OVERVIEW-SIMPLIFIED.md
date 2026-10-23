# Overture, explained simply

[← Back to README](../README.md)

A plain-language tour for anyone new to Overture: what it is, how to start,
and how it helps a coding project. The feature pages under
[features/](features/) have the full detail.

## The problem it solves

Say you're building a game, a Discord bot or a website, with an AI coding
agent such as Claude Code helping. Every few minutes the agent stops and
asks you something:

> "Should scores be saved in a file or a database?"
> "How many times should I retry when the server doesn't answer?"
> "Which login system do you want?"

Without Overture:

- Each question waits in its own terminal. With three agents, you hop
  between three terminals.
- You answer, the session ends, and **the answer is gone**. Tomorrow a new
  agent asks again, or quietly picks something different.
- Weeks later you change some code, and nobody remembers that an old
  decision depended on it.

## What Overture is

Overture is **one inbox web page for all your agents' questions**. Open it
on your laptop or your phone. It's free and open source (MIT), and it runs
on your own computer, so nothing goes to an outside service.

1. **The agent asks.** It lists two to four options, stars (★) the one it
   recommends, and shows the bit of code that matters.
2. **You answer.** Tap an option, or add your own words. When you're sure,
   you **lock** it.
3. **Every agent remembers it.** A locked answer is a **ruling**. Rulings
   are saved in your project's git history, so they last as long as the
   project does.

## The clever part: stale rulings

Each ruling remembers **which code it was decided on**, down to a single
function. Say you ruled "retry 3 times" because of how `fetchScores()`
worked, and later you rewrite `fetchScores()`. Overture marks the ruling
**stale**: the code it was decided on has changed, so check it's still
right. You never keep following a decision whose reasons have gone.

## Getting started

You need Claude Code. Inside it, run:

    /plugin marketplace add MikeHeid/overture
    /plugin install overture@overture
    /overture:console-onboard

The last command sets up your project. Its main question is how you'll
sign in to your inbox:

- **Simplest:** one-time sign-in links, on your own computer.
- **From your phone:** Tailscale or ZeroTier, free tools that link your own
  devices.
- **From anywhere:** a free Cloudflare account.

After that, your agents post their questions to the console instead of a
terminal.

## A tour of the console

- **Inbox:** questions waiting for you, with a badge for new ones.
- **Rounds:** several questions sent together. Step through them like a
  quiz with the arrow keys and number keys, then lock them all at once.
- **Feed:** a timeline of everything that happened.
- **Chat:** talk to your agents about anything, not only a question.
- **Project map:** your project's parts, coloured by how settled each is
  (open, stale, unlocked, locked).
- **Status bar:** how many agents are working right now.

## Seeing your project: visuals, charts and screenshots

Overture shows your project as pictures, not just text.

- **Ask for a visual.** On any part of your project, press **Request a
  visual**. An agent draws a diagram, such as a flowchart of how your login
  works, or a rough HTML mock-up of a screen. Diagrams are written in
  Mermaid, a simple text format for charts, and you can always see that
  text. A chime plays when one arrives.
- **Versions side by side.** Ask again and you get a second version. Step
  between "v1 of 2" and "v2 of 2" with the arrows to compare.
- **Save as SVG.** Every chart and diagram downloads as an image file for a
  README, a slide or homework.
- **Status flowchart.** Every item gets an automatic chart of its questions
  and rounds, coloured open, stale or locked. Click a box to jump to that
  question.
- **Impact graph.** A map of what connects to what: the item, its
  questions, its rulings and the files they mention. Click something to
  light up everything downstream of it, which shows what a change would
  affect.
- **Pop out.** Pull a chart into its own floating panel and keep it open
  beside your work.
- **Before and after screenshots.** When an agent changes something you can
  see, it posts a "before" and an "after". Flip through them full size, and
  attach your own sketch or screenshot too.

Everything an agent draws is shown in a locked-down frame with scripts
switched off, so a drawing can't run code in your console.

## Designing screens: UX View

For the parts of your app people look at, such as a menu, a pricing card or
a settings page, Overture has a full-screen design studio.

1. Mark a part of your project as UI (`"ux": true` in your settings).
2. Open **◫ UX View** (or press `u`). Every mock-up version of that screen
   appears in a safe preview.
3. Switch between **Mobile**, **Tablet** and **Desktop** sizes to check it
   works everywhere.
4. Press **Generate** to ask an agent for another version. Step through
   them with ◂ ▸ and keep the ones you like.
5. Already have a design in Claude Design? Link it, tick up to 10 pieces of
   it, and mark each **inspire** (borrow the look) or **swap** (build the
   new version from it).
6. Happy with one? **Save as component**. The agent saves it into your
   project through a pull request, so you review it like any other code,
   and the old version is kept in the history.

Interactive mock-ups (with JavaScript) are off by default. You turn them
on for one version yourself, and they still run walled off from the
console.

## Your own dashboard

Overture can sit beside a dashboard page of your project: its waves,
phases and lanes, and how far along each is. One command builds a starter
page, and Overture colours it by lane. Only you can publish a new version
of it; an agent can suggest one but never put it live.

## When you're not sure what to answer

Under any answer, **Next step ▾** offers helpers:

- **Deliberate:** agents lay out the options, trade-offs and a
  recommendation, so you only have to pick.
- **Roar:** a three-round panel. Several expert agents give opinions,
  argue, then agree on a plan.
- **Refine / Drill:** go deeper on one answer and turn it into a spec.
- **Grill:** agents poke holes in your plan before you build it.

## How it helps your coding projects

1. **No more babysitting.** Agents keep working while their questions wait
   in one place. Answer when you're free, even from your phone.
2. **A memory for the project.** Every "why is the code like this?" has a
   written answer, with who decided it and when. Handy after a month away,
   or when a friend joins.
3. **Agents check before editing.** Before an agent changes a file, it can
   see the rulings that touch it, so it doesn't undo something you decided
   on purpose.
4. **A safety net on pull requests.** A check can warn when a change
   touches code a ruling depends on.
5. **See it, don't just read it.** Diagrams, impact graphs and screenshots
   make a big project easier to understand.
6. **Design faster.** Generate screen versions, compare them at phone and
   desktop size, and save the winner by pull request.
7. **Not only Claude Code.** Codex, Cursor and GitHub Copilot can use it
   too.
8. **Several projects?** One portfolio page shows what's waiting across all
   of them.

## Automation, once you're comfortable

- **Playbooks:** save a routine, such as "every Monday, review open
  questions and post a summary", and run it with one click.
- **Triggers:** run a playbook on a schedule, or when GitHub says something
  happened, like a pull request opening. GitHub signs its message, so
  nobody can fake one.
- **Notifications:** a short message to Slack or Discord when questions are
  waiting. It says how many and where; the questions stay in the console.

## For teams

- Everyone gets a **role**: owner, member (answers in certain areas) or
  viewer (reads only).
- Every lock records **who** made it.
- Risky areas can need **two people** to agree before an answer locks.
- Pull requests that mention a ruling appear beside it. Ones from people
  outside your team are dimmed, so a stranger can't make their work look
  approved.

## Good habits

- **Lock only when you're sure.** An unlocked answer is a draft.
- **Treat stale rulings as homework.** Often the answer is still right and
  you just confirm it.
- **The ★ is a suggestion, not an order.** Read the options. Overture
  tracks how often you just accept the star, so you can tell if you're
  rubber-stamping.
- **Start small:** one project, one agent, a handful of questions. You'll
  see the payoff the first time a new agent already knows what you decided
  last week.
