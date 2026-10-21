"""The functions, classes and methods in a source file, found without running anything (1.54, owner K1-K3).

A `symbol` condition ties a ruling to one definition by its qualified name
(`Class.method`, `outer.inner`) and the hash of its body, so a ruling outlives
edits elsewhere in the file (K2) and can follow its code through a rename or a
move (K3). This module finds the definitions; `anchors.py` decides what a
change to them means.

- **Python** (`.py`, `.pyi`) is read with the standard library's `ast`, so a
  definition is exactly what Python sees: functions, async functions, classes,
  methods and nested definitions, decorators included.
- **JS/TS, Go, Rust, Java and C#** are read by their definition lines
  (`function`, `class`, `const f = (...) =>`, `func`, `fn`, `struct`, `impl`,
  `interface`, a method in a class body), and a body is matched brace to brace
  over a copy of the file in which every comment and every string, character,
  template and regex literal is blanked, so a brace inside one never counts.
  C and C++ are not read: their definitions cannot be told from their
  declarations by one line.

**The body hash** is the sha256 of the definition's text with comments
dropped, whitespace in code normalised (it counts only between two word
characters) and the definition's own name blanked, so a rename alone keeps the
hash and a moved or renamed body can be found by it. Docstrings and literals
are code and count verbatim, whitespace inside them included (1.54 review C1).
Line endings never count.

**Never a guess.** A file this cannot read (an unknown extension, a syntax
error, an unclosed literal, braces that do not balance, past its bounds) raises
`Unresolvable` with the reason, and a name defined twice in one file resolves
to `unchecked`, not to either one; so does one redefined where no definition
line is read (after `;` or other code on a line, or in Python by an assignment
or an import in its own scope: 1.54 review M2). Every read is bounded (MAX_CHARS,
MAX_SYMBOLS, MAX_SIGNATURE) and nothing recurses on the input, so a hostile
file cannot hang a hook.

Standard library and `schema` only, no git, no project code: hooks import it.
"""

from __future__ import annotations

import ast
import bisect
import hashlib
import io
import re
import threading
import tokenize
from typing import NamedTuple

from .schema import MAX_QUALNAME, QUALNAME   # the one shape a `symbol` condition's name is held to

MAX_CHARS = 1 << 20      # a larger file is not read for symbols (its anchor reports unchecked)
MAX_SYMBOLS = 5000       # definitions in one file, at most
MAX_SIGNATURE = 4000     # characters between a definition's name and its body's opening brace
MAX_DEF_LINE = 2000      # a longer line is never read as a definition line
MEMO_SIZE = 8            # texts whose parse `find` keeps (oldest first out)
HASH_PREFIX = "overture-symbol-1\n"   # changes only if the normalisation does

_MEMO: dict[tuple[str, str], tuple[Symbol, ...] | str] = {}
_MEMO_LOCK = threading.Lock()   # the console server reads symbols on several threads

LANGS = {".py": "python", ".pyi": "python",
         ".js": "js", ".mjs": "js", ".cjs": "js", ".jsx": "js", ".ts": "js", ".mts": "js", ".cts": "js",
         ".tsx": "js", ".go": "go", ".rs": "rust", ".java": "java", ".cs": "csharp"}


class Symbol(NamedTuple):
    qualname: str
    kind: str
    start_line: int      # 1-based, decorators and attributes included
    end_line: int        # 1-based, inclusive
    body_sha256: str


class Resolution(NamedTuple):
    """`state` is 'found' (then `symbol`), 'missing' (the file reads, the name is not in it) or 'unchecked' (`reason`)."""
    state: str
    symbol: Symbol | None
    reason: str


class Unresolvable(Exception):
    """This file's symbols cannot be read; the message says why, in words that follow "because"."""


def language(path: str) -> str | None:
    """The language a path's extension names, or None when it is not one this reads."""
    dot = path.rfind(".")
    return LANGS.get(path[dot:].lower()) if dot > path.rfind("/") else None


def qualname_problem(q: object) -> str | None:
    """Why `q` is not a dotted qualified name this kit takes (one line, at most MAX_QUALNAME); None when it is."""
    if not isinstance(q, str) or len(q) > MAX_QUALNAME or not QUALNAME.match(q):
        return (f"symbol must be a dotted name such as Class.method (letters, digits, _ and $; at most "
                f"{MAX_QUALNAME} characters)")
    return None


def split(ref: object) -> tuple[str, str] | None:
    """('path', 'Class.method') from the `path::Class.method` form agents write, or None when it is not one."""
    if not isinstance(ref, str) or ref.count("::") != 1:
        return None
    path, _, q = ref.partition("::")
    return (path, q) if path and q else None


def find(path: str, text: str) -> list[Symbol]:
    """Every definition in `text` (the content of `path`), in file order; Unresolvable when it cannot be read.

    Memoised on (path, text) for the last few texts (1.54 review M1): the
    lookup reads one file's old and new text for every condition of every
    ruling on it, and each parse is one pass over up to MAX_CHARS.
    """
    key = (path, text)
    with _MEMO_LOCK:
        got = _MEMO.get(key)
    if got is None:
        try:
            got = tuple(_find(path, text))
        except Unresolvable as e:
            got = str(e)
        with _MEMO_LOCK:
            _MEMO[key] = got
            while len(_MEMO) > MEMO_SIZE:
                del _MEMO[next(iter(_MEMO))]
    if isinstance(got, str):
        raise Unresolvable(got)
    return list(got)


def clear_cache() -> None:
    """Forget every memoised parse (a test that counts them starts here)."""
    with _MEMO_LOCK:
        _MEMO.clear()


def _find(path: str, text: str) -> list[Symbol]:
    lang = language(path)
    if lang is None:
        raise Unresolvable(f"{path} is not a language this reads (Python, JS/TS, Go, Rust, Java, C#)")
    if len(text) > MAX_CHARS:
        raise Unresolvable(f"{path} is over {MAX_CHARS >> 20} MiB")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    try:
        syms = _python(text) if lang == "python" else _lexical(text, lang, _may_hold_jsx(path, lang))
    except (RecursionError, MemoryError):
        raise Unresolvable(f"{path} nests too deeply to read") from None
    except Unresolvable as e:
        raise Unresolvable(f"{path} cannot be read for definitions: {e}") from None
    except (KeyError, IndexError, ValueError) as e:   # a shape the reader did not foresee: unchecked, never a crash
        raise Unresolvable(f"{path} cannot be read for definitions ({type(e).__name__})") from None
    if len(syms) > MAX_SYMBOLS:
        raise Unresolvable(f"{path} has over {MAX_SYMBOLS} definitions")
    return syms


