import logging

import telegram
from asgiref.sync import iscoroutinefunction, markcoroutinefunction
from django.conf import settings as django_settings
from django.core.exceptions import PermissionDenied
from django.db import connections
from django.http import Http404
from django.utils import timezone, translation
from django.utils.decorators import classonlymethod
from django.utils.functional import cached_property, classproperty
from django.views.generic.base import ContextMixin
from telegram.ext.commandhandler import CommandHandler
from telegram.ext.handler import Handler

from .. import exceptions
from ..conf import settings
from ..constants import ChatActions
from ..models import BotMenuElem, TelegramDeepLink
from ..utils import get_bot, get_user, log_response

logger = logging.getLogger(__name__)


def set_rollback():
	for db in connections.all():
		if db.settings_dict["ATOMIC_REQUESTS"] and db.in_atomic_block:
			db.set_rollback(True)


def exception_handler(exc, context):
	if isinstance(exc, Http404):
		exc = exceptions.NotFound(*(exc.args))
	elif isinstance(exc, PermissionDenied):
		exc = exceptions.PermissionDenied(*(exc.args))

	if isinstance(exc, exceptions.TelegramBotException):
		set_rollback()
		chat_reply_action = ChatActions.message
		chat_action_args = (str(exc), [])
		return (chat_reply_action, chat_action_args)

	return None


class TelegramView:
	handler_class = CommandHandler
	throttle_classes = settings.DEFAULT_THROTTLE_CLASSES
	permission_classes = settings.DEFAULT_PERMISSION_CLASSES

	def __init__(self, **kwargs):
		for key, value in kwargs.items():
			setattr(self, key, value)

	@classproperty
	def callback_is_async(cls):
		return iscoroutinefunction(cls.callback)

	@classonlymethod
	def as_handler(cls, handler_kwargs=None, **initkwargs):
		"""Main entry point for a request-response process."""
		handler_kwargs = handler_kwargs or {}

		for key in initkwargs:
			if key == "callback":
				raise TypeError(
					"The method name %s is not accepted as a keyword argument "
					"to %s()." % (key, cls.__name__)
				)
			if not hasattr(cls, key):
				raise TypeError(
					"%s() received an invalid keyword %r. as_view "
					"only accepts arguments that are already "
					"attributes of the class." % (cls.__name__, key)
				)

		def callback(
			update: telegram.Update,
			context: telegram.ext.CallbackContext,
			*args,
			**kwargs,
		):
			self = cls(**initkwargs)
			self.setup(update, context, *args, **kwargs)
			if not hasattr(self, "update"):
				raise AttributeError(
					"%s instance has no 'update' attribute. Did you override "
					"setup() and forget to call super()?" % cls.__name__
				)

			try:
				if django_settings.USE_I18N:
					language_code = update.effective_user.language_code or (
						self.user.telegram_account.language_code
						if not self.user.is_anonymous
						else None
					)
					if language_code not in [
						lang[0] for lang in django_settings.LANGUAGES
					]:
						logger.warning(
							f"{repr(self)}: language code doesn't match any code defined in settings, using default language"
						)
						language_code = django_settings.LANGUAGE_CODE
					with translation.override(language_code):
						chat_reply_action, chat_action_args = self.reply(
							update, context, *args, **kwargs
						)
				else:
					chat_reply_action, chat_action_args = self.reply(
						update, context, *args, **kwargs
					)

			except Exception as exc:
				chat_reply_action, chat_action_args = self.handle_exception(exc)

			finally:
				if not self.user.is_anonymous:
					if self.user.telegram_account.is_blocked_bot:
						self.user.telegram_account.is_blocked_bot = False
					self.user.telegram_account.language_code = (
						update.effective_user.language_code
					)
					self.user.telegram_account.last_active = timezone.now()
					self.user.telegram_account.save()
					if settings.LOG_REQUESTS:
						log_response(update)

			return self.send_answer(chat_reply_action, chat_action_args)

		callback.view_class = cls
		callback.view_initkwargs = initkwargs
		callback.handler_kwargs = handler_kwargs

		# __name__ and __qualname__ are intentionally left unchanged as
		# view_class should be used to robustly determine the name of the view
		# instead.
		callback.__doc__ = cls.__doc__
		callback.__module__ = cls.__module__
		callback.__annotations__ = cls.dispatch.__annotations__
		# Copy possible attributes set by decorators, e.g. @csrf_exempt, from
		# the dispatch method.
		callback.__dict__.update(cls.dispatch.__dict__)

		# Mark the callback if the view class is async.
		if cls.callback_is_async:
			markcoroutinefunction(callback)

		return self.get_handler(callback, **handler_kwargs)

	def get_handler_class(self) -> Handler:
		return self.handler_class

	def get_handler(self, callback, **handler_kwargs) -> Handler:
		return self.get_handler_class()(callback, **handler_kwargs)

	def reply(self, update, context, *args, **kwargs):
		raise NotImplementedError

	@cached_property
	def user(self):
		return get_user(self.update)

	@cached_property
	def bot(self):
		return get_bot(self.context)

	def setup(
		self,
		action: str,
		update: telegram.Update,
		context: telegram.ext.CallbackContext,
		*args,
		**kwargs,
	):
		if update.effective_user is None:
			raise ValueError(f"Update has no effective user: {update}")
		self.context = context
		self.update = update
		self.args = args
		self.kwargs = kwargs

	def send_answer(
		self, chat_reply_action, chat_action_args, *args, **kwargs
	) -> telegram.Message:
		if chat_reply_action != self.CHAT_ACTION_MESSAGE:
			raise ValueError(
				f"unknown chat_action {chat_reply_action} {self.utrl}, {self.user}"
			)
		return self.bot.edit_or_send(self.update, *chat_action_args)

	def permission_denied(self, user, message=None):
		"""If request is not permitted, determine what kind of exception to raise."""
		raise exceptions.PermissionDenied

	def throttled(self, user, wait):
		"""If request is throttled, determine what kind of exception to raise."""
		raise exceptions.Throttled(wait)

	def get_permissions(self):
		"""Instantiates and returns the list of permissions that this view requires."""
		return [permission() for permission in self.permission_classes]

	def get_throttles(self):
		"""Instantiates and returns the list of throttles that this view uses."""
		return [throttle() for throttle in self.throttle_classes]

	def get_exception_handler_context(self):
		"""
		Returns a dict that is passed through to EXCEPTION_HANDLER,
		as the `context` argument.
		"""
		return {
			"view": self,
			"args": getattr(self, "args", ()),
			"kwargs": getattr(self, "kwargs", {}),
			"context": getattr(self, "context", None),
			"update": getattr(self, "update", None),
			"user": getattr(self, "user", None),
			"bot": getattr(self, "bot", None),
		}

	def get_exception_handler(self):
		"""Returns the exception handler that this view uses."""
		return settings.EXCEPTION_HANDLER

	def check_permissions(self, update: telegram.Update):
		"""
		Check if the request should be permitted.
		Raises an appropriate exception if the request is not permitted.
		"""
		for permission in self.get_permissions():
			if not permission.has_permission(update, self):
				self.permission_denied(
					self.user, message=getattr(permission, "message", None)
				)

	def check_object_permissions(self, update: telegram.Update, obj):
		"""
		Check if the request should be permitted for a given object.
		Raises an appropriate exception if the request is not permitted.
		"""
		for permission in self.get_permissions():
			if not permission.has_object_permission(update, self, obj):
				self.permission_denied(
					self.user,
					message=getattr(permission, "message", None),
				)

	def check_throttles(self, update: telegram.Update):
		"""
		Check if request should be throttled.
		Raises an appropriate exception if the request is throttled.
		"""
		throttle_durations = []
		for throttle in self.get_throttles():
			if not throttle.allow_request(update, self):
				throttle_durations.append(throttle.wait())

		if throttle_durations:
			# Filter out `None` values which may happen in case of config / rate changes
			durations = [
				duration for duration in throttle_durations if duration is not None
			]

			duration = max(durations, default=None)
			self.throttled(self.user, duration)

	def check_first_income(self, user, update: telegram.Update):
		if update and update.message and update.message.text:
			query_words = update.message.text.split()
			if len(query_words) > 1 and query_words[0] == "/start":
				telelink, _ = TelegramDeepLink.objects.get_or_create(
					link=query_words[1]
				)
				telelink.telegram_accounts.add(user.telegram_account)

	def handle_exception(self, exc):
		"""
		Handle any exception that occurs, by returning an appropriate response,
		or re-raising the error.
		"""
		exception_handler = self.get_exception_handler()
		context = self.get_exception_handler_context()
		response = exception_handler(exc, context)

		if response is None:
			self.raise_uncaught_exception(exc)

		response.exception = True
		return response

	def raise_uncaught_exception(self, exc):
		raise exc


