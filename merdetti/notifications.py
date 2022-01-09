import logging
import re
from threading import Thread
from typing import Tuple

import schedule
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (CallbackContext, CallbackQueryHandler,
                          ConversationHandler, Filters, MessageHandler)
from telegram.ext.updater import Updater

(
    INITIAL_STATE,
    REMOVE_STATE,
    REMOVE_EXIT_STATE,
    CHOOSE_DAYS_STATE,
    CHOOSE_TIME_STATE,
    ADD_EXIT_STATE,
) = map(chr, range(10, 16))

(
    BACK_CALLBACK,
    REMOVE_CALLBACK,
    ADD_CALLBACK,
    REMIND_ENTER_CALLBACK,
    REMIND_EXIT_CALLBACK,
    CHOOSE_TIME_CALLBACK,
) = (
    "back_callback",
    "remove_callback",
    "add_callback",
    "remind_enter_callback",
    "remind_exit_callback",
    "choose_time_callback",
)

STAMP_REMINDERS = "stamp_reminders"
TMP_NOTIFICATION = "tmp_notification"

DAYS_OF_WEEK = {
    0: "lunedì",
    1: "martedì",
    2: "mercoledì",
    3: "giovedì",
    4: "venerdì",
    5: "sabato",
    6: "domenica",
}

STAMP_TYPE, WHEN_DAYS, WHEN_TIME = "stamp_type", "when_days", "when_time"

logger = logging.getLogger(__name__)

notification_jobs = dict()


def main_menu(update: Update, context: CallbackContext) -> int:
    stamp_reminders = context.user_data.get(STAMP_REMINDERS)
    buttons = [InlineKeyboardButton(text="Annulla", callback_data=BACK_CALLBACK)]

    if stamp_reminders and len(stamp_reminders) > 0:
        buttons.append(
            InlineKeyboardButton(text="Rimuovi notifica", callback_data=REMOVE_CALLBACK)
        )

    buttons.append(
        InlineKeyboardButton(text="Aggiungi notifica", callback_data=ADD_CALLBACK)
    )
    keyboard = InlineKeyboardMarkup([buttons])

    message = "Attraverso le notifiche ti posso avvertire quando ti dimentichi di timbrare. Scegli cosa fare!"

    if update.message:
        update.message.reply_text(text=message, reply_markup=keyboard)
    else:
        update.callback_query.answer()
        update.callback_query.edit_message_text(text=message, reply_markup=keyboard)


def end(update: Update, context: CallbackContext) -> int:
    update.callback_query.answer()
    update.callback_query.delete_message()

    return ConversationHandler.END


def back(update: Update, context: CallbackContext) -> int:
    main_menu(update, context)

    return INITIAL_STATE


def remove_menu(update: Update, context: CallbackContext) -> int:
    stamp_reminders = context.user_data.get(STAMP_REMINDERS)

    message = "Invia il numero della notifica da rimuovere, o annulla l'operazione:\n\n"

    for i in range(len(stamp_reminders)):
        stamp_type = stamp_reminders[i][STAMP_TYPE]
        when_time = stamp_reminders[i][WHEN_TIME]
        when_days = ",".join(
            [DAYS_OF_WEEK[d][:3] for d in stamp_reminders[i][WHEN_DAYS]]
        )

        message += f"{i+1}: {stamp_type} alle ore {when_time} del giorno {when_days}\n"

    button = InlineKeyboardButton(text="Annulla", callback_data=BACK_CALLBACK)
    keyboard = InlineKeyboardMarkup.from_button(button)

    update.callback_query.edit_message_text(text=message, reply_markup=keyboard)

    return REMOVE_STATE


