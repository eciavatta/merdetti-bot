import logging
import os
import re

from merdetti.zucchetti import ApiError, InvalidCredentials, ZucchettiApi
from telegram import InlineKeyboardMarkup, InlineKeyboardButton, Update
from telegram.ext import (
    Updater,
    CommandHandler,
    MessageHandler,
    Filters,
    ConversationHandler,
    CallbackQueryHandler,
    CallbackContext,
)

logger = logging.getLogger(__name__)

UNLOGGED_STATE, LOGIN_STATE, LOGGED_STATE = map(chr, range(3))

LOGIN_CALLBACK, CANCEL_CALLBACK, ENTER_CALLBACK, EXIT_CALLBACK = map(
    chr, range(3, 7))

END = ConversationHandler.END

(
    ALREADY_STARTED,
    ZUCCHETTI_API,
    PROMPT_CREDENTIALS_MESSAGE,
) = map(chr, range(7, 10))


def start(update: Update, context: CallbackContext) -> str:
    button = InlineKeyboardButton(
        text='Login', callback_data=str(LOGIN_CALLBACK))
    keyboard = InlineKeyboardMarkup.from_button(button)

    if not context.user_data.get(ALREADY_STARTED):
        update.message.reply_text(
            'Ciao! Io sono merdetti-bot 💩! Con me potrai timbrare il cartellino senza dover entrare in quell\'orribile portale 😭\n\n'
            'Ma prima devi effettuare il login!', reply_markup=keyboard
        )

        context.user_data[ALREADY_STARTED] = True

    return UNLOGGED_STATE


def login(update: Update, context: CallbackContext) -> str:
    if not context.user_data.get(PROMPT_CREDENTIALS_MESSAGE):
        if update.callback_query:
            update.callback_query.answer()
            func = update.callback_query.edit_message_text
        else:
            func = update.message.reply_text

        func(
            'Inserisci le tue credenziali di Zucchetti 🔐, separate da uno spazio.\n\n'
            'Dovrò salvare le tue credenziali in memoria per non richiederti le credenziali tutte le volte, ma non le scriverò da nessuna parte. Lo giuro! 🙇🏽‍♂️'
        )
        context.user_data[PROMPT_CREDENTIALS_MESSAGE] = True

        return LOGIN_STATE

    match = re.match(r'^([\S]+)[\s]+(\S+)$', update.message.text)
    if not match:
        update.message.reply_markdown(
            'Devi inserire le credenziali nel seguente formato: `USERNAME PASSWORD`\n'
            'Inserisci le credenziali di nuovo! 😑'
        )

        return LOGIN_STATE

    zucchetti_api = ZucchettiApi(match[1], match[2])
    try:
        zucchetti_api.login()
    except InvalidCredentials:
        update.message.reply_text(
            'Le credenziali che hai inserito non sono corrette!\n'
            'Inseriscile nuovamente (quelle giuste magari 😅)'
        )

        return LOGIN_STATE
    except ApiError as e:
        update.message.reply_text(
            'Non sono riuscito a verificare le tue credenziali 😓. Riprova più tardi rieffettuando il /login'
        )

        logger.warning(
            f'Failed to authenticate a user {update.message.from_user.first_name}: {e}')

        return UNLOGGED_STATE

    context.user_data[ZUCCHETTI_API] = zucchetti_api
    context.user_data[PROMPT_CREDENTIALS_MESSAGE] = False
    update.message.reply_text(
        'Credenziali salvate con successo!\nUtilizza /timbra per timbrare! 🎫'
    )

    return LOGGED_STATE


