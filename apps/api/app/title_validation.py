ECMASCRIPT_TRIM_CHARS = (
    "\u0009\u000a\u000b\u000c\u000d\u0020\u00a0\u1680"
    "\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a"
    "\u2028\u2029\u202f\u205f\u3000\ufeff"
)


def canonicalize_title(title: str) -> str:
    title = title.strip(ECMASCRIPT_TRIM_CHARS)
    if "\x00" in title:
        raise ValueError("title must not contain NUL")
    if any(0xD800 <= ord(character) <= 0xDFFF for character in title):
        raise ValueError("title must not contain an unpaired surrogate")
    if not 1 <= len(title) <= 120:
        raise ValueError("title must contain 1 to 120 code points")
    return title
