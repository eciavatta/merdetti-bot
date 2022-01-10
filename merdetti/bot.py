import logging
import os
import re
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, replymarkup
from telegram.bot import Bot
from telegram.ext import (
    CallbackContext,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    Filters,
    MessageHandler,
    PicklePersistence,
    Updater,
)

from merdetti import notifications
from merdetti.zucchetti import ApiError, InvalidCredentials, ZucchettiApi

logger = logging.getLogger(__name__)

UNLOGGED_STATE, LOGIN_STATE, LOGGED_STATE, NOTIFICATION_STATE = (
    "unlogged_state",
    "login_state",
    "logged_state",
    "notification_state",
)

LOGIN_CALLBACK, CANCEL_CALLBACK, ENTER_CALLBACK, EXIT_CALLBACK = (
    "login_callback",
    "cancel_callback",
    "enter_callback",
    "exit_callback",
)

END = ConversationHandler.END

(ALREADY_STARTED, PROMPT_CREDENTIALS_MESSAGE) = (
    "already_started",
    "promt_credentials_message",
)


zucchetti_users = dict()


def start(update: Update, context: CallbackContext) -> int:
    button = InlineKeyboardButton(text="Login", callback_data=LOGIN_CALLBACK)
    keyboard = InlineKeyboardMarkup.from_button(button)

    if not context.user_data.get(ALREADY_STARTED):
        update.message.reply_text(
            "Ciao! Io sono merdetti-bot 💩! Con me potrai timbrare il cartellino senza dover entrare in quell'orribile portale 😭\n\n"
            "Ma prima devi effettuare il login!",
            reply_markup=keyboard,
        )

        context.user_data[ALREADY_STARTED] = True

    return UNLOGGED_STATE


def login(update: Update, context: CallbackContext) -> int:
    if not context.user_data.get(PROMPT_CREDENTIALS_MESSAGE):
        if update.callback_query:
            func = update.callback_query.edit_message_text
        else:
            func = update.message.reply_text

        func(
            "Inserisci le tue credenziali di Zucchetti 🔐, separate da uno spazio.\n\n"
            "Dovrò salvare le tue credenziali in memoria per non richiederti le credenziali tutte le volte, ma non le scriverò da nessuna parte. Lo giuro! 🙇🏽‍♂️"
        )
        context.user_data[PROMPT_CREDENTIALS_MESSAGE] = True

        return LOGIN_STATE

    match = re.match(r"^([\S]+)[\s]+(\S+)$", update.message.text)
    if not match:
        update.message.reply_markdown(
            "Devi inserire le credenziali nel seguente formato: `USERNAME PASSWORD`\n"
            "Inserisci le credenziali di nuovo! 😑"
        )

        return LOGIN_STATE

    zucchetti_api = ZucchettiApi(match[1], match[2])
    try:
        zucchetti_api.login()
    except InvalidCredentials:
        update.message.reply_text(
            "Le credenziali che hai inserito non sono corrette!\n"
            "Inseriscile nuovamente (quelle giuste magari 😅)"
        )

        return LOGIN_STATE
    except ApiError as e:
        update.message.reply_text(
            "Non sono riuscito a verificare le tue credenziali 😓. Riprova più tardi rieffettuando il /login"
        )

        logger.warning(
            f"Failed to authenticate a user {update.message.from_user.first_name}: {e}"
        )

        return UNLOGGED_STATE

    zucchetti_users[update.effective_user.id] = zucchetti_api
    context.user_data[PROMPT_CREDENTIALS_MESSAGE] = False
    update.message.reply_text(
        "Credenziali salvate con successo!\n\nUsa /timbra per timbrare 🎫\nUsa /notifiche per impostare gli avvisi 📢"
    )

    return LOGGED_STATE


def get_zucchetti_api(update: Update, context: CallbackContext):
    zucchetti_api = zucchetti_users.get(update.effective_user.id)

    if not zucchetti_api:
        message = (
            f"Scusami tanto, ma mi sono dimenticato le tue credenziali 😕\n"
            "Devi rieffettiare il login per timbrare nuovamente"
        )
        button = InlineKeyboardButton(text="Login", callback_data=LOGIN_CALLBACK)
        keyboard = InlineKeyboardMarkup.from_button(button)

        if update.callback_query:
            update.callback_query.edit_message_text(text=message, reply_markup=keyboard)
        else:
            update.message.reply_text(text=message, reply_markup=keyboard)

    return zucchetti_api


