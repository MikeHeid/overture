# The Overture protocol, version 1.0

**Status:** published with Overture 1.55. **Records:** `schemaVersion` 1.
**License:** MIT, the same as the rest of this repository.
**Files:** this page is normative. [`overture-protocol-1.schema.json`](overture-protocol-1.schema.json)
checks one record's shape, and [`vectors/`](vectors/) holds conformance cases. Where they disagree,
this page wins; `test_spec.py` keeps all three in step with the reference implementation.

The words MUST, MUST NOT, SHOULD and MAY are used as RFC 2119 defines them.

## 1. What it is for

An agent working on a project often reaches a decision that belongs to a person. This protocol is how
it asks. The agent writes a **question** with typed options and a recommendation (the ★). The owner
writes an **answer** and then **locks** it. From then on the lock is a **ruling** that every agent
follows. Each question says what must stay true for its ruling to stand (`valid_if`), so any reader
can tell, without asking anyone, whether a ruling is still **fresh** or has gone **stale**.

Terms:

- **owner**: the person who decides. **agent**: any program that asks.
- **item**: a unit of work in the project's own tracker, named by an item id such as `PAY-2`.
- **store**: the append-only file that holds every record.
- **ruling**: a locked answer.

Version 1.0 covers the four decision kinds, `question`, `answer`, `lock` and `anchor`, and the
**ruling file** that carries a ruling into a repository (section 13). Overture's stores also hold
`message`, `transcript` and `visual` records, which belong to its console and are not part of this
protocol (section 11).

## 2. The store

A store is a UTF-8 text file. It holds one JSON object per line, and every line ends with a line feed.

- **Append-only.** A record is written once. No record is ever edited or removed. A decision changes
  only through a new record (section 6).
- **Sequence.** The record on line *n* carries `seq` *n*, counting from 1.
- **Cut writes.** A reader MUST refuse a store whose last line has no line feed. That line is a cut
  write, and the reader MUST NOT guess what it said.
- **Edits.** A reader MUST refuse a store in which any line's `seq` or `id` does not match its line
  (section 3). Such a file was edited.
- **One writer.** Only one process appends to a store. The store rules in section 9 compare a new
  record with the ones already written, and two writers could both pass the same check.
- **Other kinds.** A reader of this protocol MUST skip a record whose `type` is not one of the four
  decision kinds, and it MUST still count that record's line for `seq`.

Who may write each kind:

| Kind | Written by (`by`) | What it does |
|---|---|---|
| `question` | `agent` | asks the owner one thing |
| `answer` | `owner` | picks options, says something in the owner's own words, or both |
| `lock` | `owner` | makes the current answer a ruling |
| `anchor` | `agent` | moves the current lock's conditions to where their evidence now lives |

The store stamps `by` from the door a record arrived through. A writer never chooses its own author.

## 3. Every record

| Field | Type | Who sets it | Meaning |
|---|---|---|---|
| `type` | string | writer | `question`, `answer`, `lock` or `anchor` |
| `schemaVersion` | integer | writer, or the store by default | always `1` in this version |
| `by` | string | the store | `agent` or `owner` (section 2) |
| `nonce` | string | writer | 8 to 64 of `A-Z a-z 0-9 _ -`; a fresh one for every new write |
| `id` | string | the store | 24 lowercase hex characters, derived below |
| `seq` | integer | the store | the record's line number |
| `ts` | string | the store | UTC time it was written, `YYYY-MM-DDTHH:MM:SSZ` |

A writer MUST NOT send `id`, `seq` or `ts`, and the store MUST refuse a record that carries one.

**Unknown fields are refused.** A record with a field this version does not define is invalid, and
a reader MUST refuse it by name rather than drop the field. This lets a newer writer add a field
without an older reader misreading it (section 10).

**Deriving the id.** Take the record without `id`, `seq`, `ts` and `schemaVersion`, and keep `type`.
Write it as canonical JSON: keys sorted, no whitespace between tokens, non-ASCII characters as
themselves in UTF-8, and only the escapes JSON requires. For these four kinds that is the same as
RFC 8785 (JCS). The id is the first 24 hex characters of the SHA-256 of those bytes.

The question in the first store vector (`vectors/store.json`) has the canonical form

```
{"by":"agent","item":"PAY-2","kind":"single","nonce":"q1-nonce-0001","options":[{"description":"One more try after 30 s; cheap","id":"retry_once","label":"Retry once"},{"description":"Fail at once; the caller decides","id":"no_retry","label":"Never retry"}],"qid":"PAY-2/Q1","source":"docs/payments.md:12-14","star":"retry_once","text":"Should a failed charge retry, and how often?","type":"question","valid_if":[{"kind":"excerpt","path":"docs/payments.md","text":"A charge is attempted at most twice."}]}
```

