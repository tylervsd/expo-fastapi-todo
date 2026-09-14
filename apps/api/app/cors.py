import json
import os
from urllib.parse import urlsplit

LOCAL_ORIGIN = "http://localhost:8081"


def get_cors_origins() -> list[str]:
    raw = os.environ.get("CORS_ALLOWED_ORIGINS")
    if raw is None:
        return [LOCAL_ORIGIN]
    try:
        origins = json.loads(raw)
        if not isinstance(origins, list):
            raise TypeError
        for origin in origins:
            if not isinstance(origin, str):
                raise TypeError
            parsed = urlsplit(origin)
            _ = parsed.port
            if (
                not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path
                or parsed.query
                or parsed.fragment
                or "?" in origin
                or "#" in origin
                or "*" in origin
                or "\\" in origin
                or any(c.isspace() or ord(c) < 32 for c in origin)
                or origin != f"{parsed.scheme}://{parsed.netloc}"
                or (parsed.scheme != "https" and origin != LOCAL_ORIGIN)
            ):
                raise ValueError
        return list(dict.fromkeys(origins))
    except (ValueError, TypeError):
        raise ValueError("Invalid CORS_ALLOWED_ORIGINS configuration") from None
