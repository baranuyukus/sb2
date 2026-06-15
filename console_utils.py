import sys


def safe_print(*values, sep=" ", end="\n", file=None, flush=False):
    stream = file or sys.stdout
    text = sep.join(str(value) for value in values)

    try:
        print(text, end=end, file=stream, flush=flush)
        return
    except UnicodeEncodeError:
        pass

    encoding = getattr(stream, "encoding", None) or "utf-8"
    safe_text = text.encode(encoding, errors="replace").decode(encoding, errors="replace")
    try:
        stream.write(safe_text + end)
        if flush:
            stream.flush()
    except Exception:
        fallback = safe_text.encode("ascii", errors="replace").decode("ascii")
        stream.write(fallback + end)
        if flush:
            stream.flush()
