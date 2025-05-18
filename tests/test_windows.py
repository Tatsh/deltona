from __future__ import annotations

from deltona import windows
import pytest


def test_make_font_entry_basic() -> None:
    result = windows.make_font_entry(windows.Field.CaptionFont, name='Arial')
    assert result.startswith('\n"CaptionFont"=hex:')
    assert '41,00,72,00,69,00,61,00,6c,00' in result  # "Arial" in utf-16le hex


def test_make_font_entry_with_all_options() -> None:
    result = windows.make_font_entry(
        field=windows.Field.MenuFont,
        name='Segoe UI',
        char_set=windows.CharacterSet.ANSI_CHARSET,
        clip_precision=windows.ClipPrecision.CLIP_EMBEDDED,
        default_setting=True,
        header=True,
        dpi=96,
        escapement=10,
        font_size_pt=12,
        italic=True,
        orientation=5,
        out_precision=windows.OutputPrecision.OUT_TT_PRECIS,
        pitch_and_family=windows.Pitch.FIXED_PITCH | windows.Family.FF_ROMAN,
        quality=windows.Quality.ANTIALIASED_QUALITY,
        strike_out=True,
        underline=True,
        weight=windows.Weight.FW_BOLD,
        width=2)
    assert result.startswith(r'HKEY_USERS\.Default\Control Panel\Desktop\WindowMetrics')
    assert '"MenuFont"=hex:' in result
    assert '53,00,65,00,67,00,6f,00,65,00,20,00,55,00,49,00' in result  # "Segoe UI" in utf-16le hex


def test_make_font_entry_name_too_long() -> None:
    long_name = 'A' * (windows.LF_FULLFACESIZE + 1)
    with pytest.raises(windows.NameTooLong):
        windows.make_font_entry(windows.Field.MessageFont, name=long_name)


def test_make_font_entry_with_header_current_user() -> None:
    result = windows.make_font_entry(field=windows.Field.StatusFont,
                                     name='Tahoma',
                                     header=True,
                                     default_setting=False)
    assert result.startswith(r'HKEY_CURRENT_USER\Control Panel\Desktop\WindowMetrics')
    assert '"StatusFont"=hex:' in result


def test_make_font_entry_custom_pitch_and_family() -> None:
    pf = windows.Pitch.MONO_FONT | windows.Family.FF_MODERN
    result = windows.make_font_entry(windows.Field.MenuFont, name='Consolas', pitch_and_family=pf)
    assert '43,00,6f,00,6e,00,73,00,6f,00,6c,00,61,00,73,00' in result  # "Consolas" in utf-16le hex
