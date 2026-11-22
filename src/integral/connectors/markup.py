"""The selector grammar and a minimal, inert HTML tree (stdlib `html.parser`).

Split out of `integral.connectors` unchanged (#928); the package re-exports every name.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from html.parser import HTMLParser

from integral.connectors._base import (
    ConnectorError,
)

# ---------------------------------------------------------------------------
# the selector grammar — a closed vocabulary, matched against, never evaluated


@dataclass(frozen=True)
class SimpleSelector:
    """One compiled selector: an optional tag, id, classes and attributes.

    This is the *entire* vocabulary a connector file can use to say "find me
    this element" — no combinators, no pseudo-classes, no expressions. It is
    intentionally too small a language to smuggle anything through: every
    character in a `css` string either belongs to one of these four token
    kinds or the selector is refused at load (`compile_selector`).
    """

    tag: str | None
    id_: str | None
    classes: tuple[str, ...]
    attrs: tuple[tuple[str, str | None], ...]


_TAG_TOKEN = re.compile(r"^[a-zA-Z][\w-]*")
_OTHER_TOKEN = re.compile(r"#[\w-]+|\.[\w-]+|\[[a-zA-Z_][\w-]*(?:=(?:\"[^\"]*\"|'[^']*'))?\]")


def compile_selector(css: str) -> SimpleSelector:
    """Parse a `css` string into `SimpleSelector`, or raise `ConnectorError`.

    Every character must be consumed by one of the three token kinds
    (`#id`, `.class`, `[attr]`/`[attr="value"]`) after an optional leading tag
    name; anything left over — parentheses, quotes outside an attribute
    bracket, semicolons, whitespace, a combinator — is refused. This is what
    makes a selector like `__import__('os').system('x')` inert: it simply
    fails to parse (it is not one of the four token kinds), the same way it
    would if a human mistyped it. Nothing here ever calls `eval` on the
    string; refusal is a plain regex-driven consumption check.

    Tag names and attribute *names* are lowercased here, once, at compile
    time — never left as typed. HTML tag and attribute names are
    case-insensitive by spec, and `html.parser.HTMLParser` already lowercases
    both when it builds a `Node` (verified: `<DIV DISABLED>` tokenises to
    `tag="div"`, `attrs={"disabled": ...}`). Without this normalisation a
    selector written `DIV.job-card` or `[DISABLED]` — exactly what a
    non-programmer hand-editing a connector is liable to type — compiles
    without error and then simply never matches anything: no exception at
    load, no exception at parse, just a silently empty result, which is the
    worst possible failure mode for someone who cannot read this module to
    find out why. Attribute *values*, class names, and ids are left exactly
    as written: those ARE case-sensitive in HTML (`[data-x="Foo"]` must not
    match `data-x="foo"`, and `.Job` must not match `class="job"`), so
    lowercasing them would silently break a correctly-written connector
    instead of fixing a broken one.
    """
    text = css.strip()
    if not text:
        raise ConnectorError("empty selector")
    tag_match = _TAG_TOKEN.match(text)
    tag = tag_match.group(0).lower() if tag_match else None
    rest = text[tag_match.end() :] if tag_match else text

    id_: str | None = None
    classes: list[str] = []
    attrs: list[tuple[str, str | None]] = []
    position = 0
    for match in _OTHER_TOKEN.finditer(rest):
        if match.start() != position:
            raise ConnectorError(f"selector is not tag/#id/.class/[attr]: {css!r}")
        token = match.group(0)
        if token.startswith("#"):
            if id_ is not None:
                raise ConnectorError(f"selector names more than one id: {css!r}")
            id_ = token[1:]
        elif token.startswith("."):
            classes.append(token[1:])
        else:
            body = token[1:-1]
            name, _, value = body.partition("=")
            # Only the attribute *name* is case-insensitive HTML syntax; the
            # value (when present) is data and stays exactly as written.
            attrs.append((name.lower(), value.strip("\"'")) if value else (name.lower(), None))
        position = match.end()
    if position != len(rest):
        raise ConnectorError(f"selector is not tag/#id/.class/[attr]: {css!r}")
    if tag is None and id_ is None and not classes and not attrs:
        raise ConnectorError(f"empty selector: {css!r}")
    return SimpleSelector(tag=tag, id_=id_, classes=tuple(classes), attrs=tuple(attrs))


# ---------------------------------------------------------------------------
# a minimal, inert HTML tree — stdlib `html.parser`, nothing executed


_VOID_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)


#: Elements whose content is code, not prose. `text_content` reads an advert
#: body, and a `<script>` body is neither something a reader sees nor something
#: `dedup` should tokenise — and, because CPython resolves no character
#: reference inside script data, its text is the one place a raw `&lt;` can
#: reach `Offer.text` through the very members T169 adds to remove markup.
#:
#: Skipped in `text_content` only. `raw_text` must keep them: it is what reads
#: an embedded JSON document out of `script[type="application/ld+json"]` and
#: `script#__NEXT_DATA__`, which is rippling's and justjoin's whole route.
_NON_PROSE = frozenset({"script", "style"})


@dataclass
class Node:
    """One element in a parsed page. `<script>`/`<style>` content lands here
    exactly like any other text — it is stored, matched against selectors like
    any other node, and never executed; there is no interpreter for it to run
    in."""

    tag: str
    attrs: dict[str, str]
    children: list[Node | str] = field(default_factory=list)

    def matches(self, selector: SimpleSelector) -> bool:
        if selector.tag is not None and self.tag != selector.tag:
            return False
        if selector.id_ is not None and self.attrs.get("id") != selector.id_:
            return False
        node_classes = set(self.attrs.get("class", "").split())
        if not set(selector.classes).issubset(node_classes):
            return False
        for name, value in selector.attrs:
            if name not in self.attrs:
                return False
            if value is not None and self.attrs[name] != value:
                return False
        return True

    def iter_descendants(self) -> Iterator[Node]:
        for child in self.children:
            if isinstance(child, Node):
                yield child
                yield from child.iter_descendants()

    def text_content(self) -> str:
        pieces = [piece for piece in self._iter_text(skip=_NON_PROSE) if piece.strip()]
        return " ".join(" ".join(piece.split()) for piece in pieces).strip()

    def raw_text(self) -> str:
        """Every text piece beneath this node, concatenated unchanged.

        `text_content` is for prose read out of markup, where collapsing runs
        of whitespace is what a reader means by "the text". This is for a node
        whose text is a *document* — a `<script>` holding JSON — where
        collapsing is corruption: whitespace between JSON tokens does not
        matter, but whitespace inside a string value does, and an advert body
        is a string value. `Offer.text` is required to be what the board
        published (T11 keeps it byte-for-byte because extraction evidence spans
        are offsets into it), so a description written with a double space must
        still have it after the round trip.

        Caught by review on the PR that introduced the JSON route: the first
        implementation read these documents through `text_content` and silently
        reflowed every advert body it parsed.
        """
        return "".join(self._iter_text())

    def _iter_text(self, skip: frozenset[str] = frozenset()) -> Iterator[str]:
        for child in self.children:
            if isinstance(child, str):
                yield child
            elif child.tag not in skip:
                yield from child._iter_text(skip)


class _TreeBuilder(HTMLParser):
    """Builds a `Node` tree. Malformed markup degrades gracefully — an
    unclosed tag is simply never popped, and the document root always closes
    its own children — the same tolerance a browser's parser has, needed
    because a "recorded fixture" is exactly the kind of imperfect real-world
    HTML this has to survive."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node(tag="[document]", attrs={})
        self._stack: list[Node] = [self.root]

    def _attrs_dict(self, attrs: list[tuple[str, str | None]]) -> dict[str, str]:
        return {name: (value if value is not None else "") for name, value in attrs}

    def parse_marked_section(self, i: int, report: bool = True) -> int:
        """A marked section whose keyword is not one `_markupbase` knows.

        The base implementation ends in `assert 0, "unknown status keyword"`,
        so a board serving `<![data[…]]>` raises **out of `parse_html`** and
        takes the whole sourcing run with it. WHATWG calls an unknown marked
        section a bogus comment (`PE:cdata-in-html-content`), which yields no
        text — so that is what it becomes here: consumed, and nothing emitted.

        Found by the second reader on T169, which widened the surface: before
        it, `parse_html` only ever saw a page a connector had fetched; now it
        also sees the value of a JSON field, which is a remote string with no
        markup contract at all.
        """
        try:
            return super().parse_marked_section(i, report)
        except AssertionError:
            # WHATWG's bogus comment state ends at the next literal '>',
            # wherever it falls - not at the marked section's own ']]>'.
            end = self.rawdata.find(">", i)
            return len(self.rawdata) if end < 0 else end + 1

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = Node(tag=tag, attrs=self._attrs_dict(attrs))
        self._stack[-1].children.append(node)
        if tag not in _VOID_TAGS:
            self._stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._stack[-1].children.append(Node(tag=tag, attrs=self._attrs_dict(attrs)))

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag == tag:
                del self._stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if data:
            self._stack[-1].children.append(data)


