import math

from django.utils.translation import gettext_lazy as _, ngettext


class TelegramBotException:
	def __init__(self, detail=None):
		if detail is None:
			self.detail = self.default_detail

	def __str__(self):
		return str(self.detail)


class PermissionDenied(TelegramBotException):
	default_detail = _("You do not have permission to perform this action.")


class Throttled(TelegramBotException):
	default_detail = _("Request was throttled.")
	extra_detail_singular = _("Expected available in {wait} second.")
	extra_detail_plural = _("Expected available in {wait} seconds.")

	def __init__(self, wait=None, detail=None):
		if detail is None:
			detail = self.default_detail
		if wait is not None:
			wait = math.ceil(wait)
			detail = " ".join(
				(
					detail,
					ngettext(
						self.extra_detail_singular.format(wait=wait),
						self.extra_detail_plural.format(wait=wait),
						wait,
					),
				)
			)
		self.wait = wait
		self.detail = detail


class ActionNotAllowed(TelegramBotException):
	default_detail = _('Action "{action}" not allowed.')

	def __init__(self, action, detail=None):
		if detail is None:
			detail = self.default_detail.format(action=action)
		super().__init__(detail)
