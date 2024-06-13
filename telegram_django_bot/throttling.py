"""Provides various throttling policies."""
import time

import telegram
from django.core.cache import cache as default_cache
from django.core.exceptions import ImproperlyConfigured

from .conf import settings
from .views import TelegramView


class BaseThrottle:
	"""Rate throttling of requests."""

	def allow_request(self, update: telegram.Update, view: TelegramView):
		"""Return `True` if the request should be allowed, `False` otherwise."""
		raise NotImplementedError(".allow_request() must be overridden")

	def get_ident(self, update):
		return update.effective_user.id

	def wait(self):
		"""
		Optionally, return a recommended number of seconds to wait before
		the next request.
		"""
		return None


class SimpleRateThrottle(BaseThrottle):
	"""
	A simple cache implementation, that only requires `.get_cache_key()`
	to be overridden.

	The rate (requests / seconds) is set by a `rate` attribute on the Throttle
	class.  The attribute is a string of the form 'number_of_requests/period'.

	Period should be one of: ('s', 'sec', 'm', 'min', 'h', 'hour', 'd', 'day')

	Previous request information used for throttling is stored in the cache.
	"""

	cache = default_cache
	timer = time.time
	cache_format = "throttle_%(scope)s_%(ident)s"
	scope = None
	THROTTLE_RATES = settings.DEFAULT_THROTTLE_RATES

	def __init__(self):
		if not getattr(self, "rate", None):
			self.rate = self.get_rate()
		self.num_requests, self.duration = self.parse_rate(self.rate)

	def get_cache_key(self, update: telegram.Update, view: TelegramView):
		"""
		Should return a unique cache-key which can be used for throttling.
		Must be overridden.

		May return `None` if the request should not be throttled.
		"""
		raise NotImplementedError(".get_cache_key() must be overridden")

	def get_rate(self):
		"""Determine the string representation of the allowed request rate."""
		if not getattr(self, "scope", None):
			msg = (
				"You must set either `.scope` or `.rate` for '%s' throttle"
				% self.__class__.__name__
			)
			raise ImproperlyConfigured(msg)

		try:
			return self.THROTTLE_RATES[self.scope]
		except KeyError as e:
			msg = "No default throttle rate set for '%s' scope" % self.scope
			raise ImproperlyConfigured(msg) from e

	def parse_rate(self, rate):
		"""
		Given the request rate string, return a two tuple of:
		<allowed number of requests>, <period of time in seconds>
		"""
		if rate is None:
			return (None, None)
		num, period = rate.split("/")
		num_requests = int(num)
		duration = {"s": 1, "m": 60, "h": 3600, "d": 86400}[period[0]]
		return (num_requests, duration)

	def allow_request(self, update: telegram.Update, view: TelegramView):
		"""
		Implement the check to see if the request should be throttled.

		On success calls `throttle_success`.
		On failure calls `throttle_failure`.
		"""
		if self.rate is None:
			return True

		self.key = self.get_cache_key(update, view)
		if self.key is None:
			return True

		self.history = self.cache.get(self.key, [])
		self.now = self.timer()

		# Drop any requests from the history which have now passed the
		# throttle duration
		while self.history and self.history[-1] <= self.now - self.duration:
			self.history.pop()
		if len(self.history) >= self.num_requests:
			return self.throttle_failure()
		return self.throttle_success()

	def throttle_success(self):
		"""
		Inserts the current request's timestamp along with the key
		into the cache.
		"""
		self.history.insert(0, self.now)
		self.cache.set(self.key, self.history, self.duration)
		return True

	def throttle_failure(self):
		"""Called when a request to the API has failed due to throttling."""
		return False

	def wait(self):
		"""Returns the recommended next request time in seconds."""
		if self.history:
			remaining_duration = self.duration - (self.now - self.history[-1])
		else:
			remaining_duration = self.duration

		available_requests = self.num_requests - len(self.history) + 1
		if available_requests <= 0:
			return None

		return remaining_duration / float(available_requests)


class AnonRateThrottle(SimpleRateThrottle):
	"""
	Limits the rate of API calls that may be made by a anonymous users.

	The IP address of the request will be used as the unique cache key.
	"""

	scope = "anon"

	def get_cache_key(self, update: telegram.Update, view: TelegramView):
		if view.user and view.user.is_authenticated:
			return None  # Only throttle unauthenticated requests.

		return self.cache_format % {
			"scope": self.scope,
			"ident": self.get_ident(update),
		}


class UserRateThrottle(SimpleRateThrottle):
	"""
	Limits the rate of API calls that may be made by a given user.

	The user id will be used as a unique cache key if the user is
	authenticated.  For anonymous requests, the IP address of the request will
	be used.
	"""

	scope = "user"

	def get_cache_key(self, update: telegram.Update, view: TelegramView):
		return self.cache_format % {
			"scope": self.scope,
			"ident": self.get_ident(update),
		}


class ScopedRateThrottle(SimpleRateThrottle):
	"""
	Limits the rate of API calls by different amounts for various parts of
	the API.  Any view that has the `throttle_scope` property set will be
	throttled.  The unique cache key will be generated by concatenating the
	user id of the request, and the scope of the view being accessed.
	"""

	scope_attr = "throttle_scope"

	def __init__(self):
		# Override the usual SimpleRateThrottle, because we can't determine
		# the rate until called by the view.
		pass

	def allow_request(self, update: telegram.Update, view: TelegramView):
		# We can only determine the scope once we're called by the view.
		self.scope = getattr(view, self.scope_attr, None)

		# If a view does not have a `throttle_scope` always allow the request
		if not self.scope:
			return True

		# Determine the allowed request rate as we normally would during
		# the `__init__` call.
		self.rate = self.get_rate()
		self.num_requests, self.duration = self.parse_rate(self.rate)

		# We can now proceed as normal.
		return super().allow_request(update, view)

	def get_cache_key(self, update: telegram.Update, view: TelegramView):
		"""
		If `view.throttle_scope` is not set, don't apply this throttle.

		Otherwise generate the unique cache key by concatenating the user id
		with the `.throttle_scope` property of the view.
		"""
		return self.cache_format % {
			"scope": self.scope,
			"ident": self.get_ident(update),
		}