#: WHATWG's script data state (§13.2.5.15, `script`) and RAWTEXT state
#: (§13.2.5.3, `style` among others). In both, `<!--`, a stray `<`, or
#: anything else that looks like a tag or a comment is not tokenised as one:
#: only the element's own case-insensitive end tag leaves the state. So a scan
#: that does not know this set will mis-tokenise their content as ordinary
#: markup — which is exactly F2: a `<!--` inside `<script>` with no later
#: `-->` was read as an unterminated *comment* and dropped the rest of the
#: document with it, because nothing here knew `<script>` even opened.
#:
#: **Limited to these two, not the full RAWTEXT/RCDATA family** (second-reader
#: round 4, R4): `xmp`, `iframe`, `noembed`, `noframes` (RAWTEXT) and `title`,
#: `textarea` (RCDATA) were in this set through round 3 and every one of them
#: was wrong. None is exercised by a fixture or a test, so the mutant that
#: deletes all six survives the entire suite; and behaviourally each is
#: three-way divergent across the interpreters this repo runs on, because
#: `html.parser` itself only special-cases `script`/`style` consistently —
#: measured directly, `HTMLParser.CDATA_CONTENT_ELEMENTS` is `('script',
#: 'style')` on 3.12.3 and 3.12.11 but adds all four RAWTEXT elements above on
#: 3.11.15 and 3.13.12, and `title`/`textarea` are not members of that
#: attribute on any build. So this function declining to touch a `<!--`
#: inside e.g. `<xmp>` and handing the tag on to `html.parser` (which some
#: builds treat as RAWTEXT and some do not) is itself the "same text
#: regardless of interpreter" property broken, not honoured — pinning the set
#: to fixtures that only some builds pass would be exactly the "check pinned
#: to a proxy" this module exists to remove. Reduced to the two members whose
#: `html.parser` treatment is identical everywhere this repo runs, until each
#: of the other six has committed rows pinning its spec-required behaviour on
#: every interpreter (or its own resolution that does not depend on
#: `html.parser`'s RAWTEXT handling at all).
#:
#: Deliberately not read from `html.parser.HTMLParser.CDATA_CONTENT_ELEMENTS`
#: even for these two: that attribute is itself cross-patch unstable, per the
#: measurement above, so reading it at import time would reintroduce the same
#: hazard for a set that happens to agree today.
_OPAQUE_TEXT_ELEMENTS = frozenset({"script", "style"})