and so the id `98a1914cb7823acef2e3e563`.

**Retries.** Sending the same record again, with the same nonce, derives the same id. The store
MUST return the record it already holds and write nothing. A flaky network therefore cannot write
a decision twice. Two separate writes carry different nonces and are two records, even when they
say the same thing.

**Text fields.** "Non-empty" means it holds something other than whitespace. A **one-line** field
holds no line feed, carriage return, U+2028 or U+2029. Lengths count Unicode code points.

## 4. `question`

| Field | Required | Shape |
|---|---|---|
| `qid` | yes | `<item id>/Q<n>`, where n is 1 or more; its item part MUST equal `item` |
| `item` | yes | an item id: a letter or digit, then letters, digits, `_`, `.` or `-` |
| `text` | yes | non-empty, at most `MAX_TEXT` = 20,000 characters: what to decide and the facts it rests on |
| `kind` | yes | `single` (one pick), `multi` (any number) or `free` (own words only) |
| `options` | yes | at most `MAX_OPTIONS` = 12; `single` and `multi` offer at least 2, `free` offers none |
| `star` | yes | the recommended option's id, or `null` |
| `valid_if` | yes | at most `MAX_VALID_IF` = 16 conditions (section 8); it may be empty |
| `source` | yes | the repository path the question rests on, optionally `:line` or `:line-line`, at most 300 characters |
| `star_by` | no | whose ★ it is: `panel`, `architect`, `ux`, `security`, `determinism`, `devops`, `adversarial`, `analyst`, or `other:<role>` (1 to 40 letters, digits, spaces or hyphens). Only when `star` is not `null` |
| `forked_from` | no | the id of the owner's request that this question came out of. A forked question with a ★ MUST carry `star_by` |
| `evidence` | no | 1 to `MAX_EVIDENCE` = 8 rows (below) |

Each **option** is `{id, label, description?}`, with no other fields. The `id` is a lowercase letter
followed by lowercase letters, digits or `_`, and it is unique within the question. The `label` is
non-empty and one line. The `description`, which may be empty, is one line that says what the option
does and what it costs. Both are at most `MAX_LINE` = 300 characters.

A `qid` is minted once. A second question with the same `qid` is refused, even if the first one was
never answered.

**Evidence rows.** Each row is `{cite, command?, result?, text}`:

- `cite`: `path:line` or `path:start-end`. The path is relative, its parts are `A-Z a-z 0-9 _ . -`, and
  none is empty or `..`. The range names 1 to `MAX_EVIDENCE_LINES` = 200 lines, and start comes before end.
- `command`: one line, the command that was run.
- `result`: non-empty, at most `MAX_EVIDENCE_RESULT` = 2,000 characters, what it printed.
- `text`: the cited lines as the store read them when the question was asked, at most
  `MAX_EXCERPT` = 4,000 characters. The **store** reads and fills in `text`; a writer MUST NOT send
  it (Appendix A). A reader can compare `text` with the file now to show whether the evidence changed.

## 5. `answer`

| Field | Required | Shape |
|---|---|---|
| `qid` | yes | the question answered; it MUST exist |
| `picks` | yes | option ids of that question, no repeats; at most one for a `single` question |
| `own_text` | yes | the owner's own words, at most 20,000 characters, may be empty |
| `supersedes` | with `reason` | the id of the answer this one replaces |
| `reason` | with `supersedes` | non-empty: why the ruling changed |

An answer MUST pick something or say something: `picks` and `own_text` are not both empty.

A question's **current answer** is its latest answer. A new answer to an unlocked question simply
becomes the current one.

## 6. `lock`

| Field | Required | Shape |
|---|---|---|
| `qid` | yes | the question |
| `answer` | yes | the id of that question's **current** answer |
| `anchors` | no | 1 to 16 conditions this lock is judged by, instead of the question's `valid_if` |

Each answer is locked at most once. A lock is **never undone.** To change a ruling, the owner writes
a new answer that names the locked one in `supersedes` and gives a `reason`, and then locks that new
answer. Once a question is locked, the store MUST refuse a new answer to it that does not supersede
the current one. A lock's `anchors`, when present, were computed by the store from the project as it
stood when the lock was written. They exist so that a re-lock is judged against today's code and not
the code the question was first asked about.

## 7. `anchor`