def _may_hold_jsx(path: str, lang: str) -> bool:
    """Whether `path` may hold JSX: a JS file, or TSX; plain TypeScript (.ts, .mts, .cts) cannot."""
    return lang == "js" and not path.lower().endswith((".ts", ".mts", ".cts"))


def resolve(path: str, text: str, qualname: str) -> Resolution:
    """The one definition named `qualname` in `text`: found, missing, or unchecked (unreadable, or named twice)."""
    try:
        syms = find(path, text)
    except Unresolvable as e:
        return Resolution("unchecked", None, str(e))
    same = [s for s in syms if s.qualname == qualname]
    if len(same) > 1:
        return Resolution("unchecked", None, f"{qualname} is defined {len(same)} times in {path}")
    if not same:
        return Resolution("missing", None, f"{path} defines no {qualname}")
    return Resolution("found", same[0], "")


def enclosing(path: str, text: str, start: int, end: int) -> Resolution:
    """The innermost definition holding lines `start`-`end` (1-based, inclusive), when its name is unique there."""
    try:
        syms = find(path, text)
    except Unresolvable as e:
        return Resolution("unchecked", None, str(e))
    holding = [s for s in syms if s.start_line <= start and end <= s.end_line]
    if not holding:
        return Resolution("missing", None, f"no definition in {path} holds lines {start}-{end}")
    inner = min(holding, key=lambda s: (s.end_line - s.start_line, -s.start_line))
    if sum(s.qualname == inner.qualname for s in syms) > 1:
        return Resolution("unchecked", None, f"{inner.qualname} is defined more than once in {path}")
    return Resolution("found", inner, "")


def by_body(path: str, text: str, sha256: str) -> list[Symbol]:
    """The definitions in `text` whose body hash is `sha256` (K3: a renamed or moved body); Unresolvable as `find`."""
    return [s for s in find(path, text) if s.body_sha256 == sha256]


def _digest(normalised: str) -> str:
    return hashlib.sha256((HASH_PREFIX + normalised).encode("utf-8", errors="surrogatepass")).hexdigest()


# -- Python, through ast ------------------------------------------------------------------------

_SKIP_TOKENS = frozenset({tokenize.COMMENT, tokenize.NL, tokenize.ENCODING, tokenize.ENDMARKER})
_MARK = {tokenize.NEWLINE: "\x01", tokenize.INDENT: "\x02", tokenize.DEDENT: "\x03"}


def _python(text: str) -> list[Symbol]:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError) as e:
        raise Unresolvable(f"it does not parse as Python ({type(e).__name__}: {getattr(e, 'msg', e)})") from None
    defs = []   # (qualname, kind, first line, last line, the line of `def`/`class`, the name)
    # (scope prefix, name) -> where each binding of it that is not a def or class sits: (line, column)
    rebound: dict[tuple[str, str], list[tuple[int, int]]] = {}
    starred: dict[str, list[tuple[int, int]]] = {}   # scope prefix -> where a `from x import *` sits
    defs_at: dict[str, tuple[int, int]] = {}      # qualname -> where its def or class statement sits
    # Each node with its scope's prefix, whether that scope is a class, and whether it sits under a block that
    # may or may not run (try/except, if, with, for, while, match) within that scope.
    stack: list[tuple[ast.AST, str, bool, bool]] = [(tree, "", False, False)]
    conditional: set[str] = set()   # the qualnames of defs that sit under such a block
    while stack:    # iterative: a deep tree costs memory, never Python's stack
        node, prefix, in_class, cond = stack.pop()
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                q = prefix + child.name
                defs_at.setdefault(q, (child.lineno, child.col_offset))
                cls = isinstance(child, ast.ClassDef)
                kind = "class" if cls else "method" if in_class else "function"
                first = min([child.lineno] + [d.lineno for d in child.decorator_list])
                defs.append((q, kind, first, child.end_lineno or child.lineno, child.lineno, child.name))
                if cond:
                    conditional.add(q)
                if len(defs) > MAX_SYMBOLS:
                    raise Unresolvable(f"it has over {MAX_SYMBOLS} definitions")
                stack.append((child, q + ".", cls, False))
            elif not isinstance(child, (ast.expr_context, ast.operator, ast.unaryop, ast.cmpop, ast.boolop)):
                _bindings(child, prefix, rebound, starred)
                stack.append((child, prefix, in_class, cond or isinstance(child, _BLOCKS)))
    try:
        toks = [t for t in tokenize.generate_tokens(io.StringIO(text).readline) if t.type not in _SKIP_TOKENS]
    except (tokenize.TokenError, SyntaxError) as e:
        raise Unresolvable(f"it does not tokenize as Python ({type(e).__name__})") from None
    rows = [t.start[0] for t in toks]
    out = []
    for q, kind, first, last, at, name in defs:
        seg = toks[bisect.bisect_left(rows, first):bisect.bisect_right(rows, last)]
        while seg and seg[0].type in _MARK:     # an INDENT or DEDENT that only says where it sits
            seg = seg[1:]
        words, blanked = [], False
        for i, t in enumerate(seg):
            if (not blanked and t.type == tokenize.NAME and t.string == name and t.start[0] == at and i
                    and seg[i - 1].string in ("def", "class")):
                words.append("\x00")
                blanked = True
            else:
                words.append(_MARK.get(t.type, t.string))
        out.append(Symbol(q, kind, first, last, _digest(" ".join(words))))
        scope = q[:len(q) - len(name)]
        here = defs_at.get(q, (at, 0))
        bound = rebound.get((scope, name), []) + starred.get(scope, [])
        # 1.54 review, round 3: a def that may not run (`except ImportError: def f` after `from fast import f`)
        # is not the one that runs when anything else binds its name, before it or after; an unconditional
        # def overrides what came before it, so only a later binding counts.
        after = sorted(bound) if q in conditional else [w for w in bound if w > here]
        if after:   # 1.54 review M2: bound again after its def (`f = ...`, `for f in`, `global f`): unchecked
            out.append(Symbol(q, kind, after[0][0], after[0][0], ""))
    return sorted(out, key=lambda s: (s.start_line, -s.end_line))


