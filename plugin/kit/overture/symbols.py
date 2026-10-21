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
dropped, whitespace normalised (it counts only between two word characters)
and the definition's own name blanked, so a rename alone keeps the hash and a
moved or renamed body can be found by it. Docstrings and string literals are
code and do count. Line endings never count.

**Never a guess.** A file this cannot read (an unknown extension, a syntax
error, an unclosed literal, braces that do not balance, past its bounds) raises
`Unresolvable` with the reason, and a name defined twice in one file resolves
to `unchecked`, not to either one. Every read is bounded (MAX_CHARS,
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
import tokenize
from typing import NamedTuple

from .schema import MAX_QUALNAME, QUALNAME   # the one shape a `symbol` condition's name is held to

MAX_CHARS = 1 << 20      # a larger file is not read for symbols (its anchor reports unchecked)
MAX_SYMBOLS = 5000       # definitions in one file, at most
MAX_SIGNATURE = 4000     # characters between a definition's name and its body's opening brace
MAX_DEF_LINE = 2000      # a longer line is never read as a definition line
HASH_PREFIX = "overture-symbol-1\n"   # changes only if the normalisation does

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
    """Every definition in `text` (the content of `path`), in file order; Unresolvable when it cannot be read."""
    lang = language(path)
    if lang is None:
        raise Unresolvable(f"{path} is not a language this reads (Python, JS/TS, Go, Rust, Java, C#)")
    if len(text) > MAX_CHARS:
        raise Unresolvable(f"{path} is over {MAX_CHARS >> 20} MiB")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    try:
        syms = _python(text) if lang == "python" else _lexical(text, lang)
    except (RecursionError, MemoryError):
        raise Unresolvable(f"{path} nests too deeply to read") from None
    except Unresolvable as e:
        raise Unresolvable(f"{path} cannot be read for definitions: {e}") from None
    except (KeyError, IndexError, ValueError) as e:   # a shape the reader did not foresee: unchecked, never a crash
        raise Unresolvable(f"{path} cannot be read for definitions ({type(e).__name__})") from None
    if len(syms) > MAX_SYMBOLS:
        raise Unresolvable(f"{path} has over {MAX_SYMBOLS} definitions")
    return syms


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
    stack: list[tuple[ast.AST, str, bool]] = [(tree, "", False)]
    while stack:    # iterative: a deep tree costs memory, never Python's stack
        node, prefix, in_class = stack.pop()
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                q = prefix + child.name
                cls = isinstance(child, ast.ClassDef)
                kind = "class" if cls else "method" if in_class else "function"
                first = min([child.lineno] + [d.lineno for d in child.decorator_list])
                defs.append((q, kind, first, child.end_lineno or child.lineno, child.lineno, child.name))
                if len(defs) > MAX_SYMBOLS:
                    raise Unresolvable(f"it has over {MAX_SYMBOLS} definitions")
                stack.append((child, q + ".", cls))
            elif not isinstance(child, (ast.expr_context, ast.operator, ast.unaryop, ast.cmpop, ast.boolop)):
                stack.append((child, prefix, in_class))
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
    return sorted(out, key=lambda s: (s.start_line, -s.end_line))


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


class _Lexed(NamedTuple):
    mask: str                       # the text, comments as spaces and literals as LIT, newlines kept
    comments: list[tuple[int, int]]
    pairs: dict[int, int]           # each code `{` offset -> its `}` offset
    owner: list[int]                # per line: the offset of the innermost `{` open at its start, or -1


def _lex(text: str, lang: str) -> _Lexed:
    n, stops = len(text), _STOPS[lang]
    pieces, comments, last = [], [], 0
    pairs: dict[int, int] = {}
    braces: list[int] = []
    tpl: list[int] = []            # JS: per open `${`, the depth of plain braces inside it
    owner_at: list[tuple[int, int]] = []   # (offset, innermost open brace) at each brace event

    def blank(a: int, b: int, ch: str) -> None:
        nonlocal last
        pieces.append(text[last:a])
        pieces.append(_BLANK.sub(ch, text[a:b]))
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
            if "@" in tok:   # C# verbatim: "" is a quote, any lines
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
    return _Lexed(mask, comments, pairs, owner)


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
        ("any", "function", re.compile(r"\s*(?:export\s+(?:default\s+)?)?(?:declare\s+)?(?:async\s+)?function\b\s*\*?"
                                        r"\s*(?P<name>[A-Za-z_$][\w$]*)")),
        ("any", "class", re.compile(r"\s*(?:export\s+(?:default\s+)?)?(?:declare\s+)?(?:abstract\s+)?class\s+"
                                     r"(?P<name>[A-Za-z_$][\w$]*)")),
        ("any", "interface", re.compile(r"\s*(?:export\s+)?(?:declare\s+)?interface\s+(?P<name>[A-Za-z_$][\w$]*)")),
        ("any", "enum", re.compile(r"\s*(?:export\s+)?(?:declare\s+)?(?:const\s+)?enum\s+(?P<name>[A-Za-z_$][\w$]*)")),
        ("any", "namespace", re.compile(r"\s*(?:export\s+)?(?:declare\s+)?(?:namespace|module)\s+"
                                         r"(?P<name>[A-Za-z_$][\w$]*)\s*(?:\{|\Z)")),
        ("any", "arrow", re.compile(r"\s*(?:export\s+)?(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*"
                                     r"(?::[^=\n]+)?=\s*(?:async\s+)?(?=function\b|\(|[A-Za-z_$][\w$]*\s*=>)")),
        ("type", "method", re.compile(r"\s*" + _JS_MODS + r"\*?\s*(?P<name>#?[A-Za-z_$][\w$]*)\s*[?!]?\s*(?:<[^>\n]*>)?\s*\(")),
        ("type", "field-arrow", re.compile(r"\s*" + _JS_MODS + r"(?P<name>#?[A-Za-z_$][\w$]*)\s*(?::[^=\n]+)?=\s*"
                                            r"(?:async\s+)?(?=\(|[A-Za-z_$][\w$]*\s*=>|function\b)")),
    ],
    "go": [
        ("any", "function", re.compile(r"func\s*(?:\(\s*(?:[A-Za-z_]\w*\s+)?\*?\s*(?P<recv>[A-Za-z_]\w*)"
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
        ("type", "method", re.compile(r"\s*" + _CS_ATTR + _CS_MODS + _RET + r"(?P<name>[A-Za-z_]\w*)\s*(?:<[^>\n]*>)?"
                                      r"\s*\(")),
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


def _lexical(text: str, lang: str) -> list[Symbol]:
    lx = _lex(text, lang)
    mask = lx.mask
    starts = [0] + [m.end() for m in re.finditer("\n", mask)]
    type_bodies: set[int] = set()     # `{` offsets that open a type's body: a method is found only directly in one
    lines = mask.split("\n")
    pending: list[tuple[int, int, str, str, re.Match, str | None]] = []
    for ln, line in enumerate(lines):
        if len(line) > MAX_DEF_LINE or not line.strip():
            continue
        for scope, kind, pat in _PATTERNS[lang]:
            m = pat.match(line)
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
    return _symbols(text, lx, starts, defs, lang)


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


def _symbols(text: str, lx: _Lexed, starts: list[int], defs: list[_Def], lang: str) -> list[Symbol]:
    def line(off: int) -> int:
        return bisect.bisect_right(starts, off)

    def extent(d: _Def) -> tuple[int, int]:
        return d.start, d.body[1] + 1

    chain: list[tuple[_Def, int]] = []      # the definitions around the current one, with where each ends
    out = []
    comments = lx.comments
    cstarts = [a for a, _ in comments]
    for d in defs:
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
        body = _normalise(text, a, b, comments, cstarts, d.name_span)
        out.append(Symbol(q, kind, line(a), line(b - 1), _digest(body)))
        if len(out) > MAX_SYMBOLS:
            raise Unresolvable(f"it has over {MAX_SYMBOLS} definitions")
    return out


_GAP = re.compile(r"(?<=[^\w$])\s+|\s+(?=[^\w$])")


def _normalise(text: str, a: int, b: int, comments: list[tuple[int, int]], cstarts: list[int],
               name: tuple[int, int]) -> str:
    """text[a:b] with comments dropped, the definition's own name blanked, and whitespace counted only between words."""
    parts, pos = [], a
    k = bisect.bisect_left(cstarts, a)
    cuts = [(name[0], name[1], "\x00")] if a <= name[0] < b and name[1] > name[0] else []
    while k < len(comments) and comments[k][0] < b:
        cuts.append((comments[k][0], min(comments[k][1], b), " "))
        k += 1
    for s, e, rep in sorted(cuts):
        if s < pos:
            continue
        parts += [text[pos:s], rep]
        pos = e
    parts.append(text[pos:b])
    return _GAP.sub("", " ".join("".join(parts).split()))
