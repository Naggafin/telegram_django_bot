from telegram import TelegramError
from telegram.ext.dispatcher import Dispatcher
from telegram.ext.handler import Handler
from telegram.utils.helpers import DEFAULT_FALSE

from .utrls import TelegramPattern, get_resolver


def build_handlers(dispatcher, resolver):
	app_name = resolver.app_name
	handler = resolver.callback
	if app_name not in dispatcher.handlers:
		dispatcher.handlers[app_name] = []
	dispatcher.handlers[app_name].append(handler)

	for pattern in resolver.utrl_patterns:
		if isinstance(pattern, TelegramPattern):
			handler = pattern.callback
			if not isinstance(handler, Handler):
				raise TypeError(f"handler is not an instance of {Handler.__name__}")
			if handler.persistent and not dispatcher.persistence:
				raise ValueError(
					f"ConversationHandler {handler.name} can not be persistent if dispatcher has no persistence"
				)
			dispatcher.handlers[app_name].append(handler)
		else:  # pattern is a resolver
			build_handlers(dispatcher, pattern)


class RouteDispatcher(Dispatcher):
	def __init__(self, *args, utrl_conf=None, **kwargs):
		super.__init__(*args, **kwargs)
		self.utrl_conf = utrl_conf
		self._user_routes = {}
		self.collect_handlers(self.utrl_conf)

	def collect_handlers(self, utrl_conf=None):
		resolver = get_resolver(utrl_conf)
		if not resolver._populated:
			resolver.check()
			resolver._populate()

		build_handlers(self, resolver)

	def process_update(self, update: object) -> None:
		if isinstance(update, TelegramError):
			try:
				self.dispatch_error(None, update)
			except Exception:
				self.logger.exception(
					"An uncaught error was raised while handling the error."
				)
			return

		# initial record of user's last request
		user = update.effective_user
		if user and user.id not in self._user_routes:
			resolver = get_resolver()
			self._user_routes[user.id] = resolver.app_name

		app_name = self._user_routes[user.id]
		context = None
		handled = False
		sync_modes = []

		try:
			for handler in self.handlers[app_name]:
				check = handler.check_update(update)
				if check is not None and check is not False:
					if not context and self.use_context:
						context = self.context_types.context.from_update(update, self)
						context.refresh_data()
					handled = True
					sync_modes.append(handler.run_async)
					handler.handle_update(update, self, check, context)
					break

		# Stop processing with any other handler.
		except DispatcherHandlerStop:
			self.logger.debug("Stopping further handlers due to DispatcherHandlerStop")
			self.update_persistence(update=update)
			break

		# Dispatch any error.
		except Exception as exc:
			try:
				self.dispatch_error(update, exc)
			except DispatcherHandlerStop:
				self.logger.debug("Error handler stopped further handlers")
				break
			# Errors should not stop the thread.
			except Exception:
				self.logger.exception(
					"An uncaught error was raised while handling the error."
				)

		# Update persistence, if handled
		handled_only_async = all(sync_modes)
		if handled:
			# Respect default settings
			if all(mode is DEFAULT_FALSE for mode in sync_modes) and self.bot.defaults:
				handled_only_async = self.bot.defaults.run_async
			# If update was only handled by async handlers, we don't need to update here
			if not handled_only_async:
				self.update_persistence(update=update)

	def add_handler(self, handler, group):
		raise NotImplementedError("functionality has moved to 'collect_handlers()'")

	def remove_handler(self, handler, group):
		pass