def stamp_command(update: Update, context: CallbackContext) -> str:
    zucchetti_api = context.user_data[ZUCCHETTI_API]

    try:
        zucchetti_api.login()
    except InvalidCredentials:
        button = InlineKeyboardButton(
            text='Login', callback_data=str(LOGIN_STATE))
        keyboard = InlineKeyboardMarkup.from_button(button)

        update.message.reply_text(
            text='Le credenziali che avevi precedentemente inserito non sono più valide 🙁', reply_markup=keyboard)

        return LOGIN_STATE
    except ApiError as e:
        update.message.reply_text(
            '⚠️ Non riesco a effettuare il login. Riprova più tardi..')

        logger.warning(
            f'Failed to authenticate a user {update.message.from_user.first_name}: {e}')

        return LOGGED_STATE

    try:
        status = zucchetti_api.status()
    except ApiError as e:
        update.message.reply_text(
            '⚠️ Non riesco a ottenere lo stato del cartellino. Riprova più tardi..')

        logger.warning(
            f'Failed to obtain status for user {update.message.from_user.first_name}: {e}')

        return LOGGED_STATE

    keyboard = None
    if 'E' in status and 'U' in status:
        message = 'Hai già timbrato, scioccə! 😒'
    elif 'E' in status:
        message = 'Buona sera! Un\'altra giornata è finita 🌚'
        buttons = [
            [
                InlineKeyboardButton(
                    text='Cancella', callback_data=str(CANCEL_CALLBACK)),
                InlineKeyboardButton(text='Timbra uscita',
                                     callback_data=str(EXIT_CALLBACK)),
            ],
        ]
        keyboard = InlineKeyboardMarkup(buttons)
    else:
        message = 'Buongiorno! Una bella giornata ti aspetta! 🌞'
        buttons = [
            [
                InlineKeyboardButton(
                    text='Cancella', callback_data=str(CANCEL_CALLBACK)),
                InlineKeyboardButton(text='Timbra entrata',
                                     callback_data=str(ENTER_CALLBACK)),
            ],
        ]
        keyboard = InlineKeyboardMarkup(buttons)

    message += '\n\n' + stamp_message(status)

    update.message.reply_text(text=message, reply_markup=keyboard)

    return LOGGED_STATE


def cancel(update: Update, context: CallbackContext) -> int:
    update.callback_query.answer()

    update.callback_query.delete_message()

    return LOGGED_STATE


def enter(update: Update, context: CallbackContext) -> int:
    return stamp(update, context, True)


def exit(update: Update, context: CallbackContext) -> int:
    return stamp(update, context, False)


def stamp(update: Update, context: CallbackContext, enter: bool) -> int:
    zucchetti_api = context.user_data[ZUCCHETTI_API]

    update.callback_query.answer()

    try:
        if enter:
            zucchetti_api.enter()
        else:
            zucchetti_api.exit()

        status = zucchetti_api.status()
    except ApiError as e:
        update.callback_query.edit_message_text(
            '⚠️ Non riesco a timbrare. Riprova più tardi..')

        logger.warning(
            f'Failed to stamp for user {update.message.from_user.first_name}: {e}')

        return LOGGED_STATE

    update.callback_query.edit_message_text(
        f'Timbrato con successo 🤟🏽\n\n{stamp_message(status)}')

    return LOGGED_STATE


def stamp_message(status: dict) -> str:
    stamps = ''
    if 'E' in status:
        stamps = f'Entrata ➡️ {status["E"]}'
    if 'U' in status:
        stamps += f'\nUscita ⬅️ {status["U"]}'

    return stamps


def run() -> None:
    updater = Updater(os.getenv('TELEGRAM_TOKEN'))

    dispatcher = updater.dispatcher

    UNLOGGED_STATE, LOGIN_STATE, LOGGED_STATE, CANCEL_CALLBACK, ENTER_CALLBACK, EXIT_CALLBACK

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('start', start),
            CommandHandler('login', login),
            CommandHandler('timbra', login),
        ],
        states={
            UNLOGGED_STATE: [
                CommandHandler('login', login),
                CallbackQueryHandler(login, pattern='^' +
                                     str(LOGIN_CALLBACK) + '$')
            ],
            LOGIN_STATE: [
                MessageHandler(Filters.text & ~Filters.command, login)
            ],
            LOGGED_STATE: [
                CommandHandler('timbra', stamp_command),
                CommandHandler('login', login),
                CallbackQueryHandler(
                    cancel, pattern='^' + str(CANCEL_CALLBACK) + '$'),
                CallbackQueryHandler(enter, pattern='^' +
                                     str(ENTER_CALLBACK) + '$'),
                CallbackQueryHandler(exit, pattern='^' +
                                     str(EXIT_CALLBACK) + '$')
            ],
        },
        fallbacks=[]
    )

    dispatcher.add_handler(conv_handler)

    updater.start_polling()

    updater.idle()
