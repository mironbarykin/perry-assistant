import logging
from logging.handlers import TimedRotatingFileHandler

# Logging setup
LOG_PATH = "/data/logs.log"
file_handler = TimedRotatingFileHandler(LOG_PATH, when="midnight", encoding="utf-8")
file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    handlers=[
        file_handler,
        logging.StreamHandler()
    ]
)

from dotenv import load_dotenv

from telegram.ext import (
    ApplicationBuilder, 
    CommandHandler, 
    MessageHandler, 
    ConversationHandler, 
    filters
)

from config import TG_TOKEN
from handlers import (
    start, today, tomorrow, weekend, leftschool, morning, myid,
    settime, handle_time_message, button_handler, error_handler,
    schedule_notifications, SET_TIME
)

def main():
    app = ApplicationBuilder().token(TG_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("today", today))
    app.add_handler(CommandHandler("tomorrow", tomorrow))
    app.add_handler(CommandHandler("weekend", weekend))
    app.add_handler(CommandHandler("leftschool", leftschool))
    app.add_handler(CommandHandler("morning", morning))
    app.add_handler(CommandHandler("myid", myid))

    conv = ConversationHandler(
        entry_points=[CommandHandler("settime", settime)],
        states={SET_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_time_message)]},
        fallbacks=[]
    )
    app.add_handler(conv)

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, button_handler))
    app.add_error_handler(error_handler)

    schedule_notifications(app)
    app.run_polling()

if __name__ == "__main__":
    main()
