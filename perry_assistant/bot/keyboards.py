from telegram import KeyboardButton, ReplyKeyboardMarkup


def build_main_keyboard(is_admin: bool) -> ReplyKeyboardMarkup:
    base_row = [KeyboardButton("TODAY"), KeyboardButton("WEEKEND")]
    second_row = [KeyboardButton("ABSENCES")]
    if is_admin:
        second_row.append(KeyboardButton("EMAILS"))
    return ReplyKeyboardMarkup([base_row, second_row], resize_keyboard=True)

