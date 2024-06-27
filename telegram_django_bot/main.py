import functools
import os
from queue import Queue

import django
from django.core.exceptions import ImproperlyConfigured
from telegram.ext import ExtBot, JobQueue, Updater
from telegram.utils.request import Request

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


@functools.cache
def get_dispatcher() -> RouteDispatcher:
	workers = 0 if settings.DEBUG else len(os.sched_getaffinity(0))
	con_pool_size = workers + 4
	request = Request(con_pool_size=con_pool_size)
	bot = ExtBot(settings.TELEGRAM_TOKEN, request=request)
	update_queue = Queue()
	job_queue = JobQueue()
	persistence = DatabasePersistence()
	dispatcher = RouteDispatcher(
		bot,
		update_queue,
		job_queue=job_queue,
		workers=workers,
		persistence=persistence,
		utrl_conf=settings.ROOT_UTRLCONF,
	)
	job_queue.set_dispatcher(dispatcher)
	return dispatcher


def main():
	dispatcher = get_dispatcher()
	updater = Updater(dispatcher=dispatcher)
	add_handlers(updater)
	updater.start_polling()
	updater.idle()


if __name__ == "__main__":
	try:
		main()
	except telegram.error.Unauthorized as e:
		raise ImproperlyConfigured("Invalid 'TELEGRAM_TOKEN' specified.") from e
