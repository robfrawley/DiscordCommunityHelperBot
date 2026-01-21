
def flatten_newlines_and_strip_str(text: str) -> str:
    return " ".join(line.strip() for line in text.splitlines() if line.strip())
