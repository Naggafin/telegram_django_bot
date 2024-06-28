import telegram
from django.core.exceptions import ImproperlyConfigured
from django.core.paginator import InvalidPage, Paginator
from django.db.models import QuerySet
from django.utils import formats
from django.utils.translation import gettext_lazy as _
from tabulate import tabulate

from ..exceptions import NotFound
from .base import ContextMixin, TelegramView, TemplateResponseMixin
from .details import DisplayFieldsMixin


class MultipleObjectMixin(ContextMixin):
	allow_empty = True
	queryset = None
	model = None
	paginate_by = None
	paginate_orphans = 0
	context_object_name = None
	paginator_class = Paginator
	page_kwarg = "page"
	ordering = None

	def get_queryset(self):
		if self.queryset is not None:
			queryset = self.queryset
			if isinstance(queryset, QuerySet):
				queryset = queryset.all()
		elif self.model is not None:
			queryset = self.model._default_manager.all()
		else:
			raise ImproperlyConfigured(
				"%(cls)s is missing a QuerySet. Define "
				"%(cls)s.model, %(cls)s.queryset, or override "
				"%(cls)s.get_queryset()." % {"cls": self.__class__.__name__}
			)
		ordering = self.get_ordering()
		if ordering:
			if isinstance(ordering, str):
				ordering = (ordering,)
			queryset = queryset.order_by(*ordering)

		return queryset

	def get_ordering(self):
		return self.ordering

	def paginate_queryset(self, queryset, page_size):
		paginator = self.get_paginator(
			queryset,
			page_size,
			orphans=self.get_paginate_orphans(),
			allow_empty_first_page=self.get_allow_empty(),
		)
		page_kwarg = self.page_kwarg
		page = self.kwargs.get(page_kwarg) or self.request.GET.get(page_kwarg) or 1
		try:
			page_number = int(page)
		except ValueError:
			if page == "last":
				page_number = paginator.num_pages
			else:
				raise NotFound(
					_("Page is not “last”, nor can it be converted to an int.")
				)
		try:
			page = paginator.page(page_number)
			return (paginator, page, page.object_list, page.has_other_pages())
		except InvalidPage as e:
			raise NotFound(
				_("Invalid page (%(page_number)s): %(message)s")
				% {"page_number": page_number, "message": str(e)}
			)

	def get_paginate_by(self, queryset):
		return self.paginate_by

	def get_paginator(
		self, queryset, per_page, orphans=0, allow_empty_first_page=True, **kwargs
	):
		return self.paginator_class(
			queryset,
			per_page,
			orphans=orphans,
			allow_empty_first_page=allow_empty_first_page,
			**kwargs,
		)

	def get_paginate_orphans(self):
		return self.paginate_orphans

	def get_allow_empty(self):
		return self.allow_empty

	def get_context_object_name(self, object_list):
		if self.context_object_name:
			return self.context_object_name
		elif hasattr(object_list, "model"):
			return "%s_list" % object_list.model._meta.model_name
		else:
			return None

	def get_context_data(self, *, object_list=None, **kwargs):
		queryset = object_list if object_list is not None else self.object_list
		page_size = self.get_paginate_by(queryset)
		context_object_name = self.get_context_object_name(queryset)
		if page_size:
			paginator, page, queryset, is_paginated = self.paginate_queryset(
				queryset, page_size
			)
			context = {
				"paginator": paginator,
				"page_obj": page,
				"is_paginated": is_paginated,
				"object_list": queryset,
			}
		else:
			context = {
				"paginator": None,
				"page_obj": None,
				"is_paginated": False,
				"object_list": queryset,
			}
		if context_object_name is not None:
			context[context_object_name] = queryset
		context.update(kwargs)
		return super().get_context_data(**context)


class ListView(
	TemplateResponseMixin, DisplayFieldsMixin, MultipleObjectMixin, TelegramView
):
	def reply(self, request, *args, **kwargs):
		self.object_list = self.get_queryset()
		allow_empty = self.get_allow_empty()

		if not allow_empty:
			if self.get_paginate_by(self.object_list) is not None and hasattr(
				self.object_list, "exists"
			):
				is_empty = not self.object_list.exists()
			else:
				is_empty = not self.object_list
			if is_empty:
				raise NotFound(
					_("Empty list and “%(class_name)s.allow_empty” is False.")
					% {
						"class_name": self.__class__.__name__,
					}
				)
		context = self.get_context_data()
		return self.render_response(context)

	def render_response(self, context):
		template = self.render_template(context)
		return self.update.message.reply_text(
			f"```\n{template}\n```", parse_mode=telegram.ParseMode.MARKDOWN_V2
		)

	def render_template(self, context):
		fields = []
		display_fields = self.get_display_fields()
		for field_name in display_fields:
			fields.append(self.object._meta.get_field(field_name))
		data = [[str(f.verbose_name).upper() for f in fields]]
		object_list = (
			context["page_obj"].object_list
			if context["page_obj"]
			else context["object_list"]
		)
		for obj in object_list:
			row = []
			for field_name in display_fields:
				try:
					item = getattr(self.object, f"get_{field_name}_display")()
				except AttributeError:
					item = formats.localize(getattr(self.object, field_name))
				row.append(str(item))
			data.append(row)
		return tabulate(data, headers="firstrow", tablefmt="pipe")
