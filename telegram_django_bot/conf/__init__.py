from django.conf import settings as django_settings

# Import from `django.core.signals` instead of the official location
# `django.test.signals` to avoid importing the test module unnecessarily.
from django.core.signals import setting_changed
from django.utils.module_loading import import_string

DEFAULTS = {
	"TELEGRAM_TOKEN": None,
	"ROOT_UTRLCONF": None,
	"LOG_REQUESTS": True,
	# Base API policies
	"DEFAULT_PERMISSION_CLASSES": ["telegram_django_bot.permissions.AllowAny"],
	"DEFAULT_THROTTLE_CLASSES": [],
	# Generic view behavior
	"DEFAULT_PAGINATION_CLASS": None,
	"DEFAULT_FILTER_BACKENDS": [],
	# Throttling
	"DEFAULT_THROTTLE_RATES": {
		"user": None,
		"anon": None,
	},
	"NUM_PROXIES": None,
	# Filtering
	"SEARCH_PARAM": "search",
	"ORDERING_PARAM": "ordering",
	# View configuration
	"VIEW_NAME_FUNCTION": "rest_framework.views.get_view_name",
	"VIEW_DESCRIPTION_FUNCTION": "rest_framework.views.get_view_description",
	# Exception handling
	"EXCEPTION_HANDLER": "telegram_django_bot.views.exception_handler",
	"NON_FIELD_ERRORS_KEY": "non_field_errors",
}


# List of settings that may be in string import notation.
IMPORT_STRINGS = [
	"DEFAULT_PERMISSION_CLASSES",
	"DEFAULT_THROTTLE_CLASSES",
	"DEFAULT_PAGINATION_CLASS",
	"DEFAULT_FILTER_BACKENDS",
	"EXCEPTION_HANDLER",
	"VIEW_NAME_FUNCTION",
	"VIEW_DESCRIPTION_FUNCTION",
]


# List of settings that have been removed
REMOVED_SETTINGS = []


def perform_import(val, setting_name):
	"""
	If the given setting is a string import notation,
	then perform the necessary import or imports.
	"""
	if val is None:
		return None
	elif isinstance(val, str):
		return import_from_string(val, setting_name)
	elif isinstance(val, (list, tuple)):
		return [import_from_string(item, setting_name) for item in val]
	return val


def import_from_string(val, setting_name):
	"""Attempt to import a class from a string representation."""
	try:
		return import_string(val)
	except ImportError as e:
		msg = "Could not import '%s' for Telegram setting '%s'. %s: %s." % (
			val,
			setting_name,
			e.__class__.__name__,
			e,
		)
		raise ImportError(msg) from e


class TelegramBotSettings:
	def __init__(self, user_settings=None, defaults=None, import_strings=None):
		if user_settings:
			self._user_settings = self.__check_user_settings(user_settings)
		self.defaults = defaults or DEFAULTS
		self.import_strings = import_strings or IMPORT_STRINGS
		self._cached_attrs = set()

	@property
	def user_settings(self):
		if not hasattr(self, "_user_settings"):
			self._user_settings = getattr(django_settings, "TELEGRAM_BOT", {})
		return self._user_settings

	def __getattr__(self, attr):
		if attr not in self.defaults:
			raise AttributeError("Invalid Telegram setting: '%s'" % attr)

		try:
			# Check if present in user settings
			val = self.user_settings[attr]
		except KeyError:
			# Fall back to defaults
			val = self.defaults[attr]

		# Coerce import strings into classes
		if attr in self.import_strings:
			val = perform_import(val, attr)

		# Cache the result
		self._cached_attrs.add(attr)
		setattr(self, attr, val)
		return val

	def __check_user_settings(self, user_settings):
		SETTINGS_DOC = ""  # TODO
		for setting in REMOVED_SETTINGS:
			if setting in user_settings:
				raise RuntimeError(
					"The '%s' setting has been removed. Please refer to '%s' for available settings."
					% (setting, SETTINGS_DOC)
				)
		return user_settings

	def reload(self):
		for attr in self._cached_attrs:
			delattr(self, attr)
		self._cached_attrs.clear()
		if hasattr(self, "_user_settings"):
			delattr(self, "_user_settings")


settings = TelegramBotSettings(None, DEFAULTS, IMPORT_STRINGS)


def reload_telegram_bot_settings(*args, **kwargs):
	setting = kwargs["setting"]
	if setting == "TELEGRAM_BOT":
		settings.reload()


setting_changed.connect(reload_telegram_bot_settings)
