"""Find and mask financial identifiers and credentials in outgoing prompt text.

Stdlib only. Deliberately narrow: it targets values that could be used to move
money or sign in (card, SSN, routing, account and IBAN numbers, passwords, API
keys) and prefers missing a borderline case to flagging everyday numbers such
as phone numbers, dates, timestamps and order or task IDs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


KINDS = ("card", "ssn", "routing", "account", "iban", "credential")
# When two matches overlap, the earlier kind wins.
_PRIORITY = ("credential", "card", "iban", "ssn", "routing", "account")
MAX_PREVIEWS = 5


@dataclass(frozen=True)
class Finding:
    kind: str
    start: int
    end: int
    preview: str  # masked, never the raw value


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def _tail_preview(digits: str) -> str:
    # Show the last four only when they are a minority of the number.
    return "****" + digits[-4:] if len(digits) >= 9 else "****"


def luhn_ok(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = int(char)
        if index % 2:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def aba_ok(digits: str) -> bool:
    if len(digits) != 9 or digits == "0" * 9:
        return False
    d = [int(char) for char in digits]
    return (3 * (d[0] + d[3] + d[6]) + 7 * (d[1] + d[4] + d[7]) + (d[2] + d[5] + d[8])) % 10 == 0


def _is_yyyymmdd(digits: str) -> bool:
    return (
        len(digits) == 8
        and digits[:2] in ("19", "20")
        and "01" <= digits[4:6] <= "12"
        and "01" <= digits[6:8] <= "31"
    )


# --- payment cards -------------------------------------------------------

_CARD_START_RE = re.compile(r"(?<![A-Za-z0-9_.])(?<!\d-)\d")
# Longest shape first; a trailing stray number must not hide a real card.
_CARD_SHAPES = (
    re.compile(r"\d{4}([ -])\d{4}\1\d{4}\1\d{4}\1\d{1,3}"),
    re.compile(r"\d{4}([ -])\d{4}\1\d{4}\1\d{4}"),
    re.compile(r"\d{4}([ -])\d{6}\1\d{5}"),
    re.compile(r"\d{4}([ -])\d{6}\1\d{4}"),
    re.compile(r"\d{13,19}"),
)


def _card_prefix_ok(digits: str) -> bool:
    n = len(digits)
    p2, p3, p4 = int(digits[:2]), int(digits[:3]), int(digits[:4])
    if digits[0] == "4":  # Visa
        return n in (13, 16, 19)
    if 51 <= p2 <= 55 or 2221 <= p4 <= 2720:  # Mastercard
        return n == 16
    if p2 in (34, 37):  # American Express
        return n == 15
    if p4 == 6011 or 644 <= p3 <= 649 or p2 == 65:  # Discover
        return 16 <= n <= 19
    if p2 == 62:  # UnionPay
        return 16 <= n <= 19
    if 3528 <= p4 <= 3589:  # JCB
        return 16 <= n <= 19
    if 300 <= p3 <= 305 or p2 in (36, 38, 39):  # Diners Club
        return 14 <= n <= 19
    return False


def _card_end_ok(text: str, end: int) -> bool:
    return not (re.match(r"[A-Za-z0-9_]", text[end:end + 1]) or re.match(r"[-.]\d", text[end:end + 2]))


def _find_cards(text: str) -> list[Finding]:
    found = []
    resume = 0
    for start in _CARD_START_RE.finditer(text):
        if start.start() < resume:
            continue
        for shape in _CARD_SHAPES:
            match = shape.match(text, start.start())
            if not match or not _card_end_ok(text, match.end()):
                continue
            digits = _digits(match.group())
            if _card_prefix_ok(digits) and luhn_ok(digits):
                found.append(Finding("card", match.start(), match.end(), _tail_preview(digits)))
                resume = match.end()
                break
    return found


# --- SSN, routing and account numbers -------------------------------------

_SSN_RE = re.compile(r"(?<![\w-])(\d{3})-(\d{2})-(\d{4})(?![\w-])")
# Non-digit gap between a keyword and its number, never crossing a line.
_GAP = r"[^\d\n]{0,30}"
_NINE = r"(?<![A-Za-z0-9])(\d{9})(?![A-Za-z0-9])"
_SSN_KEYWORD_RE = re.compile(
    r"(?i:\b(?:ssn|social\s+security(?:\s+(?:number|no\.?|num\.?|#))?|soc\.?\s*sec\.?|ss\s*#))" + _GAP + _NINE
)
_ROUTING_KEYWORD_RE = re.compile(r"(?i:\b(?:routing|aba|rtn)\b)" + _GAP + _NINE)
_ACCOUNT_KEYWORD = (
    r"(?:account\s*(?:number|num\.?|no\.?|nr\.?|#|:)"
    r"|acct\b\.?\s*(?:number|num\.?|no\.?|#|:)?"
    r"|a/c\b"
    r"|(?:checking|savings|brokerage|bank|deposit)\s+account(?:\s+(?:number|no\.?|#))?)"
)
_ACCOUNT_RE = re.compile(
    r"(?i:\b" + _ACCOUNT_KEYWORD + r")" + _GAP +
    r"(?<![A-Za-z0-9])(\d{3,}(?:[ -]\d{3,}){0,5})(?![A-Za-z0-9])"
)


def _ssn_range_ok(area: str, group: str, serial: str) -> bool:
    return not (area in ("000", "666") or area[0] == "9" or group == "00" or serial == "0000")


def _find_ssns(text: str) -> list[Finding]:
    found = []
    for match in _SSN_RE.finditer(text):
        if _ssn_range_ok(*match.groups()):
            found.append(Finding("ssn", match.start(), match.end(), "****" + match.group(3)))
    for match in _SSN_KEYWORD_RE.finditer(text):
        digits = match.group(1)
        if _ssn_range_ok(digits[:3], digits[3:5], digits[5:]):
            found.append(Finding("ssn", match.start(1), match.end(1), "****" + digits[5:]))
    return found


def _find_routing(text: str) -> list[Finding]:
    return [
        Finding("routing", m.start(1), m.end(1), _tail_preview(m.group(1)))
        for m in _ROUTING_KEYWORD_RE.finditer(text)
        if aba_ok(m.group(1))
    ]


def _find_accounts(text: str) -> list[Finding]:
    found = []
    for match in _ACCOUNT_RE.finditer(text):
        raw = match.group(1)
        digits = _digits(raw)
        groups = tuple(len(group) for group in re.split(r"[ -]", raw))
        if groups in ((3, 3, 4), (3, 4)):  # phone number, not an account
            continue
        before = text[:match.start(1)].rstrip(" ")
        if before.endswith("$") or re.match(r"\.\d", text[match.end(1):match.end(1) + 2]):
            continue  # a dollar amount, not an account
        if 6 <= len(digits) <= 17 and not _is_yyyymmdd(digits):
            found.append(Finding("account", match.start(1), match.end(1), _tail_preview(digits)))
    return found


# --- IBAN ----------------------------------------------------------------

_IBAN_LENGTHS = dict(
    pair.split(":")
    for pair in (
        "AD:24 AE:23 AL:28 AT:20 AZ:28 BA:20 BE:16 BG:22 BH:22 BR:29 BY:28 CH:21 CR:22 CY:28 CZ:24 DE:22 "
        "DK:18 DO:28 EE:20 EG:29 ES:24 FI:18 FO:18 FR:27 GB:22 GE:22 GI:23 GL:18 GR:27 GT:28 HR:21 HU:28 "
        "IE:22 IL:23 IQ:23 IS:26 IT:27 JO:30 KW:30 KZ:20 LB:28 LC:32 LI:21 LT:20 LU:20 LV:21 LY:25 MC:27 "
        "MD:24 ME:22 MK:19 MR:27 MT:31 MU:30 NL:18 NO:15 PK:24 PL:28 PS:29 PT:25 QA:29 RO:24 RS:22 SA:24 "
        "SC:31 SE:24 SI:19 SK:24 SM:27 ST:25 SV:28 TL:23 TN:24 TR:26 UA:29 VA:22 VG:24 XK:20"
    ).split()
)
_IBAN_START_RE = re.compile(r"(?<![A-Za-z0-9])[A-Z]{2}\d{2}")


def iban_ok(compact: str) -> bool:
    rearranged = compact[4:] + compact[:4]
    return int("".join(str(int(char, 36)) for char in rearranged)) % 97 == 1


def _find_ibans(text: str) -> list[Finding]:
    found = []
    for match in _IBAN_START_RE.finditer(text):
        length = int(_IBAN_LENGTHS.get(match.group()[:2], 0))
        if not length:
            continue
        # Walk forward collecting capitals and digits, allowing single spaces.
        chars, pos = [], match.start()
        while pos < len(text) and len(chars) < length:
            char = text[pos]
            if char.isascii() and (char.isdigit() or char.isupper()):
                chars.append(char)
            elif char != " " or text[pos - 1] == " ":
                break
            pos += 1
        if len(chars) == length and not re.match(r"[A-Za-z0-9]", text[pos:pos + 1]) and iban_ok("".join(chars)):
            found.append(Finding("iban", match.start(), pos, _tail_preview("".join(chars))))
    return found


# --- credentials ---------------------------------------------------------

_PASSWORD_RE = re.compile(
    r"(?i:(?<![A-Za-z])(?:password|passwd|pwd|passcode|passphrase))[\"']?[ \t]*[:=][ \t]*"
    r"(?:\"([^\"\n]{4,})\"|'([^'\n]{4,})'|([^\s,;\"']{3,}[^\s,;\"'.)\]]))"
)
_PIN_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:PIN[ \t]*#?[ \t]*|(?i:pin)(?:[ \t]+(?:code|number))?[ \t]*(?:[:=]|\bis\b)[ \t]*)"
    r"[\"']?(\d{4,8})(?![\w-])"
)
_KEY_PATTERNS = (
    re.compile(r"(?<![A-Za-z0-9_-])sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"(?<![A-Za-z0-9_])[sr]k_live_[A-Za-z0-9]{16,}"),
    re.compile(r"(?<![A-Za-z0-9_])gh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"(?<![A-Za-z0-9_])github_pat_[A-Za-z0-9_]{50,}"),
    re.compile(r"(?<![A-Za-z0-9-])xox[abprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"(?<![A-Za-z0-9])(?:AKIA|ASIA)[0-9A-Z]{16}(?![A-Za-z0-9])"),
    re.compile(r"(?<![A-Za-z0-9_-])AIza[0-9A-Za-z_-]{35}"),
)
_BEARER_RE = re.compile(r"(?i:\bbearer)[ \t]+([A-Za-z0-9._~+/-]{20,}=*)")
_PEM_RE = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"(?:[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----|(?:[ \t]*\r?\n[A-Za-z0-9+/=]{20,}[ \t]*)+)"
)
_PLACEHOLDER_WORDS = {"password", "passwd", "secret", "changeme", "example"}


def _has_digit(value: str) -> bool:
    return any(char.isdigit() for char in value)


def _password_value_ok(value: str) -> bool:
    if value.lower() in _PLACEHOLDER_WORDS or "REDACTED" in value:
        return False
    if value[0] in "<{$%[(*\u2022.#" or not value.strip("xX*\u2022._-#"):
        return False
    if value.lower().startswith(("http://", "https://", "www.")):
        return False
    if re.search(r"\s", value) and not _has_digit(value):
        return False
    # A bare lowercase word ("required", "reset") is prose, not a password.
    return not (value.isalpha() and value.islower())


def _find_credentials(text: str) -> list[Finding]:
    found = []
    for match in _PASSWORD_RE.finditer(text):
        group = next(i for i in (1, 2, 3) if match.group(i))
        if _password_value_ok(match.group(group)):
            found.append(Finding("credential", match.start(group), match.end(group), "password"))
    for match in _PIN_RE.finditer(text):
        found.append(Finding("credential", match.start(1), match.end(1), "PIN"))
    for pattern in _KEY_PATTERNS:
        for match in pattern.finditer(text):
            if _has_digit(match.group()):
                found.append(Finding("credential", match.start(), match.end(), "API key"))
    for match in _BEARER_RE.finditer(text):
        if _has_digit(match.group(1)) and re.search(r"[A-Za-z]", match.group(1)):
            found.append(Finding("credential", match.start(1), match.end(1), "bearer token"))
    for match in _PEM_RE.finditer(text):
        found.append(Finding("credential", match.start(), match.end(), "private key"))
    return found


# --- public API ----------------------------------------------------------

def find_sensitive(text: str) -> list[Finding]:
    """Return non-overlapping findings in text order."""
    candidates = (
        _find_credentials(text) + _find_cards(text) + _find_ibans(text) + _find_ssns(text)
        + _find_routing(text) + _find_accounts(text)
    )
    candidates.sort(key=lambda f: (_PRIORITY.index(f.kind), f.start))
    kept: list[Finding] = []
    for finding in candidates:
        if all(finding.end <= other.start or finding.start >= other.end for other in kept):
            kept.append(finding)
    return sorted(kept, key=lambda f: f.start)


def mask_sensitive(text: str, findings: list[Finding] | None = None) -> tuple[str, list[Finding]]:
    """Replace each finding with [REDACTED:<kind>]; return the masked text and the findings."""
    if findings is None:
        findings = find_sensitive(text)
    pieces, cursor = [], 0
    for finding in findings:
        pieces.append(text[cursor:finding.start])
        pieces.append(f"[REDACTED:{finding.kind}]")
        cursor = finding.end
    pieces.append(text[cursor:])
    return "".join(pieces), findings


def summarize(findings: list[Finding]) -> list[dict[str, object]]:
    """Per-kind counts with masked previews, safe to print or store."""
    rows = []
    for kind in KINDS:
        of_kind = [f for f in findings if f.kind == kind]
        if of_kind:
            previews = list(dict.fromkeys(f.preview for f in of_kind))[:MAX_PREVIEWS]
            rows.append({"kind": kind, "count": len(of_kind), "previews": previews})
    return rows