def _opening_tag_name(markup: str, lt: int, gt: int) -> str | None:
    """The lower-cased tag name if `markup[lt:gt+1]` opens an element, else
    `None` — an end tag (`</p>`) or anything that isn't a start tag opens
    nothing."""
    match = re.match(r"<(/?)([A-Za-z][A-Za-z0-9:_-]*)", markup[lt : gt + 1])
    if match is None or match.group(1):
        return None
    return match.group(2).lower()


def _skip_opaque_element(markup: str, tag_name: str, after_open_tag: int) -> int | None:
    """Index just past `</tag_name...>`, searching from `after_open_tag`, or
    `None` if no such end tag exists before EOF.

    A `None` here does not mean "unterminated" in the sense the rest of this
    function cares about: once an opaque element opens, *everything* after it
    is that element's content until either its own end tag or the end of the
    document — there is no comment, tag or declaration left inside for a
    truncation to mistake for something else, so the caller is safe to stop
    scanning altogether rather than searching for one.
    """
    end_open = re.compile(rf"</{re.escape(tag_name)}(?=[\t\n\f\r />]|$)", re.IGNORECASE)
    match = end_open.search(markup, after_open_tag)
    if match is None:
        return None
    close = markup.find(">", match.start())
    return len(markup) if close == -1 else close + 1