_BLOCKS = tuple(getattr(ast, n) for n in ("Try", "TryStar", "If", "With", "AsyncWith", "For", "AsyncFor", "While",
                                          "Match") if hasattr(ast, n))   # a block whose body may not run
_LATER = (1 << 30, 0)   # a binding whose time cannot be told (a function's `global f`): after every def


def _bindings(node: ast.AST, prefix: str, rebound: dict[tuple[str, str], list[tuple[int, int]]],
              starred: dict[str, list[tuple[int, int]]]) -> None:
    """Record any binding `node` itself makes in scope `prefix`, by any form but `def` and `class`.

    Fail closed (1.54 review M2, security): not a list of statements but every
    node that binds a name: a Name stored or deleted (assignment, `for`, `with`,
    walrus, `del`, a `type` alias), a match capture, an `except ... as`, an
    import's alias. A function's `global f` or `nonlocal f` binds f in the
    module or an enclosing scope, at a time that cannot be told: always later.
    The traversal reaches each node once, with the prefix of the scope it is in.
    """
    def add(scope: str, name: str, where: tuple[int, int]) -> None:
        rebound.setdefault((scope, name), []).append(where)

    where = (getattr(node, "lineno", _LATER[0]), getattr(node, "col_offset", 0))
    names: list[str] = []
    if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
        names = [node.id]
    elif isinstance(node, ast.ExceptHandler) and node.name:
        names = [node.name]
    elif isinstance(node, ast.alias):
        if node.name == "*":
            starred.setdefault(prefix, []).append(where)
        else:
            names = [(node.asname or node.name).split(".")[0]]
    elif type(node).__name__ in ("MatchAs", "MatchStar") and getattr(node, "name", None):
        names = [node.name]
    elif type(node).__name__ == "MatchMapping" and getattr(node, "rest", None):
        names = [node.rest]
    elif type(node).__name__ == "TypeAlias" and isinstance(getattr(node, "name", None), ast.Name):
        names = [node.name.id]
    elif isinstance(node, ast.Global):
        for n in node.names:
            add("", n, _LATER)
    elif isinstance(node, ast.Nonlocal):
        parts = prefix.split(".")[:-1]   # "outer.g." -> ["outer", "g"]: every enclosing scope but the module's
        for k in range(1, len(parts)):
            for n in node.names:
                add(".".join(parts[:k]) + ".", n, _LATER)
    for n in names:
        add(prefix, n, where)


# -- the brace languages, by definition lines -------------------------------------------------

LIT = "\x04"   # what a literal's characters become in the mask (never a word character, never a space)
_BLANK = re.compile(r"[^\n]")
_STOPS = {   # where the lexer must look: everything else is plain code and is skipped in one regex step
    "js": re.compile(r"//|/\*|[\"'`{}/]"),
    "go": re.compile(r"//|/\*|[\"'`{}]"),
    "rust": re.compile(r"//|/\*|(?<![A-Za-z0-9_])b?r#*\"|[\"'{}]"),
    "java": re.compile(r"//|/\*|\"\"\"|[\"'{}]"),
    "csharp": re.compile(r"//|/\*|\"\"\"|\$?@\$?\"|[\"'{}]"),
}
_REGEX_AFTER = frozenset("(,=:[!&|?{};+-*%<>~^")
_REGEX_WORDS = frozenset({"return", "typeof", "instanceof", "in", "of", "new", "delete", "void", "throw", "case",
                          "do", "else", "yield", "await"})
_TPL_STOP = re.compile(r"[\\`]|\$\{")
# A tag, a closing tag or a fragment in code: JSX, whose text (`<a>http://x</a>`) a lexer this small would read as
# a comment. In a file with one every comment counts in the hash (1.54 review C2): a false "stale", never a hold.
_JSX = re.compile(r"<(?:[A-Za-z][\w.:-]*[\s/>]|/|>)")


class _Lexed(NamedTuple):
    mask: str                       # the text, comments as spaces and literals as LIT, newlines kept
    comments: list[tuple[int, int]]
    literals: list[tuple[int, int]]   # each literal's [start, end): its text counts verbatim in a body's hash
    pairs: dict[int, int]           # each code `{` offset -> its `}` offset
    owner: list[int]                # per line: the offset of the innermost `{` open at its start, or -1
    events: list[tuple[int, int]]   # (offset, the innermost `{` open from there), at each brace, in offset order


