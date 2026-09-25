# -*- coding: utf-8 -*-
"""One VisiLean API token per project: where it comes from and how it is used.

VisiLean scopes a token to one project, and one token serves every feed a dashboard
reads (type=task, type=task + history flags, type=constraintLog). A project's token is
looked up in this order, and every candidate found is kept:

  1. the per-project repository secret          VL_TOKEN_<KEY>      e.g. VL_TOKEN_SJVN
  2. that project's entry in VL_TOKENS_JSON     {"sjvn": "<token>", "ntpc": "<token>"}
  3. locally, the same flat map in the gitignored scripts/vl_tokens.json

The builders fetch with the first candidate. If VisiLean rejects it (HTTP 400 "not
valid for the requested project", or HTTP 500 "API does not exist") they switch to the
next one and put a ::warning on the run naming the secret to fix. Only when every
candidate is rejected does a fetch give up, with TokenRejected, which the builders turn
into a failed cycle rather than the quiet "SKIP this cycle" an outage gets.

Nothing here ever prints a token.
"""
import io, json, os, time, urllib.error, urllib.request

SCR = os.path.dirname(os.path.abspath(__file__))
TOKENS_FILE = os.path.join(SCR, "vl_tokens.json")
TOKENS_FILE_NAME = "scripts/vl_tokens.json"

KEYS = ("ntpc", "sjvn", "adani", "adanis7", "floating")
LABELS = {
    "ntpc":     "NTPC Bikaner Block 8",
    "sjvn":     "SJVN Khavda",
    "adani":    "Adani S6a",
    "adanis7":  "Adani S7",
    "floating": "Floating Solar",
}
# keys that only ever appeared in the old three-tokens-per-project shape
LEGACY_KEYS = {"task", "history", "constraintlog", "constraints", "hist", "notes",
               "adopt_task", "adopt_hist", "adopt_notes"}

OLD_SHAPE = (
    '%s is in the old per-feed shape ({"ntpc": {"task": ..., "history": ..., '
    '"constraintLog": ...}} or {"task": ..., "history": ...}). VisiLean now issues one '
    'token per project that serves every feed, so each value must be a single string: '
    '{"ntpc": "<token>", "sjvn": "<token>"}')


class TokenError(Exception):
    """A secret or token file that cannot be used. The message is user-facing."""


class TokenRejected(Exception):
    """VisiLean rejected every token this project has."""


def env_name(key):
    return "VL_TOKEN_" + key.upper()


def parse_tokens_map(blob, source="VL_TOKENS_JSON"):
    """The flat {key: token} map, validated. Raises TokenError on anything else."""
    try:
        parsed = json.loads(blob)
    except Exception as e:
        raise TokenError("%s is not valid JSON: %s" % (source, e))
    if not isinstance(parsed, dict):
        raise TokenError('%s must be a JSON object like {"ntpc": "<token>"}, got %s'
                         % (source, type(parsed).__name__))
    out = {}
    for k, v in parsed.items():
        kl = str(k).strip().lower()
        if kl in LEGACY_KEYS or isinstance(v, dict):
            raise TokenError(OLD_SHAPE % source)
        if v is None or (isinstance(v, str) and not v.strip()):
            continue                                   # a placeholder, treat as absent
        if not isinstance(v, str):
            raise TokenError('%s: the value for "%s" must be a string, got %s'
                             % (source, k, type(v).__name__))
        out[kl] = v.strip()
    return out


def tokens_from_env():
    blob = os.environ.get("VL_TOKENS_JSON", "").strip()
    return parse_tokens_map(blob) if blob else {}


def tokens_from_file():
    if not os.path.exists(TOKENS_FILE):
        return {}
    text = io.open(TOKENS_FILE, encoding="utf-8").read()
    return parse_tokens_map(text, TOKENS_FILE_NAME) if text.strip() else {}


