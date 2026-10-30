"""Minecraft text formatting, color code parser, and ANSI/Rich styler.

Supports classic §0-§f, styles §k-§r, hex color formats (§x§r§r§g§g§b§b, &#rrggbb, <#rrggbb>),
and ampersand (&) alternatives.
"""

from __future__ import annotations

import re
from typing import Dict, Tuple

# Standard Minecraft color palette mapping to (R, G, B)
COLOR_PALETTE: Dict[str, Tuple[int, int, int]] = {
    "0": (0, 0, 0),        # Black
    "1": (0, 0, 170),      # Dark Blue
    "2": (0, 170, 0),      # Dark Green
    "3": (0, 170, 170),    # Dark Aqua
    "4": (170, 0, 0),      # Dark Red
    "5": (170, 0, 170),    # Dark Purple
    "6": (255, 170, 0),    # Gold
    "7": (170, 170, 170),  # Gray
    "8": (85, 85, 85),     # Dark Gray
    "9": (85, 85, 255),    # Blue
    "a": (85, 255, 85),    # Green
    "b": (85, 255, 255),   # Aqua
    "c": (255, 85, 85),    # Red
    "d": (255, 85, 255),   # Light Purple
    "e": (255, 255, 85),   # Yellow
    "f": (255, 255, 255),  # White
}

# Style codes
STYLE_CODES: Dict[str, str] = {
    "k": "\033[5m",  # Obfuscated / blink
    "l": "\033[1m",  # Bold
    "m": "\033[9m",  # Strikethrough
    "n": "\033[4m",  # Underline
    "o": "\033[3m",  # Italic
    "r": "\033[0m",  # Reset
}

# Regex to match extended hex formats
# 1. Spigot/Bungee hex: §x§r§r§g§g§b§b or &x&r&r&g&g&b&b
RE_SPIGOT_HEX = re.compile(
    r"[§&]x[§&]([0-9a-fA-F])[§&]([0-9a-fA-F])[§&]([0-9a-fA-F])[§&]([0-9a-fA-F])[§&]([0-9a-fA-F])[§&]([0-9a-fA-F])"
)
# 2. Modern plugin hex: &#RRGGBB or &xRRGGBB
RE_AMP_HEX = re.compile(r"[§&]#[0-9a-fA-F]{6}")
# 3. MiniMessage hex: <#RRGGBB> or </#RRGGBB>
RE_MINIMESSAGE_HEX = re.compile(r"<\/?#([0-9a-fA-F]{6})>")
# 4. Standard section/ampersand codes: §c or &c
RE_STANDARD_CODES = re.compile(r"[§&]([0-9a-fk-orA-FK-OR])")

ANSI_RESET = "\033[0m"


def rgb_to_ansi(r: int, g: int, b: int) -> str:
    """Returns ANSI 24-bit foreground escape sequence for RGB."""
    return f"\033[38;2;{r};{g};{b}m"


def hex_to_rgb(hex_str: str) -> Tuple[int, int, int]:
    """Converts a 6-character hex string to RGB tuple."""
    hex_str = hex_str.lstrip("#")
    return int(hex_str[0:2], 16), int(hex_str[2:4], 16), int(hex_str[4:6], 16)


def strip_minecraft_formatting(text: str) -> str:
    """Removes all Minecraft color and formatting codes from the text, returning pure text."""
    if not text:
        return ""
    # Strip Spigot §x§r§r§g§g§b§b
    text = RE_SPIGOT_HEX.sub("", text)
    # Strip &#RRGGBB
    text = RE_AMP_HEX.sub("", text)
    # Strip <#RRGGBB>
    text = RE_MINIMESSAGE_HEX.sub("", text)
    # Strip §c and &c
    text = RE_STANDARD_CODES.sub("", text)
    return text


def minecraft_to_ansi(text: str, support_ampersand: bool = True, reset_at_end: bool = True) -> str:
    """Converts Minecraft formatting codes (§ and optionally &) to ANSI terminal color codes.

    Handles standard colors (§0-§f), styles (§k-§r), and hex formats:
    - §x§r§r§g§g§b§b / &x&r&r&g&g&b&b
    - &#RRGGBB / §#RRGGBB
    - <#RRGGBB>

    In Minecraft specification: setting a new color resets active formatting styles.
    """
    if not text:
        return ""

    # Normalize Spigot hex format §x§r§r§g§g§b§b -> \x01#RRGGBB\x02
    def _replace_spigot_hex(m: re.Match) -> str:
        hex_digits = "".join(m.groups())
        return f"\x01#{hex_digits}\x02"

    text_working = RE_SPIGOT_HEX.sub(_replace_spigot_hex, text)

    # Normalize &#RRGGBB -> \x01#RRGGBB\x02
    def _replace_amp_hex(m: re.Match) -> str:
        code = m.group(0)
        hex_digits = code[2:]
        return f"\x01#{hex_digits}\x02"

    text_working = RE_AMP_HEX.sub(_replace_amp_hex, text_working)

    # Normalize <#RRGGBB> -> \x01#RRGGBB\x02
    def _replace_minimessage(m: re.Match) -> str:
        return f"\x01#{m.group(1)}\x02"

    text_working = RE_MINIMESSAGE_HEX.sub(_replace_minimessage, text_working)

    # Split and process characters
    result = []
    i = 0
    n = len(text_working)
    has_active_styles = False

    while i < n:
        # Check normalized hex token
        if text_working[i : i + 2] == "\x01#":
            end_idx = text_working.find("\x02", i)
            if end_idx != -1:
                hex_str = text_working[i + 2 : end_idx]
                r, g, b = hex_to_rgb(hex_str)
                # Setting color resets styles per Minecraft spec
                result.append(f"{ANSI_RESET}{rgb_to_ansi(r, g, b)}")
                has_active_styles = True
                i = end_idx + 1
                continue

        char = text_working[i]
        # Check section sign or ampersand
        if char == "§" or (support_ampersand and char == "&"):
            if i + 1 < n:
                code = text_working[i + 1].lower()
                if code in COLOR_PALETTE:
                    r, g, b = COLOR_PALETTE[code]
                    result.append(f"{ANSI_RESET}{rgb_to_ansi(r, g, b)}")
                    has_active_styles = True
                    i += 2
                    continue
                elif code in STYLE_CODES:
                    ansi_code = STYLE_CODES[code]
                    result.append(ansi_code)
                    if code == "r":
                        has_active_styles = False
                    else:
                        has_active_styles = True
                    i += 2
                    continue

        result.append(char)
        i += 1

    formatted = "".join(result)
    if reset_at_end and has_active_styles and not formatted.endswith(ANSI_RESET):
        formatted += ANSI_RESET

    return formatted
