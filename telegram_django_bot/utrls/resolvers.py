import functools
import inspect
import re

from django.core.checks import Error, Warning
from django.core.exceptions import ViewDoesNotExist
from django.urls import URLPattern, URLResolver
from django.urls.resolvers import CheckURLMixin, LocaleRegexDescriptor
from django.utils.functional import cached_property

from ..conf import settings


def get_resolver(utrlconf=None):
	if utrlconf is None:
		utrlconf = settings.ROOT_UTRLCONF
	return _get_cached_resolver(utrlconf)


@functools.cache
def _get_cached_resolver(utrlconf=None):
	return TelegramResolver(CommandPattern("/start"), utrlconf)


class CheckCommandMixin(CheckURLMixin):
	def _check_pattern_startswith_slash(self):
		regex_pattern = self.regex.pattern
		if not regex_pattern.startswith(("/", "^/", "^\\/")):
			warning = Warning(
				f"Your command {self.describe()} does not begin with a slash."
			)
			return [warning]
		else:
			return []


class CommandPattern(CheckCommandMixin):
	regex = LocaleRegexDescriptor("_regex")

	def __init__(self, command, name=None, is_endpoint=False):
		self._command = command
		self._regex_dict = {}
		self._is_endpoint = is_endpoint
		self.name = name
		self.converters = {}

	def match(self, command: str):
		if not command:
			return None
		args = ""
		if "@" in command:
			command, args = command.split("@")
		if command != self._command:
			return None
		args = set(args.split())
		kwargs = {}
		for arg in args:
			if "=" in arg:
				try:
					key, value = arg.split("=")
				except ValueError:
					pass
				else:
					kwargs[key] = value
		# now remove all caught kwargs from args to reduce redundancy
		for kwarg in kwargs:
			args.discard(kwarg)
		return command, args, kwargs

	def check(self):
		return self._check_pattern_startswith_slash()

	def describe(self):
		return "'{}'".format(self)

	def _compile(self, command):
		return re.compile(command)

	def __str__(self):
		return self._command


class TelegramPattern(URLPattern):
	def _check_callback(self):
		from ..views import TelegramView

		errors = []
		view = self.callback
		if inspect.isclass(view):
			if not issubclass(view, TelegramView):
				errors.append(
					Error(
						"Your UTRL pattern %s has an invalid view. Ensure the view "
						"is a subclass of %s instead of %s."
						% (
							self.pattern.describe(),
							TelegramView.__name__,
							view.__name__,
						),
						id="urls.E009",
					)
				)
			errors.append(
				Error(
					"Your UTRL pattern %s has an invalid view, pass %s.as_view() "
					"instead of %s."
					% (
						self.pattern.describe(),
						view.__name__,
						view.__name__,
					),
					id="urls.E009",
				)
			)

		return errors


class TelegramResolver(URLResolver):
	def _check_custom_error_handlers(self):
		messages = []
		# All handlers take (update, context, exception) arguments except handler500
		# which takes (update, context).
		for status_code, num_parameters in [(400, 3), (403, 3), (404, 3), (500, 2)]:
			try:
				handler = self.resolve_error_handler(status_code)
			except (ImportError, ViewDoesNotExist) as e:
				path = getattr(self.utrlconf_module, "handler%s" % status_code)
				msg = (
					"The custom handler{status_code} view '{path}' could not be "
					"imported."
				).format(status_code=status_code, path=path)
				messages.append(Error(msg, hint=str(e), id="urls.E008"))
				continue
			signature = inspect.signature(handler)
			args = [None] * num_parameters
			try:
				signature.bind(*args)
			except TypeError:
				msg = (
					"The custom handler{status_code} view '{path}' does not "
					"take the correct number of arguments ({args})."
				).format(
					status_code=status_code,
					path=handler.__module__ + "." + handler.__qualname__,
					args="update, context, exception"
					if num_parameters == 2
					else "update, context",
				)
				messages.append(Error(msg, id="urls.E007"))
		return messages

	@cached_property
	def url_patterns(self):
		# urlconf_module might be a valid set of patterns, so we default to it
		patterns = getattr(self.urlconf_module, "utrlpatterns", self.urlconf_module)
		try:
			iter(patterns)
		except TypeError as e:
			msg = (
				"The included UTRLconf '{name}' does not appear to have "
				"any patterns in it. If you see the 'utrlpatterns' variable "
				"with valid patterns in the file then the issue is probably "
				"caused by a circular import."
			)
			raise ImproperlyConfigured(msg.format(name=self.urlconf_name)) from e
		return patterns
