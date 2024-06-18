from collections import defaultdict

from django.db import DatabaseError, transaction
from telegram.ext import BasePersistence
from telegram.ext.contexttypes import ContextTypes
from telegram.ext.utils.types import CDCData

from ..models import Persistence


class DatabasePersistence(BasePersistence):
	def __init__(
		self,
		store_user_data: bool = True,
		store_chat_data: bool = True,
		store_bot_data: bool = True,
		on_flush: bool = False,
		store_callback_data: bool = False,
		context_types: ContextTypes = None,
		database_id: int = None,
	):
		super().__init__(
			store_user_data=store_user_data,
			store_chat_data=store_chat_data,
			store_bot_data=store_bot_data,
			store_callback_data=store_callback_data,
		)
		self.on_flush = on_flush
		self.user_data = None
		self.chat_data = None
		self.bot_data = None
		self.callback_data = None
		self.conversations = None
		self.context_types = context_types or ContextTypes()
		self.database_id = database_id or 1

	def _load_data(self):
		try:
			self.instance = data = Persistence.objects.get_or_create(
				id=self.database_id
			)
			self.conversations = data.conversations
			self.user_data = defaultdict(self.context_types.user_data, data.user_data)
			self.chat_data = defaultdict(self.context_types.chat_data, data.chat_data)
			self.bot_data = data.bot_data or self.context_types.bot_data()
			self.callback_data = data.callback_data
			self.callback_data[0] = tuple(
				self.callback_data[0]
			)  # for telegram.ext.types.CDCData compatibility
		except DatabaseError:
			self.instance = None
			self.conversations = {}
			self.user_data = defaultdict(self.context_types.user_data)
			self.chat_data = defaultdict(self.context_types.chat_data)
			self.bot_data = self.context_types.bot_data()
			self.callback_data = None
		except Exception as exc:
			raise TypeError("Something went wrong loading persistence data") from exc

	@transaction.atomic
	def _save_data(self, update_fields: list | tuple = None):
		self.instance.conversations = self.conversations
		self.instance.user_data = self.user_data
		self.instance.chat_data = self.chat_data
		self.instance.bot_data = self.bot_data
		self.instance.callback_data = [
			list(self.callback_data[0]),
			self.callback_data[1],
		]
		self.instance.save(update_fields=update_fields)

	def get_user_data(self) -> dict:
		if self.user_data:
			pass
		self._load_data()
		return self.user_data

	def get_chat_data(self) -> dict:
		if self.chat_data:
			pass
		self._load_data()
		return self.chat_data

	def get_bot_data(self) -> dict:
		if self.bot_data:
			pass
		self._load_data()
		return self.bot_data

	def get_callback_data(self) -> tuple | None:
		if self.callback_data:
			pass
		self._load_data()
		if self.callback_data is None:
			return None
		return tuple(self.callback_data[0]), self.callback_data[1].copy()

	def get_conversations(self, name: str) -> dict:
		if self.conversations:
			pass
		self._load_data()
		return self.conversations.get(name, {}).copy()

	def update_conversation(self, name: str, key: tuple, new_state=None):
		if not self.conversations:
			self.conversations = {}
		if self.conversations.setdefault(name, {}).get(key) == new_state:
			return
		self.conversations[name][key] = new_state
		if not self.on_flush:
			self._save_data(["conversations"])

	def update_user_data(self, user_id: int, data: dict):
		if self.user_data is None:
			self.user_data = defaultdict(self.context_types.user_data)
		if self.user_data.get(user_id) == data:
			return
		self.user_data[user_id] = data
		if not self.on_flush:
			self._save_data(["user_data"])

	def update_chat_data(self, chat_id: int, data: dict):
		if self.chat_data is None:
			self.chat_data = defaultdict(self.context_types.chat_data)
		if self.chat_data.get(chat_id) == data:
			return
		self.chat_data[chat_id] = data
		if not self.on_flush:
			self._save_data(["chat_data"])

	def update_bot_data(self, data: dict):
		if self.bot_data == data:
			return
		self.bot_data = data
		if not self.on_flush:
			self._save_data(["bot_data"])

	def update_callback_data(self, data: CDCData):
		if self.callback_data == data:
			return
		self.callback_data = (data[0], data[1].copy())
		if not self.on_flush:
			self._save_data(["callback_data"])

	def refresh_user_data(self, user_id: int, user_data: dict):
		pass

	def refresh_chat_data(self, chat_id: int, chat_data: dict):
		pass

	def refresh_bot_data(self, bot_data: dict):
		pass

	def flush(self):
		self._save_data()