def _lex(text: str, lang: str) -> _Lexed:
    n, stops = len(text), _STOPS[lang]
    pieces, comments, literals, last = [], [], [], 0
    pairs: dict[int, int] = {}
    braces: list[int] = []
    tpl: list[int] = []            # JS: per open `${`, the depth of plain braces inside it
    owner_at: list[tuple[int, int]] = []   # (offset, innermost open brace) at each brace event

    def blank(a: int, b: int, ch: str) -> None:
        nonlocal last
        pieces.append(text[last:a])
        pieces.append(_BLANK.sub(ch, text[a:b]))
        if ch == LIT:
            literals.append((a, b))
        last = b

    def line_of(i: int) -> int:
        return text.count("\n", 0, i) + 1

    def string_end(i: int, q: str, multiline: bool) -> int:
        j = i + 1
        while j < n:
            c = text[j]
            if c == "\\":
                j += 2
                continue
            if c == q:
                return j + 1
            if c == "\n" and not multiline:
                break
            j += 1
        raise Unresolvable(f"a {'character' if q == chr(39) else 'string'} literal on line {line_of(i)} is not closed")

    def interpolated_end(i: int, j: int, verbatim: bool) -> int:
        """From after the opening quote of a C# `$"..."` (or `$@"..."`): the offset after its closing quote.

        1.54 review C2: a hole's code is read as code, its own strings and
        characters skipped whole, so `$"{(a ? "//" : "y")}"` is one literal and
        never a string, then a comment. A string interpolated inside a hole is
        not read (Unresolvable): a nest this small a lexer cannot follow.
        """
        depth = 0
        while j < n:
            c = text[j]
            if depth == 0:
                if c == "\\" and not verbatim:
                    j += 2
                    continue
                if c == '"':
                    if verbatim and text[j + 1:j + 2] == '"':
                        j += 2
                        continue
                    return j + 1
                if c == "{" or c == "}":
                    if text[j + 1:j + 2] == c:    # `{{` and `}}` are a brace in the text
                        j += 2
                        continue
                    depth = 1 if c == "{" else 0
                elif c == "\n" and not verbatim:
                    break
                j += 1
                continue
            if c == '"':
                if text[j - 1:j] in ("$", "@"):
                    raise Unresolvable(f"an interpolated string on line {line_of(i)} holds another in a {{...}}")
                j = string_end(j, '"', multiline=False)
                continue
            if c == "'":
                j = string_end(j, "'", multiline=False)
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
            elif c == "\n" and not verbatim:
                break
            j += 1
        raise Unresolvable(f"an interpolated string on line {line_of(i)} is not closed")

    def template_end(j: int) -> tuple[int, bool]:
        """From inside a template literal: (offset after it, False) or (offset after a `${`, True)."""
        while True:
            m = _TPL_STOP.search(text, j)
            if m is None:
                raise Unresolvable(f"a template literal is not closed (from line {line_of(j)})")
            if m.group() == "\\":
                j = m.end() + 1
                continue
            return m.end(), m.group() == "${"

    i = 0
    while True:
        m = stops.search(text, i)
        if m is None:
            break
        i, tok = m.start(), m.group()
        if tok == "//":
            j = text.find("\n", i)
            j = n if j < 0 else j
            comments.append((i, j))
            blank(i, j, " ")
            i = j
        elif tok == "/*":
            j = _block_comment_end(text, i, nested=lang == "rust")
            if j < 0:
                raise Unresolvable(f"a block comment on line {line_of(i)} is not closed")
            comments.append((i, j))
            blank(i, j, " ")
            i = j
        elif tok == "{":
            if tpl:
                tpl[-1] += 1
            braces.append(i)
            owner_at.append((i + 1, i))
            i += 1
        elif tok == "}":
            if tpl and tpl[-1] == 0:   # the end of a `${...}`: back inside the template literal
                tpl.pop()
                j, more = template_end(i + 1)
                if more:
                    tpl.append(0)
                blank(i, j, LIT)
                i = j
                continue
            if tpl:
                tpl[-1] -= 1
            if not braces:
                raise Unresolvable(f"a closing brace on line {line_of(i)} has no opening one")
            pairs[braces.pop()] = i
            owner_at.append((i + 1, braces[-1] if braces else -1))
            i += 1
        elif tok == "`":
            if lang == "go":   # a raw string: no escapes, any lines
                j = text.find("`", i + 1)
                if j < 0:
                    raise Unresolvable(f"a raw string on line {line_of(i)} is not closed")
                blank(i, j + 1, LIT)
                i = j + 1
            else:
                j, more = template_end(i + 1)
                if more:
                    tpl.append(0)
                blank(i, j, LIT)
                i = j
        elif tok == "/":   # JS only: a regex literal, or division
            j = _regex_end(text, i) if _regex_may_start(text, last, i) else -1
            if j < 0:
                k = i - 1
                while k >= last and text[k] in " \t":
                    k -= 1
                if k >= last and text[k] in ")]":
                    # 1.54 review: after `)` or `]` a regex (`if (s) /a  b/`) cannot be told from a division,
                    # so to the line's end the text counts verbatim in the hash, either way it reads. It stays
                    # code in the mask (braces count); a reformatted division is a false "stale", never a hold.
                    e = text.find("\n", i)
                    literals.append((i, n if e < 0 else e))
                i += 1
            else:
                blank(i, j, LIT)
                i = j
        elif tok == '"""':   # a Java text block or a C# raw string
            j = text.find('"""', i + 3)
            if j < 0:
                raise Unresolvable(f"a text block on line {line_of(i)} is not closed")
            j += 3
            while j < n and text[j] == '"':
                j += 1
            blank(i, j, LIT)
            i = j
        elif tok.endswith('"') and ("@" in tok or tok.startswith(("r", "b"))):
            if "$" in tok:   # C# interpolated verbatim: $@"..{x}.." or @$"..{x}.."
                j = interpolated_end(i, i + len(tok), verbatim=True)
            elif "@" in tok:   # C# verbatim: "" is a quote, any lines
                j = i + len(tok)
                while True:
                    k = text.find('"', j)
                    if k < 0:
                        raise Unresolvable(f"a verbatim string on line {line_of(i)} is not closed")
                    if text[k + 1:k + 2] == '"':
                        j = k + 2
                        continue
                    j = k + 1
                    break
            else:            # Rust raw: r"..", r#".."#, br".."
                close = '"' + "#" * tok.count("#")
                k = text.find(close, i + len(tok))
                if k < 0:
                    raise Unresolvable(f"a raw string on line {line_of(i)} is not closed")
                j = k + len(close)
            blank(i, j, LIT)
            i = j
        elif tok == '"' and lang == "csharp" and text[i - 1:i] == "$":
            j = interpolated_end(i, i + 1, verbatim=False)
            blank(i, j, LIT)
            i = j
        elif tok == '"':
            j = string_end(i, '"', multiline=lang == "rust")
            blank(i, j, LIT)
            i = j
        else:   # "'"
            if lang == "rust":
                if text[i + 1:i + 2] == "\\":
                    j = string_end(i, "'", False)
                elif text[i + 2:i + 3] == "'":
                    j = i + 3
                else:          # a lifetime, 'a: plain code
                    i += 1
                    continue
            else:
                j = string_end(i, "'", multiline=False)
            blank(i, j, LIT)
            i = j
    if tpl:
        raise Unresolvable("a template literal's ${...} is not closed")
    if braces:
        raise Unresolvable(f"{len(braces)} brace(s) are not closed (the first on line {line_of(braces[0])})")
    pieces.append(text[last:])
    mask = "".join(pieces)
    # The innermost open brace at the start of each line, from the brace events in offset order.
    owner, k, cur, pos = [], 0, -1, 0
    for line in mask.split("\n"):
        while k < len(owner_at) and owner_at[k][0] <= pos:
            cur = owner_at[k][1]
            k += 1
        owner.append(cur)
        pos += len(line) + 1
    return _Lexed(mask, comments, literals, pairs, owner, owner_at)


