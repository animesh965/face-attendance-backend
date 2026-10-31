import re
from fastapi import HTTPException


def normalize_indian_mobile(value: str) -> str:
    raw = (value or "").strip()
    digits = re.sub(r"[^0-9]", "", raw)
    if digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    if len(digits) != 10 or digits[0] not in "6789":
        raise HTTPException(status_code=422, detail="Enter a valid 10-digit Indian mobile number")
    if len(set(digits)) == 1:
        raise HTTPException(status_code=422, detail="Repeated-digit phone numbers are not allowed")
    ascending = "0123456789"
    descending = "9876543210"
    if any(digits[i:i+5] in ascending or digits[i:i+5] in descending for i in range(6)):
        raise HTTPException(status_code=422, detail="Sequential phone number patterns are not allowed")
    if any(digits == str(i) * 10 for i in range(10)):
        raise HTTPException(status_code=422, detail="Repeated-digit phone numbers are not allowed")
    return digits
