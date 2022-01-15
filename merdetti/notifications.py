import logging
import re
from datetime import datetime
from typing import Tuple

from dateutil import tz
from telegram import Update
from telegram.ext import CallbackContext, CallbackQueryHandler
from telegram.ext.updater import Updater

from .constants import *
from .helpers import callback, callback_pattern, logged_user, make_keyboard

(
    NOTIFICATION_EXIT_CALLBACK,
    NOTIFICATION_BACK_CALLBACK,
    NOTIFICATION_REMOVE_CALLBACK,
    NOTIFICATION_ADD_CALLBACK,
    REMIND_ENTER_CALLBACK,
    REMIND_EXIT_CALLBACK,
    CHOOSE_TIME_CALLBACK,
) = (
    "not_exit_callback",
    "not_back_callback",
    "not_remove_callback",
    "not_add_callback",
    "remind_enter_callback",
    "remind_exit_callback",
    "choose_time_callback",
)

STAMP_REMINDERS = "stamp_reminders"
TMP_NOTIFICATION = "tmp_notification"

KIND_NOTIFICATION_INDEX = "notification_index"
KIND_NOTIFICATION_TIME = "notification_time"

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


@logged_user
def main_menu(update: Update, context: CallbackContext):
    stamp_reminders = context.user_data.get(STAMP_REMINDERS)
    buttons = [("Indietro", NOTIFICATION_EXIT_CALLBACK)]

    if stamp_reminders and len(stamp_reminders) > 0:
        buttons.append(("Rimuovi 🔕", NOTIFICATION_REMOVE_CALLBACK))

    buttons.append(("Aggiungi 🔔", NOTIFICATION_ADD_CALLBACK))
    keyboard = make_keyboard([buttons], context)

    message = (
        "Attraverso le notifiche ti posso avvertire quando ti dimentichi di timbrare 🚨"
    )

    if update.message:
        update.message.reply_text(text=message, reply_markup=keyboard)
    else:
        update.callback_query.edit_message_text(text=message, reply_markup=keyboard)


@callback
def exit_callback(update: Update, context: CallbackContext):
    update.callback_query.delete_message()


@callback
def back_callback(update: Update, context: CallbackContext):
    main_menu(update, context)


@callback
def remove_callback(update: Update, context: CallbackContext):
    stamp_reminders = context.user_data.get(STAMP_REMINDERS)

    message = "Invia il numero della notifica da rimuovere ✍🏽\n\n"

    for i in range(len(stamp_reminders)):
        stamp_type = stamp_reminders[i][STAMP_TYPE]
        when_time = stamp_reminders[i][WHEN_TIME]
        when_days = ",".join(
            [DAYS_OF_WEEK[d][:3] for d in stamp_reminders[i][WHEN_DAYS]]
        )

        message += f"{i+1}: {stamp_type} alle ore {when_time} nei giorni {when_days}\n"

    keyboard = make_keyboard(("Indietro", NOTIFICATION_BACK_CALLBACK), context)
    update.callback_query.edit_message_text(text=message, reply_markup=keyboard)

    context.user_data[INPUT_KIND] = KIND_NOTIFICATION_INDEX


def remove_action(update: Update, context: CallbackContext):
    try:
        index = int(update.message.text.strip())
        index -= 1
    except:
        update.message.reply_text(
            text="Devi inserire il numero della notifica da rimuovere 🔢"
        )
        return

    stamp_reminders = context.user_data.get(STAMP_REMINDERS)

    if index < 0 or index >= len(stamp_reminders):
        update.message.reply_text(
            text=f"Devi inserire l'id della notifica da rimuovere 🔢"
        )
        return

    notification_jobs[
        (update.effective_user.id, notification_key(stamp_reminders[index]))
    ].schedule_removal()
    context.user_data[STAMP_REMINDERS].remove(stamp_reminders[index])

    keyboard = make_keyboard(("Indietro", NOTIFICATION_BACK_CALLBACK), context)
    update.message.reply_text(text="Notifica rimossa! ✅", reply_markup=keyboard)

    context.user_data[INPUT_KIND] = None


@callback
def add_callback(update: Update, context: CallbackContext):
    context.user_data[TMP_NOTIFICATION] = {WHEN_DAYS: [0, 1, 2, 3, 4]}

    buttons = [
        ("Indietro", NOTIFICATION_BACK_CALLBACK),
        ("Entrata ➡️", REMIND_ENTER_CALLBACK),
        ("Uscita ⬅️", REMIND_EXIT_CALLBACK),
    ]
    update.callback_query.edit_message_text(
        "Scegli il tipo di notifica da aggiungere 📢",
        reply_markup=make_keyboard([buttons], context),
    )


