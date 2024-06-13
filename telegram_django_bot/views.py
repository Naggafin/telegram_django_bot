import telegram
from asgiref.sync import iscoroutinefunction, markcoroutinefunction
from django.conf import settings as django_settings
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone, translation
from django.utils.decorators import classonlymethod
from django.utils.functional import cached_property, classproperty

from . import exceptions
from .conf import settings
from .models import BotMenuElem, TeleDeepLink
from .utils import add_log_action, get_bot, get_user


class TelegramView:
	actions = {
		"cr": "create",
		"up": "update",
		"dl": "delete",
		"dt": "detail",
		"li": "list",
	}

	def __init__(self, **kwargs):
		"""
		Constructor. Called in the URLconf; can contain helpful extra
		keyword arguments, and other things.
		"""
		# Go through keyword arguments, and either save their values to our
		# instance, or raise an error.
		for key, value in kwargs.items():
			setattr(self, key, value)

	@classproperty
	def view_is_async(cls):
		handlers = [getattr(cls, method) for method in cls.actions]
		if not handlers:
			return False
		is_async = iscoroutinefunction(handlers[0])
		if not all(iscoroutinefunction(h) == is_async for h in handlers[1:]):
			raise ImproperlyConfigured(
				f"{cls.__qualname__} handlers must either be all sync or all async."
			)
		return is_async

	@classonlymethod
	def as_view(cls, actions: dict = None, **initkwargs):
		"""Main entry point for a request-response process."""
		## TODO: need these?
		# The name and description initkwargs may be explicitly overridden for
		# certain route configurations. eg, names of extra actions.
		cls.name = None
		cls.description = None

		# The suffix initkwarg is reserved for displaying the viewset type.
		# This initkwarg should have no effect if the name is provided.
		# eg. 'List' or 'Instance'.
		cls.suffix = None

		# The detail initkwarg is reserved for introspecting the viewset type.
		cls.detail = None

		# Setting a basename allows a view to reverse its action urls. This
		# value is provided by the router through the initkwargs.
		cls.basename = None
		##

		# actions must not be empty
		if not actions:
			raise TypeError(
				"The `actions` argument must be provided when "
				"calling `.as_view()` on a ViewSet. For example "
				"`.as_view({'detail': 'dt'})`"
			)

		for key in initkwargs:
			if key in cls.actions:
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

		def view(
			route: str,
			update: telegram.Update,
			context: telegram.ext.CallbackContext,
			*args,
			**kwargs,
		):
			self = cls(**initkwargs)
			self.setup(route, actions, update, context, *args, **kwargs)
			if not hasattr(self, "request"):
				raise AttributeError(
					"%s instance has no 'request' attribute. Did you override "
					"setup() and forget to call super()?" % cls.__name__
				)
			return self.dispatch(route, update, context, *args, **kwargs)

		view.view_class = cls
		view.view_initkwargs = initkwargs

		# __name__ and __qualname__ are intentionally left unchanged as
		# view_class should be used to robustly determine the name of the view
		# instead.
		view.__doc__ = cls.__doc__
		view.__module__ = cls.__module__
		view.__annotations__ = cls.dispatch.__annotations__
		# Copy possible attributes set by decorators, e.g. @csrf_exempt, from
		# the dispatch method.
		view.__dict__.update(cls.dispatch.__dict__)

		# Mark the callback if the view class is async.
		if cls.view_is_async:
			markcoroutinefunction(view)

		return view

	@cached_property
	def user(self):
		return get_user(self.update)

	@cached_property
	def bot(self):
		return get_bot(self.context)

	def get_action(self, route) -> str:
		return route.split("/")[0]

	def setup(
		self,
		route: str,
		actions: dict,
		update: telegram.Update,
		context: telegram.ext.CallbackContext,
		*args,
		**kwargs,
	):
		"""Initialize attributes shared by all view methods."""
		if update.effective_user is None:
			raise ValueError(f"Update has no effective user: {update}")
		self.action_map = actions
		for method, action in actions.items():
			handler = getattr(self, action)
			setattr(self, method, handler)
		self.action = self.get_action(route).lower()
		self.context = context
		self.update = update
		self.args = args
		self.kwargs = kwargs

		# activate translation
		if django_settings.USE_I18N:
			translation.activate(
				getattr(self.user, "language_code", None)
				or update.effective_user.language_code
			)

	def dispatch(
		self,
		route: str,
		update: telegram.Update,
		context: telegram.ext.CallbackContext,
		*args,
		**kwargs,
	):
		try:
			self.check_permissions(update)
			self.check_throttles(update)
			self.check_first_income(self.user, update)

			# Get the appropriate handler method
			if self.action in self.action_map:
				handler = getattr(self, self.action, self.handle_action_not_allowed)
			else:
				handler = self.handle_action_not_allowed

			response = handler(update, context, *args, **kwargs)

		except Exception as exc:
			response = self.handle_exception(exc)
		finally:
			if not self.user.is_anonymous:
				if self.user.telegram_account.is_blocked:
					self.user.telegram_account.is_blocked = False
				self.user.telegram_account.last_active = timezone.now()
				self.user.telegram_account.save()
				if settings.LOG_REQUESTS:
					log_value = self.__qualname__
					add_log_action(self.user.telegram_account.pk, log_value[:64])

		return response

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
				telelink, _ = TeleDeepLink.objects.get_or_create(link=query_words[1])
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

	def handle_action_not_allowed(self):
		raise exceptions.ActionNotAllowed


def all_command_bme_handler(
	route: str, update: telegram.Update, context: telegram.ext.CallbackContext
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
	route: str, update: telegram.Update, context: telegram.ext.CallbackContext
):
	menu_elem = BotMenuElem.objects.filter(
		callbacks_db__contains=update.callback_query.data, is_visable=True
	).first()
	user = get_user(update)
	bot = get_bot(context)
	return bot.send_botmenuelem(update, user, menu_elem)
