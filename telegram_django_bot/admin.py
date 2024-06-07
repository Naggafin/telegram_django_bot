from django.apps import apps
from django.contrib import admin
from django.db.models import Count
from django.utils.translation import gettext_lazy as _
from import_export.admin import (
	ExportActionModelAdmin,
	ImportExportActionModelAdmin,
)

from .admin_utils import (
	CustomRelatedOnlyDropdownFilter,
	DefaultOverrideAdminWidgetsForm,
)
from .models import (
	ActionLog,
	BotMenuElem,
	BotMenuElemAttrText,
	TeleDeepLink,
	TelegramAccount,
	Trigger,
	UserTrigger,
)
from .resources import (
	ActionLogResource,
	BotMenuElemAttrTextResource,
	BotMenuElemResource,
	TeleDeepLinkResource,
	TelegramAccountResource,
	TriggerResource,
	UserTriggerResource,
)


@admin.register(TelegramAccount)
class TelegramAccountAdmin(ExportActionModelAdmin):
	resource_class = TelegramAccountResource

	def __init__(self, model, admin_site) -> None:
		if apps.is_installed("rangefilter"):
			from rangefilter.filters import DateRangeFilter

			self.list_filter = (
				"is_active",
				("date_added", DateRangeFilter),
				("teledeeplink", CustomRelatedOnlyDropdownFilter),
			)
		super().__init__(model, admin_site)

	list_display = (
		"telegram_account_id",
		"first_name",
		"last_name",
		"telegram_username",
	)
	search_fields = (
		"first_name__startswith",
		"last_name__startswith",
		"username__startswith",
		"telegram_account_id",
	)
	list_filter = (
		"is_blocked",
		"date_added",
		("teledeeplink", CustomRelatedOnlyDropdownFilter),
	)


@admin.register(ActionLog)
class ActionLogAdmin(ExportActionModelAdmin):
	resource_class = ActionLogResource

	def __init__(self, model, admin_site) -> None:
		if apps.is_installed("rangefilter"):
			from rangefilter.filters import DateRangeFilter

			self.list_filter = (
				"type",
				("dttm", DateRangeFilter),
				("telegram_account", CustomRelatedOnlyDropdownFilter),
			)
		super().__init__(model, admin_site)

	list_display = ("id", "telegram_account", "dttm", "type")
	list_select_related = ("telegram_account",)
	search_fields = ("type__startswith",)
	list_filter = (
		"type",
		"dttm",
		("telegram_account", CustomRelatedOnlyDropdownFilter),
	)
	raw_id_fields = ("telegram_account",)


@admin.register(TeleDeepLink)
class TeleDeepLinkAdmin(ExportActionModelAdmin):
	resource_class = TeleDeepLinkResource
	list_display = ("id", "title", "price", "link", "count_users")
	search_fields = ("title", "link")

	def get_queryset(self, request):
		qs = super(TeleDeepLinkAdmin, self).get_queryset(request)
		return qs.annotate(c_users=Count("telegram_accounts"))

	@admin.display(description=_("User count"))
	def count_users(self, inst):
		return inst.c_users

	count_users.admin_order_field = "c_users"

	def count_activated(self, inst):
		return inst.ca_users

	count_activated.admin_order_field = "ca_users"


class BotMenuElemAdminForm(DefaultOverrideAdminWidgetsForm):
	list_json_fields = [
		"buttons_db",
		"callbacks_db",
	]


@admin.register(BotMenuElem)
class BotMenuElemAdmin(ImportExportActionModelAdmin):
	resource_class = BotMenuElemResource
	list_display = ("id", "message", "is_visable", "callbacks_db")
	search_fields = (
		"command",
		"callbacks_db",
		"message",
		"buttons_db",
	)
	list_filter = ("is_visable", "empty_block")
	form = BotMenuElemAdminForm


@admin.register(BotMenuElemAttrText)
class BotMenuElemAttrTextAdmin(ImportExportActionModelAdmin):
	resource_class = BotMenuElemAttrTextResource
	list_display = (
		"id",
		"dttm_added",
		"language_code",
		"default_text",
		"translated_text",
	)
	search_fields = ("default_text", "translated_text")
	list_filter = ("language_code", "bot_menu_elem")


class TriggerAdminForm(DefaultOverrideAdminWidgetsForm):
	json_fields = [
		"condition_db",
	]


@admin.register(Trigger)
class TriggerAdmin(ImportExportActionModelAdmin):
	resource_class = TriggerResource
	list_display = ("id", "name", "min_duration", "priority", "botmenuelem")
	list_select_related = ("botmenuelem",)
	search_fields = ("name", "condition_db")
	form = TriggerAdminForm


@admin.register(UserTrigger)
class UserTriggerAdmin(ExportActionModelAdmin):
	resource_class = UserTriggerResource
	list_display = ("id", "dttm_added", "trigger", "telegram_account", "is_sent")
	list_select_related = ("trigger", "telegram_account")
	list_filter = ("trigger", "is_sent")
