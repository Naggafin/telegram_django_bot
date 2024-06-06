import enum
import sys
from calendar import monthcalendar
from functools import wraps

import telegram
from allauth.utils import generate_unique_username
from dateutil.relativedelta import relativedelta
from django.conf import settings as django_settings  # LANGUAGES, USE_I18N
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.utils import timezone, translation
from django.utils.translation import gettext_lazy as _

from .conf import settings
from .models import ActionLog, TeleDeepLink, TelegramAccount
from .telegram_lib_redefinition import InlineKeyboardButtonDJ as inlinebutt

ERROR_MESSAGE = _(
	"Oops! It seems that an error has occurred, please write to support (contact in bio)!"
)


class LogType(enum.Enum):
	function = "F"
	callback = "C"
	user_status = "U"
	no_log = "N"


def add_log_action(user_id: int, action: str):
	if settings.LOGGING_TELEGRAM_ACTIONS:
		ActionLog.objects.create(type=action, telegram_account_id=user_id)


def handler_decor(log_type: int = LogType.function, update_user_info: bool = True):
	"""

	:param log_type: 'F' -- функция, 'C' -- callback or command, 'U' -- user-status, 'N' -- NO LOG
	:param update_user_info: update user info if it has been changed
	:return:
	"""

	def decor(func):
		@wraps(func)
		def wrapper(
			update: telegram.Update, callback_context: telegram.ext.CallbackContext
		):
			def check_first_income(tg_user: TelegramAccount):
				if update and update.message and update.message.text:
					query_words = update.message.text.split()
					if len(query_words) > 1 and query_words[0] == "/start":
						telelink, _ = TeleDeepLink.objects.get_or_create(
							link=query_words[1]
						)
						telelink.telegram_accounts.add(tg_user)

			bot = callback_context.bot

			user_details = update.effective_user
			# if update.callback_query:
			# user_details = update.callback_query.from_user
			# elif update.inline_query:
			# user_details = update.inline_query.from_user
			# else:
			# user_details = update.message.from_user

			if user_details is None:
				raise ValueError(
					f"handler_decor is made for communication with user, current update has not any user: {update}"
				)

			# new user
			# todo: this whole process ought to use django-allauth for telegram signup/login
			if not (
				tg_user := TelegramAccount.objects.filter(id=user_details.id)
				.select_related("user")
				.first()
			):
				User = get_user_model()

				username = user_details.username.replace("@", "").strip()

				if username:
					lookup_kwargs = (
						{"username_iexact": username}
						if settings.CASE_INSENSITIVE_USERNAME_LOOKUP
						else {"username": username}
					)
					user, created = User.objects.get_or_create(**lookup_kwargs)
				elif settings.REQUIRE_USERNAME:
					raise ValueError(
						_(
							"A username is required. Please add a username your Telegram account."
						)
					)
				else:
					texts = [username, user_details.first_name, user_details.last_name]
					user, created = (
						User.objects.create(username=generate_unique_username(texts)),
						True,
					)

				if created:
					user_adding_info = {
						"telegram_language_code": user_details.language_code,
						"telegram_username": user_details.username[:64]
						if user_details.username
						else "",
						"first_name": user_details.first_name[:30]
						if user_details.first_name
						else "",
						"last_name": user_details.last_name[:60]
						if user_details.last_name
						else "",
					}
					tg_user = TelegramAccount(user=user, **user_adding_info)
					tg_user.full_clean()
					tg_user.save()

					add_log_action(tg_user.pk, "ACTION_CREATED")
					check_first_income(tg_user)

			# existing user
			elif update_user_info:
				user = tg_user.user
				# check if telegram_username or first_name or last_name changed
				fields_changed = False
				for key in ("telegram_username", "first_name", "last_name"):
					if getattr(tg_user, key) != user_adding_info[key]:
						setattr(tg_user, key, user_adding_info[key])
						fields_changed = True

				if fields_changed:
					tg_user.save()

			if not user.is_active:
				if not settings.ACTIVATE_INACTIVE_USERS:
					raise PermissionDenied(_("This account is inactive."))
				check_first_income(tg_user)
				user.is_active = True
				user.save()

			if django_settings.USE_I18N:
				translation.activate(tg_user.language_code)

			raise_error = None
			try:
				res = func(bot, update, user)
			except telegram.error.BadRequest as error:
				if "Message is not modified:" in error.message:
					res = None
				else:
					res = bot.send_message(
						user.pk, str(ERROR_MESSAGE)
					)  # should be bot.send_format_message
					tb = sys.exc_info()[2]
					raise_error = error.with_traceback(tb)
			except Exception as error:
				res = bot.send_message(
					user.pk, str(ERROR_MESSAGE)
				)  # should be bot.send_format_message
				tb = sys.exc_info()[2]
				raise_error = error.with_traceback(tb)

			# log actions

			if log_type != LogType.no_log:
				if log_type == LogType.callback:
					if update.callback_query:
						log_value = update.callback_query.data
					else:
						log_value = update.message.text
				elif log_type == LogType.user_status:
					log_value = user.current_utrl
				# elif log_type == LogType.function:
				else:
					log_value = func.__name__

				add_log_action(user.id, log_value[:32])

			if not ActionLog.objects.filter(
				user=user,
				type="ACTION_ACTIVE_TODAY",
				dttm__date=timezone.now().date(),
			).exists():
				add_log_action(user.id, "ACTION_ACTIVE_TODAY")

			if raise_error:
				raise raise_error

			return res

		return wrapper

	return decor


