"""Faker-backed test data so every run uses fresh, unique values."""
from __future__ import annotations

import random
import string

from faker import Faker

fake = Faker("en_IN")

_IFSC_BANKS = ["HDFC", "ICIC", "SBIN", "UTIB", "KKBK", "PUNB", "YESB"]


def valid_ifsc() -> str:
    """4 letters + '0' + 6 alphanumerics = 11 chars."""
    bank = random.choice(_IFSC_BANKS)
    tail = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"{bank}0{tail}"


def account_number(length: int = 14) -> str:
    return "".join(random.choices(string.digits, k=length))


def mobile_10() -> str:
    return "9" + "".join(random.choices(string.digits, k=9))


def beneficiary_code() -> str:
    return "BEN" + "".join(random.choices(string.digits, k=6))


# Real, long-standing branch IFSCs: the app resolves the bank from the first four
# characters and the bank may check the branch, so random tails are avoided here.
REAL_IFSC = ["SBIN0000001", "HDFC0000001", "ICIC0000001"]


def bank_account(length: int = 14) -> str:
    """A digits-only account number that does not start with 0."""
    return random.choice("123456789") + "".join(random.choices(string.digits, k=length - 1))


def valid_password() -> str:
    """8–12 chars with lower, upper, digit and symbol."""
    return "Qa!" + "".join(random.choices(string.ascii_letters + string.digits, k=6))


# A spread of passwords that MUST be rejected, labelled for readable test ids.
INVALID_PASSWORDS = [
    ("too_short_7", "Ab@1xyz"),
    ("too_long_13", "Abcd@12345678"),
    ("no_lowercase", "ABCD@1234"),
    ("no_uppercase", "abcd@1234"),
    ("no_digit", "Abcd@xyz"),
    ("no_symbol", "Abcd1234"),
]


def safe_email(prefix: str = "qa") -> str:
    """Unique address on example.com (reserved, never delivered), so invitations or
    notifications from the shared UAT never reach a real person."""
    token = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    return f"{prefix}.{token}@example.com"


def new_beneficiary(with_mobile: bool = True) -> dict:
    """Add-beneficiary form data. The beneficiary code is issued by the app, so
    it is not generated here. Names start with 'QA Auto' to spot test data."""
    acc = bank_account()
    data = {
        "name": f"QA Auto {fake.first_name()} {fake.last_name()}",
        "account_number": acc,
        "confirm_account_number": acc,
        "ifsc": random.choice(REAL_IFSC),
        "email": safe_email("qa.ben"),
    }
    if with_mobile:
        data["mobile"] = mobile_10()
    return data


def beneficiary_payload(code: str, with_mobile: bool = True) -> dict:
    """Body for POST /api/v1/beneficiaries, as the UI sends it."""
    d = new_beneficiary(with_mobile)
    body = {"beneCode": code, "beneName": d["name"], "beneAccNum": d["account_number"],
            "beneIfscCode": d["ifsc"], "beneEmailAddr1": d["email"]}
    if with_mobile:
        body["beneMobileNo"] = d["mobile"]
    return body


def new_user(role: str = "Operations") -> dict:
    return {
        "email": safe_email("qa.user"),
        "full_name": fake.name(),
        "contact": mobile_10(),
        "role": role,
    }


def new_role(prefix: str = "QA") -> dict:
    suffix = "".join(random.choices(string.ascii_uppercase, k=5))
    return {"name": f"{prefix}_{suffix}", "description": fake.sentence(nb_words=6)}
