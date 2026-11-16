import logging
import re
import threading


class LogMasker:
    """All masking for log output and error text, in one place.

    mask() runs every rule. Secrets (passwords, answers), URL session tokens, key=value secrets
    (PWD=, AccountKey=, sig=, ...) and URL passwords (postgresql://user:***@host) are always masked. The PII rules in pii_rules (ER numbers today)
    run only while `enabled` is True, which LogSetup.configure sets from mask_sensitive_data in
    logger.properties.

    Secrets come from two places: the `secrets` a caller passes to one mask() call, and the ones
    registered with register_secret (a run's STEERS password, a new draft's application password),
    which every later mask() call hides, in every log line, until they are cleared. A registered value
    is replaced wherever it appears, so register only long, random values: a short common word (a
    security answer) would rewrite fixed text into a *** that gives it away. Pass those per call.

    To add a rule: write a method that takes text and returns it masked, then add its name to
    pii_rules (switched by the flag) or always_rules (never switched off).
    """

    MASK = "***"
    ER_NUMBER = re.compile(r"\bER\d{4,}\b", re.IGNORECASE)
    # The token ends at &, whitespace, a quote, or a bracket, so "[... ?log=abc]" keeps its closing ].
    URL_SESSION_PARAM = re.compile(
        r"\b(log|cfsecid|cfsectoken|cfid|cftoken|jsessionid)=[^&\s\"'<>()\[\]]+", re.IGNORECASE
    )
    # Connection-string and URL secrets. The key must not follow a letter or digit (design= is not sig=,
    # db_password= is Password=). The value ends at ;, &, whitespace or the end of the text; an ODBC
    # value in braces ({a;b}, with }} for a literal }) is masked whole.
    KEY_VALUE_SECRET = re.compile(
        r"(?<![A-Za-z0-9])(PWD|Password|AccountKey|SharedAccessSignature|sig|Client_?Secret)([ \t]*=[ \t]*)"
        r"(?:\{(?:[^}\n]|\}\})*\}?|[^;&\s]+)",  # an unclosed brace is masked to the end of the line
        re.IGNORECASE,
    )
    # The password in a URL's user:password@ part, e.g. DATABASE_URL (postgresql://postgres:secret@host).
    URL_CREDENTIALS = re.compile(r"(://[^:/?#@\s]+:)[^@\s/]+@")

    always_rules = ("mask_session_tokens", "mask_key_value_secrets", "mask_url_credentials")
    pii_rules = ("mask_er_numbers",)

    def __init__(self, enabled=True):
        """Start with masking on (the safe default until a properties file says otherwise)."""
        self.enabled = enabled
        self._registered = set()
        self._registered_lock = threading.Lock()  # log lines can come from several threads

    def register_secret(self, value):
        """Hide this exact value in every later mask() call; empty or blank values are ignored."""
        if not isinstance(value, str) or not value.strip():
            return
        with self._registered_lock:
            self._registered.add(value)

    def clear_registered_secrets(self):
        """Forget every registered secret (tests, or a process that starts a new run)."""
        with self._registered_lock:
            self._registered.clear()

    def mask(self, text, secrets=()):
        """Return text with the given and the registered secrets and every rule's matches masked."""
        with self._registered_lock:
            registered = tuple(self._registered)
        masked = self.mask_secrets(text or "", (*secrets, *registered))
        rules = self.always_rules + (self.pii_rules if self.enabled else ())
        for name in rules:
            masked = getattr(self, name)(masked)
        return masked

    def mask_secrets(self, text, secrets):
        """Replace each exact secret value with ***, longest first, ignoring case; empty ones are skipped."""
        for secret in sorted((s for s in secrets if s), key=len, reverse=True):
            text = re.sub(re.escape(secret), self.MASK, text, flags=re.IGNORECASE)
        return text

    def mask_session_tokens(self, text):
        """Blank STEERS session tokens in URLs: log=abc123 -> log=..."""
        return self.URL_SESSION_PARAM.sub(lambda match: f"{match.group(1)}=...", text)

    def mask_key_value_secrets(self, text):
        """Mask the value of each secret key=value pair, keeping the key: PWD=abc;UID=x -> PWD=***;UID=x."""
        return self.KEY_VALUE_SECRET.sub(lambda match: f"{match.group(1)}{match.group(2)}{self.MASK}", text)

    def mask_url_credentials(self, text):
        """Mask a URL's password, keeping the user: postgresql://postgres:pw@host -> postgresql://postgres:***@host."""
        return self.URL_CREDENTIALS.sub(lambda match: f"{match.group(1)}{self.MASK}@", text)

    def mask_er_numbers(self, text):
        """Shorten every ER number in free text: ER000000 -> ER****00."""
        return self.ER_NUMBER.sub(lambda match: self._shorten_er_number(match.group(0)), text)

    def mask_er_number(self, er_number):
        """Shorten one ER number (ER000000 -> ER****00) while masking is on; short input gives ER****."""
        text = (er_number or "").strip()
        return self._shorten_er_number(text) if self.enabled else text

    @staticmethod
    def _shorten_er_number(text):
        """Keep the first 2 and last 2 characters: ER000000 -> ER****00."""
        if len(text) <= 4:
            return "ER****"
        return text[:2] + "*" * (len(text) - 4) + text[-2:]


class MaskingFormatter(logging.Formatter):
    """Wraps another handler's formatter (e.g. the console's) and masks each finished line."""

    def __init__(self, inner, masker):
        """Keep the formatter to wrap and the masker to apply."""
        super().__init__()
        self.inner = inner or logging.Formatter()
        self.masker = masker

    def format(self, record):
        """The inner formatter's line, masked."""
        return self.masker.mask(self.inner.format(record))


masker = LogMasker()  # the one instance shared by the logger and the code's own masking calls
