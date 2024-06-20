"""Functions for use in URLsconfs."""

from functools import partial
from importlib import import_module

from django.core.exceptions import ImproperlyConfigured

from .resolvers import CommandPattern, TelegramPattern, TelegramResolver


def include(arg, namespace=None):
	app_name = None
	if isinstance(arg, tuple):
		# Callable returning a namespace hint.
		try:
			utrlconf_module, app_name = arg
		except ValueError as e:
			if namespace:
				raise ImproperlyConfigured(
					"Cannot override the namespace for a dynamic module that "
					"provides a namespace."
				) from e
			raise ImproperlyConfigured(
				"Passing a %d-tuple to include() is not supported. Pass a "
				"2-tuple containing the list of patterns and app_name, and "
				"provide the namespace argument to include() instead." % len(arg)
			) from e
	else:
		# No namespace hint - use manually provided namespace.
		utrlconf_module = arg

	if isinstance(utrlconf_module, str):
		utrlconf_module = import_module(utrlconf_module)
	patterns = getattr(utrlconf_module, "utrlpatterns", utrlconf_module)
	app_name = getattr(utrlconf_module, "app_name", app_name)
	if namespace and not app_name:
		raise ImproperlyConfigured(
			"Specifying a namespace in include() without providing an app_name "
			"is not supported. Set the app_name attribute in the included "
			"module, or pass a 2-tuple containing the list of patterns and "
			"app_name instead.",
		)
	namespace = namespace or app_name
	# Make sure the patterns can be iterated through (without this, some
	# testcases will break).
	if isinstance(patterns, (list, tuple)):
		for url_pattern in patterns:
			getattr(url_pattern, "pattern", None)
	return (utrlconf_module, app_name, namespace)


def _command(route, view, kwargs=None, name=None, Pattern=None):
	from django.views import View

	from ..views import TelegramView

	if kwargs is not None and not isinstance(kwargs, dict):
		raise TypeError(
			f"kwargs argument must be a dict, but got {kwargs.__class__.__name__}."
		)
	if isinstance(view, (list, tuple)):
		# For include(...) processing.
		pattern = Pattern(route, is_endpoint=False)
		utrlconf_module, app_name, namespace = view
		return TelegramResolver(
			pattern,
			utrlconf_module,
			kwargs,
			app_name=app_name,
			namespace=namespace,
		)
	elif callable(view):
		pattern = Pattern(route, name=name, is_endpoint=True)
		return TelegramPattern(pattern, view, kwargs, name)
	elif isinstance(view, View):
		view_cls_name = view.__class__.__name__
		raise TypeError(
			f"view must be a callable, pass {view_cls_name}.as_view(), not "
			f"{view_cls_name}()."
		)
	elif not isinstance(view, TelegramView):
		view_cls_name = view.__class__.__name__
		raise TypeError(
			f"view class must be a subclass of {TelegramView.__name__}, not "
			f"{view_cls_name}."
		)
	else:
		raise TypeError(
			"view must be a callable or a list/tuple in the case of include()."
		)


command = partial(_command, Pattern=CommandPattern)
# re_command = partial(_command, Pattern=RegexPattern)  # TODO
