from urllib.parse import urljoin
import re

ABS = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")


def expand_iri(value: str, *, base: str | None, prefixes: dict[str, str] | None) -> str:
    v = (value or "").strip()
    if not v:
        raise ValueError("Empty IRI")
    if ABS.match(v):
        return v

    # CURIE expansion allowed on input, but output will be expanded
    if ":" in v and not v.startswith("//"):
        pfx, suf = v.split(":", 1)
        if prefixes and pfx in prefixes:
            return urljoin(prefixes[pfx], suf)

    if base:
        return urljoin(base.rstrip("/") + "/", v.lstrip("/"))

    return v


def api_iri(base_url: str, path: str) -> str:
    return urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
