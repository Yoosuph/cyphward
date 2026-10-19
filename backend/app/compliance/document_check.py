"""The check on reworded draft text (packet C5b). Pure: no database, no network, never raises.

A draft is built from a fixed template. A model may reword it, and this module decides whether the reworded
text may be stored. The decision is structural. Reworded text is accepted only when it is the template, line for
line and sentence for sentence, with the same words in a possibly different order, plus a short fixed list of
glue words that cannot carry a claim.

1. Both texts go through one normaliser (`fold`): compatibility forms, invisible characters, combining marks,
   look-alike letters, hyphen splits and case. Every comparison below uses it.
2. Output may not contain a non-ASCII character that the template (outside its placeholders) does not contain.
3. The reworded text has the same lines in the same order, with the same heading, list number and table rows.
4. Each line has the same number of sentences, and sentence N of the output is compared with sentence N of the
   template. Nothing is dropped, merged, split or added.
5. In each pair of sentences, every word that is not on the glue list (`FREE`) must appear exactly as often as in
   the template. This holds for negations, modals, quantifiers, commitment verbs, numbers, dates, units, names,
   `{{TOKENS}}` and `[MISSING: ...]` placeholders, and it also stops a content word being dropped (dropping
   "outside Nigeria" from a negation would widen what it covers).
6. Content words keep the template's order inside each clause (the pieces between commas, semicolons and
   colons); only whole clauses may change places.
7. For every negation, modal, quantifier, conjunction and condition word, the next content word must be the
   same as in the template, so a "not" cannot end up pointing at another verb.
8. A defence-in-depth detector rejects a sentence that has the shape of an obligation or assurance that the
   template sentence lacks.

What this does not do: it does not read meaning. Glue words are free and whole clauses may change places, so a
rewording can still be clumsy, and moving a clause can change how a sentence reads (the words and their order
inside each clause cannot change). The draft carries the "not legal advice" label and a practitioner is told to review it.
"""
import re
import unicodedata
from collections import Counter
from typing import Callable, Dict, List, Optional, Tuple

SLOT = re.compile(r"\{\{[A-Z_]+\}\}")
PLACEHOLDER = re.compile(r"\[MISSING: [^\[\]\n]{1,200}\]")
TOKEN = re.compile(SLOT.pattern + "|" + PLACEHOLDER.pattern)

# Claims a drafting assistant is most tempted to make. Matched as lowercase substrings of the normalised text.
BANNED = (
    "partial compliance", "fully compliant", "is compliant", "compliant", "complies", "in compliance",
    "satisfy ndpa", "satisfies", "satisfied", "certif", "ndpa 2023 compliant", "cbn compliant",
    "passes audit", "pass the audit", "compliance score", "fully meets", "meets the requirement",
    "meets the requirements", "is met", "guarantee", "adequate", "adequacy", "legally sufficient",
    "legal sufficiency", "ensures compliance", "sufficient for compliance",
)
STEMS = ("compliant", "complies", "certif", "satisf", "adequa", "guarante")

# Look-alike letters that survive NFKC, folded to the Latin letter they imitate (applied after lowercasing).
CONFUSABLES = str.maketrans({
    # Cyrillic
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x", "у": "y", "і": "i", "ј": "j", "ѕ": "s", "һ": "h",
    "ԁ": "d", "ɡ": "g", "ԍ": "g", "ѵ": "v", "ԛ": "q", "ԝ": "w", "ӏ": "l", "к": "k", "т": "t", "м": "m", "н": "h",
    "в": "b", "п": "n", "ё": "e",
    # Greek
    "ν": "v", "ο": "o", "α": "a", "ε": "e", "ι": "i", "κ": "k", "ρ": "p", "τ": "t", "υ": "u", "γ": "y", "η": "n",
    "χ": "x", "μ": "u", "β": "b",
    # Armenian
    "օ": "o", "ո": "n", "ս": "u", "հ": "h", "ց": "g", "զ": "q", "ԑ": "e", "ɩ": "i",
    # Latin letters that do not decompose
    "ø": "o", "ł": "l", "đ": "d", "ı": "i", "ð": "d", "ƒ": "f", "ɑ": "a", "ʋ": "v",
})
HYPHENS = "‐‑‒­-"
HYPHEN_SPLIT = re.compile(rf"(?<=[a-z])\s*[{re.escape(HYPHENS)}]+\s*(?=[a-z])")


