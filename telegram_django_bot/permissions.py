import telegram

from .views import TelegramView


class BasePermission:
	def has_permissions(self, update: telegram.Update, view: TelegramView):
		return True

	def has_object_permission(self, update: telegram.Update, view: TelegramView, obj):
		return True


class AllowAny(BasePermission):
	def has_permissions(self, update: telegram.Update, view: TelegramView):
		return True


class IsAuthenticated(BasePermission):
	def has_permissions(self, update: telegram.Update, view: TelegramView):
		return view.user and not view.user.is_anonymous


class IsAdminUser(BasePermission):
	def has_permissions(self, update: telegram.Update, view: TelegramView):
		return view.user and view.user.is_staff
