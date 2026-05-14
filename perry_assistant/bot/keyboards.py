from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup


def build_schedule_keyboard() -> ReplyKeyboardMarkup:
    row1 = [KeyboardButton("THIS WEEKEND"), KeyboardButton("NEXT WEEKEND")]
    row2 = [KeyboardButton("OTHER DATE"), KeyboardButton("BACK")]
    return ReplyKeyboardMarkup([row1, row2], resize_keyboard=True)


def build_main_keyboard(is_admin: bool, is_parent: bool = False) -> ReplyKeyboardMarkup:
    if is_admin:
        row1 = [KeyboardButton("TODAY"), KeyboardButton("SCHEDULE")]
        row2 = [KeyboardButton("ABSENCES"), KeyboardButton("REFEREE")]
        row3 = [KeyboardButton("TRACKER")]
        return ReplyKeyboardMarkup([row1, row2, row3], resize_keyboard=True)
    if is_parent:
        row1 = [KeyboardButton("TODAY"), KeyboardButton("TOMORROW")]
        row2 = [KeyboardButton("THIS WEEKEND")]
        row3 = [KeyboardButton("OTHER DATE")]
        return ReplyKeyboardMarkup([row1, row2, row3], resize_keyboard=True)
    row1 = [KeyboardButton("UNTIS")]
    return ReplyKeyboardMarkup([row1], resize_keyboard=True)

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
    row2 = [KeyboardButton("GAMES"), KeyboardButton("BACK")]
    return ReplyKeyboardMarkup([row1, row2], resize_keyboard=True)

def build_tracker_menu_keyboard() -> ReplyKeyboardMarkup:
    row1 = [KeyboardButton("SHOWER"), KeyboardButton("FAP")]
    row2 = [KeyboardButton("BACK")]
    return ReplyKeyboardMarkup([row1, row2], resize_keyboard=True)
