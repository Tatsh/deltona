from __future__ import annotations

from deltona.naming import Mode, adjust_title


def test_adjust_title_basic_english() -> None:
    assert adjust_title('the quick brown fox') == 'The Quick Brown Fox'
    assert adjust_title('a tale of two cities') == 'A Tale of Two Cities'
    assert adjust_title('in the heat of the night') == 'In the Heat of the Night'


def test_adjust_title_with_stop_words() -> None:
    assert adjust_title('by the river and the sea') == 'By the River and the Sea'
    assert adjust_title('feat john smith') == 'Feat John Smith'
    assert adjust_title('mr smith goes to washington') == 'Mr Smith Goes to Washington'


def test_adjust_title_with_names_to_fix() -> None:
    assert adjust_title("mcdonald's farm") == "McDonald's Farm"
    assert adjust_title('imessage update') == 'iMessage Update'
    assert adjust_title('ios release') == 'iOS Release'
    assert adjust_title('itunes music') == 'iTunes Music'
    assert adjust_title('ios tvos watchos macos imessage') == 'iOS tvOS watchOS macOS iMessage'


def test_adjust_title_with_names_disabled() -> None:
    assert adjust_title("mcdonald's farm", disable_names=True) != "McDonald's Farm"


def test_adjust_title_ampersands() -> None:
    assert adjust_title('rock and roll', ampersands=True) == 'Rock & Roll'
    assert adjust_title('love and peace and happiness',
                        ampersands=True) == 'Love & Peace & Happiness'


def test_adjust_title_roman_numerals() -> None:
    assert adjust_title('world war ii') == 'World War II'
    assert adjust_title('chapter ix') == 'Chapter IX'
    assert adjust_title('extended mix') == 'Extended Mix'  # 'mix' is ignored for roman numeral


def test_adjust_title_ordinals() -> None:
    assert adjust_title('the 1st time') == 'The 1st Time'
    assert adjust_title('my 2nd home') == 'My 2nd Home'
    assert adjust_title('the 3rd degree') == 'The 3rd Degree'
    assert adjust_title('the 4th wall') == 'The 4th Wall'


def test_adjust_title_with_punctuation() -> None:
    assert adjust_title('hello, world!') == 'Hello, World!'
    assert adjust_title('the end.') == 'The End.'
    assert adjust_title("what's up?") == "What's Up?"


def test_adjust_title_uppercase_preserved() -> None:
    assert adjust_title('NASA launches rocket') == 'NASA Launches Rocket'
    assert adjust_title('WWDC keynote') == 'WWDC Keynote'


def test_adjust_title_multiple_modes() -> None:
    # Should lowercase Japanese particles if Mode.Japanese is used
    result = adjust_title('no wa to', modes=(Mode.Japanese,))
    assert result == 'No wa to'
    # Should lowercase Arabic stops if Mode.Arabic is used
    result = adjust_title('al wa min', modes=(Mode.Arabic,))
    assert result == 'Al wa min'


def test_adjust_title_roman_numeral_at_beginning() -> None:
    assert adjust_title('ii world war I ANOTHER1') == 'II World War I ANOTHER1'
    assert adjust_title('iv       \n    seasons') == 'IV Seasons'


def test_adjust_title_abbreviations() -> None:
    assert adjust_title(
        'Song Name Of The Year (Feat. Artist Name)') == 'Song Name of the Year (feat Artist Name)'