class TemplateResponseMixin:
	def render_response(self, context):
		template = self.render_template(context)
		return self.update.message.reply_text(template)

	def render_template(self, context) -> str:
		raise NotImplementedError


class TemplateView(TemplateResponseMixin, ContextMixin, TelegramView):
	def reply(self, update, context, *args, **kwargs):
		context = self.get_context_data(**kwargs)
		return self.render_response(context)


def all_command_bme_handler(
	utrl: str, update: telegram.Update, context: telegram.ext.CallbackContext
):
	if len(update.message.text[1:]) and "start" == update.message.text[1:].split()[0]:
		menu_elem = None
		if len(update.message.text[1:]) > 6:  # 'start ' + something
			menu_elem = BotMenuElem.objects.filter(
				command__contains=update.message.text[1:], is_visable=True
			).first()

		if menu_elem is None:
			menu_elem = BotMenuElem.objects.filter(
				command="start", is_visable=True
			).first()
	else:
		menu_elem = BotMenuElem.objects.filter(
			command=update.message.text[1:], is_visable=True
		).first()
	user = get_user(update)
	bot = get_bot(context)
	return bot.send_botmenuelem(update, user, menu_elem)


def all_callback_bme_handler(
	utrl: str, update: telegram.Update, context: telegram.ext.CallbackContext
):
	menu_elem = BotMenuElem.objects.filter(
		callbacks_db__contains=update.callback_query.data, is_visable=True
	).first()
	user = get_user(update)
	bot = get_bot(context)
	return bot.send_botmenuelem(update, user, menu_elem)
