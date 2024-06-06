class BasePermissionClass:
	def has_permissions(self, bot, update, user, utrl_args, **kwargs):
		raise NotImplementedError()


class PermissionAllowAny(BasePermissionClass):
	def has_permissions(self, bot, update, user, utrl_args, **kwargs):
		return True


class PermissionIsAuthenticated(BasePermissionClass):
	def has_permissions(self, bot, update, user, utrl_args, **kwargs):
		return bool(user)


class PermissionIsAdminUser(BasePermissionClass):
	def has_permissions(self, bot, update, user, utrl_args, **kwargs):
		return bool(user and user.is_staff)