def remove_action(update: Update, context: CallbackContext) -> int:
    try:
        index = int(update.message.text.strip())
        index -= 1
    except:
        update.message.reply_text(
            text="Devi inserire il numero della notifica da rimuovere"
        )
        return

    stamp_reminders = context.user_data.get(STAMP_REMINDERS)

    if index < 0 or index >= len(stamp_reminders):
        update.message.reply_text(
            text=f"Devi inserire l'id della notifica da rimuovere"
        )
        return

    schedule.cancel_job(
        notification_jobs[
            (update.effective_user.id, notification_key(stamp_reminders[index]))
        ]
    )
    context.user_data[STAMP_REMINDERS].remove(stamp_reminders[index])

    button = InlineKeyboardButton(text="Indietro", callback_data=BACK_CALLBACK)
    keyboard = InlineKeyboardMarkup.from_button(button)
    update.message.reply_text(text="Notifica rimossa!", reply_markup=keyboard)

    return REMOVE_EXIT_STATE


def add_menu(update: Update, context: CallbackContext) -> int:
    context.user_data[TMP_NOTIFICATION] = {WHEN_DAYS: [0, 1, 2, 3, 4]}

    buttons = [
        InlineKeyboardButton(text="Annulla", callback_data=BACK_CALLBACK),
        InlineKeyboardButton(
            text="Ricorda entrata", callback_data=REMIND_ENTER_CALLBACK
        ),
        InlineKeyboardButton(text="Ricorda uscita", callback_data=REMIND_EXIT_CALLBACK),
    ]
    keyboard = InlineKeyboardMarkup([buttons])
    update.callback_query.edit_message_text(
        "Scegli il tipo di notifica da aggiungere", reply_markup=keyboard
    )

    return CHOOSE_DAYS_STATE


def choose_days(update: Update, context: CallbackContext) -> int:
    tmp_notification = context.user_data[TMP_NOTIFICATION]

    if update.callback_query.data == REMIND_ENTER_CALLBACK:
        tmp_notification[STAMP_TYPE] = "entrata"
        tmp_notification[WHEN_TIME] = "9:15"
    elif update.callback_query.data == REMIND_EXIT_CALLBACK:
        tmp_notification[STAMP_TYPE] = "uscita"
        tmp_notification[WHEN_TIME] = "18:15"
    elif update.callback_query.data in DAYS_OF_WEEK.values():
        when_days = tmp_notification[WHEN_DAYS]
        for index, name in DAYS_OF_WEEK.items():
            if name == update.callback_query.data:
                current = index
                break

        if current in when_days:
            when_days.remove(current)
        else:
            when_days.append(current)
            when_days.sort()

    days_of_week_buttons = [
        InlineKeyboardButton(text=day.capitalize(), callback_data=day)
        for day in DAYS_OF_WEEK.values()
    ]

    message = (
        "Scegli i giorni della settimana in cui vuoi essere notificato.\n\nAttivi: "
    )
    message += ", ".join(DAYS_OF_WEEK[d] for d in tmp_notification[WHEN_DAYS])

    buttons = [
        days_of_week_buttons[:3],
        days_of_week_buttons[3:6],
        [
            days_of_week_buttons[6],
            InlineKeyboardButton(text="Annulla", callback_data=BACK_CALLBACK),
            InlineKeyboardButton(text="Fatto", callback_data=CHOOSE_TIME_CALLBACK),
        ],
    ]
    keyboard = InlineKeyboardMarkup(buttons)
    update.callback_query.edit_message_text(message, reply_markup=keyboard)


