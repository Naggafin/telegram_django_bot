from django.contrib import admin

from telegram_django_bot.admin import TelegramUserAdmin as CustomUserAdmin

from .models import Category, Entity, Size, User


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
	pass


@admin.register(Entity)
class EntityAdmin(admin.ModelAdmin):
	pass


@admin.register(Size)
class SizeAdmin(admin.ModelAdmin):
	pass


@admin.register(User)
class UserAdmin(CustomUserAdmin, admin.ModelAdmin):
	pass