# todo: rewrite code
# ButtonPagination WITHOUT WARRANTY
class ButtonPagination:
	"""
	Construct several pages with buttons.

	buttons -- array of buttons with values for display to user, button format:
	   [text; value]
	selected_buttons -- selected buttons (add icon)
	header_buttons -- buttons in the header for navigation or other cases, format:
	   [text; value; callback_prefix]  -- if callback_prefix=None then self.callback_prefix is selected
	footer_buttons -- same as header_buttons, but in the footer

	"""

	def __init__(
		self,
		callback_prefix,
		buttons=None,
		selected_values=None,
		callback_prefix_context_values=None,
		rows=8,
		columns=1,
	):
		self.SELECTED_TICK = "✅ "
		self.PREV_PAGE_STR = "⏮"
		self.NEXT_PAGE_STR = "⏭"
		self.PAGE_CALLBACK_SYMBOL = "telegram_p"

		self.callback_prefix = callback_prefix
		self.buttons = buttons
		self.callback_prefix_context_values = callback_prefix_context_values
		self.selected_values = selected_values
		self.rows = rows
		self.columns = columns

	@property
	def buttons_per_page(self):
		return self.rows * self.columns

	@property
	def full_callback_prefix(self):
		context_callback = ""
		if self.callback_prefix_context_values:
			context_callback = (
				"-".join(map(str, self.callback_prefix_context_values)) + "-"
			)
		return self.callback_prefix + context_callback

	def value_page(self, value):
		"""
		Select the default page for display.

		:param value: ???
		:return:
		"""
		selected_item_index = list(map(lambda x: x[1], self.buttons)).index(value)
		return selected_item_index // self.buttons_per_page

	def _select_page_buttons(self, page_num):
		"""
		Select buttons for display on the page_num page. Func is created for easy logic redefinition.

		:param page_num: if None, then  _select_page is called
		:return:
		"""
		return self.buttons[
			page_num * self.buttons_per_page : (page_num + 1) * self.buttons_per_page
		]

	def construct_inline_curr_page(self, page_num=None):
		"""
		Created inline buttons.

		:param page_num:
		:return:
		"""
		telegram_buttons = []
		if page_num is None:
			if self.selected_values:
				page_num = self.value_page(self.selected_values[0])
			else:
				page_num = 0

		value_buttons = self._select_page_buttons(page_num)

		col_index = 0
		for button in value_buttons:
			button_text = ""
			if self.selected_values and (button[1] in self.selected_values):
				button_text += self.SELECTED_TICK

			button_text += button[0]
			button_telegram = inlinebutt(
				button_text, callback_data=self.full_callback_prefix + button[1]
			)

			if col_index == 0:
				# new row
				telegram_buttons.append([button_telegram])
			else:
				# add in last row
				telegram_buttons[-1].append(button_telegram)

			col_index += 1
			if col_index == self.columns:
				col_index = 0

		# neighbor pages
		neighbor_buttons = []
		if page_num > 0:
			callback_data = (
				self.full_callback_prefix
				+ self.PAGE_CALLBACK_SYMBOL
				+ str(page_num - 1)
			)
			neighbor_buttons.append(
				inlinebutt(self.PREV_PAGE_STR, callback_data=callback_data)
			)
		if page_num < int(len(self.buttons) / self.buttons_per_page + 0.9999) - 1:
			callback_data = (
				self.full_callback_prefix
				+ self.PAGE_CALLBACK_SYMBOL
				+ str(page_num + 1)
			)
			neighbor_buttons.append(
				inlinebutt(self.NEXT_PAGE_STR, callback_data=callback_data)
			)
		if neighbor_buttons:
			telegram_buttons.append(neighbor_buttons)

		return telegram_buttons


class CalendarPagination:
	def __init__(
		self,
		callback_prefix,
		curr_month,
		buttons: dict = None,
		selected_values=None,
		month_callback_prefix=None,
		month_callback_str_format=None,
		not_clickable=True,
	):
		self.SELECTED_TICK = "✅ "
		self.PREV_PAGE_STR = "⏮"
		self.NEXT_PAGE_STR = "⏭"

		self.callback_prefix = callback_prefix
		self.curr_month = curr_month
		self.buttons = buttons or {}
		self.selected_values = selected_values or []
		self.month_callback_prefix = month_callback_prefix or callback_prefix
		self.month_callback_str_format = month_callback_str_format or "%y.%m"

		self.not_clickable = not_clickable

	def construct_inline_curr_page(self):
		prev_month = self.curr_month - relativedelta(months=1)
		next_month = self.curr_month + relativedelta(months=1)
		curr_month_callback = self.month_callback_prefix + self.curr_month.strftime(
			self.month_callback_str_format
		)

		month_buttons = [
			[
				inlinebutt(
					self.PREV_PAGE_STR,
					callback_data=self.month_callback_prefix
					+ prev_month.strftime(self.month_callback_str_format),
				),
				inlinebutt(
					self.NEXT_PAGE_STR,
					callback_data=self.month_callback_prefix
					+ next_month.strftime(self.month_callback_str_format),
				),
			]
		]

		for week_row in monthcalendar(self.curr_month.year, self.curr_month.month):
			week_buttons = []
			for month_day in week_row:
				if month_day > 0:
					day_button_info = self.buttons.get(month_day)
					if day_button_info:
						button_callback, button_text = day_button_info
					else:
						button_callback = (
							curr_month_callback
							if self.not_clickable
							else self.callback_prefix + f"{month_day}"
						)
						button_text = f"{month_day}"

					if month_day in self.selected_values:
						button_text = f"{self.SELECTED_TICK} {button_text}"

				else:
					button_text = "\u200b"
					button_callback = curr_month_callback

				week_buttons.append(
					inlinebutt(button_text, callback_data=button_callback)
				)
			month_buttons.append(week_buttons)
		return month_buttons
