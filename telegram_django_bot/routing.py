import logging

import telegram
from django.urls import Resolver404, resolve, reverse

from .conf import settings
from .models import TelegramAccount
from .views import all_callback_bme_handler, all_command_bme_handler

try:
	# version 20.x +
	from telegram.ext import BaseHandler as Handler
except ImportError:
	# old version
	from telegram.ext import Handler


def telegram_resolve(path, utrl_conf=None):
	if path[0] != "/":
		path = f"/{path}"

	if "?" in path:
		path = path.split("?")[0]

	if utrl_conf is None:
		utrl_conf = settings.ROOT_UTRLCONF

	try:
		resolver_match = resolve(path, utrl_conf)
	except Resolver404:
		resolver_match = None
	return resolver_match


def telegram_reverse(
	viewname, utrl_conf=None, args=None, kwargs=None, current_app=None
):
	if utrl_conf is None:
		utrl_conf = settings.ROOT_UTRLCONF

	response = reverse(viewname, utrl_conf, args, kwargs, current_app)
	if response[0] == "/":
		response = response[1:]
	return response


class RouterCallbackMessageCommandHandler(Handler):
	def __init__(self, utrl_conf=None, only_utrl=False, **kwargs):
		kwargs["callback"] = lambda x: "for base class"
		super().__init__(**kwargs)
		self.callback = None
		self.utrl_conf = utrl_conf
		self.only_utrl = only_utrl  # without BME elems

	def resolve(self, update: telegram.Update):
		resolver_match = None
		# check if utrls
		if update.callback_query:
			resolver_match = telegram_resolve(
				update.callback_query.data, self.utrl_conf
			)
		elif (
			update.message and update.message.text and update.message.text[0] == "/"
		):  # is it ok? seems message couldnt be an url
			resolver_match = telegram_resolve(update.message.text, self.utrl_conf)

		if resolver_match is None:
			# update.message -- could be data or info for managing, command could not be a data, it is managing info
			if update.message and (
				update.message.text is None or update.message.text[0] != "/"
			):
				user_details = update.effective_user

				tg_user = (
					TelegramAccount.objects.filter(telegram_id=user_details.id)
					.only("current_utrl")
					.first()
				)
				if tg_user is not None:
					logging.info(f"tg_user.current_utrl {tg_user.current_utrl}")
					if tg_user.current_utrl:
						resolver_match = telegram_resolve(
							tg_user.current_utrl, self.utrl_conf
						)
		return resolver_match

	def check_update(self, update: object):
		"""
		Check if callback or message (command actually is message).

		:param update:
		:return:
		"""
		if isinstance(update, telegram.Update) and (
			update.effective_message or update.callback_query
		):
			resolver_match = self.resolve(update)
			if resolver_match:
				return True
			elif not self.only_utrl:
				if (
					update.message
					and update.message.text
					and update.message.text[0] == "/"
				):
					# if it is a command then it should be early in handlers
					# or in BME (then return True)
					return True
				elif update.callback_query:
					return True
		return None

	def handle_update(
		self,
		update: telegram.Update,
		dispatcher: telegram.ext.Dispatcher,
		check_result: object,
		context: telegram.ext.CallbackContext = None,
	):
		# todo: add flush utrl and data if viewset utrl change or error

		resolver_match = self.resolve(update)

		if resolver_match is not None:
			route = resolver_match.route.replace("^", "").replace("$", "")
			callback_func, args, kwargs = resolver_match

		# check if in BME (we do not need check only_utrl here, as there was a check in self.check_update)
		else:
			route = ""
			if update.callback_query:
				callback_func, args, kwargs = (all_callback_bme_handler, [], {})
			else:
				callback_func, args, kwargs = (all_command_bme_handler, [], {})

		self.collect_additional_context(context, update, dispatcher, check_result)

		# TODO: execute any middlewares

		return callback_func(route, update, context, *args, **kwargs)
