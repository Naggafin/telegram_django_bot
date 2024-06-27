import itertools
from collections import namedtuple

from django.core.exceptions import ImproperlyConfigured

from .utrls import command

Route = namedtuple("Route", ["utrl", "mapping", "name", "detail", "initkwargs"])
DynamicRoute = namedtuple("DynamicRoute", ["utrl", "name", "detail", "initkwargs"])


def flatten(list_of_lists):
	return itertools.chain(*list_of_lists)


class BaseRouter:
	def __init__(self):
		self.registry = []

	def register(self, viewset, basename=None):
		if basename is None:
			basename = self.get_default_basename(viewset)

		if self.is_already_registered(basename):
			msg = (
				f'Router with basename "{basename}" is already registered. '
				f'Please provide a unique basename for viewset "{viewset}"'
			)
			raise ImproperlyConfigured(msg)

		self.registry.append((viewset, basename))

		# invalidate the utrls cache
		if hasattr(self, "_utrls"):
			del self._utrls

	def is_already_registered(self, new_basename):
		return any(
			basename == new_basename for _prefix, _viewset, basename in self.registry
		)

	def get_default_basename(self, viewset):
		raise NotImplementedError("get_default_basename must be overridden")

	def get_utrls(self):
		raise NotImplementedError("get_utrls must be overridden")

	@property
	def utrls(self):
		if not hasattr(self, "_utrls"):
			self._utrls = self.get_utrls()
		return self._utrls


class SimpleRouter(BaseRouter):
	routes = [
		# List route.
		Route(
			utrl=r"^/list$",
			mapping="list",
			name="{basename}-list",
			detail=False,
			initkwargs={"suffix": "List"},
		),
		Route(
			utrl=r"^/create$",
			mapping="create",
			name="{basename}-create",
			detail=False,
			initkwargs={"suffix": "Create"},
		),
		# Dynamically generated list routes. Generated using
		# @action(detail=False) decorator on methods of the viewset.
		DynamicRoute(
			utrl=r"^/{command}$",
			name="{basename}-{utrl_name}",
			detail=False,
			initkwargs={},
		),
		# Detail route.
		Route(
			utrl=r"^/retrieve$",
			mapping="retrieve",
			name="{basename}-retrieve",
			detail=True,
			initkwargs={"suffix": "Retrieve"},
		),
		Route(
			utrl=r"^/update$",
			mapping="update",
			name="{basename}-update",
			detail=True,
			initkwargs={"suffix": "Update"},
		),
		Route(
			utrl=r"^/delete$",
			mapping="delete",
			name="{basename}-delete",
			detail=True,
			initkwargs={"suffix": "Delete"},
		),
		# Dynamically generated detail routes. Generated using
		# @action(detail=True) decorator on methods of the viewset.
		DynamicRoute(
			utrl=r"^/{command}$",
			name="{basename}-{utrl_name}",
			detail=True,
			initkwargs={},
		),
	]

	def __init__(self):
		self._utrl_conf = command
		# remove regex characters from routes
		_routes = []
		for route in self.routes:
			utrl_param = route.utrl
			if utrl_param[0] == "^":
				utrl_param = utrl_param[1:]
			if utrl_param[-1] == "$":
				utrl_param = utrl_param[:-1]

			_routes.append(route._replace(utrl=utrl_param))
		self.routes = _routes
		super().__init__()

	def get_default_basename(self, viewset):
		queryset = getattr(viewset, "queryset", None)
		assert queryset is not None, (
			"`basename` argument not specified, and could "
			"not automatically determine the name from the viewset, as "
			"it does not have a `.queryset` attribute."
		)
		return queryset.model._meta.object_name.lower()

	def get_routes(self, viewset):
		known_actions = [
			route.mapping for route in self.routes if isinstance(route, Route)
		]
		extra_actions = viewset.get_extra_actions()

		# checking action names against the known actions list
		not_allowed = [
			action.__name__
			for action in extra_actions
			if action.__name__ in known_actions
		]
		if not_allowed:
			msg = (
				"Cannot use the @action decorator on the following "
				"actions, as they are existing routes: %s"
			)
			raise ImproperlyConfigured(msg % ", ".join(not_allowed))

		# partition detail and list actions
		detail_actions = [action for action in extra_actions if action.detail]
		list_actions = [action for action in extra_actions if not action.detail]

		routes = []
		for route in self.routes:
			if isinstance(route, DynamicRoute) and route.detail:
				routes += list(
					flatten(
						[
							self._get_dynamic_routes(route, action)
							for action in detail_actions
						]
					)
				)
			elif isinstance(route, DynamicRoute) and not route.detail:
				routes += list(
					flatten(
						[
							self._get_dynamic_routes(route, action)
							for action in list_actions
						]
					)
				)
			else:
				routes.append(route)
		return routes

	def _get_dynamic_routes(self, route, action) -> list:
		initkwargs = route.initkwargs.copy()
		initkwargs.update(action.kwargs)
		routes = []
		for command in action.mapping:
			routes.append(
				Route(
					utrl=route.utrl.replace("{command}", command),
					mapping=action.__name__,
					name=route.name.replace("{utrl_name}", action.utrl_name),
					detail=route.detail,
					initkwargs=initkwargs,
				)
			)
		return routes

	def get_utrls(self):
		ret = []
		for viewset, basename in self.registry:
			routes = self.get_routes(viewset)
			for route in routes:
				if not hasattr(viewset, route.mapping):
					continue

				initkwargs = route.initkwargs.copy()
				initkwargs.update({"basename": basename, "detail": route.detail})

				view = viewset.as_view(route.mapping, **initkwargs)
				name = route.name.format(basename=basename)
				ret.append(self._utrl_conf(route.utrl, view, name=name))

		return ret