#: A tag really opens (or closes) only on an ASCII letter right after `<`, or
#: right after `</` — WHATWG's tag open state (§13.2.5.6) and end tag open
#: state (§13.2.5.7): anything else is "anything else", which never consumes
#: past the `<` itself. Used to tell a genuine `<tag` or `</tag` apart from a
#: bare `<` that merely has some *later*, unrelated `>` somewhere in the
#: document (R2/R3, second-reader round 4) — the two must not be treated the
#: same just because `str.find(">", lt)` cannot tell them apart on its own.
_TAG_OPEN_RE = re.compile(r"</?[A-Za-z]")


def _comment_close_end(markup: str, content_start: int) -> int | None:
    """Index just past a comment's closing token, walking WHATWG's comment
    states (§13.2.5.44 comment start, onward) from `content_start` — the
    first character after the comment's own `<!--` — or `None` if the
    comment is never closed before EOF.

    Every legal close (`-->`, `--!>` comment-end-bang §13.2.5.52, and the
    abrupt-closing-of-empty-comment forms `<!-->`/`<!--->` in comment-start
    and comment-start-dash states, §13.2.5.44-45) is one rule here instead of
    a fixed set of literal strings matched from a fixed offset — that fixed
    list is what missed `<!--->` (second-reader round 4, R5): searching for
    `-->` or `--!>` starting at `content_start` finds neither in `->tail`, so
    the previous code read the comment as unterminated and dropped the rest
    of the document, though the comment closes right there per spec.
    """
    n = len(markup)
    i = content_start
    state = "start"
    while i < n:
        ch = markup[i]
        if state == "start":
            if ch == "-":
                state = "start-dash"
                i += 1
            elif ch == ">":
                return i + 1
            else:
                state = "content"
        elif state == "start-dash":
            if ch == "-":
                state = "end"
                i += 1
            elif ch == ">":
                return i + 1
            else:
                state = "content"
        elif state == "content":
            if ch == "-":
                state = "end-dash"
            i += 1
        elif state == "end-dash":
            if ch == "-":
                state = "end"
                i += 1
            else:
                state = "content"
        elif state == "end":
            if ch == ">":
                return i + 1
            if ch == "!":
                state = "end-bang"
                i += 1
            elif ch == "-":
                i += 1
            else:
                state = "content"
        elif state == "end-bang":
            if ch == ">":
                return i + 1
            if ch == "-":
                state = "end-dash"
                i += 1
            else:
                state = "content"
    return None


#: A canonical, empty comment. `html.parser`'s own comment-close pattern is
#: not a fixed literal, and not even stable within one minor version —
#: measured directly against every interpreter installed in this
#: environment: 3.12.11 (what `uv python install 3.12` draws here, and what
#: `make host-gate`/CI run on) closes a comment on `--\s*>`
#: (whitespace-tolerant), while 3.12.13, 3.12.14 and 3.14.4 all close on
#: `--!?>` (bang-tolerant, not whitespace-tolerant) instead — so no fixed
#: pattern this function could search for agrees with every build it has to
#: run on, and the literal substring `-->` that a naive reading of
#: `html.parser` suggests is not what *any* of them actually search for.
#: Rewriting the whole matched span to this literal — which every measured
#: build parses identically — resolves the ambiguity before `html.parser`
#: ever sees it, rather than leaving the interpreter to guess (R1, R5, R6,
#: second-reader round 5, S2).
_CANONICAL_EMPTY_COMMENT = "<!---->"