def fold(text: str) -> str:
    """Text as a reader sees it, for every comparison: compatibility forms folded (full-width letters), invisible
    format characters (Cf) and combining marks (Mn) removed, look-alike letters mapped to Latin, hyphen splits
    joined ("com- pliant"), lower case. Whitespace is left alone."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if unicodedata.category(ch) not in ("Cf", "Mn"))
    text = unicodedata.normalize("NFKC", text).lower().translate(CONFUSABLES)
    return HYPHEN_SPLIT.sub("", text)


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", fold(text)).strip()


def banned_hits(text: str) -> List[str]:
    lowered = _squash(text)
    hits = [phrase for phrase in BANNED if phrase in lowered]
    # A claim broken up inside one word with dots or other marks ("c.o.m.p.l.i.a.n.t"): check each token with
    # its non-letters removed (per token, so letters of neighbouring words never join up).
    tokens = lowered.split()
    for token in tokens:
        letters = re.sub(r"[^a-z]", "", token)
        hits += [stem for stem in STEMS if stem in letters and stem not in hits]
    # ... or spelled out one letter at a time ("c o m p l i a n t"): join runs of single-letter tokens.
    run = ""
    for token in tokens + [""]:
        letters = re.sub(r"[^a-z]", "", token)
        if len(letters) == 1:
            run += letters
            continue
        hits += [stem for stem in STEMS if len(run) > 3 and stem in run and stem not in hits]
        run = ""
    return hits


# ── Words ────────────────────────────────────────────────────────────────────

# Words that cannot carry a claim. Output may use any of them any number of times, and need not keep the ones the
# template has. Everything else must match the template exactly (see the module note).
GLUE = frozenset("""
    a an the of to in on at by for with from as that this these those it its which who whom is are be been being was
    were am do does did has have had also then there here example out
""".split())
# Verbs that describe the document itself. "explains how" may become "describes how".
NEUTRAL = frozenset("explain explains describe describes outline outlines show shows list lists cover covers sets".split())
FREE = GLUE | NEUTRAL

NEGATIONS = frozenset("not no never none cannot without nor neither nothing nobody nowhere nt".split())
MODALS = frozenset("will shall must may can could should would might cannot".split())
QUANTIFIERS = frozenset("all every any each only some always both either many few several most more less".split())
COMMITMENT_VERBS = frozenset("""
    ensure ensures ensured guarantee guarantees commit commits committed promise promises undertake undertakes
    require requires required secure secures encrypt encrypts encrypted delete deletes erase erases protect
    protects comply complies meet meets fulfil fulfils fulfill satisfy satisfies safeguard safeguards
""".split())
CONNECTIVES = frozenset("and or if when where unless until once after before within while because since except".split())
SCOPED = NEGATIONS | MODALS | QUANTIFIERS | COMMITMENT_VERBS | CONNECTIVES
# Number, month and weekday words carry facts without a digit ("seven years", "every March").
FACT_WORDS = frozenset("""
    one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen
    eighteen nineteen twenty thirty forty fifty sixty seventy eighty ninety hundred thousand million dozen
    january february march april may june july august september october november december
    jan feb mar apr jun jul aug sep sept oct nov dec monday tuesday wednesday thursday friday saturday sunday
    daily weekly monthly quarterly annually yearly annual
    second seconds minute minutes hour hours day days week weeks month months year years
