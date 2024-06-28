from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from telegram import ReplyKeyboardRemove, Update
from telegram.ext import (
	CallbackContext,
	CommandHandler,
	ConversationHandler,
	Filters,
	MessageHandler,
)

from ..forms import models as model_forms
from .base import TelegramView
from .detail import SingleObjectMixin


class FormMixin:
	initial = {}
	form_class = None
	handler_class = ConversationHandler

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self._form_data = {}

	def get_handler(self, entry_callback, **handler_kwargs):
		form = self.get_form()
		field_names = [f for f in form.fields]
		handler_class = self.get_handler_class()
		entry_command = handler_kwargs.pop("command")
		fallback_command = handler_kwargs.pop("fallback")
		states = {}

		# create all our callbacks for each stage of the form
		for i, field_name in enumerate(field_names):

			def state_callback(update, context):
				# first, validate last response
				if i > 0:
					last_field = field_names[i - 1]
					bf = form[last_field]
					field = bf.field
					value = update.message.text or bf.initial
					try:
						field.clean(value)
					except ValidationError as e:
						update.message.reply_text(str(e))
						return i - 1
					else:
						self._form_data[last_field] = value
				# now prompt the user for a value on the current field
				update.message.reply_text(
					_("Please enter a value for %(field)s.") % {"field": field.label}
				)
				return i + 1

			states[i] = [
				MessageHandler(Filters.text & ~Filters.command, state_callback)
			]

		# create the last stage
		def state_callback(update, context):
			form.data = self._form_data
			if form.is_valid():
				return self.form_valid(form)
			else:
				return self.form_invalid(form)

		states[len(field_names) + 1] = [
			MessageHandler(Filters.text & ~Filters.command, state_callback)
		]

		# now create handler
		handler = ConversationHandler(
			entry_points=[CommandHandler(entry_command, entry_callback)],
			states=states,
			fallbacks=[CommandHandler(fallback_command, self.form_cancelled)],
		)
		return handler

	def get_initial(self):
		return self.initial.copy()

	def get_form_class(self):
		return self.form_class

	def get_form(self, form_class=None):
		if form_class is None:
			form_class = self.get_form_class()
		return form_class(**self.get_form_kwargs())

	def get_form_kwargs(self):
		kwargs = {"initial": self.get_initial(), "data": self._form_data}
		return kwargs

	def form_valid(self, form):
		pass  # TODO
		return ConversationHandler.END

	def render_errors(self, form):
		errors = form.errors.as_data()
		# TODO

	def form_invalid(self, form):
		errors = self.render_errors(form)
		update.message.reply_text(
			_("Submission failed due to the following errors: %(errors)s")
			% {"errors": errors}
		)
		return ConversationHandler.END

	@staticmethod
	def form_cancelled(update: Update, context: CallbackContext):
		update.message.reply_text(
			str(_("Operation cancelled.")), reply_markup=ReplyKeyboardRemove()
		)
		return ConversationHandler.END

	def get_context_data(self, **kwargs):
		if "form" not in kwargs:
			kwargs["form"] = self.get_form()
		return super().get_context_data(**kwargs)


class ModelFormMixin(FormMixin, SingleObjectMixin):
	fields = None

	def get_form_class(self):
		if self.fields is not None and self.form_class:
			raise ImproperlyConfigured(
				"Specifying both 'fields' and 'form_class' is not permitted."
			)
		if self.form_class:
			return self.form_class
		else:
			if self.model is not None:
				# If a model has been explicitly provided, use it
				model = self.model
			elif getattr(self, "object", None) is not None:
				# If this view is operating on a single object, use
				# the class of that object
				model = self.object.__class__
			else:
				# Try to get a queryset and extract the model class
				# from that
				model = self.get_queryset().model

			if self.fields is None:
				raise ImproperlyConfigured(
					"Using ModelFormMixin (base class of %s) without "
					"the 'fields' attribute is prohibited." % self.__class__.__name__
				)

			return model_forms.modelform_factory(model, fields=self.fields)

	def get_form_kwargs(self):
		kwargs = super().get_form_kwargs()
		if hasattr(self, "object"):
			kwargs.update({"instance": self.object})
		return kwargs

	def form_valid(self, form):
		self.object = form.save()
		return super().form_valid(form)


class FormView(TemplateResponseMixin, FormMixin, TelegramView):
	pass  # TODO


class ModelFormView(TemplateResponseMixin, ModelFormMixin, TelegramView):
	pass  # TODO