def candidates(key):
    """Ordered, de-duplicated [(token, source)] for this project. May raise TokenError."""
    out, seen = [], set()

    def add(tok, src):
        tok = (tok or "").strip()
        if tok and tok not in seen:
            seen.add(tok)
            out.append((tok, src))

    add(os.environ.get(env_name(key)), env_name(key))
    add(tokens_from_env().get(key), "VL_TOKENS_JSON")
    add(tokens_from_file().get(key), TOKENS_FILE_NAME)
    return out


def missing_message(key):
    return ('no VisiLean token for %s: set the %s secret, or add "%s" to VL_TOKENS_JSON '
            '(or %s locally) as {"%s": "<token>"}'
            % (LABELS.get(key, key), env_name(key), key, TOKENS_FILE_NAME, key))


def _body(e):
    """The response body of an HTTPError, read once and cached on the exception."""
    if not hasattr(e, "vl_body"):
        try:
            e.vl_body = e.read().decode("utf-8", "replace")
        except Exception:
            e.vl_body = ""
    return e.vl_body


def describe(e):
    """A log-safe one-liner for a fetch failure. Never includes the URL."""
    if isinstance(e, urllib.error.HTTPError):
        msg = ""
        try:
            msg = json.loads(_body(e)).get("error", "")
        except Exception:
            pass
        return "HTTP %s%s" % (e.code, " - " + str(msg)[:120] if msg else "")
    return str(e)[:160]


def is_rejection(e):
    """True when VisiLean is saying 'wrong token', as opposed to being down."""
    if not isinstance(e, urllib.error.HTTPError):
        return False
    if e.code == 400:
        return True
    return e.code == 500 and "api does not exist" in _body(e).lower()


class TokenPool:
    """This project's candidate tokens, in the order they should be tried."""

    def __init__(self, key, label=None):
        self.key = key
        self.label = label or LABELS.get(key, key)
        try:
            self._c = candidates(key)
        except TokenError as e:
            raise SystemExit(str(e))
        if not self._c:
            raise SystemExit(missing_message(key))
        self.rejected = []

    def current(self):
        return self._c[0]

    def sources(self):
        return [s for _, s in self._c]

    def reject(self, err):
        """Drop the active candidate in favour of the next. Returns True if there is a
        next one. The last candidate is never dropped, so later feeds can still try it."""
        _, src = self._c[0]
        self.rejected.append(src)
        if len(self._c) > 1:
            self._c.pop(0)
            print("::warning title=%s token rejected::%s was rejected by VisiLean (%s); "
                  "switching to %s. Fix or delete that secret."
                  % (self.label, src, describe(err), self._c[0][1]))
            return True
        print("::error title=%s token rejected::%s was rejected by VisiLean (%s) and there "
              "is no other token to try." % (self.label, src, describe(err)))
        return False


def fetch_json(pool, make_url, attempts=3, label="", agent="VisiLean-MIS-v2", timeout=120):
    """GET make_url(token) and parse JSON, retrying outages and rotating rejected tokens."""
    while True:
        tok, _ = pool.current()
        last = None
        for i in range(attempts):
            try:
                req = urllib.request.Request(make_url(tok), headers={"User-Agent": agent})
                raw = urllib.request.urlopen(req, timeout=timeout).read()
                return json.loads(raw.decode("utf-8", errors="replace"))
            except Exception as e:                                # noqa: BLE001
                last = e
                if is_rejection(e):
                    print("fetch %s: token rejected (%s)" % (label, describe(e)))
                    break                                         # retrying will not help
                print("fetch %s attempt %d/%d failed: %s" % (label, i + 1, attempts, describe(e)))
                if i + 1 < attempts:
                    time.sleep(15 * (i + 1))
        if is_rejection(last):
            if pool.reject(last):
                continue
            raise TokenRejected("every VisiLean token for %s was rejected (%s)"
                                % (pool.label, ", ".join(pool.rejected)))
        raise last
