import logging
import os
import re

from telegram import Update
from telegram.ext import (
    CallbackContext,
    CallbackQueryHandler,
    CommandHandler,
    Filters,
    MessageHandler,
    PicklePersistence,
    Updater,
)

from . import notifications
from .zucchetti import ApiError, InvalidCredentials, ZucchettiApi

from .constants import *
from .helpers import (
    admin_user,
    callback,
    callback_pattern,
    command,
    logged_user,
    make_keyboard,
)

CANCEL_CALLBACK, ENTER_CALLBACK, EXIT_CALLBACK = (
    "cancel_callback",
    "enter_callback",
    "exit_callback",
)

KIND_CREDENTIALS = "credentials"

logger = logging.getLogger(__name__)


LOGIN_MESSAGE = (
    "Inserisci le tue credenziali di Zucchetti 🔐, separate da uno spazio.\n\n"
    "Dovrò salvare le tue credenziali in memoria per non richiederti le credenziali tutte le volte, ma non le scriverò da nessuna parte. Lo giuro! 🙇🏽‍♂️"
)


zucchetti_users = dict()


@command
def start_command(update: Update, context: CallbackContext):
    update.message.reply_text(
        "Ciao! Io sono merdetti-bot 💩! Con me potrai timbrare il cartellino senza dover entrare in quell'orribile portale 😭\n\n"
        "Ma prima devi effettuare il login!",
        reply_markup=make_keyboard(("Login", LOGIN_CALLBACK), context),
    )


@command
def login_command(update: Update, context: CallbackContext):
    context.user_data[INPUT_KIND] = KIND_CREDENTIALS
    update.message.reply_text(LOGIN_MESSAGE)


@callback
def login_callback(update: Update, context: CallbackContext):
    context.user_data[INPUT_KIND] = KIND_CREDENTIALS
    update.callback_query.edit_message_text(LOGIN_MESSAGE)


def credentials_input(update: Update, context: CallbackContext):
    match = re.match(r"^([\S]+)[\s]+(\S+)$", update.message.text)
    if not match:
        update.message.reply_markdown(
            "Devi inserire le credenziali nel seguente formato: `USERNAME PASSWORD`\n"
            "Inserisci le credenziali di nuovo! 😑"
        )
        return

    zucchetti_api = ZucchettiApi(match[1], match[2])
    try:
        zucchetti_api.login()
    except InvalidCredentials:
        update.message.reply_text(
            "Le credenziali che hai inserito non sono corrette!\n"
            "Inseriscile nuovamente (quelle giuste magari 😅)"
        )
        return
    except ApiError as e:
        update.message.reply_text(
            "Non sono riuscito a verificare le tue credenziali 😓. Riprova più tardi rieffettuando il /login"
        )

        logger.warning(
            f"Failed to authenticate a user {update.message.from_user.first_name}: {e}"
        )

        context.user_data[INPUT_KIND] = None

        return

    zucchetti_users[update.effective_user.id] = zucchetti_api
    context.user_data[LOGGED] = True
    context.user_data[INPUT_KIND] = None

    logger.info(
        "User %s (%s) logged in",
        update.effective_user.id,
        update.effective_user.first_name,
    )

    update.message.reply_text(
        "Credenziali salvate con successo!\n\nUsa /timbra per timbrare 🎫\nUsa /notifiche per impostare gli avvisi 📢"
    )


def user_input(update: Update, context: CallbackContext):
    input_kinds = [
        (KIND_CREDENTIALS, credentials_input)
    ] + notifications.user_input_handlers(stamp_reminder)

    for input_kind, input_callback in input_kinds:
        if context.user_data.get(INPUT_KIND) == input_kind:
            input_callback(update, context)

            return


def get_zucchetti_api(update: Update, context: CallbackContext):
    zucchetti_api = zucchetti_users.get(update.effective_user.id)

    if not zucchetti_api:
        message = (
            f"Scusami tanto, ma mi sono dimenticato le tue credenziali 😕\n"
            "Devi rieffettiare il login per timbrare nuovamente"
        )
        keyboard = make_keyboard(("Login", LOGIN_CALLBACK), context)

        if update.callback_query:
            update.callback_query.edit_message_text(text=message, reply_markup=keyboard)
        else:
            update.message.reply_text(text=message, reply_markup=keyboard)

    return zucchetti_api


@command
@logged_user
def stamp_command(update: Update, context: CallbackContext):
    zucchetti_api = get_zucchetti_api(update, context)
    if not zucchetti_api:
        context.user_data[LOGGED] = False
        return

    try:
        zucchetti_api.login()
    except InvalidCredentials:
        update.message.reply_text(
            text="Le credenziali che avevi precedentemente inserito non sono più valide 🙁",
            reply_markup=make_keyboard(("Login", LOGIN_CALLBACK), context),
        )

        context.user_data[LOGGED] = False
        return
    except ApiError as e:
        update.message.reply_text(
            "⚠️ Non riesco a effettuare il login. Riprova più tardi.."
        )

        logger.warning(
            f"Failed to authenticate a user {update.message.from_user.first_name}: {e}"
        )

        return

    try:
        last_stamps = zucchetti_api.last_stamps()
    except ApiError as e:
        update.message.reply_text(
            "⚠️ Non riesco a ottenere lo stato del cartellino. Riprova più tardi.."
        )

        logger.warning(
            f"Failed to obtain status for user {update.message.from_user.first_name}: {e}"
        )

        return

    buttons = [("Cancella", CANCEL_CALLBACK)]

    if len(last_stamps) == 0 or last_stamps[-1][0] == "U":
        message = "Un nuovo turno deve iniziare! 🌞"
        buttons.append(("Timbra entrata", ENTER_CALLBACK))
    else:
        message = "Turno finito! 🌚"
        buttons.append(("Timbra uscita", EXIT_CALLBACK))

    message += "\n\n" + stamp_message(last_stamps)

    update.message.reply_text(
        text=message, reply_markup=make_keyboard([buttons], context)
    )


