import datetime
import json
import random
import zoneinfo

import dateutil
from django.conf import settings as django_settings
from django.core import validators
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.utils import timezone
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _
from telegram import InlineKeyboardButton  # no lazy text so standart possible to use


class TelegramDjangoJSONDecoder(json.JSONDecoder):
	def __init__(self, *args, **kwargs):
		super(TelegramDjangoJSONDecoder, self).__init__(
			*args, object_hook=self.object_hook_decoder, **kwargs
		)

	def object_hook_decoder(self, sub_dict, *args, **kwargs):
		# so it works only for dictionary data (if datetime is in list it will not be worked)
		for key, value in sub_dict.items():
			if isinstance(value, str):
				try:
					sub_dict[key] = dateutil.parser.isoparse(value)
				except ValueError:
					pass

		return sub_dict


class TelegramDjangoJSONEncoder(DjangoJSONEncoder):
	def default(self, o):
		if isinstance(o, models.Model):
			return o.pk
		elif hasattr(o, "__iter__") and any(isinstance(obj, models.Model) for obj in o):
			return [obj.pk if isinstance(obj, models.Model) else obj for obj in o]
		else:
			return super().default(o)


class MESSAGE_FORMAT:
	TEXT = "T"
	PHOTO = "P"
	DOCUMENT = "D"
	AUDIO = "A"
	VIDEO = "V"
	GIF = "G"
	VOICE = "TV"
	VIDEO_NOTE = "VN"
	STICKER = "S"
	LOCATION = "L"
	GROUP_MEDIA = "GM"

	MESSAGE_FORMATS = (
		(TEXT, _("Text")),
		(PHOTO, _("Image")),
		(DOCUMENT, _("Document")),
		(AUDIO, _("Audio")),
		(VIDEO, _("Video")),
		(GIF, _("GIF/animation")),
		(VOICE, _("Voice")),
		(VIDEO_NOTE, _("Video note")),
		(STICKER, _("Sticker")),
		(LOCATION, _("Location")),
		(GROUP_MEDIA, _("Media Group")),
	)

	ALL_FORMATS = (elem[0] for elem in MESSAGE_FORMATS)


class ModelwithTimeManager(models.Manager):
	def bot_filter_active(self, *args, **kwargs):
		return self.filter(*args, dttm_deleted__isnull=True, **kwargs)


class AbstractActiveModel(models.Model):
	dttm_added = models.DateTimeField(default=timezone.now)
	dttm_deleted = models.DateTimeField(null=True, blank=True)

	objects = ModelwithTimeManager()

	class Meta:
		abstract = True


class TelegramAbstractActiveModel(AbstractActiveModel):
	message_id = models.BigIntegerField(null=True, blank=True)

	class Meta:
		abstract = True


def _seed_code():
	return random.randint(0, 100)


def _default_timezone():
	if not django_settings.USE_TZ:
		return datetime.timedelta()
	dt = datetime.datetime.now(tz=zoneinfo.ZoneInfo(django_settings.TIME_ZONE))
	return dt.utcoffset()


class TelegramAccount(models.Model):
	user = models.OneToOneField(
		django_settings.AUTH_USER_MODEL,
		verbose_name=_("user"),
		related_name="telegram_account",
		on_delete=models.CASCADE,
		editable=False,
	)

	date_added = models.DateField(auto_now_add=True)
	last_active = models.DateTimeField(editable=False, null=True)

	seed_code = models.IntegerField(default=_seed_code, editable=False)
	telegram_id = models.BigIntegerField(primary_key=True, editable=False)
	telegram_username = models.CharField(
		max_length=64, null=True, blank=True, editable=False
	)
	telegram_language_code = models.CharField(
		max_length=16, default=django_settings.LANGUAGE_CODE
	)

	timezone = models.DurationField(default=_default_timezone)

	# todo: add verify comparison current_utrl and current_utrl_context/current_utrl_form
	current_utrl = models.CharField(max_length=64, blank=True)
	current_utrl_code_dttm = models.DateTimeField(null=True, blank=True)
	current_utrl_context = models.JSONField(
		default=dict,
		encoder=TelegramDjangoJSONEncoder,
		decoder=TelegramDjangoJSONDecoder,
		blank=True,
	)
	# form structure {'form_name': '', 'form_data': {}}
	current_utrl_form = models.JSONField(
		default=dict,
		encoder=TelegramDjangoJSONEncoder,
		decoder=TelegramDjangoJSONDecoder,
		blank=True,
	)

	is_blocked = models.BooleanField(default=False)

	def __str__(self):
		return self.telegram_username if self.telegram_username else f"#{self.pk}"

	def __repr__(self):
		return f"TelegramAccount({self.pk}, {self.telegram_username or '-'}, {self.first_name or '-'})"

	@property
	def id(self):
		return self.telegram_id

	def clear_status(self, commit=True):
		self.current_utrl = ""
		self.current_utrl_code_dttm = None
		self.current_utrl_context = {}
		self.current_utrl_form = {}
		if commit:
			self.save()

	@property
	def language_code(self):
		if self.telegram_language_code in map(
			lambda x: x[0], django_settings.LANGUAGES
		):
			return self.telegram_language_code
		return django_settings.LANGUAGE_CODE