def _neutralise_unterminated_tail(markup: str) -> str:
    """Make an EOF-truncated tag or comment survive as text, deterministically.

    A construct that opens with `<` and never finds its closing token before
    EOF can never become a real tag, comment, declaration or PI — there is
    nothing left in the document to close it with. *What* a tokeniser does
    with that unparseable remainder is not settled across CPython patches:
    measured directly, an EOF-truncated start tag is silently discarded by
    3.12.3/3.13.12 and resurfaces as literal data on 3.12.11 (the build
    `uv python install 3.12` — CI's own resolution, unpinned to a patch —
    draws in this environment), and an EOF-truncated comment reaches
    `handle_comment` on one and `handle_data` on another. Pinning
    `MARKUP_CONTRACTS` to whichever behaviour a given CI run happens to draw
    is exactly a check pinned to a proxy for the property (CLAUDE.md's
    second-reader section) rather than to the property itself — the
    candidate should see the same text regardless of which patch of 3.12 CI
    happens to install — so this is resolved before the value ever reaches
    `html.parser`, closed rather than enumerated. The property is: **a
    truncated construct is resolved as the construct it is, and nothing else
    in the document is altered.**

    * Inside `_OPAQUE_TEXT_ELEMENTS` (`<script>`, `<style>`, …), nothing is a
      tag, a comment or a declaration — only the element's own end tag ends
      the state — so no scanning happens there at all; see that constant.
    * A comment (`<!--`) that finds its close (`-->`, `--!>`, or one of the
      abrupt empty-comment forms, `<!-->`/`<!--->`) is rewritten to the
      canonical empty form `<!---->` unconditionally — a terminated comment
      contributes no text either way, and `html.parser`'s own close pattern
      is not stable even within one minor version (`_CANONICAL_EMPTY_COMMENT`'s
      docstring has the measurement), so no spelling of the original is safe
      to leave for the real parser to re-read (R1, R5, R6, second-reader
      round 5, S2: `_comment_close_end` walks the actual comment states
      rather than matching a fixed set of literal closing strings). One that
      never closes is dropped, content and all — a comment contributes no
      text whether or not it manages to close, the same rule an ordinary,
      *well-formed* comment already follows a few lines up in
      `MARKUP_CONTRACTS`. A `>` inside it is literal comment content, not a
      close, exactly as WHATWG's comment states require.
    * `<!` not followed by `--` (bogus comment, §13.2.5.42's "anything else",
      or a DOCTYPE, §13.2.5.53) and `<?` (also a bogus comment, tag open
      state's "anything else") are both tokens that contribute no text
      whether or not they close either — the *same* rule as a comment, so a
      truncated one is dropped the same way. A terminated one is left for the
      real parser, which already handles it — `<![CDATA[…]]>` (exact,
      case-sensitive literal only) on its own, literal `]]>`-searching path
      inside `html.parser`'s own `parse_html_declaration`, not through
      `_markupbase.ParserBase.parse_marked_section`, which empirically is
      never reached from `HTMLParser.feed()`/`goahead()` on this
      interpreter; every other `<![…` spelling — lower-cased, or an
      unrecognised keyword — is a bogus comment ending at the next literal
      `>`, the same as this branch's own fallback (second-reader round 5,
      S3).
    * `</` immediately followed by anything other than an ASCII letter, a
      `>`, or EOF is WHATWG's end tag open state "anything else"
      (§13.2.5.7): a bogus comment, ending at the next `>` and contributing
      no text — the same rule and the same shape as the `<!`/`<?` branch
      just above, not the bare-`<` neutralisation below, which would
      otherwise leave the comment's own content as surviving prose. `</>`
      (the `>` comes immediately) is the same bogus-comment search, landing
      on that very next `>` with nothing consumed in between. `</` at EOF is
      deliberately left to the bare-`<` rule below instead: WHATWG emits `<`
      and `/` as literal characters there, which that rule already produces
      without a dedicated branch (second-reader round 5, S1).
    * Anything else that opens with `<` but is not itself the start of a tag,
      and was not already handled by the `</` rule just above — WHATWG's tag
      open state only treats `<` as opening one on an ASCII letter, or `</`
      on one (`_TAG_OPEN_RE`) — is neutralised to a character reference at
      **that `<` alone**, and scanning resumes right after it,
      regardless of whether some later, unrelated `>` exists anywhere else in
      the document. This is F1 (round 2) *and* R2/R3 (round 4, the same rule
      applied generally rather than only to the `gt == -1` sub-case): the
      round-2 fix neutralised a bare `<` this way only when no `>` followed it
      anywhere in the document, so `5 < 10 <!-- salary` was fixed but `5 < 10
      <!-- salary <p>x</p>` was not — `gt = markup.find(">", lt)` is the *next*
      `>` in the whole document, not this bare `<`'s own, so the scan jumped
      to `gt + 1` and stepped over an unclassified `<!--`, `<!`, `<?` or start
      tag beginning in between, welding it into surviving prose (R2) or, when
      the skipped region was a `<script>` open tag, hiding the opaque element
      from the branch below entirely and reading its own internal `<!--` as a
      real, unterminated comment — deleting the rest of the document (R3). The
      scan must never step over a region it has not classified; only a
      confirmed tag or end tag may be skipped as one.

    Walked left to right rather than anchored on the document's last `>`:
    an outer, never-closed comment can itself contain `<tag>`-looking text
    whose own `>` would otherwise be mistaken for the point everything is
    "closed up to" — `<!-- <p>looks closed</p> but is not -->`'s outer
    comment has no real close (this constructed one does, on purpose, so it
    stays a no-op; a copy with the trailing `-->` deleted is what the tests
    exercise). Every ordinary `<...>` this scan passes over is treated as
    settled without asking whether it is *individually* well-formed — this
    function's only job is spotting a remainder with no closing token left
    anywhere in the document, not re-validating markup that already has one.

    **Known, accepted limit (F4, second-reader round 2): a `>` inside a
    quoted attribute value is not ordinary data to this scan** — `gt =
    markup.find(">", lt)` finds it and treats the tag as settled there, one
    interpreter patch (3.12.11, in this environment) then reads the rest of
    the malformed tag as literal data. Genuinely settled rather than fixed
    here: closing it needs attribute-value-aware scanning (tracking whether
    `lt..gt` is inside a `"`/`'` pair), which is exactly the "re-validating
    markup that already has one" this function declines to do, above. Rarer
    than F1/F2 in practice. **Not a claim about how many cases remain
    interpreter-dependent overall** — round 2's docstring stated a count here
    ("the one case left, of 28 checked") that round 3's own changes made
    false without anyone re-measuring it (second-reader round 4, R6: nothing
    tests prose), so this paragraph now says only what it can still stand
    behind: F4 itself is unresolved, on purpose, for the reason above.
    """
    i = 0
    while True:
        lt = markup.find("<", i)
        if lt == -1:
            return markup
        if markup.startswith("<!--", lt):
            content_start = lt + 4
            close_end = _comment_close_end(markup, content_start)
            if close_end is None:
                return markup[:lt]
            # Every terminated comment contributes no text either way, so
            # it is rewritten to the canonical empty form unconditionally
            # instead of being left verbatim for html.parser to close
            # itself - no build this repo runs on actually closes a
            # comment at the literal substring "-->" (see
            # _CANONICAL_EMPTY_COMMENT), so leaving any spelling for the
            # real parser to re-read was never safe (R1, R5, R6,
            # second-reader round 5, S2).
            markup = markup[:lt] + _CANONICAL_EMPTY_COMMENT + markup[close_end:]
            i = lt + len(_CANONICAL_EMPTY_COMMENT)
            continue
        if markup[lt : lt + 2] in ("<!", "<?"):
            if markup.startswith("<![CDATA[", lt):
                # html.parser's own dispatch (parse_html_declaration)
                # recognises only this exact, case-sensitive 9-character
                # literal as CDATA, and closes it on a plain,
                # non-whitespace-tolerant substring search for ']]>' -
                # never the next '>' - confirmed by reading that method's
                # source directly. Every other '<![' spelling, including a
                # lower-cased '<![cdata[' or an unrecognised marked-section
                # keyword, gets no such treatment and falls through to the
                # same "next literal '>'" handling as DOCTYPE and a bogus
                # comment below (measured directly against the real
                # parser), so only this one exact prefix needs its own
                # branch (second-reader round 5, S3).
                close = markup.find("]]>", lt + 9)
                if close == -1:
                    # EOF-truncated CDATA: once close() is called with no
                    # ']]>' found, html.parser's own EOF fallback consumes
                    # everything from just past '<![' to EOF as one
                    # declaration - the same "contributes no text" outcome
                    # as any other unterminated token here.
                    return markup[:lt]
                i = close + 3
                continue
            gt = markup.find(">", lt)
            if gt == -1:
                # Bogus comment or DOCTYPE, EOF-truncated: still a token that
                # contributes no text, exactly like an unterminated comment.
                return markup[:lt]
            i = gt + 1
            continue
        if (
            markup[lt : lt + 2] == "</"
            and lt + 2 < len(markup)
            and not _TAG_OPEN_RE.match(markup, lt)
        ):
            # WHATWG end tag open state (§13.2.5.7): '</' followed by
            # anything but a letter is "invalid-first-character-of-
            # tag-name" -> bogus comment (§13.2.5.41), which consumes to
            # the next '>' and contributes no text - a comment token, not
            # a character token - the same shape as the '<!'/'<?' branch
            # above, not the bare-'<' rule below it. '</' at EOF is
            # excluded on purpose: WHATWG's own EOF case there emits '<'
            # and '/' as literal characters, which the bare-'<'
            # neutralisation below already produces without help
            # (second-reader round 5, S1).
            gt = markup.find(">", lt)
            if gt == -1:
                return markup[:lt]
            i = gt + 1
            continue
        if not _TAG_OPEN_RE.match(markup, lt):
            # R2/R3 (round 4), generalising F1 (round 2): this '<' cannot
            # open a real tag no matter what '>' the rest of the document
            # holds - WHATWG's tag open state only starts one on an ASCII
            # letter (or '</' + one). Neutralise only this '<' and keep
            # scanning; a later, independent construct (another '<!--',
            # another '<', a real tag) must never be stepped over just
            # because this bare '<' happens to precede some unrelated '>'.
            markup = markup[:lt] + "&lt;" + markup[lt + 1 :]
            i = lt + 4
            continue
        gt = markup.find(">", lt)
        if gt == -1:
            # A genuine tag open with no '>' anywhere after it: EOF-truncated
            # start/end tag, F1's original bare-'<' rule applies the same way
            # here — neutralise the '<' alone and keep scanning.
            markup = markup[:lt] + "&lt;" + markup[lt + 1 :]
            i = lt + 4
            continue
        tag_name = _opening_tag_name(markup, lt, gt)
        if tag_name in _OPAQUE_TEXT_ELEMENTS:
            skip_to = _skip_opaque_element(markup, tag_name, gt + 1)
            if skip_to is None:
                # No end tag before EOF: everything left is this element's
                # opaque content anyway: there's nothing here left to mistake
                # for a tag or a comment.
                return markup
            i = skip_to
            continue
        i = gt + 1


def parse_html(html: str) -> Node:
    """Turn a page of markup into a `Node` tree. `HTMLParser` tokenises;
    nothing it produces is ever executed — every tag becomes a `Node`, every
    run of text becomes a string, full stop."""
    builder = _TreeBuilder()
    builder.feed(_neutralise_unterminated_tail(html))
    builder.close()
    return builder.root


def select_first(root: Node, selector: SimpleSelector) -> Node | None:
    """The first descendant of `root` matching `selector`, in document order,
    or `None`."""
    for node in root.iter_descendants():
        if node.matches(selector):
            return node
    return None


def select_all(root: Node, selector: SimpleSelector) -> list[Node]:
    """Every descendant of `root` matching `selector`, in document order."""
    return [node for node in root.iter_descendants() if node.matches(selector)]