def stamp_command(update: Update, context: CallbackContext) -> int:
    if not context.user_data.get(ALREADY_STARTED):
        message = (
            f"Devi fornirmi prima le tue credenziali se vuoi iniziare ad usare il bot 🙂"
        )
        button = InlineKeyboardButton(text="Login", callback_data=LOGIN_CALLBACK)
        keyboard = InlineKeyboardMarkup.from_button(button)

        return UNLOGGED_STATE

    zucchetti_api = get_zucchetti_api(update, context)
    if not zucchetti_api:
        return UNLOGGED_STATE

    try:
        zucchetti_api.login()
    except InvalidCredentials:
        button = InlineKeyboardButton(text="Login", callback_data=LOGIN_CALLBACK)
        keyboard = InlineKeyboardMarkup.from_button(button)

        update.message.reply_text(
            text="Le credenziali che avevi precedentemente inserito non sono più valide 🙁",
            reply_markup=keyboard,
        )

        return UNLOGGED_STATE
    except ApiError as e:
        update.message.reply_text(
            "⚠️ Non riesco a effettuare il login. Riprova più tardi.."
        )

        logger.warning(
            f"Failed to authenticate a user {update.message.from_user.first_name}: {e}"
        )

        return LOGGED_STATE

    try:
        last_stamps = zucchetti_api.last_stamps()
    except ApiError as e:
        update.message.reply_text(
            "⚠️ Non riesco a ottenere lo stato del cartellino. Riprova più tardi.."
        )

        logger.warning(
            f"Failed to obtain status for user {update.message.from_user.first_name}: {e}"
        )

        return LOGGED_STATE

    buttons = [InlineKeyboardButton(text="Cancella", callback_data=CANCEL_CALLBACK)]

    if len(last_stamps) == 0 or last_stamps[-1][0] == "U":
        message = "Un nuovo turno deve iniziare! 🌞"
        buttons.append(
            InlineKeyboardButton(text="Timbra entrata", callback_data=ENTER_CALLBACK)
        )
    else:
        message = "Turno finito! 🌚"
        buttons.append(
            InlineKeyboardButton(text="Timbra uscita", callback_data=EXIT_CALLBACK)
        )

    keyboard = InlineKeyboardMarkup([buttons])
    message += "\n\n" + stamp_message(last_stamps)

    update.message.reply_text(text=message, reply_markup=keyboard)

    return LOGGED_STATE


def cancel(update: Update, context: CallbackContext) -> int:
    update.callback_query.delete_message()

    return LOGGED_STATE


def enter(update: Update, context: CallbackContext) -> int:
    return stamp(update, context, True)


def exit(update: Update, context: CallbackContext) -> int:
    return stamp(update, context, False)


def stamp(update: Update, context: CallbackContext, enter: bool) -> int:
    zucchetti_api = get_zucchetti_api(update, context)
    if not zucchetti_api:
        return LOGIN_STATE

    update.callback_query.answer()

    try:
        if enter:
            zucchetti_api.enter()
        else:
            zucchetti_api.exit()

        last_stamps = zucchetti_api.last_stamps()
    except ApiError as e:
        update.callback_query.edit_message_text(
            "⚠️ Non riesco a timbrare. Riprova più tardi.."
        )

        logger.warning(
            f"Failed to stamp for user {update.callback_query.from_user.first_name}: {e}"
        )

        return LOGGED_STATE

    update.callback_query.edit_message_text(
        f"Timbrato con successo 🤟🏽\n\n{stamp_message(last_stamps)}"
    )

    return LOGGED_STATE


def message(update: Update, context: CallbackContext) -> int:
    admins = os.getenv("ADMIN_USERS")
    if not admins:
        return

    if not str(update.message.from_user.id) in admins:
        return

    message = re.sub("^/messaggio ", "", update.message.text)
    for user_id, _ in context.dispatcher.persistence.get_user_data().items():
        context.bot.send_message(chat_id=user_id, text=message)


def stamp_message(stamps: list) -> str:
    return "\n".join(
        [
            ("Entrata ➡️ " if stamp[0] == "E" else "Uscita ⬅️ ") + stamp[1]
            for stamp in stamps
        ]
    )


