import telegram
from .views import TelegramView

from django.contrib.auth.models import AbstractUser


class BasePermission:
	def has_permissions(self, user: AbstractUser, view: TelegramView):
		return True
	
	def has_object_permission(self, user: AbstractUser, view: TelegramView, obj):
		return True


class AllowAny(BasePermission):
	def has_permissions(self, user: AbstractUser, view: TelegramView):
		return True


class IsAuthenticated(BasePermission):
	def has_permissions(self, user: AbstractUser, view: TelegramView):
		return bool(user)


class IsAdminUser(BasePermission):
	def has_permissions(self, user: AbstractUser, view: TelegramView):
		return bool(user and user.is_staff)
