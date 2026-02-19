from telegram import KeyboardButton, ReplyKeyboardMarkup


def build_schedule_keyboard() -> ReplyKeyboardMarkup:
    row1 = [KeyboardButton("THIS WEEKEND"), KeyboardButton("NEXT WEEKEND")]
    row2 = [KeyboardButton("OTHER"), KeyboardButton("BACK")]
    return ReplyKeyboardMarkup([row1, row2], resize_keyboard=True)


def build_main_keyboard(is_admin: bool) -> ReplyKeyboardMarkup:
    base_row = [KeyboardButton("TODAY"), KeyboardButton("SCHEDULE")]
    second_row = []
    if is_admin:
        second_row.append(KeyboardButton("ABSENCES"))
        second_row.append(KeyboardButton("EMAILS"))
    return ReplyKeyboardMarkup([base_row, second_row] if second_row else [base_row], resize_keyboard=True)

def build_absences_menu_keyboard() -> ReplyKeyboardMarkup:
    row = [KeyboardButton("EXCUSABLE TODAY"), KeyboardButton("I AM ABSENT"), KeyboardButton("ALL ABSENCES"), KeyboardButton("BACK")]
    return ReplyKeyboardMarkup([row[:2], row[2:]], resize_keyboard=True)