@callback
def cancel_callback(update: Update, context: CallbackContext):
    update.callback_query.delete_message()


@callback
def enter_callback(update: Update, context: CallbackContext):
    return stamp(update, context, True)


@callback
def exit_callback(update: Update, context: CallbackContext):
    return stamp(update, context, False)


@logged_user
def stamp(update: Update, context: CallbackContext, enter: bool):
    zucchetti_api = get_zucchetti_api(update, context)
    if not zucchetti_api:
        return

    if update.message:
        reply = update.message.reply_text
    else:
        reply = update.callback_query.edit_message_text

    try:
        if enter:
            zucchetti_api.enter()
        else:
            zucchetti_api.exit()

        last_stamps = zucchetti_api.last_stamps()
    except ApiError as e:
        reply("⚠️ Non riesco a timbrare. Riprova più tardi..")

        logger.warning(
            f"Failed to stamp for user {update.callback_query.from_user.first_name}: {e}"
        )

        return

    logger.info(
        "User %s (%s) stamp %s",
        update.effective_user.id,
        update.effective_user.first_name,
        "entry" if enter else "exit",
    )
    reply(f"Timbrato con successo 🤟🏽\n\n{stamp_message(last_stamps)}")


@command
@admin_user
def message_command(update: Update, context: CallbackContext):
    message = re.sub("^/messaggio", "", update.message.text).strip()
    if message == "":
        return

    for user_id, _ in context.dispatcher.persistence.get_user_data().items():
        context.bot.send_message(
            chat_id=user_id, text=f"{update.effective_user.first_name}: {message}"
        )


def stamp_message(stamps: list) -> str:
    return "\n".join(
        [
            ("Entrata ➡️ " if stamp[0] == "E" else "Uscita ⬅️ ") + stamp[1]
            for stamp in stamps
        ]
    )


def stamp_reminder(context) -> None:
    bot = context.job.context["bot"]
    user_id = context.job.context["user_id"]
    user_data = context.job.context["user_data"]
    schedule_data = context.job.context["schedule_data"]

    user_data[INPUT_KIND] = None

    stamp_type = schedule_data["stamp_type"]
    zucchetti_api = zucchetti_users.get(user_id)
    if not zucchetti_api:
        message = f"Hey! Forse dovresti timbrare l'{stamp_type}, ma non ho più le tue credenziali per poter verificare 😕"
        bot.send_message(
            chat_id=user_id,
            text=message,
            reply_markup=make_keyboard(("Login", LOGIN_CALLBACK), user_data=user_data),
        )
        return

    error_message = f"Hey! Dovresti tibrare l'{stamp_type}, "
    try:
        zucchetti_api.login()
    except InvalidCredentials:
        bot.send_message(
            chat_id=user_id,
            text=error_message
            + "ma le credenziali che avevi precedentemente inserito non sono più valide 🙁",
            reply_markup=make_keyboard(("Login", LOGIN_CALLBACK), context),
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

    message = f"Hey! Devi timbrare l'{stamp_type}! 📢\n\n" + stamp_message(last_stamps)
    if stamp_type == "entrata":
        button = ("Timbra entrata", ENTER_CALLBACK)
    else:
        button = ("Timbra uscita", EXIT_CALLBACK)
    keyboard = make_keyboard(
        [[("Cancella", CANCEL_CALLBACK), button]], user_data=user_data
    )

    bot.send_message(chat_id=user_id, text=message, reply_markup=keyboard)


@command
def notification_command(update: Update, context: CallbackContext):
    notifications.main_menu(update, context)


def run() -> None:
    data_dir = os.getenv("DATA_DIR") or os.getcwd()
    persistence = PicklePersistence(filename=os.path.join(data_dir, "bot.db"))
    updater = Updater(os.getenv("TELEGRAM_TOKEN"), persistence=persistence)

    dispatcher = updater.dispatcher

    handlers = [
        CommandHandler("start", start_command),
        CommandHandler("login", login_command),
        CommandHandler("timbra", stamp_command),
        CommandHandler("entra", enter_callback),
        CommandHandler("esci", exit_callback),
        CommandHandler("messaggio", message_command),
        CommandHandler("notifiche", notification_command),
        CallbackQueryHandler(login_callback, pattern=callback_pattern(LOGIN_CALLBACK)),
        CallbackQueryHandler(
            cancel_callback, pattern=callback_pattern(CANCEL_CALLBACK)
        ),
        CallbackQueryHandler(enter_callback, pattern=callback_pattern(ENTER_CALLBACK)),
        CallbackQueryHandler(exit_callback, pattern=callback_pattern(EXIT_CALLBACK)),
        MessageHandler(Filters.text & ~Filters.command, user_input),
    ] + notifications.handlers(stamp_reminder)

    notifications.setup_scheduler(updater, stamp_reminder)

    for handler in handlers:
        dispatcher.add_handler(handler)

    updater.start_polling()

    updater.idle()