def _block_comment_end(text: str, i: int, nested: bool) -> int:
    if not nested:
        j = text.find("*/", i + 2)
        return -1 if j < 0 else j + 2
    depth, j = 1, i + 2
    while depth:
        a, b = text.find("/*", j), text.find("*/", j)
        if b < 0:
            return -1
        if 0 <= a < b:
            depth, j = depth + 1, a + 2
        else:
            depth, j = depth - 1, b + 2
    return j


def _regex_may_start(text: str, last: int, i: int) -> bool:
    """Whether a `/` at `i` starts a regex literal, by the code before it; `last` ends the latest literal or comment.

    After a value (a name, a number, a closing bracket, a literal) it divides;
    after an operator, an opening bracket or a keyword such as `return` it
    starts a regex.
    """
    k = i - 1
    while k >= last and text[k] in " \t\n":
        k -= 1
    if k < last:
        return last == 0    # the start of the file; else right after a literal (a value) or a comment
    prev = text[k]
    if prev in ")]":
        return False
    if prev.isalnum() or prev in "_$":
        word = re.search(r"[A-Za-z0-9_$]+\Z", text[max(last, k - 20):k + 1])
        return bool(word) and word.group() in _REGEX_WORDS
    return prev in _REGEX_AFTER or prev == "}"


def _regex_end(text: str, i: int) -> int:
    j, n, cls = i + 1, len(text), False
    while j < n:
        c = text[j]
        if c == "\n":
            return -1
        if c == "\\":
            j += 2
            continue
        if c == "[":
            cls = True
        elif c == "]":
            cls = False
        elif c == "/" and not cls:
            j += 1
            while j < n and (text[j].isalpha()):
                j += 1
            return j
        j += 1
    return -1


# Definition lines. Each pattern is matched at the start of one line of the mask; group "name" is the
# definition's name. `scope` says where a pattern counts: anywhere, or only directly in a type's body.
_JS_MODS = r"(?:(?:public|private|protected|static|readonly|abstract|override|async|declare|accessor|get|set)\s+)*"
_JAVA_MODS = (r"(?:(?:public|private|protected|static|final|abstract|synchronized|native|default|strictfp|sealed|"
              r"non-sealed|transient|volatile)\s+)*")
_CS_MODS = (r"(?:(?:public|private|protected|internal|static|virtual|override|abstract|sealed|async|extern|unsafe|"
            r"new|partial|readonly|ref|file|required)\s+)*")
_ANN = r"(?:@[\w.]+(?:\([^)\n]*\))?\s+)*"
_CS_ATTR = r"(?:\[[^\]\n]*\]\s*)*"
_RET = r"(?:[\w.$?]+(?:<[^;{}()=\n]*>)?(?:\[\s*\])*\??\s+)?"
_PATTERNS = {
    "js": [
        ("any", "function", re.compile(r"\s*(?:export\s+(?:default\s+)?)?(?:declare\s+)?(?:async\s+)?function\b\s*(?:\*\s*)?"
                                        r"(?P<name>[A-Za-z_$][\w$]*)")),
        ("any", "class", re.compile(r"\s*(?:export\s+(?:default\s+)?)?(?:declare\s+)?(?:abstract\s+)?class\s+"
                                     r"(?P<name>[A-Za-z_$][\w$]*)")),
        ("any", "interface", re.compile(r"\s*(?:export\s+)?(?:declare\s+)?interface\s+(?P<name>[A-Za-z_$][\w$]*)")),
        ("any", "enum", re.compile(r"\s*(?:export\s+)?(?:declare\s+)?(?:const\s+)?enum\s+(?P<name>[A-Za-z_$][\w$]*)")),
        ("any", "namespace", re.compile(r"\s*(?:export\s+)?(?:declare\s+)?(?:namespace|module)\s+"
                                         r"(?P<name>[A-Za-z_$][\w$]*)\s*(?:\{|\Z)")),
        ("any", "arrow", re.compile(r"\s*(?:export\s+)?(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*"
                                     r"(?::[^=\n]+)?=\s*(?:async\s+)?(?=function\b|\(|[A-Za-z_$][\w$]*\s*=>)")),
        ("type", "method", re.compile(r"\s*" + _JS_MODS + r"(?:\*\s*)?(?P<name>#?[A-Za-z_$][\w$]*)\s*(?:[?!]\s*)?"
                                      r"(?:<[^>\n]*>\s*)?\(")),
        ("type", "field-arrow", re.compile(r"\s*" + _JS_MODS + r"(?P<name>#?[A-Za-z_$][\w$]*)\s*(?::[^=\n]+)?=\s*"
                                            r"(?:async\s+)?(?=\(|[A-Za-z_$][\w$]*\s*=>|function\b)")),
    ],
    "go": [
        ("any", "function", re.compile(r"func\s*(?:\(\s*(?:[A-Za-z_]\w*\s+)?(?:\*\s*)?(?P<recv>[A-Za-z_]\w*)"
                                        r"(?:\[[^\]\n]*\])?\s*\)\s*)?(?P<name>[A-Za-z_]\w*)")),
        ("any", "type", re.compile(r"type\s+(?P<name>[A-Za-z_]\w*)\s*(?:\[[^\]\n]*\]\s*)?(?P<what>struct|interface)\b")),
    ],
    "rust": [
        ("any", "function", re.compile(r"\s*(?:pub(?:\s*\([^)\n]*\))?\s+)?(?:(?:const|async|unsafe|default|extern"
                                        r"(?:\s+\x04+)?)\s+)*fn\s+(?P<name>[A-Za-z_]\w*)")),
        ("any", "type", re.compile(r"\s*(?:pub(?:\s*\([^)\n]*\))?\s+)?(?:unsafe\s+)?(?P<what>struct|enum|union|trait|mod)"
                                    r"\s+(?P<name>[A-Za-z_]\w*)")),
        ("any", "impl", re.compile(r"\s*(?:unsafe\s+)?impl\b(?P<name>)")),
    ],
    "java": [
        ("any", "type", re.compile(r"\s*" + _ANN + _JAVA_MODS + r"(?P<what>class|interface|enum|record|@interface)\s+"
                                    r"(?P<name>[A-Za-z_$][\w$]*)")),
        ("type", "method", re.compile(r"\s*" + _ANN + _JAVA_MODS + r"(?:<[^>\n]*>\s*)?" + _RET +
                                      r"(?P<name>[A-Za-z_$][\w$]*)\s*\(")),
    ],
    "csharp": [
        ("any", "namespace", re.compile(r"\s*namespace\s+[\w.]+\s*(?:\{|$)(?P<name>)")),
        ("any", "type", re.compile(r"\s*" + _CS_ATTR + _CS_MODS + r"(?P<what>class|interface|struct|enum|record"
                                   r"(?:\s+(?:class|struct))?)\s+(?P<name>[A-Za-z_]\w*)")),
        ("type", "method", re.compile(r"\s*" + _CS_ATTR + _CS_MODS + _RET + r"(?P<name>[A-Za-z_]\w*)\s*(?:<[^>\n]*>\s*)?"
                                      r"\(")),
    ],
}
# Statement words that are never a method's name where a definition line is read (a type's body holds no
# statements, so this only keeps a stray line out); `of`, `delete` and `get` are fine method names.
_KEYWORDS = frozenset({"if", "for", "while", "switch", "catch", "return", "new", "throw", "else", "do", "try",
                       "using", "lock", "foreach", "synchronized", "function", "super", "this", "base"})
