from perry_assistant.bot.keyboards import (
    build_main_keyboard,
    build_referee_menu_keyboard,
    build_schedule_keyboard,
)


def _button_texts(markup) -> list[list[str]]:  # noqa: ANN001
    return [[button.text for button in row] for row in markup.keyboard]

def test_main_keyboard_regular_user_contains_only_untis():
    layout = _button_texts(build_main_keyboard(is_admin=False, is_parent=False))
    all_buttons = [btn for row in layout for btn in row]
    assert "UNTIS" in all_buttons
    assert "TODAY" not in all_buttons
    assert "SCHEDULE" not in all_buttons


def test_parent_keyboard_layout():
    layout = _button_texts(build_main_keyboard(is_admin=False, is_parent=True))
    assert ["TODAY", "TOMORROW"] in layout
    assert ["THIS WEEKEND"] in layout
    assert ["OTHER DATE"] in layout
    all_buttons = [btn for row in layout for btn in row]
    assert "UNTIS" not in all_buttons
    assert "SCHEDULE" not in all_buttons


def test_referee_menu_contains_expected_buttons():
    layout = _button_texts(build_referee_menu_keyboard())
    assert ["EMAILS", "UPORTAL"] in layout
    assert ["GAMES", "BACK"] in layout


def test_other_keyboards_still_build():
    assert build_schedule_keyboard().keyboard

