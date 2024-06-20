import os

import django
from django.core.exceptions import ImproperlyConfigured
from telegram.ext import Updater

try:
	os.environ["DJANGO_SETTINGS_MODULE"]
except KeyError as e:
	raise ImproperlyConfigured(
		"You must set the 'DJANGO_SETTINGS_MODULE' environment variable "
		"before you can launch the Telegram bot receiver."
	) from e

django.setup()

from telegram_django_bot.conf import settings
from telegram_django_bot.ext.databasepersistence import DatabasePersistence
from telegram_django_bot.routing import RouterCallbackMessageCommandHandler
from telegram_django_bot.tg_dj_bot import TG_DJ_Bot


def add_handlers(updater):
	dp = updater.dispatcher
	dp.add_handler(RouterCallbackMessageCommandHandler())


def main():
	n_workers = 0 if settings.DEBUG else len(os.sched_getaffinity(0))
	updater = Updater(
		bot=TG_DJ_Bot(settings.TELEGRAM_TOKEN),
		workers=n_workers,
		persistence=DatabasePersistence(),
	)
	add_handlers(updater)
	updater.start_polling()
	updater.idle()


if __name__ == "__main__":
	try:
		main()
	except telegram.error.Unauthorized as e:
		raise ImproperlyConfigured("Invalid 'TELEGRAM_TOKEN' specified.") from e
