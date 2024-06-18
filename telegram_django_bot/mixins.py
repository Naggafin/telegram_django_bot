import copy

import telegram
from django.forms import models as model_forms

from . import constants


class FormMixin:
	initial = {}
	form_class = None

	def get_initial(self):
		"""Return the initial data to use for forms on this view."""
		return copy.deepcopy(self.initial)

	def get_form_class(self):
		"""Return the form class to use."""
		return self.form_class

	def get_form(self, form_class=None):
		"""Return an instance of the form to be used in this view."""
		if form_class is None:
			form_class = self.get_form_class()
		return form_class(**self.get_form_kwargs())

	def get_form_data(self):
		data = {}
		if field:
			field_value = None
			if value:
				match value:
					case constants.WRITE_MESSAGE_VARIANT_SYMBOLS:
						want_write_self_variant = True
					case constants.GO_NEXT_MULTICHOICE_SYMBOLS:
						want_1more_variant_for_multichoice = False
					case constants.NONE_VARIANT_SYMBOLS:
						data[field] = None
					case _:
						field_value = value
			elif self.update.message:
				field_value = self.update.message.text

			if field_value is not None:
				data[field] = (
					field_value.split(",") if is_multichoice_field else field_value
				)

	def get_form_kwargs(self):
		kwargs = {"user": self.user, "initial": self.get_initial()}
		return kwargs

	def form_valid(self, form):
		pass

	def form_invalid(self, form):
		pass


class ModelFormMixin(FormMixin):
	fields = None

	def get_form_class(self):
		"""Return the form class to use in this view."""
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
		"""Return the keyword arguments for instantiating the form."""
		kwargs = super().get_form_kwargs()
		if hasattr(self, "object"):
			kwargs.update({"instance": self.object})
		return kwargs

	def form_valid(self, form):
		"""If the form is valid, save the associated model."""
		self.object = form.save()
		return super().form_valid(form)


class CreateModelMixin(ModelFormMixin):
	def create(
		self,
		update: telegram.Update,
		context: telegram.ext.CallbackContext,
		*args,
		field: str = None,
		value: str = None,
		**kwargs,
	):
		"""Creating item, could be several steps."""
		if field is None and value is None:
			# then it is starting adding
			self.user.telegram_account.clear_status(commit=False)

		Form = self.get_form_class()

		is_multichoice_field = (
			isinstance(Form.base_fields[field], ModelMultipleChoiceField)
			if field
			else False
		)
		show_field_variants_for_update = False
		want_1more_variant_for_multichoice = True
		want_write_self_variant = False

		# some prepare work
		want_1more_variant_for_multichoice &= (
			is_multichoice_field  # and len(data.get('field', []))
		)

		self.form = Form(data=data)

		# show message or change data in backend...
		if want_write_self_variant:
			res = self.gm_self_variant(
				field, func_response=func_response, instance_id=instance_id
			)
		else:
			if not form.is_valid():
				res = self.gm_value_error(
					field or list(form.fields.keys())[-1],
					form.errors,
					func_response=func_response,
					instance_id=instance_id,
				)
			else:
				if not show_field_variants_for_update:
					# todo: rewrite as is_completed will work only form ModelForm
					form.save(is_completed=not want_1more_variant_for_multichoice)

				if want_1more_variant_for_multichoice or show_field_variants_for_update:
					res = self.gm_next_field(
						field, func_response=func_response, instance_id=instance_id
					)

				elif form.next_field:
					res = self.gm_next_field(
						form.next_field,
						func_response=func_response,
						instance_id=instance_id,
					)
				else:
					if func_response == "create":
						res = self.gm_success_created(self.form.instance)
					else:
						res = self.show_elem(
							self.form.instance, _("The field has been updated!\n\n")
						)
		return res


class ListModelMixin:
	def list(
		self,
		update: telegram.Update,
		context: telegram.ext.CallbackContext,
		*args,
		**kwargs,
	):
		queryset = self.filter_queryset(self.get_queryset())

		page = self.paginate_queryset(queryset)
		if page is not None:
			serializer = self.get_serializer(page, many=True)
			return self.get_paginated_response(serializer.data)

		serializer = self.get_serializer(queryset, many=True)
		return Response(serializer.data)


class RetrieveModelMixin:
	def retrieve(
		self,
		update: telegram.Update,
		context: telegram.ext.CallbackContext,
		*args,
		**kwargs,
	):
		instance = self.get_object()
		serializer = self.get_serializer(instance)
		return Response(serializer.data)


class UpdateModelMixin:
	def update(
		self,
		update: telegram.Update,
		context: telegram.ext.CallbackContext,
		*args,
		**kwargs,
	):
		partial = kwargs.pop("partial", False)
		instance = self.get_object()
		serializer = self.get_serializer(instance, data=request.data, partial=partial)
		serializer.is_valid(raise_exception=True)
		self.perform_update(serializer)

		if getattr(instance, "_prefetched_objects_cache", None):
			# If 'prefetch_related' has been applied to a queryset, we need to
			# forcibly invalidate the prefetch cache on the instance.
			instance._prefetched_objects_cache = {}

		return Response(serializer.data)


class DestroyModelMixin:
	def destroy(
		self,
		update: telegram.Update,
		context: telegram.ext.CallbackContext,
		*args,
		**kwargs,
	):
		instance = self.get_object()
		self.perform_destroy(instance)
		return Response(status=status.HTTP_204_NO_CONTENT)
