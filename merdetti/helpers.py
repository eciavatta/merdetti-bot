import logging
import os
import re
import uuid

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext

from .constants import *

CALLBACK_SESSION = "callback_session"

logger = logging.getLogger(__name__)


def make_keyboard(buttons: list, context: CallbackContext = None, user_data: dict = None):
    keyboard = []

    session = str(uuid.uuid4())
    if context:
        context.user_data[CALLBACK_SESSION] = session
    else:
        user_data[CALLBACK_SESSION] = session

    if isinstance(buttons, list):
        for row in buttons:
            keyboard.append(
                [
                    InlineKeyboardButton(
                        text=button[0], callback_data=f"{button[1]}#{session}"
                    )
                    for button in row
                ]
            )
    elif isinstance(buttons, tuple):
        keyboard = [
            [
                InlineKeyboardButton(
                    text=buttons[0], callback_data=f"{buttons[1]}#{session}"
                )
            ]
        ]
    else:
        raise Exception("Invalid buttons type")

    return InlineKeyboardMarkup(keyboard)


def logged_user(func):
    def wrapper(*args, **kwargs):
        update, context = args[0], args[1]

        if context.user_data.get(LOGGED):
            func(*args, **kwargs)
        else:
            message = "Devi prima loggarti per utilizzare questo comando! ⛔"
            keyboard = make_keyboard(("Login", LOGIN_CALLBACK), context)
            if update.callback_query:
                update.callback_query.answer()
                update.callback_query.edit_message_text(
                    text=message, reply_markup=keyboard
                )
            else:
                update.message.reply_text(text=message, reply_markup=keyboard)

    return wrapper


def admin_user(func):
    def wrapper(*args, **kwargs):
        update = args[0]

        admins = os.getenv("ADMIN_USERS")
        if not admins:
            return

        if not str(update.message.from_user.id) in admins:
            return

        func(*args, **kwargs)

    return wrapper


def callback(func):
    def wrapper(*args, **kwargs):
        update, context = args[0], args[1]

        if not update.callback_query:
            func(*args, **kwargs)
            return

        update.callback_query.answer()

        match = re.match(r"^([\w]+)#([\w-]+)$", update.callback_query.data)
        if not match:
            update.callback_query.delete_message()
            return

        if match[2] != context.user_data.get(CALLBACK_SESSION):
            update.callback_query.delete_message()
            return

        func(*args, **kwargs)

    return wrapper


def callback_pattern(key):
    return "^" + key + "#[\w-]+$"


def command(func):
    def wrapper(*args, **kwargs):
        context = args[1]

        context.user_data[INPUT_KIND] = None

        func(*args, **kwargs)

    return wrapper