_TYPES = frozenset({"class", "interface", "enum", "struct", "union", "trait", "mod", "impl", "namespace", "record",
                    "type"})
_DECOR = {"js": ("@",), "java": ("@",), "csharp": ("[",), "rust": ("#[",), "go": ()}
_BODY_SCAN = re.compile(r"[(){}\[\];]|=>")


class _Def(NamedTuple):
    name: str
    kind: str
    start: int           # offset: the line the definition (with its decorators) starts on
    name_span: tuple[int, int]
    body: tuple[int, int]  # offsets [open, close] of its braces; (-1, end) for an expression body
    recv: str | None     # Go: the receiver's type; Rust impl: the type it is for
    scope: bool          # a type's body names the definitions in it (a class, an impl, ...)
    named: bool          # it adds its name to the qualified names inside it (an impl and a C# namespace do not)


def _lexical(text: str, lang: str, jsx: bool = False) -> list[Symbol]:
    lx = _lex(text, lang)
    mask = lx.mask
    starts = [0] + [m.end() for m in re.finditer("\n", mask)]
    type_bodies: set[int] = set()     # `{` offsets that open a type's body: a method is found only directly in one
    lines = mask.split("\n")
    pending: list[tuple[int, int, str, str, re.Match, str | None]] = []
    for ln, line in enumerate(lines):
        if len(line) > MAX_DEF_LINE or not line.strip():
            continue
        # 1.54 review M1: matched from the line's indent, so a pattern's leading `\s*` never re-reads it (a
        # line of spaces was quadratic). Go's patterns name a top-level definition: column 0 only, as before.
        indent = 0 if lang == "go" else len(line) - len(line.lstrip(" \t"))
        for scope, kind, pat in _PATTERNS[lang]:
            m = pat.match(line, indent)
            if not m:
                continue
            name = m.group("name")
            if kind in ("method", "field-arrow") and (name in _KEYWORDS or not name):
                continue
            if lang == "js" and kind in ("function", "arrow") and name in _KEYWORDS:
                continue
            what = m.groupdict().get("what") or kind
            pending.append((ln, starts[ln], scope, what, m, m.groupdict().get("recv")))
            break
    if len(pending) > MAX_SYMBOLS:
        raise Unresolvable(f"it has over {MAX_SYMBOLS} definitions")
    # Types first, so a method is checked against the bodies the types around it open.
    found: list[tuple[int, _Def]] = []
    for ln, at, scope, what, m, recv in pending:
        if scope != "any":
            continue
        d = _definition(text, mask, lx, lang, at, what, m, recv)
        if d is not None:
            found.append((ln, d))
            if d.scope and d.body[0] >= 0:
                type_bodies.add(d.body[0])
    for ln, at, scope, what, m, recv in pending:
        if scope != "type" or lx.owner[ln] not in type_bodies:
            continue
        d = _definition(text, mask, lx, lang, at, "method", m, recv)
        if d is not None:
            found.append((ln, d))
    defs = [d for _, d in sorted(found, key=lambda x: x[1].start)]
    hidden = _hidden(mask, lx, lang, defs, type_bodies)
    return _symbols(text, lx, starts, defs, lang, comments_count=jsx and _JSX.search(mask) is not None,
                    hidden=hidden)


# 1.54 review M2: a definition the line patterns do not index (after `;` or other code on its line) that
# redefines an indexed name in the same scope. Each is linear: no two adjacent unbounded repeats.
_REDEF = {
    "js": [re.compile(r"(?<![\w$.])function\b\s*(?:\*\s*)?(?P<name>[A-Za-z_$][\w$]*)"),
           re.compile(r"(?<![\w$.])class\s+(?P<name>[A-Za-z_$][\w$]*)")],
    "go": [re.compile(r"(?<![\w.])func\s*(?:\([^()\n]*\)\s*)?(?P<name>[A-Za-z_]\w*)"),
           re.compile(r"(?<![\w.])type\s+(?P<name>[A-Za-z_]\w*)")],
    "rust": [re.compile(r"(?<![\w.])(?:fn|struct|enum|union|trait|mod)\s+(?P<name>[A-Za-z_]\w*)")],
    "java": [re.compile(r"(?<![\w.$@])(?:class|interface|enum|record)\s+(?P<name>[A-Za-z_$][\w$]*)")],
    "csharp": [re.compile(r"(?<![\w.])(?:class|interface|struct|enum|record)\s+(?P<name>[A-Za-z_]\w*)")],
}
# A method's shape, counted only directly in a type's body (where code is only definitions): `m(..) {` or `=> `.
_METHOD_SHAPE = re.compile(r"(?<![\w$.#])(?P<name>#?[A-Za-z_$][\w$]*)\s*(?:<[^<>()\n]*>\s*)?\([^()\n]*\)"
                           r"[^;{}()\n=]*(?:\{|=>)")


