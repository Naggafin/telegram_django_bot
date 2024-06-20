from django.forms.utils import pretty_name

from .views import TelegramView


def telegram_view():
	def decorator(func):
		WrappedTelegramView = type(
			"WrappedTelegramView", (TelegramView,), {"__doc__": func.__doc__}
		)

		def handler(self, *args, **kwargs):
			return func(*args, **kwargs)

		WrappedTelegramView.handler = handler
		WrappedTelegramView.__name__ = func.__name__
		WrappedTelegramView.__module__ = func.__module__
		WrappedTelegramView.throttle_classes = getattr(
			func, "throttle_classes", TelegramView.throttle_classes
		)
		WrappedTelegramView.permission_classes = getattr(
			func, "permission_classes", TelegramView.permission_classes
		)
		return WrappedTelegramView.as_view()

	return decorator


def action(
	commands=None,
	detail=None,
	description=None,
	utrl_path=None,
	utrl_name=None,
	**kwargs,
):
	commands = commands or []
	commands = [command.lower() for command in commands]

	assert detail is not None, "@action() missing required argument: 'detail'"

	# name and suffix are mutually exclusive
	if "name" in kwargs and "suffix" in kwargs:
		raise TypeError("`name` and `suffix` are mutually exclusive arguments.")

	def decorator(func):
		if func.__name__.lower() not in commands:
			commands.append(func.__name__.lower())
		func.mapping = MethodMapper(commands)
		func.detail = detail
		func.utrl_path = utrl_path if utrl_path else func.__name__
		func.utrl_name = utrl_name if utrl_name else func.__name__.replace("_", "-")
		func.kwargs = kwargs

		# Set descriptive arguments for viewsets
		if "name" not in kwargs and "suffix" not in kwargs:
			func.kwargs["name"] = pretty_name(func.__name__)
		func.kwargs["description"] = description or func.__doc__ or None

		return func

	return decorator


class MethodMapper(list):
	pass
