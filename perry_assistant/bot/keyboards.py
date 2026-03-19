from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup


def build_schedule_keyboard() -> ReplyKeyboardMarkup:
    row1 = [KeyboardButton("THIS WEEKEND"), KeyboardButton("NEXT WEEKEND")]
    row2 = [KeyboardButton("OTHER"), KeyboardButton("BACK")]
    return ReplyKeyboardMarkup([row1, row2], resize_keyboard=True)


def build_main_keyboard(is_admin: bool) -> ReplyKeyboardMarkup:
    base_row = [KeyboardButton("TODAY"), KeyboardButton("SCHEDULE")]
    second_row = [KeyboardButton("UNTIS")]
    if is_admin:
        second_row.append(KeyboardButton("ABSENCES"))
        second_row.append(KeyboardButton("REFEREE"))
    return ReplyKeyboardMarkup([base_row, second_row], resize_keyboard=True)


def build_parent_keyboard() -> ReplyKeyboardMarkup:
    row1 = [KeyboardButton("TODAY"), KeyboardButton("TOMORROW")]
    row2 = [KeyboardButton("THIS WEEKEND")]
    row3 = [KeyboardButton("OTHER DATE")]
    return ReplyKeyboardMarkup([row1, row2, row3], resize_keyboard=True)


def build_untis_setup_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🏫 Untis einrichten", callback_data="untis_setup")]]
    )


def build_absences_menu_keyboard() -> ReplyKeyboardMarkup:
    row1 = [KeyboardButton("EXCUSABLE TODAY"), KeyboardButton("I AM ABSENT")]
    row2 = [KeyboardButton("ALL ABSENCES"), KeyboardButton("EXCUSED ABSENCES")]
    row3 = [KeyboardButton("BACK")]
    return ReplyKeyboardMarkup([row1, row2, row3], resize_keyboard=True)


def build_referee_menu_keyboard() -> ReplyKeyboardMarkup:
    row1 = [KeyboardButton("EMAILS"), KeyboardButton("UPORTAL")]
    row2 = [KeyboardButton("BACK")]
    return ReplyKeyboardMarkup([row1, row2], resize_keyboard=True)