# 1.54 review, round 3: JS replaces a function by assignment. `f = ...`, `f += ...` or `var|let|const f = ...`
# (not `==`, `===` or `=>`); a method by `this.m = ...` in its class or `A.prototype.m = ...`. Not covered:
# destructuring (`[f] = ...`), `Object.defineProperty`, `A.m = ...` for a static method, and `window.f = ...`.
_JS_OP = r"\s*(?:\*\*|<<|>>>|>>|&&|\|\||\?\?|[-+*/%&|^])?=(?![=>])"
_JS_ASSIGN = re.compile(r"(?<![\w$.])(?:(?P<decl>var|let|const)\s+)?(?P<name>[A-Za-z_$][\w$]*)" + _JS_OP)
_JS_THIS = re.compile(r"(?<![\w$.])this\s*\.\s*(?P<name>#?[A-Za-z_$][\w$]*)" + _JS_OP)
_JS_PROTO = re.compile(r"(?<![\w$.])(?P<type>[A-Za-z_$][\w$]*)\.prototype\.(?P<name>[A-Za-z_$][\w$]*)" + _JS_OP)


def _hidden(mask: str, lx: _Lexed, lang: str, defs: list[_Def], type_bodies: set[int]) -> dict[int, int]:
    """Each indexed definition (by index in `defs`) that an unindexed one of the same name, in the same scope,
    redefines: index -> that redefinition's offset. Such a name resolves to unchecked, never to the first."""
    offs = [o for o, _ in lx.events]

    def scope(off: int) -> int:
        k = bisect.bisect_right(offs, off) - 1
        return lx.events[k][1] if k >= 0 else -1

    indexed = {d.name_span[0] for d in defs}
    by_name: dict[tuple[str, int], list[int]] = {}
    for i, d in enumerate(defs):
        if d.name:
            by_name.setdefault((d.name, scope(d.name_span[0])), []).append(i)
    found: dict[int, int] = {}
    pats = [(p, False) for p in _REDEF[lang]] + ([(_METHOD_SHAPE, True)] if lang in ("js", "java", "csharp") else [])
    for pat, in_type in pats:
        for m in pat.finditer(mask):
            at = m.start("name")
            if at in indexed:
                continue
            where = scope(at)
            if in_type and (where not in type_bodies or m.group("name") in _KEYWORDS):
                continue
            for i in by_name.get((m.group("name"), where), ()):
                found.setdefault(i, at)
    if lang == "js":
        _js_reassigned(mask, lx, defs, type_bodies, indexed, scope, by_name, found)
    return found


def _js_reassigned(mask: str, lx: _Lexed, defs: list[_Def], type_bodies: set[int], indexed: set[int], scope,
                   by_name: dict[tuple[str, int], list[int]], found: dict[int, int]) -> None:
    """Add to `found` each JS function or method that an assignment replaces (round 3; see _JS_ASSIGN)."""
    plain: dict[str, list[int]] = {}      # a name -> the defs a bare `name = ...` anywhere may replace (not methods)
    methods: dict[tuple[int, str], list[int]] = {}   # (its class body's `{`, its name) -> the methods
    classes = {d.body[0]: d.name for d in defs if d.scope and d.body[0] >= 0}
    for i, d in enumerate(defs):
        if not d.name:
            continue
        where = scope(d.name_span[0])
        if where in type_bodies:
            methods.setdefault((where, d.name), []).append(i)
        else:
            plain.setdefault(d.name, []).append(i)
    for m in _JS_ASSIGN.finditer(mask):
        at, name = m.start("name"), m.group("name")
        if at in indexed or name in ("var", "let", "const"):
            continue
        k = at - 1
        while k >= 0 and mask[k] in " \t":
            k -= 1
        if k >= 0 and mask[k] == ":":   # a TS annotation (`const u: User = ...`) names a type, not a binding
            continue
        where = scope(at)
        if m.group("decl") in ("let", "const"):   # block-scoped: it shadows only where it is declared
            hit = by_name.get((name, where), [])
        elif where in type_bodies:                 # a class field `f = 1` is the class's own
            hit = []
        else:                                      # a bare assignment, or a hoisted `var`: it may reach out
            hit = plain.get(name, [])
        for i in hit:
            found.setdefault(i, at)
    for m in _JS_THIS.finditer(mask):
        at = m.start("name")
        for (body, name), hit in methods.items():
            if name == m.group("name") and body < at < lx.pairs[body]:
                for i in hit:
                    found.setdefault(i, at)
    for m in _JS_PROTO.finditer(mask):
        for (body, name), hit in methods.items():
            if name == m.group("name") and classes.get(body) == m.group("type"):
                for i in hit:
                    found.setdefault(i, m.start("name"))


def _definition(text: str, mask: str, lx: _Lexed, lang: str, at: int, what: str, m: re.Match,
                recv: str | None) -> _Def | None:
    """One definition from its line's match: where its body is, or None when it has none (a declaration)."""
    name_span = (at + m.start("name"), at + m.end("name"))
    name = m.group("name")
    pos = at + m.end()
    if mask[pos - 1:pos] in ("{", "("):   # a pattern that ends on its body's brace or its parameters' bracket
        pos -= 1
    what = what.split()[0].lstrip("@")   # "record struct" is a record, "@interface" an interface
    if what == "impl":
        open_ = _first_brace(mask, pos)
        if open_ < 0:
            return None
        recv = _impl_type(mask[pos:open_])
        if recv is None:
            return None
        return _Def(recv, "impl", at, name_span, (open_, lx.pairs[open_]), recv, True, True)
    if what == "namespace" and lang == "csharp":
        open_ = _first_brace(mask, pos)
        if open_ < 0:
            return None
        return _Def("", "namespace", at, name_span, (open_, lx.pairs[open_]), None, True, False)
    arrow = what in ("arrow", "field-arrow")
    end = _body(mask, lx, pos, arrow)
    if end is None:
        return None
    kind = {"arrow": "function", "field-arrow": "method", "type": "type"}.get(what, what)
    if lang == "go" and recv:
        kind = "method"
    scope = kind in _TYPES or what in _TYPES
    start = _decorated_start(mask, at, _DECOR[lang])
    return _Def(name, what if what in _TYPES else kind, start, name_span, end, recv, scope, True)


def _first_brace(mask: str, pos: int) -> int:
    depth = 0
    for m in _BODY_SCAN.finditer(mask, pos, min(len(mask), pos + MAX_SIGNATURE)):
        t = m.group()
        if t in "([":
            depth += 1
        elif t in ")]":
            depth -= 1
        elif t == "{" and depth <= 0:
            return m.start()
        elif t in ";}" and depth <= 0:
            return -1
    return -1