@callback
def choose_days(update: Update, context: CallbackContext):
    tmp_notification = context.user_data[TMP_NOTIFICATION]

    callback_data = update.callback_query.data[: update.callback_query.data.index("#")]
    if callback_data == REMIND_ENTER_CALLBACK:
        tmp_notification[STAMP_TYPE] = "entrata"
        tmp_notification[WHEN_TIME] = "9:15"
    elif callback_data == REMIND_EXIT_CALLBACK:
        tmp_notification[STAMP_TYPE] = "uscita"
        tmp_notification[WHEN_TIME] = "18:15"
    elif callback_data in DAYS_OF_WEEK.values():
        when_days = tmp_notification[WHEN_DAYS]
        for index, name in DAYS_OF_WEEK.items():
            if name == callback_data:
                current = index
                break

        if current in when_days:
            when_days.remove(current)
        else:
            when_days.append(current)
            when_days.sort()

    days_of_week_buttons = [(day.capitalize(), day) for day in DAYS_OF_WEEK.values()]

    message = "Scegli i giorni della settimana in cui vuoi essere notificato 🗓️\n\nGiorni abilitati: "
    message += ", ".join(DAYS_OF_WEEK[d] for d in tmp_notification[WHEN_DAYS])

    buttons = [
        days_of_week_buttons[:3],
        days_of_week_buttons[3:6],
        [
            days_of_week_buttons[6],
            ("Indietro", NOTIFICATION_BACK_CALLBACK),
            ("Fatto", CHOOSE_TIME_CALLBACK),
        ],
    ]
    update.callback_query.edit_message_text(
        message, reply_markup=make_keyboard(buttons, context)
    )


def choose_time_wrapper(stamp_reminder_callback):
    @callback
    def choose_time(update: Update, context: CallbackContext):
        keyboard = make_keyboard(("Indietro", NOTIFICATION_BACK_CALLBACK), context)

        if update.callback_query:
            message = (
                "Inserisci l'orario in cui inviare la notifica, nel formato HH:MM 🕐"
            )
            update.callback_query.edit_message_text(text=message, reply_markup=keyboard)

            context.user_data[INPUT_KIND] = KIND_NOTIFICATION_TIME
            return

        input_time = update.message.text.strip()
        if re.match(r"^(0[0-9]|1[0-9]|2[0-3]):[0-5][0-9]$", input_time):
            context.user_data[TMP_NOTIFICATION][WHEN_TIME] = input_time

            user_id = update.effective_user.id
            schedule_data = context.user_data[TMP_NOTIFICATION]
            del context.user_data[TMP_NOTIFICATION]

            reminders = context.user_data.get(STAMP_REMINDERS) or []
            reminders.append(schedule_data)
            context.user_data[STAMP_REMINDERS] = reminders

            job = context.job_queue.run_daily(
                stamp_reminder_callback,
                time=job_time(schedule_data[WHEN_TIME]),
                days=schedule_data[WHEN_DAYS],
                context={
                    "bot": context.bot,
                    "user_id": user_id,
                    "user_data": context.user_data,
                    "schedule_data": schedule_data,
                },
            )

            logger.info(
                "Added reminder for user %s (%s): %s",
                user_id,
                update.effective_user.first_name,
                schedule_data,
            )
            notification_jobs[(user_id, notification_key(schedule_data))] = job

            message = "Notifica aggiunta! ✅"
            update.message.reply_text(text=message, reply_markup=keyboard)

            context.user_data[INPUT_KIND] = None
            return

        message = "L'orario deve essere nel formato HH:MM ⚠️"
        update.message.reply_text(text=message, reply_markup=keyboard)

    return choose_time


def setup_scheduler(updater: Updater, stamp_reminder_callback):
    for user_id, user_values in updater.dispatcher.user_data.items():
        if STAMP_REMINDERS in user_values:
            for schedule_data in user_values[STAMP_REMINDERS]:
                job = updater.job_queue.run_daily(
                    stamp_reminder_callback,
                    time=job_time(schedule_data[WHEN_TIME]),
                    days=schedule_data[WHEN_DAYS],
                    context={
                        "bot": updater.bot,
                        "user_id": user_id,
                        "user_data": user_values,
                        "schedule_data": schedule_data,
                    },
                )

                logger.info("Setup reminder for user %s: %s", user_id, schedule_data)

                notification_jobs[(user_id, notification_key(schedule_data))] = job


def handlers(stamp_reminder_callback):
    choose_time_handler = choose_time_wrapper(stamp_reminder_callback)

    return [
        CallbackQueryHandler(
            exit_callback, pattern=callback_pattern(NOTIFICATION_EXIT_CALLBACK)
        ),
        CallbackQueryHandler(
            back_callback, pattern=callback_pattern(NOTIFICATION_BACK_CALLBACK)
        ),
        CallbackQueryHandler(
            remove_callback, pattern=callback_pattern(NOTIFICATION_REMOVE_CALLBACK)
        ),
        CallbackQueryHandler(
            add_callback, pattern=callback_pattern(NOTIFICATION_ADD_CALLBACK)
        ),
        CallbackQueryHandler(
            choose_days,
            pattern=callback_pattern(
                f'({REMIND_ENTER_CALLBACK}|{REMIND_EXIT_CALLBACK}|{"|".join(DAYS_OF_WEEK.values())})'
            ),
        ),
        CallbackQueryHandler(
            choose_time_handler, pattern=callback_pattern(CHOOSE_TIME_CALLBACK)
        ),
    ]


def user_input_handlers(stamp_reminder_callback):
    choose_time_handler = choose_time_wrapper(stamp_reminder_callback)

    return [
        (KIND_NOTIFICATION_TIME, choose_time_handler),
        (KIND_NOTIFICATION_INDEX, remove_action),
    ]


def notification_key(notification: dict) -> Tuple:
    return (
        notification[STAMP_TYPE],
        ",".join([str(d) for d in notification[WHEN_DAYS]]),
        notification[WHEN_TIME],
    )


def job_time(time):
    return (
        datetime.strptime(time, "%H:%M")
        .replace(tzinfo=tz.tzlocal())
        .astimezone(tz.UTC)
        .time()
    )