class TeleDeepLink(models.Model):
	title = models.CharField(max_length=64, blank=True)
	price = models.DecimalField(null=True, blank=True)
	link = models.CharField(
		max_length=64,
		validators=[
			validators.RegexValidator(
				"^[a-zA-Z0-9_-]+$",
				_(
					"Telegram only accepts letters, numbers, underscores ('_'), and hyphens ('-')."
				),
			)
		],
	)
	telegram_accounts = models.ManyToManyField(TelegramAccount)

	def __str__(self):
		return f"TDL({self.id}, {self.link})"


class ActionLog(models.Model):
	"""User actions logs."""

	dttm = models.DateTimeField(auto_now_add=True, editable=False)
	type = models.CharField(max_length=64, editable=False)
	telegram_id = models.BigIntegerField(null=True, blank=True, editable=False)

	@cached_property
	def telegram_account(self) -> TelegramAccount | None:
		return TelegramAccount.objects.filter(telegram_id=self.telegram_id).first()

	def __str__(self):
		return "AL({}, {}, {})".format(self.telegram_id, self.dttm, self.type)

	class Meta:
		indexes = [models.Index(fields=["dttm"])]


class BotMenuElem(models.Model):
	command = models.TextField(  # for multichoice start
		null=True,
		blank=True,  # todo: add manual check
		help_text=_(
			"Bot command that can call this menu block. Add 1 command per row."
		),
	)

	empty_block = models.BooleanField(
		default=False,
		help_text=_("This block will be shown if there is no catching callback."),
	)
	is_visable = models.BooleanField(
		default=True,
		help_text=_(
			"Whether to display this menu block to users (can be hidden and not deleted for convenience)."
		),
	)

	callbacks = models.JSONField(
		default=list,
		help_text=_(
			"List of regular expressions (so far only an explicit list) for callbacks that call this menu block. "
			'For example, list ["data", "callback2"] will catch the clicking InlineKeyboardButtons with callback_data "data" or "callback2".'
		),
	)

	forward_message_id = models.IntegerField(null=True, blank=True)
	forward_chat_id = models.IntegerField(null=True, blank=True)

	message_format = models.CharField(
		max_length=2,
		choices=MESSAGE_FORMAT.MESSAGE_FORMATS,
		default=MESSAGE_FORMAT.TEXT,
	)
	message = models.TextField(help_text=_("The message text."))
	buttons = models.JSONField(
		default=list,
		help_text=_(
			"InlineKeyboardMarkup buttons structure (double list of dict), where each button(dict) has next format: "
			'{"text": "text", "url": "google.com"} or {"text": "text", "callback_data": "data"}).'
		),
	)
	media = models.FileField(
		help_text=_("File attachment to the message."), null=True, blank=True
	)
	telegram_file_code = models.CharField(
		max_length=512,
		null=True,
		blank=True,
		help_text=_("File code in telegram (must be deleted when replacing file)."),
	)

	def __str__(self):
		return f"BME({self.id}, {self.command[:32] if self.command else self.message[:32]})"

	def save(self, *args, **kwargs):
		# bot = telegram.Bot(TELEGRAM_TOKEN)

		super(BotMenuElem, self).save(*args, **kwargs)

		# check and create new models for translation
		if django_settings.USE_I18N and len(django_settings.LANGUAGES) > 0:
			language_codes = set(map(lambda x: x[0], django_settings.LANGUAGES))
			if django_settings.LANGUAGE_CODE in language_codes:
				language_codes.remove(django_settings.LANGUAGE_CODE)

			get_existed_language_codes = lambda text: set(
				BotMenuElemAttrText.objects.filter(
					language_code__in=language_codes,
					bot_menu_elem_id=self.id,
					default_text=text,
				).values_list("language_code", flat=True)
			)

			BotMenuElemAttrText.objects.bulk_create(
				[
					BotMenuElemAttrText(
						language_code=language_code,
						default_text=self.message,
						bot_menu_elem_id=self.id,
					)
					for language_code in language_codes
					- get_existed_language_codes(self.message)
				]
			)

			for row_elem in self.buttons:
				for elem in row_elem:
					if text := elem.get("text"):
						BotMenuElemAttrText.objects.bulk_create(
							[
								BotMenuElemAttrText(
									language_code=language_code,
									default_text=text,
									bot_menu_elem_id=self.id,
								)
								for language_code in language_codes
								- get_existed_language_codes(text)
							]
						)

	def get_message(self, language="en"):
		translated_text = None
		if language != django_settings.LANGUAGE_CODE and django_settings.USE_I18N:
			obj = (
				BotMenuElemAttrText.objects.filter(
					language_code=language,
					bot_menu_elem_id=self.id,
					default_text=self.message,
					translated_text__isnull=False,
				)
				.only("translated_text")
				.first()
			)
			translated_text = obj.translated_text
		text = translated_text or self.message
		return text

	def get_buttons(self, language="en"):
		need_translation = (
			language != django_settings.LANGUAGE_CODE and django_settings.USE_I18N
		)

		# this solution will only make 1 query because
		# the results are cached after evaluation
		# see: djangoproject.com/topics/db/queries.html#caching-and-querysets
		translated_texts = {}
		if need_translation:
			qs = BotMenuElemAttrText.objects.filter(
				language_code=language,
				bot_menu_elem_id=self.pk,
				translated_text__isnull=False,
			).only("default_text", "translated_text")
			translated_texts = {obj.default_text: obj.translated_text for obj in qs}

		buttons = []

		for row_elem in self.buttons:
			row_buttons = []
			for item_in_row in row_elem:
				elem = dict(item_in_row)
				if (
					elem.get("text")
					and need_translation
					and (
						translated_text := translated_texts.get(
							default_text=elem["text"]
						)
					)
				):
					elem["text"] = translated_text
				row_buttons.append(InlineKeyboardButton(**elem))

			buttons.append(row_buttons)
		return buttons