def _body(mask: str, lx: _Lexed, pos: int, arrow: bool) -> tuple[int, int] | None:
    """(open, close) of the body braces after `pos`; (-1, end) for an expression body; None for no body."""
    depth, seen_arrow = 0, False
    for m in _BODY_SCAN.finditer(mask, pos, min(len(mask), pos + MAX_SIGNATURE)):
        t = m.group()
        if t in "([":
            depth += 1
        elif t in ")]":
            depth -= 1
            if depth < 0:
                return None
        elif depth > 0:
            continue
        elif t == "{":
            return m.start(), lx.pairs[m.start()]
        elif t == "=>":
            seen_arrow = True
            after = mask[m.end():m.end() + MAX_SIGNATURE].lstrip(" \t\n")
            if after.startswith("{"):
                o = mask.index("{", m.end())
                return o, lx.pairs[o]
            return -1, _expression_end(mask, m.end())
        elif t == ";":
            return (-1, m.start()) if arrow and seen_arrow else None
        elif t == "}":
            return None
    return None


def _expression_end(mask: str, pos: int) -> int:
    """Where an expression body that starts at `pos` ends: a `;`, a line end, or a closer, at its own depth."""
    depth = 0
    for k in range(pos, min(len(mask), pos + MAX_SIGNATURE * 4)):
        c = mask[k]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
            if depth < 0:
                return k - 1
        elif depth == 0 and c in ";\n" and mask[pos:k].strip():
            return k
    return min(len(mask), pos + MAX_SIGNATURE * 4) - 1


def _impl_type(head: str) -> str | None:
    """The type a Rust `impl ... {` head is for: `impl<T> Trait for Type<T> where ..` -> 'Type'."""
    s = re.sub(r"\bwhere\b.*", "", head, flags=re.S)
    depth, flat = 0, []
    for c in s:           # drop generic arguments, however deep
        if c == "<":
            depth += 1
        elif c == ">" and depth:
            depth -= 1
        elif depth == 0:
            flat.append(c)
    s = "".join(flat)
    s = s.split(" for ", 1)[1] if " for " in s else s
    m = re.search(r"([A-Za-z_]\w*)\s*\Z", s.replace("::", " ").strip().rstrip("&").strip())
    return m.group(1) if m else None


def _decorated_start(mask: str, at: int, marks: tuple[str, ...]) -> int:
    """The start of the decorator or attribute lines right above a definition line, if any."""
    start = at
    while marks and start > 0:
        prev = mask.rfind("\n", 0, start - 1) + 1
        line = mask[prev:start - 1].strip()
        if not line or not line.startswith(marks):
            break
        start = prev
    return start


def _symbols(text: str, lx: _Lexed, starts: list[int], defs: list[_Def], lang: str,
             comments_count: bool = False, hidden: dict[int, int] | None = None) -> list[Symbol]:
    def line(off: int) -> int:
        return bisect.bisect_right(starts, off)

    def extent(d: _Def) -> tuple[int, int]:
        return d.start, d.body[1] + 1

    chain: list[tuple[_Def, int]] = []      # the definitions around the current one, with where each ends
    out = []
    dropped = [] if comments_count else [(s, e, " ") for s, e in lx.comments]
    cuts = sorted(dropped + [(s, e, None) for s, e in lx.literals])
    cstarts = [s for s, _, _ in cuts]
    hidden = hidden or {}
    for n, d in enumerate(defs):
        a, b = extent(d)
        while chain and chain[-1][1] <= a:
            chain.pop()
        if d.recv and lang == "go":
            prefix = d.recv + "."
        else:
            prefix = "".join(p.name + "." for p, _ in chain if p.named and p.name)
        chain.append((d, b))
        if d.kind in ("impl",) or (d.kind == "namespace" and lang == "csharp"):
            continue
        q = prefix + d.name
        kind = "method" if d.kind == "function" and chain[:-1] and chain[-2][0].scope else d.kind
        body = _normalise(text, a, b, cuts, cstarts, d.name_span)
        out.append(Symbol(q, kind, line(a), line(b - 1), _digest(body)))
        if n in hidden:   # redefined where no pattern reads it: a second entry, so the name resolves unchecked
            out.append(Symbol(q, kind, line(hidden[n]), line(hidden[n]), ""))
        if len(out) > MAX_SYMBOLS:
            raise Unresolvable(f"it has over {MAX_SYMBOLS} definitions")
    return out


_GAP = re.compile(r"(?<=[^\w$])\s+|\s+(?=[^\w$])")
_HOLE = "\x05"   # where a literal sits in the code being normalised; never in code these languages take


def _normalise(text: str, a: int, b: int, cuts: list[tuple[int, int, str | None]], cstarts: list[int],
               name: tuple[int, int]) -> str:
    """text[a:b] with comments dropped, the definition's own name blanked, and whitespace counted only between words.

    1.54 review C1: whitespace counts only in code. A literal (a string, a
    template's text, a regex, a raw or verbatim string) is kept verbatim, its
    length before it, so `join(", ")` and `join(",")` hash apart.
    """
    k = bisect.bisect_left(cstarts, a)
    while k > 0 and cuts[k - 1][1] > a:   # a cut that starts before the definition and reaches into it
        k -= 1
    marks = [(name[0], name[1], "\x00")] if a <= name[0] < b and name[1] > name[0] else []
    while k < len(cuts) and cuts[k][0] < b:
        s, e, rep = cuts[k]
        marks.append((max(s, a), min(e, b), rep))
        k += 1
    code, lits, pos = [], [], a
    for s, e, rep in sorted(marks, key=lambda m: (m[0], m[1])):
        if s < pos:
            continue
        code.append(text[pos:s])
        if rep is None:
            lits.append(text[s:e])
            code.append(_HOLE)
        else:
            code.append(rep)
        pos = e
    code.append(text[pos:b])
    flat = "".join(code)
    if flat.count(_HOLE) != len(lits):
        raise Unresolvable("it holds a \\x05 control character outside a literal")
    out = _GAP.sub("", " ".join(flat.split())).split(_HOLE)
    return "".join(piece + (f"{_HOLE}{len(lits[i])}:{lits[i]}" if i < len(lits) else "") for i, piece in enumerate(out))
