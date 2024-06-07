from celery import current_app
from django.db.models import Count, Exists, OuterRef
from django.db.models.functions import Coalesce
from django.utils import timezone

from .conf import settings
from .models import ActionLog, TelegramAccount, Trigger, UserTrigger
from .tg_dj_bot import TG_DJ_Bot


@current_app.task
def create_triggers():
	def get_duration_dict(trigger, elem, add_prefix=True):
		prefix = "actionlog__"
		if not add_prefix:
			prefix = ""
		return {
			f"{prefix}dttm__gte": dttm_now - trigger.get_timedelta(elem.pop("duration"))
		}

	dttm_now = timezone.now()

	for trigger in (
		Trigger.objects.bot_filter_active()
		.order_by("-priority")
		.select_related("botmenuelem")
	):
		tg_users = TelegramAccount.objects.filter(is_blocked=False)

		seeds = trigger.condition.pop("seeds", [])
		if seeds:
			tg_users = tg_users.filter(seed_code__in=seeds)

		# sequence = trigger.condition.pop('sequence', [])
		# if len(sequence):
		#     query = Q()
		#     for seq_elem in sequence:
		#         query = Q()
		#         for elem in seq_elem:
		#             kwargs = get_duration_dict(trigger, elem)
		#             for key, value in elem.items():
		#                 kwargs[f'actionlog__{key}'] = value
		#             query |= Q(**kwargs)
		#     tg_users = tg_users.filter(query)

		# exclude = trigger.condition.pop('exclude', [])
		# if len(exclude):
		#     query = Q()
		#     for elem in exclude:
		#         kwargs = get_duration_dict(trigger, elem)
		#         for key, value in elem.items():
		#             kwargs[f'actionlog__{key}'] = value
		#         query |= Q(**kwargs)
		#     tg_users = tg_users.exclude(query)

		check_amount = trigger.condition.pop("amount", [])
		if len(check_amount):
			for it, elem in enumerate(check_amount):
				filter_key = None
				filter_kwargs = get_duration_dict(trigger, elem, False)
				for key_d, value in elem.items():
					if "type" in key_d:
						filter_kwargs[key_d] = value
					else:
						filter_key = key_d
						filter_value = value
				if filter_key:
					key = f"amount{it}"
					subquery = (
						ActionLog.objects.filter(
							telegram_account_id=OuterRef("telegram_id"),
							**filter_kwargs,
						)
						.values("telegram_account_id")
						.annotate(amount=Count("telegram_account_id"))
						.values("amount")
					)

					tg_users = tg_users.annotate(**{key: Coalesce(subquery, 0)}).filter(
						**{f"{key}__{filter_key}": filter_value}
					)

		user_triggers = UserTrigger.objects.filter(
			trigger=trigger,
			telegram_account_id=OuterRef("telegram_id"),
			dttm_added__gte=dttm_now - trigger.min_duration,
		)

		tg_users = tg_users.annotate(exist_trigger=Exists(user_triggers)).filter(
			exist_trigger=False
		)

		# todo: intersection with other triggers -- minimum time between triggers to do?

		UserTrigger.objects.bulk_create(
			[
				UserTrigger(trigger=trigger, telegram_account=tg_user)
				for tg_user in tg_users
			]
		)

		trig_users = []
		for tg_user in tg_users:
			trig_users.append(tg_user.pk)
			if len(trig_users) >= settings.SEND_TRIGGER_BLOCK_SIZE:
				send_triggers.delay(trig_users)
				trig_users = []

		if len(trig_users):
			send_triggers.delay(trig_users)


@current_app.task
def send_triggers(user_ids):
	dttm_now = timezone.now()
	UserTrigger.objects.filter(
		is_sent=False,
		telegram_account_id__in=user_ids,
		dttm_added__lt=dttm_now
		- timezone.timedelta(
			hours=16  # triggers not sent in the first 16 hours are deleted
		),
	).update(dttm_deleted=dttm_now)

	user_triggers = UserTrigger.objects.filter(
		is_sent=False,
		dttm_deleted__isnull=True,
		telegram_account_id__in=user_ids,
	).select_related("trigger", "trigger__botmenuelem", "telegram_account__user")

	bot = TG_DJ_Bot(settings.TELEGRAM_TOKEN)

	def _send_wrapper(self, *args, **kwargs):
		return bot.send_botmenuelem(*args, **kwargs)

	sent_user_triggers = []
	for user_trigger in user_triggers:
		is_sent, res_mess = bot.task_send_message_handler(
			_send_wrapper,
			user_trigger.telegram_account.user,
			None,
			user_trigger.telegram_account.user,  # for task_send_message_handler и для send_botmenuelem
			user_trigger.trigger.botmenuelem,
		)
		if is_sent:
			sent_user_triggers.append(user_trigger)

	UserTrigger.objects.filter(id__in=[x.id for x in sent_user_triggers]).update(
		is_sent=True
	)
	ActionLog.objects.bulk_create(
		[
			ActionLog(
				type=f"TRIGGER_SENT-{x.trigger_id}",
				telegram_account_id=x.telegram_account_id,
			)
			for x in sent_user_triggers
		]
	)
