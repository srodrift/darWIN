def luhn_valid(number):
    if not isinstance(number, str):
        return False
    digits = number.replace(" ", "").replace("-", "")
    if len(digits) < 2 or not digits.isdigit():
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0