class BotMenuElemAttrText(models.Model):
	dttm_added = models.DateTimeField(default=timezone.now)
	bot_menu_elem = models.ForeignKey(BotMenuElem, null=False, on_delete=models.CASCADE)

	language_code = models.CharField(max_length=16)
	default_text = models.TextField(help_text=_("The default text to display."))
	translated_text = models.TextField(
		blank=True,
		null=True,
		help_text=_("A translated version of the default text to display."),
	)

	class Meta:
		indexes = [models.Index(["bot_menu_elem", "language_code", "default_text"])]
		constraints = [
			models.UniqueConstraint(
				fields=["bot_menu_elem", "language_code", "default_text"],
				name="unique_bot_menu_elem_attr",
			)
		]


class Trigger(AbstractActiveModel):
	name = models.CharField(max_length=512, unique=True)
	condition = models.JSONField(
		help_text="""
		{
			seeds: [1, 2, 3, 4, 5],
			'amount': [{
				'gte': 5,
				'type__contains': 'dd',  // type__in, type
				'duration': '7d'
			}]
		}
		"""
	)

	min_duration = models.DurationField(
		help_text=_(
			"The minimum period in which there can be 1 notification for a user of this type."
		)
	)
	priority = models.IntegerField(
		default=1,
		help_text=_(
			"the more topics will be executed first"
		),  # todo: help text is confusing
	)

	botmenuelem = models.ForeignKey(
		BotMenuElem,
		on_delete=models.PROTECT,
		help_text=_("Which trigger message to show."),
	)

	@staticmethod
	def get_timedelta(delta_string: str):
		days = 0
		hours = 0
		for part in delta_string.split():
			if "d" in part:
				days = float(part.replace("d", ""))
			elif "h" in part:
				hours = float(part.replace("h", ""))
			else:
				raise ValueError(f"unknown format {part}")

		return timezone.timedelta(days=days, hours=hours)

	def __str__(self):
		return f"T({self.id}, {self.name})"


class UserTrigger(TelegramAbstractActiveModel):
	trigger = models.ForeignKey(Trigger, on_delete=models.PROTECT)
	telegram_account = models.ForeignKey(TelegramAccount, on_delete=models.PROTECT)

	is_sent = models.BooleanField(default=False)


class Persistence(models.Model):
	user_data = models.JSONField(default=dict, editable=False)
	chat_data = models.JSONField(default=dict, editable=False)
	bot_data = models.JSONField(default=dict, editable=False)
	callback_data = models.JSONField(default=list, editable=False)
	conversations = models.JSONField(default=dict, editable=False)
