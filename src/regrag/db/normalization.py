from urllib.parse import urlsplit, urlunsplit


def normalize_identifier_scheme(scheme: str) -> str:
    return scheme.strip().lower()


def normalize_identifier_value(scheme: str, value: str) -> str:
    normalized_scheme = normalize_identifier_scheme(scheme)
    if normalized_scheme != "url":
        return value.strip()

    value = value.strip()
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
    except ValueError:
        return value
    if not parsed.scheme or not hostname:
        return value

    userinfo = ""
    if parsed.username is not None:
        userinfo = parsed.username
        if parsed.password is not None:
            userinfo += f":{parsed.password}"
        userinfo += "@"

    host = hostname.lower()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"

    try:
        port = parsed.port
    except ValueError:
        return value

    if port is not None and not (
        (parsed.scheme.lower() == "http" and port == 80)
        or (parsed.scheme.lower() == "https" and port == 443)
    ):
        host = f"{host}:{port}"

    return urlunsplit(
        (
            parsed.scheme.lower(),
            f"{userinfo}{host}",
            parsed.path or "/",
            parsed.query,
            "",
        )
    )
