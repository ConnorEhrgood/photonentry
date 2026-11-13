"""Card numbers as an Axis controller reports them in the `Card` IdData: the reader's raw bits, as lowercase hex, left-padded to whole bytes
(Axis's H10301 example: facility 0, card 10213 → `02004fcb`). A credential's `Card` must equal what the reader sends for the access decision
(authentication profile `CardOnly`: `Card` with `IdDataEqual`), so the parity bits are computed here exactly as the reader sets them.

- `h10301`: 26 bits = even parity over bits 2-13, facility (8), card (16), odd parity over bits 14-25.
- `w34`: 34 bits = even parity over bits 2-17, card (32), odd parity over bits 18-33 (what an Akuvox intercom sends in 34-bit mode,
  ARCHITECTURE §3.4). Padding to 40 bits (10 hex digits) follows the H10301 example's rule; bench test H5 confirms it on a real controller.
- `raw`: the number is the reader's value already; written as hex, at least 8 digits.
"""
from __future__ import annotations

from app.document import Card


def _parity_even(bits: str) -> str:
    return "1" if bits.count("1") % 2 else "0"


def _parity_odd(bits: str) -> str:
    return "0" if bits.count("1") % 2 else "1"


def _hex(bits: str) -> str:
    width = (len(bits) + 7) // 8 * 2
    return format(int(bits, 2), f"0{width}x")


def card_data(card: Card) -> str:
    if card.format == "h10301":
        data = format(card.facility or 0, "08b") + format(card.number, "016b")
        return _hex(_parity_even(data[:12]) + data + _parity_odd(data[12:]))
    if card.format == "w34":
        data = format(card.number, "032b")
        return _hex(_parity_even(data[:16]) + data + _parity_odd(data[16:]))
    return format(card.number, "08x")
