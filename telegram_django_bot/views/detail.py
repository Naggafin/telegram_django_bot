import telegram
from django.core.exceptions import ImproperlyConfigured
from django.utils import formats
from django.utils.translation import gettext_lazy as _
from django.views.generic.base import ContextMixin
from tabulate import tabulate

from ..exceptions import NotFound
from .base import ContextMixin, TelegramView, TemplateResponseMixin


class SingleObjectMixin(ContextMixin):
	model = None
	queryset = None
	pk_kwarg = "pk"

	def get_object(self, queryset=None):
		if queryset is None:
			queryset = self.get_queryset()

		pk = self.kwargs.get(self.pk_kwarg)
		if pk:
			queryset = queryset.filter(pk=pk)
		else:
			raise AttributeError(
				"Generic detail view %s must be called with either an object "
				"pk or a slug in the URLconf." % self.__class__.__name__
			)

		try:
			# Get the single item from the filtered queryset
			obj = queryset.get()
		except queryset.model.DoesNotExist:
			raise NotFound(
				_("No %(verbose_name)s found matching the query")
				% {"verbose_name": queryset.model._meta.verbose_name}
			)
		return obj

	def get_queryset(self):
		if self.queryset is None:
			if self.model:
				return self.model._default_manager.all()
			else:
				raise ImproperlyConfigured(
					"%(cls)s is missing a QuerySet. Define "
					"%(cls)s.model, %(cls)s.queryset, or override "
					"%(cls)s.get_queryset()." % {"cls": self.__class__.__name__}
				)
		return self.queryset.all()

	def get_context_data(self, **kwargs):
		context = {}
		if self.object:
			context["object"] = self.object
			context_object_name = self.get_context_object_name(self.object)
			if context_object_name:
				context[context_object_name] = self.object
		context.update(kwargs)
		return super().get_context_data(**context)


class DisplayFieldsMixin:
	display_fields = None

	def get_display_fields(self):
		return self.display_fields or [f.name for f in self.model._meta.fields]


class DetailView(
	TemplateResponseMixin, DisplayFieldsMixin, SingleObjectMixin, TelegramView
):
	def reply(self, update, context, *args, **kwargs):
		self.object = self.get_object()
		context = self.get_context_data(object=self.object)
		return self.render_response(context)

	def render_response(self, context):
		template = self.render_template(context)
		return self.update.message.reply_text(
			f"```\n{template}\n```", parse_mode=telegram.ParseMode.MARKDOWN_V2
		)

	def render_template(self, context):
		data = [
			str(_("%(object)s details") % {"object": self.object.verbose_name}).upper()
		]
		data.append("".join(["=" for _ in range(len(header))]))
		fields = []
		for field_name in self.get_display_fields():
			fields.append(self.object._meta.get_field(field_name))
		for field in fields:
			name = f.verbose_name
			value = getattr(self.object, f.name)
			try:
				value = getattr(self.object, f"get_{field_name}_display")()
			except AttributeError:
				value = formats.localize(getattr(self.object, field_name))
			data.append("%s: %s" % (name, value))
		return tabulate("\n".join(data), headers="firstrow", tablefmt="pipe")
