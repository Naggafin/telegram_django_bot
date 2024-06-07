from import_export import resources

from .models import (
	ActionLog,
	BotMenuElem,
	BotMenuElemAttrText,
	TeleDeepLink,
	TelegramAccount,
	Trigger,
	UserTrigger,
)


class TelegramAccountResource(resources.ModelResource):
	class Meta:
		model = TelegramAccount


class TeleDeepLinkResource(resources.ModelResource):
	class Meta:
		model = TeleDeepLink


class ActionLogResource(resources.ModelResource):
	class Meta:
		model = ActionLog


class BotMenuElemResource(resources.ModelResource):
	class Meta:
		model = BotMenuElem


class BotMenuElemAttrTextResource(resources.ModelResource):
	class Meta:
		model = BotMenuElemAttrText


class TriggerResource(resources.ModelResource):
	class Meta:
		model = Trigger


class UserTriggerResource(resources.ModelResource):
	class Meta:
		model = UserTrigger
