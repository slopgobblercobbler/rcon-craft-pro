"""Unit tests for Minecraft formatting code parsing, hex color translation, and stripping."""

from rcon_craft.colors import (
    ANSI_RESET,
    COLOR_PALETTE,
    STYLE_CODES,
    hex_to_rgb,
    minecraft_to_ansi,
    rgb_to_ansi,
    strip_minecraft_formatting,
)


def test_hex_to_rgb():
    assert hex_to_rgb("#ffffff") == (255, 255, 255)
    assert hex_to_rgb("00aa00") == (0, 170, 0)
    assert hex_to_rgb("#123456") == (18, 52, 86)


def test_rgb_to_ansi():
    ansi = rgb_to_ansi(255, 170, 0)
    assert ansi == "\033[38;2;255;170;0m"


def test_strip_classic_formatting():
    raw = "§aHello §lWorld§r! §cRed §6Gold"
    cleaned = strip_minecraft_formatting(raw)
    assert cleaned == "Hello World! Red Gold"


def test_strip_ampersand_formatting():
    raw = "&eWarning: &4Do not touch &nthe button&r."
    cleaned = strip_minecraft_formatting(raw)
    assert cleaned == "Warning: Do not touch the button."


def test_strip_hex_spigot():
    raw = "§x§f§f§5§5§a§aCustom Hex Text"
    cleaned = strip_minecraft_formatting(raw)
    assert cleaned == "Custom Hex Text"


def test_strip_hex_ampersand_and_minimessage():
    raw = "&#ff5500Modern Hex and <#123456>MiniMessage</#123456>"
    cleaned = strip_minecraft_formatting(raw)
    assert cleaned == "Modern Hex and MiniMessage"


def test_strip_empty_and_plain():
    assert strip_minecraft_formatting("") == ""
    assert strip_minecraft_formatting("Just regular text") == "Just regular text"


def test_minecraft_to_ansi_classic_colors():
    raw = "§aGreen §cRed"
    ansi = minecraft_to_ansi(raw)
    expected_green = rgb_to_ansi(*COLOR_PALETTE["a"])
    expected_red = rgb_to_ansi(*COLOR_PALETTE["c"])
    assert expected_green in ansi
    assert expected_red in ansi
    assert ansi.endswith(ANSI_RESET)


def test_minecraft_to_ansi_styles():
    raw = "§lBold §oItalic §mStrike §nUnderline §kMagic §rReset"
    ansi = minecraft_to_ansi(raw)
    assert STYLE_CODES["l"] in ansi
    assert STYLE_CODES["o"] in ansi
    assert STYLE_CODES["m"] in ansi
    assert STYLE_CODES["n"] in ansi
    assert STYLE_CODES["k"] in ansi
    assert ANSI_RESET in ansi


def test_minecraft_to_ansi_spigot_hex():
    raw = "§x§a§a§b§b§c§cHex Colored"
    ansi = minecraft_to_ansi(raw)
    expected = rgb_to_ansi(170, 187, 204)
    assert expected in ansi
    assert "Hex Colored" in ansi


def test_minecraft_to_ansi_ampersand_hex():
    raw = "&#00ff88Teal Hex"
    ansi = minecraft_to_ansi(raw)
    expected = rgb_to_ansi(0, 255, 136)
    assert expected in ansi
    assert "Teal Hex" in ansi


def test_minecraft_to_ansi_minimessage():
    raw = "<#abcdef>MiniMessage Color"
    ansi = minecraft_to_ansi(raw)
    expected = rgb_to_ansi(171, 205, 239)
    assert expected in ansi
    assert "MiniMessage Color" in ansi


def test_color_resets_previous_styles():
    # In Minecraft, setting a new color implicitly resets bold/italic/etc.
    raw = "§l§aBold Green §cRed (should reset bold)"
    ansi = minecraft_to_ansi(raw)
    # The second color §c should have ANSI_RESET preceding its color code
    assert f"{ANSI_RESET}{rgb_to_ansi(*COLOR_PALETTE['c'])}" in ansi


def test_minecraft_to_ansi_no_formatting():
    assert minecraft_to_ansi("Clean Text") == "Clean Text"
    assert minecraft_to_ansi("") == ""