def choose_time_wrapper(stamp_reminder_callback):
    def choose_time(update: Update, context: CallbackContext) -> int:
        button = InlineKeyboardButton(text="Annulla", callback_data=BACK_CALLBACK)
        keyboard = InlineKeyboardMarkup.from_button(button)

        if update.callback_query:
            message = "Inserisci l'orario in cui inviare la notifica, nel formato HH:MM"
            update.callback_query.edit_message_text(text=message, reply_markup=keyboard)

            return CHOOSE_TIME_STATE

        input_time = update.message.text.strip()
        if re.match(r"^(0[0-9]|1[0-9]|2[0-3]):[0-5][0-9]$", input_time):
            context.user_data[TMP_NOTIFICATION][WHEN_TIME] = input_time

            user_id = update.effective_user.id
            schedule_data = context.user_data[TMP_NOTIFICATION]
            del context.user_data[TMP_NOTIFICATION]

            reminders = context.user_data.get(STAMP_REMINDERS) or []
            reminders.append(schedule_data)
            context.user_data[STAMP_REMINDERS] = reminders

            job = (
                schedule.every()
                .day.at(input_time)
                .do(
                    stamp_reminder_callback,
                    bot=context.bot,
                    user_id=user_id,
                    schedule_data=schedule_data,
                )
            )
            notification_jobs[(user_id, notification_key(schedule_data))] = job

            message = "Notifica aggiunta con successo!"
            update.message.reply_text(text=message, reply_markup=keyboard)

            return ADD_EXIT_STATE

        message = "L'orario deve essere nel formato HH:MM"
        update.message.reply_text(text=message, reply_markup=keyboard)

    return choose_time


def schedule_loop():
    while True:
        schedule.run_pending()


def setup_scheduler(updater: Updater, stamp_reminder_callback):
    for user_id, user_values in updater.persistence.get_user_data().items():
        if STAMP_REMINDERS in user_values:
            for schedule_data in user_values[STAMP_REMINDERS]:
                job = (
                    schedule.every()
                    .day.at(schedule_data[WHEN_TIME])
                    .do(
                        stamp_reminder_callback,
                        bot=updater.bot,
                        user_id=user_id,
                        schedule_data=schedule_data,
                    )
                )
                notification_jobs[(user_id, notification_key(schedule_data))] = job

    schedule_thread = Thread(target=schedule_loop)
    schedule_thread.start()


def notification_handler(exit_state: int, stamp_reminder_callback):
    menu_state = [
        CallbackQueryHandler(end, pattern="^" + BACK_CALLBACK + "$"),
        CallbackQueryHandler(remove_menu, pattern="^" + REMOVE_CALLBACK + "$"),
        CallbackQueryHandler(add_menu, pattern="^" + ADD_CALLBACK + "$"),
    ]

    choose_time_handler = choose_time_wrapper(stamp_reminder_callback)

    return ConversationHandler(
        entry_points=menu_state,
        states={
            INITIAL_STATE: menu_state,
            REMOVE_STATE: [
                MessageHandler(Filters.text & ~Filters.command, remove_action),
                CallbackQueryHandler(back, pattern="^" + BACK_CALLBACK + "$"),
            ],
            REMOVE_EXIT_STATE: [
                CallbackQueryHandler(back, pattern="^" + BACK_CALLBACK + "$"),
            ],
            CHOOSE_DAYS_STATE: [
                CallbackQueryHandler(
                    choose_days,
                    pattern=f'^({REMIND_ENTER_CALLBACK}|{REMIND_EXIT_CALLBACK}|{"|".join(DAYS_OF_WEEK.values())})$',
                ),
                CallbackQueryHandler(
                    choose_time_handler, pattern="^" + CHOOSE_TIME_CALLBACK + "$"
                ),
                CallbackQueryHandler(back, pattern="^" + BACK_CALLBACK + "$"),
            ],
            CHOOSE_TIME_STATE: [
                CallbackQueryHandler(back, pattern="^" + BACK_CALLBACK + "$"),
                MessageHandler(Filters.text & ~Filters.command, choose_time_handler),
            ],
            ADD_EXIT_STATE: [
                CallbackQueryHandler(back, pattern="^" + BACK_CALLBACK + "$"),
            ],
        },
        fallbacks=[],
        map_to_parent={
            ConversationHandler.END: exit_state,
        },
        name="notification_handler",
        persistent=True,
    )


def notification_key(notification: dict) -> Tuple:
    return (
        notification[STAMP_TYPE],
        ",".join([str(d) for d in notification[WHEN_DAYS]]),
        notification[WHEN_TIME],
    )