def stamp_reminder(bot: Bot, user_id: int, schedule_data: dict) -> None:
    if not datetime.now().weekday() in schedule_data["when_days"]:
        return

    stamp_type = schedule_data["stamp_type"]
    zucchetti_api = zucchetti_users.get(user_id)
    if not zucchetti_api:
        message = (
            f"Hey! Forse dovresti timbrare l'{stamp_type}, ma non ho più le tue credenziali per poter verificare 😕"
        )
        button = InlineKeyboardButton(text="Login", callback_data=LOGIN_CALLBACK)
        keyboard = InlineKeyboardMarkup.from_button(button)
        bot.send_message(chat_id=user_id, text=message, reply_markup=keyboard)
        return

    error_message = f"Hey! Dovresti tibrare l'{stamp_type}, "
    try:
        zucchetti_api.login()
    except InvalidCredentials:
        button = InlineKeyboardButton(text="Login", callback_data=LOGIN_CALLBACK)
        keyboard = InlineKeyboardMarkup.from_button(button)

        bot.send_message(
            chat_id=user_id,
            text=error_message
            + "ma le credenziali che avevi precedentemente inserito non sono più valide 🙁",
            reply_markup=keyboard,
        )

        return
    except ApiError:
        bot.send_message(
            chat_id=user_id,
            text=error_message
            + "ma non riesco ad accedere al portale per verificare 🙁",
        )
        return

    try:
        last_stamps = zucchetti_api.last_stamps()
    except ApiError:
        bot.send_message(
            chat_id=user_id,
            text=error_message + "ma non riesco a verificare lo stato del cartellino 🙁",
        )
        return

    if len(last_stamps) > 0:
        if (stamp_type == "entrata" and last_stamps[-1][0] == "E") or (
            stamp_type == "uscita" and last_stamps[-1][0] == "U"
        ):
            # already stamp
            return

    keyboard = None
    message = (
        f"Hey! Devi timbrare l'{stamp_type}! 📢\n\n"
        + stamp_message(last_stamps)
    )
    if stamp_type == "entrata":
        button = InlineKeyboardButton(
            text="Timbra entrata", callback_data=ENTER_CALLBACK
        )
    else:
        button = InlineKeyboardButton(text="Timbra uscita", callback_data=EXIT_CALLBACK)
    buttons = [
        [
            InlineKeyboardButton(text="Cancella", callback_data=CANCEL_CALLBACK),
            button,
        ],
    ]
    keyboard = InlineKeyboardMarkup(buttons)

    bot.send_message(chat_id=user_id, text=message, reply_markup=keyboard)


def notification_menu(update: Update, context: CallbackContext) -> int:
    notifications.main_menu(update, context)

    return NOTIFICATION_STATE


def unknown_callback(update: Update, context: CallbackContext) -> int:
    update.callback_query.delete_message()


def run() -> None:
    data_dir = os.getenv("DATA_DIR") or os.getcwd()
    persistence = PicklePersistence(filename=os.path.join(data_dir, "bot.db"))
    updater = Updater(os.getenv("TELEGRAM_TOKEN"), persistence=persistence)

    dispatcher = updater.dispatcher

    main_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CommandHandler("login", login),
            CommandHandler("timbra", login),
        ],
        states={
            UNLOGGED_STATE: [
                CommandHandler("login", login),
                CallbackQueryHandler(login, pattern="^" + LOGIN_CALLBACK + "$"),
            ],
            LOGIN_STATE: [MessageHandler(Filters.text & ~Filters.command, login)],
            LOGGED_STATE: [
                CommandHandler("timbra", stamp_command),
                CommandHandler("login", login),
                CommandHandler("notifiche", notification_menu),
                CallbackQueryHandler(login, pattern="^" + LOGIN_CALLBACK + "$"),
                CallbackQueryHandler(cancel, pattern="^" + CANCEL_CALLBACK + "$"),
                CallbackQueryHandler(enter, pattern="^" + ENTER_CALLBACK + "$"),
                CallbackQueryHandler(exit, pattern="^" + EXIT_CALLBACK + "$"),
            ],
            NOTIFICATION_STATE: [
                notifications.notification_handler(LOGGED_STATE, stamp_reminder),
            ],
        },
        fallbacks=[
            CommandHandler("messaggio", message),
            CallbackQueryHandler(unknown_callback),
        ],
        name="main_conversation",
        persistent=True,
    )

    notifications.setup_scheduler(updater, stamp_reminder)

    dispatcher.add_handler(main_handler)

    updater.start_polling()

    updater.idle()