""".split())

# Nothing the check relies on may be free: a glue word that is also a claim word would let one be added.
assert not (FREE & (SCOPED | FACT_WORDS))

WORD = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")


def _is_negation(word: str) -> bool:
    return word in NEGATIONS or word.endswith("n't")


def _atom(match: "re.Match") -> str:
    # A placeholder or slot becomes one opaque word that is the same for the same token text.
    import hashlib
    return " zz" + hashlib.sha1(match.group(0).encode()).hexdigest()[:10] + " "


# ── Structure ────────────────────────────────────────────────────────────────

LINE_PREFIX = re.compile(r"^(?:#{1,6}\s+|\d{1,2}[.)]\s+|[-*+]\s+)")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


class Parsed:
    """A text split into non-empty lines; each prose line into (prefix, sentences of normalised words)."""

    def __init__(self, text: str):
        atomised = TOKEN.sub(_atom, text.replace("\r", ""))
        self.lines: List[Tuple[str, str, List[str]]] = []  # (kind, prefix, sentences)
        for raw in atomised.split("\n"):
            line = raw.strip()
            if not line:
                continue
            if line.startswith("#") or line.startswith("|"):
                self.lines.append(("exact", "", [_squash(line)]))
                continue
            prefix = LINE_PREFIX.match(line)
            head = prefix.group(0).strip() if prefix else ""
            body = line[prefix.end():] if prefix else line
            sentences = [s.strip(" \t.!?") for s in SENTENCE_END.split(body)]
            self.lines.append(("prose", head, [_squash(s) for s in sentences if s.strip(" \t.!?")]))


def _words(sentence: str) -> List[str]:
    return WORD.findall(sentence)


def _content(words: List[str]) -> List[str]:
    return [w for w in words if w not in FREE]


def _scope_pairs(words: List[str]) -> Counter:
    pairs: Counter = Counter()
    for i, word in enumerate(words):
        if word in SCOPED or _is_negation(word):
            following = next((w for w in words[i + 1:] if w not in FREE), "<end>")
            pairs[(word, following)] += 1
    return pairs


# Obligation and assurance shapes. A sentence may have one only when its template sentence has it too.
_ACTS = r"(?:encrypt|delet|eras|protect|secur|compl|meet|ensur|fulfil|satisf|safeguard|retain|keep|share|sell|guarant)\w*"
CLAIM_SHAPES = tuple(re.compile(p) for p in (
    r"\b(?:we|us|our)\b.*\b(?:will|shall|always|never|must|ensure|guarantee|commit|promise|undertake)",
    rf"\b(?:will|shall|always|never|must)\b.*\b{_ACTS}",
    rf"\b(?:every|all|any)\b.*\b{_ACTS}",
    r"\bin accordance with\b", r"\bin line with\b", r"\bin compliance\b", r"\bas required by\b",
    r"\bfulfil", r"\bsatisf", r"\bcompl(?:y|ies|ying|iant)\b", r"\bensur", r"\bmeet", r"\bmet\b",
    r"\bapplicable (?:data protection )?(?:law|laws|legislation|regulations?)\b", r"\blegal obligations?\b",
    r"\bin full\b", r"\bfully\b",
))


# ── Rules ────────────────────────────────────────────────────────────────────
# Each rule takes the reworded and the template text, and returns a reason or None. They run in order.

Rule = Callable[[str, str, Parsed, Parsed], Optional[str]]


def _outside_placeholders(text: str) -> str:
    return TOKEN.sub(" ", text)


def rule_non_ascii(output: str, template: str, o: Parsed, t: Parsed) -> Optional[str]:
    extra = {ch for ch in _outside_placeholders(output) if ord(ch) > 127} - {
        ch for ch in _outside_placeholders(template) if ord(ch) > 127}
    return "non_ascii_added" if extra else None


def rule_lines(output: str, template: str, o: Parsed, t: Parsed) -> Optional[str]:
    if len(o.lines) != len(t.lines):
        return "lines_changed"
    for (ok, op, os_), (tk, tp, ts) in zip(o.lines, t.lines):
        if ok != tk or op != tp:
            return "structure_changed"
        if tk == "exact" and os_ != ts:
            return "structure_changed"  # headings and table rows are not reworded
    return None


def rule_sentence_count(output: str, template: str, o: Parsed, t: Parsed) -> Optional[str]:
    for (_, _, os_), (_, _, ts) in zip(o.lines, t.lines):
        if len(os_) != len(ts):
            return "sentences_changed"
    return None


def _pairs(o: Parsed, t: Parsed):
    for (kind, _, os_), (_, _, ts) in zip(o.lines, t.lines):
        if kind == "prose":
            yield from zip(os_, ts)


def _count_rule(select: Callable[[str], bool], reason: str) -> Rule:
    def rule(output: str, template: str, o: Parsed, t: Parsed) -> Optional[str]:
        for out_s, tpl_s in _pairs(o, t):
            if Counter(w for w in _words(out_s) if select(w)) != Counter(w for w in _words(tpl_s) if select(w)):
                return reason
        return None
    return rule


rule_negations = _count_rule(_is_negation, "negation_changed")
rule_commitments = _count_rule(lambda w: w in MODALS or w in QUANTIFIERS or w in COMMITMENT_VERBS, "commitment_changed")
rule_numbers = _count_rule(lambda w: any(c.isdigit() for c in w) or w in FACT_WORDS, "number_changed")


def rule_content_words(output: str, template: str, o: Parsed, t: Parsed) -> Optional[str]:
    for out_s, tpl_s in _pairs(o, t):
        have, want = Counter(_content(_words(out_s))), Counter(_content(_words(tpl_s)))
        if have != want:
            return "words_added" if have - want else "words_dropped"
    return None


CLAUSE_BREAK = re.compile(r"[,;:]")


def _clause_sequences(sentence: str) -> List[Tuple[str, ...]]:
    parts = (tuple(_content(_words(part))) for part in CLAUSE_BREAK.split(sentence))
    return [part for part in parts if part]


def _is_clause_permutation(sequence: Tuple[str, ...], clauses: List[Tuple[str, ...]]) -> bool:
    """True when `sequence` is the clauses laid end to end in some order."""
    def go(pos: int, remaining: List[Tuple[str, ...]]) -> bool:
        if pos == len(sequence):
            return not remaining
        for i, clause in enumerate(remaining):
            if (i == 0 or remaining[i - 1] != clause) and sequence[pos:pos + len(clause)] == clause:
                if go(pos + len(clause), remaining[:i] + remaining[i + 1:]):
                    return True
        return False
    return go(0, clauses)


def rule_clause_order(output: str, template: str, o: Parsed, t: Parsed) -> Optional[str]:
    """Only whole clauses (the pieces between commas, semicolons and colons) may change places. The content
    words inside a clause keep the template's order, so "do not store personal data or send it" cannot be made
    out of "do not store or send personal data"."""
    for out_s, tpl_s in _pairs(o, t):
        if not _is_clause_permutation(tuple(_content(_words(out_s))), _clause_sequences(tpl_s)):
            return "order_changed"
    return None


def rule_scope(output: str, template: str, o: Parsed, t: Parsed) -> Optional[str]:
    for out_s, tpl_s in _pairs(o, t):
        if _scope_pairs(_words(out_s)) != _scope_pairs(_words(tpl_s)):
            return "scope_changed"
    return None


def rule_claim_shape(output: str, template: str, o: Parsed, t: Parsed) -> Optional[str]:
    for out_s, tpl_s in _pairs(o, t):
        for shape in CLAIM_SHAPES:
            if shape.search(out_s) and not shape.search(tpl_s):
                return "claim_shape"
    return None


RULES: List[Tuple[str, Rule]] = [
    ("non_ascii", rule_non_ascii),
    ("lines", rule_lines),
    ("sentence_count", rule_sentence_count),
    ("negations", rule_negations),
    ("commitments", rule_commitments),
    ("numbers", rule_numbers),
    ("content_words", rule_content_words),
    ("clause_order", rule_clause_order),
    ("scope", rule_scope),
    ("claim_shape", rule_claim_shape),
]


def structural_problem(output: str, template: str, rules: Optional[List[Tuple[str, Rule]]] = None) -> Optional[str]:
    """None when `output` is a faithful rewording of `template`, otherwise a short reason. Never raises: any
    error while checking counts as a rejection."""
    try:
        o, t = Parsed(output), Parsed(template)
        for _, rule in (RULES if rules is None else rules):
            problem = rule(output, template, o, t)
            if problem:
                return problem
        return None
    except Exception:  # fail safe: if the check cannot run, the text is not used
        return "check_failed"
