import logging

from asgiref.sync import iscoroutinefunction, markcoroutinefunction
import telegram
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.http import (
	HttpResponse,
	HttpResponseGone,
	HttpResponseNotAllowed,
	HttpResponsePermanentRedirect,
	HttpResponseRedirect,
)
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.decorators import classonlymethod
from django.utils.functional import classproperty
from .exceptions import Throttled


class TelegramView:
	actions = {
		"create": "cr",
		"change": 'ch',
		"delete": 'dl',
		"detail": 'dt',
		"list": 'li',
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
		handlers = [
			getattr(cls, method)
			for method in cls.actions
		]
		if not handlers:
			return False
		is_async = iscoroutinefunction(handlers[0])
		if not all(iscoroutinefunction(h) == is_async for h in handlers[1:]):
			raise ImproperlyConfigured(
				f"{cls.__qualname__} handlers must either be all sync or all async."
			)
		return is_async

	@classonlymethod
	def as_view(cls, actions: dict=None, **initkwargs):
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
			raise TypeError("The `actions` argument must be provided when "
							"calling `.as_view()` on a ViewSet. For example "
							"`.as_view({'detail': 'dt'})`")
		
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

		def view(bot: telegram.Bot, update: telegram.Update, user: AbstractUser, *args, **kwargs):
			self = cls(**initkwargs)
			self.setup(bot, update, user, actions, *args, **kwargs)
			if not hasattr(self, "request"):
				raise AttributeError(
					"%s instance has no 'request' attribute. Did you override "
					"setup() and forget to call super()?" % cls.__name__
				)
			return self.dispatch(bot, update, user, *args, **kwargs)

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

	def setup(self, bot: telegram.Bot, update: telegram.Update, user: AbstractUser, actions: dict, *args, **kwargs):
		"""Initialize attributes shared by all view methods."""
		self.action_map = actions
		for method, action in actions.items():
			handler = getattr(self, action)
			setattr(self, method, handler)
		self.bot = bot
		self.update = update
		self.user = user
		self.args = args
		self.kwargs = kwargs

	def dispatch(self, bot: telegram.Bot, update: telegram.Update, user: AbstractUser, *args, **kwargs):
		# Try to dispatch to the right method; if a method doesn't exist,
		# defer to the error handler. Also defer to the error handler if the
		# request method isn't on the approved list.
		if request.method.lower() in self.http_method_names:
			handler = getattr(
				self, request.method.lower(), self.http_method_not_allowed
			)
		else:
			handler = self.http_method_not_allowed
		return handler(request, *args, **kwargs)

	def permission_denied(self, request, message=None, code=None):
		"""
		If request is not permitted, determine what kind of exception to raise.
		"""
		raise PermissionDenied

	def throttled(self, request, wait):
		"""
		If request is throttled, determine what kind of exception to raise.
		"""
		raise Throttled(wait)

	def get_permissions(self):
		"""
		Instantiates and returns the list of permissions that this view requires.
		"""
		return [permission() for permission in self.permission_classes]

	def get_throttles(self):
		"""
		Instantiates and returns the list of throttles that this view uses.
		"""
		return [throttle() for throttle in self.throttle_classes]

	def get_exception_handler_context(self):
		"""
		Returns a dict that is passed through to EXCEPTION_HANDLER,
		as the `context` argument.
		"""
		return {
			'view': self,
			'args': getattr(self, 'args', ()),
			'kwargs': getattr(self, 'kwargs', {}),
			'bot': getattr(self, 'bot', None),
			'update': getattr(self, 'update', None),
			'user': getattr(self, 'user', None),
		}

	def get_exception_handler(self):
		"""
		Returns the exception handler that this view uses.
		"""
		return self.settings.EXCEPTION_HANDLER

	def check_permissions(self, request):
		"""
		Check if the request should be permitted.
		Raises an appropriate exception if the request is not permitted.
		"""
		for permission in self.get_permissions():
			if not permission.has_permission(user, self):
				self.permission_denied(
					request,
					message=getattr(permission, 'message', None),
					code=getattr(permission, 'code', None)
				)

	def check_object_permissions(self, request, obj):
		"""
		Check if the request should be permitted for a given object.
		Raises an appropriate exception if the request is not permitted.
		"""
		for permission in self.get_permissions():
			if not permission.has_object_permission(request, self, obj):
				self.permission_denied(
					request,
					message=getattr(permission, 'message', None),
					code=getattr(permission, 'code', None)
				)

	def check_throttles(self, request):
		"""
		Check if request should be throttled.
		Raises an appropriate exception if the request is throttled.
		"""
		throttle_durations = []
		for throttle in self.get_throttles():
			if not throttle.allow_request(request, self):
				throttle_durations.append(throttle.wait())

		if throttle_durations:
			# Filter out `None` values which may happen in case of config / rate
			# changes, see #1438
			durations = [
				duration for duration in throttle_durations
				if duration is not None
			]

			duration = max(durations, default=None)
			self.throttled(request, duration)

	def determine_version(self, request, *args, **kwargs):
		"""
		If versioning is being used, then determine any API version for the
		incoming request. Returns a two-tuple of (version, versioning_scheme)
		"""
		if self.versioning_class is None:
			return (None, None)
		scheme = self.versioning_class()
		return (scheme.determine_version(request, *args, **kwargs), scheme)

	# Dispatch methods

	def initialize_request(self, request, *args, **kwargs):
		"""
		Returns the initial request object.
		"""
		parser_context = self.get_parser_context(request)

		return Request(
			request,
			parsers=self.get_parsers(),
			authenticators=self.get_authenticators(),
			negotiator=self.get_content_negotiator(),
			parser_context=parser_context
		)

	def initial(self, request, *args, **kwargs):
		"""
		Runs anything that needs to occur prior to calling the method handler.
		"""
		self.format_kwarg = self.get_format_suffix(**kwargs)

		# Perform content negotiation and store the accepted info on the request
		neg = self.perform_content_negotiation(request)
		request.accepted_renderer, request.accepted_media_type = neg

		# Determine the API version, if versioning is in use.
		version, scheme = self.determine_version(request, *args, **kwargs)
		request.version, request.versioning_scheme = version, scheme

		# Ensure that the incoming request is permitted
		self.perform_authentication(request)
		self.check_permissions(request)
		self.check_throttles(request)

	def finalize_response(self, request, response, *args, **kwargs):
		"""
		Returns the final response object.
		"""
		# Make the error obvious if a proper response is not returned
		assert isinstance(response, HttpResponseBase), (
			'Expected a `Response`, `HttpResponse` or `HttpStreamingResponse` '
			'to be returned from the view, but received a `%s`'
			% type(response)
		)

		if isinstance(response, Response):
			if not getattr(request, 'accepted_renderer', None):
				neg = self.perform_content_negotiation(request, force=True)
				request.accepted_renderer, request.accepted_media_type = neg

			response.accepted_renderer = request.accepted_renderer
			response.accepted_media_type = request.accepted_media_type
			response.renderer_context = self.get_renderer_context()

		# Add new vary headers to the response instead of overwriting.
		vary_headers = self.headers.pop('Vary', None)
		if vary_headers is not None:
			patch_vary_headers(response, cc_delim_re.split(vary_headers))

		for key, value in self.headers.items():
			response[key] = value

		return response

	def handle_exception(self, exc):
		"""
		Handle any exception that occurs, by returning an appropriate response,
		or re-raising the error.
		"""
		if isinstance(exc, (exceptions.NotAuthenticated,
							exceptions.AuthenticationFailed)):
			# WWW-Authenticate header for 401 responses, else coerce to 403
			auth_header = self.get_authenticate_header(self.request)

			if auth_header:
				exc.auth_header = auth_header
			else:
				exc.status_code = status.HTTP_403_FORBIDDEN

		exception_handler = self.get_exception_handler()

		context = self.get_exception_handler_context()
		response = exception_handler(exc, context)

		if response is None:
			self.raise_uncaught_exception(exc)

		response.exception = True
		return response

	def raise_uncaught_exception(self, exc):
		if settings.DEBUG:
			request = self.request
			renderer_format = getattr(request.accepted_renderer, 'format')
			use_plaintext_traceback = renderer_format not in ('html', 'api', 'admin')
			request.force_plaintext_errors(use_plaintext_traceback)
		raise exc

	# Note: Views are made CSRF exempt from within `as_view` as to prevent
	# accidental removal of this exemption in cases where `dispatch` needs to
	# be overridden.
	def dispatch(self, request, *args, **kwargs):
		"""
		`.dispatch()` is pretty much the same as Django's regular dispatch,
		but with extra hooks for startup, finalize, and exception handling.
		"""
		self.args = args
		self.kwargs = kwargs
		request = self.initialize_request(request, *args, **kwargs)
		self.request = request
		self.headers = self.default_response_headers  # deprecate?

		try:
			self.initial(request, *args, **kwargs)

			# Get the appropriate handler method
			if request.method.lower() in self.http_method_names:
				handler = getattr(self, request.method.lower(),
								  self.http_method_not_allowed)
			else:
				handler = self.http_method_not_allowed

			response = handler(request, *args, **kwargs)

		except Exception as exc:
			response = self.handle_exception(exc)

		self.response = self.finalize_response(request, response, *args, **kwargs)
		return self.response

	def options(self, request, *args, **kwargs):
		"""
		Handler method for HTTP 'OPTIONS' request.
		"""
		if self.metadata_class is None:
			return self.http_method_not_allowed(request, *args, **kwargs)
		data = self.metadata_class().determine_metadata(request, self)
		return Response(data, status=status.HTTP_200_OK)