| Field | Required | Shape |
|---|---|---|
| `qid` | yes | the question |
| `lock` | yes | the id of the question's **current** lock |
| `anchors` | yes | 1 to 16 conditions |
| `basis` | yes | non-empty: why these conditions carry the same ruling, e.g. "moved from billing.py with the same body" |

An agent writes an anchor when a ruling's evidence moved but did not change, for example when an
excerpt's paragraph moved to another file. It re-anchors only the current lock. The latest anchor
for a lock replaces that lock's conditions (section 8.2).

## 8. Conditions

### 8.1 The four kinds

Every condition is an object with exactly the fields below, all of them non-empty strings.

| `kind` | Fields | Holds when |
|---|---|---|
| `file_sha256` | `path`, `sha256` | the SHA-256 of the file's bytes, in lowercase hex, equals `sha256` |
| `item_status` | `item`, `status` | the item's status in the project's tracker equals `status` |
| `excerpt` | `path`, `text` | the normalised `text` occurs in the normalised file |
| `symbol` | `path`, `symbol`, `sha256` | the definition named `symbol` in `path` has the body hash `sha256` |

**Paths** are relative to the project root. They do not start with `/`, have no `..` part and hold
no control character. A `symbol` path is at most 300 characters.

**`excerpt`.** To normalise, replace every run of whitespace (line endings included) with one space
and trim both ends. The excerpt's `text` is at least `MIN_EXCERPT` = 8 characters once normalised,
because a shorter one matches by accident, and at most 4,000 characters as written, because a longer
one is a whole-file hash by another name. The file is read as UTF-8, and a byte sequence that is not
valid UTF-8 reads as U+FFFD. An excerpt survives a move within its file and a re-wrapped paragraph.
It does not survive a change to its words.

**`symbol`.** The `symbol` field is a dotted name such as `Ledger.charge` or `outer.inner`: parts of
letters, digits, `_` and `$`, where a part does not start with a digit (it may start with `#`), and
at most `MAX_QUALNAME` = 200 characters in all. The body hash is defined by the normalisation named
`overture-symbol-1` and implemented in `plugin/kit/overture/symbols.py`. Comments are dropped,
whitespace in code counts only between two word characters, the definition's own name is blanked
(so a rename alone keeps the hash), literals count verbatim, and line endings never count. It covers
Python (`.py`, `.pyi`), JavaScript and TypeScript, Go, Rust, Java and C#. This version does not
restate that algorithm in prose. **A reader that does not compute `overture-symbol-1` MUST report a
`symbol` condition as unchecked (8.3), never as holding.**

When `symbol` is not found at its name, a reader MAY look for the same body hash in the same file and
in files the change touched, in the same language. Found exactly once, the code **moved**. Found in
more than one place, which one the ruling meant cannot be told, so the condition is unchecked. Found
nowhere, it is **gone**. A name defined twice in one file is unchecked.

**Reading files safely.** A reader MUST NOT read a file that resolves outside the project root, and
SHOULD NOT follow a symbolic link at any depth. It MUST NOT read a secrets file: anything under a
`.git` or `.ssh` directory, or a file named `.env*`, `*.pem`, `*.key`, `id_rsa*`, `id_ed25519*`,
`*.p12` or `*.pfx` (case-insensitive). The reference does not read a file over 2 MiB. A condition on
a file that cannot be read, for any of these reasons or because it is missing, does not hold.

### 8.2 Which conditions decide a ruling

For an unlocked question, its `valid_if` decides. For a question whose current answer is locked, the
first of these that exists decides:

1. the latest `anchor` record for that lock;
2. the lock's own `anchors`;
3. the question's `valid_if`.

(The reference also keeps, beside the store, anchors the owner confirmed after a symbol moved. A
reader that does not read that log falls through to the list above and reports such a ruling stale,
never fresh.)

### 8.3 Fresh, stale and unchecked

A ruling is **fresh** when every deciding condition holds, and **stale** otherwise. A ruling with no
conditions is never stale. A strict checker MAY still report it, because nothing can tell it has gone out of date.

A checker that runs on a change, such as a pull-request check, SHOULD report each condition as one of three things:

- **holds**: it holds, or its `symbol` moved and was found exactly once;
- **broken**: it does not hold;
- **unchecked**: the checker cannot tell. Examples: a `symbol` in a language it does not read, a file that does not parse, a name defined twice, or an `item_status` it has no tracker for.

A checker MUST NOT report an unchecked condition as holding. In a store's own view, a moved
`symbol` shows stale until a new `anchor` records where it went.

