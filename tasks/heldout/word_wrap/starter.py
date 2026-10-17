def wrap(text, width):
    return [text[i:i+width] for i in range(0, len(text), width)]