## 9. Checks beyond the JSON Schema

The JSON Schema checks each field's type, shape, length and count, and the kind-specific rules above
that one record can show. These checks need more than a JSON Schema can say, and a conforming store
MUST make them too:

**Within one record:**

- a question's `qid` names its own `item`;
- `star` is one of the question's option ids, and option ids do not repeat;
- an `excerpt` is at least 8 characters **after** normalisation (the schema checks 8 as written);
- an evidence `cite` names 1 to 200 lines, start before end.

**Against the store (section 2's single writer):**

- a `qid` is minted once;
- an answer's `qid` names an existing question, its picks are that question's options, and a
  `single` question gets at most one pick;
- `supersedes` names the question's current answer, and an answer to a locked question supersedes;
- a lock names the question's current answer, and locks it once;
- an anchor names the question's current lock;
- a `forked_from` names an owner's request;
- when the store knows the tracker's item list, a question's `item` is on it.

## 10. Conformance

- **A conforming writer** sends only records that are valid under sections 3 to 8 and pass the JSON
  Schema, without `id`, `seq` or `ts`.
- **A conforming store** makes every check in section 9, assigns `id`, `seq` and `ts` as section 3
  says, and returns the stored record on a retry.
- **A conforming reader** refuses a store that fails section 2, skips kinds it does not know, and
  decides fresh and stale as section 8 says.

The vectors make this testable. `vectors/records.json` lists single records, each marked `valid` or
not. An invalid one also says whether the JSON Schema alone catches it (`schema_catches`) and gives
the words the reference uses (`reference_error`, informative only). `vectors/store.json` lists
sequences of writes, each accepted, with its `id` and `seq`, or refused. Every id in it can be
checked against section 3. `vectors/rulings.json` lists ruling files (section 13) in the same way
as the records, with each file's name.

### Versioning and compatibility

The protocol has its own version, `major.minor`, separate from Overture's release number.

- **A minor version** adds something optional: a field, a condition kind or a value. Every record
  that was valid stays valid and means the same, so `schemaVersion` stays 1. A reader of an older
  minor version refuses the new thing by name, as section 3 requires, and never reads it as
  something else.
- **A major version** changes what a valid record means. It raises `schemaVersion`, and a reader
  MUST refuse a record whose `schemaVersion` it does not know rather than coerce it.

## 11. What 1.0 does not cover

- **Transport and authentication.** How a writer reaches a store is the implementation's business.
  Overture's is in Appendix A.
- **The item tracker.** Where item ids and statuses come from is the project's business.
- **Console kinds.** `message` (threads, the owner's requests for deliberation, chat), `transcript`
  and `visual` records, and the log beside the store where the owner settles stale rulings, are
  Overture's own. They may change without a protocol version, and readers of this one skip them. What
  that log decides reaches a ruling file as `outcome` (section 13).
- **Adapters for other agent tools.** These are separate work. Any tool that speaks MCP can already
  ask through Appendix A.

## 12. Limits

| Constant | Value | Applies to |
|---|---|---|
| `MAX_TEXT` = 20000 | characters | `text`, `own_text`, `reason`, `basis` |
| `MAX_LINE` = 300 | characters | option labels and descriptions, `source`, `cite`, `command`, a `symbol` path |
| `MAX_OPTIONS` = 12 | options | `options`, `picks` |
| `MAX_VALID_IF` = 16 | conditions | `valid_if`, a lock's or an anchor's `anchors` |
| `MAX_EVIDENCE` = 8 | rows | `evidence` |
| `MAX_EVIDENCE_LINES` = 200 | lines | one evidence `cite` |
| `MAX_EVIDENCE_RESULT` = 2000 | characters | an evidence `result` |
| `MIN_EXCERPT` = 8 | characters, normalised | an `excerpt`'s `text` |
| `MAX_EXCERPT` = 4000 | characters | an `excerpt`'s `text`, an evidence row's `text` |
| `MAX_QUALNAME` = 200 | characters | a `symbol` name |

The names are the constants in `plugin/kit/overture/schema.py`.

## 13. Ruling files

A ruling also travels as a file committed to the project's repository, so a pull-request check or any
other tool can read it without the store. Overture writes them with `fold.py export`, into
`.overture/locked/` unless the project's `.overture.json` names another folder in `fold.locked`.

- **One file per ruling**: one for every question whose current answer is locked, named by its `qid`
  with `/` written as `__`, plus `.json` (`PAY-2/Q1` is `PAY-2__Q1.json`).
- **Byte form**: JSON with keys sorted, an indent of two spaces, non-ASCII characters as themselves in
  UTF-8, and a final line feed. A ruling that has not changed exports to the same bytes.
- **Shape**: check a file against `#/$defs/rulingFile` in the JSON Schema. The schema's root checks
  a store record.

**The question, as it was put:** `qid`, `item`, `kind`, `options`, `star`, `source`, `valid_if`, and
`forked_from`, `star_by` and `evidence` when the question has them, with the meanings in section 4.
Three fields are renamed: `question` is the question's `text`, `asked_by` its `by` (always
`agent`), and `asked_at` its `ts`. `asked_by_agent`, when present, is the short name of the session
that asked (1 to 32 lowercase letters, digits and single hyphens, starting with a letter, and not
`agent` or `owner`). It is never an email address.

**The answers:**

| Field | What it holds |
|---|---|
| `locked` | the current, locked answer |
| `history` | earlier answers that were locked and later superseded, oldest first |
| `earlier` | answers that were never locked, at most 100 |
| `order` | every answer's id in store order. A writer MUST write it. A reader accepts a file without it only when `earlier` is empty, and then takes the order of `history` followed by `locked` |

A **locked answer** carries `answer_id`, `picks`, `own_text`, `by` (`owner`) and `answered_at`
from its answer, and `lock_id`, `locked_by` (`owner`) and `locked_at` from its lock. It also carries
`supersedes` and `reason` when the answer has them, and three fields derived from the question:
`picked_labels`, `rejected_labels` and `picked_star`. A reader MUST recompute the derived fields and
refuse the file when they differ, because they are what gets printed. `locked_by_name`, when
present, is the short name the owner gave the login that locked it. When the ruling is not decided
by the question's `valid_if` (section 8.2), the answer also says what decides it. `anchored_by`
is `lock`, with `anchors`. Or it is `reanchor` or `confirmed`, with `anchors`, `anchor_id`,
`anchor_basis` and `anchored_at`.

An **earlier answer** carries exactly `answer_id`, `picks`, `picked_labels`, `own_text`, `by` and
`answered_at`, plus `supersedes` and `reason` together.

**What became of a stale ruling** (optional):

- `outcome`: the owner settled it, so it is no longer reported stale. It is `{kind, by, at, record,
  …}`, with `by` always `owner`. A `withdrawn` outcome carries a `reason`. An `untracked` one (kept,
  but no longer checked) may carry one. A `superseded` one names the newer question in `replaced_by`.
- `replaces`: the `qid` of an older ruling that this question was asked to replace.
- `fork`: when `forked_from` is present, the owner's request it names, as Overture stored it. Its
  shape is Overture's own (section 11). Its `id` MUST equal `forked_from` and derive from it as
  section 3 says.

**Checks beyond the JSON Schema.** These files arrive by pull request, not through the store, so a
reader MUST check them as strictly as the store checked the records:

- the file name matches the `qid`, and the question part passes section 9's checks within one record;
- every pick is one of the options, and the derived fields match;
- `order` lists every answer exactly once, the locked answers appear in it in sequence, and it
  ends on `locked`;
- replaying `order`: the first answer supersedes nothing, an answer that follows a locked one
  supersedes it, and an answer that follows an unlocked one supersedes nothing or that one;
- `replaces` and `replaced_by` name another question, not this one;
- `fork` is an owner's request for deliberation whose id is `forked_from`;
- when the reader knows the tracker's item list, `item` is on it.

A writer MUST NOT add fields. A reader SHOULD refuse a field this section does not define.

## Appendix A. Overture's transport (informative)

Overture's server is the store's single writer. Agents reach it through `agent.py`, or through its MCP
server, `plugin/kit/mcp_server.py`, which any MCP client can launch over stdio. The MCP tools are
`todo`, `view`, `answers`, `check`, `lesson_match`, `health`, `ask`, `reply`, `working` and `rulings`;
[MCP and CI](../features/mcp-and-ci.md) describes them.

A request to `ask` differs from the stored question in three ways:

- it carries no `by`, `id`, `seq`, `ts` or `schemaVersion`, all of which the server stamps;
- an evidence row carries no `text`, which the server reads from the cited lines. The server also
  refuses a `cite` or a condition path that names a secrets file (8.1);
- a `valid_if` entry may be the string `"path::Class.method"`. The server reads that definition and
  stores a full `symbol` condition with its body hash.

The pull-request check (`rulecheck.py`, the repository's `action.yml`) is the reference for section
8.3: `--strict` fails on unchecked rulings and on rulings with no conditions.
