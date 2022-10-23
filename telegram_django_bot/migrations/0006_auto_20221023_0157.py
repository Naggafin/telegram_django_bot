# Generated by Django 3.1 on 2022-10-23 01:57

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('telegram_django_bot', '0005_auto_20221010_1330'),
    ]

    operations = [
        migrations.AlterField(
            model_name='botmenuelem',
            name='command',
            field=models.TextField(blank=True, help_text='Bot command that can call this menu block', null=True, unique=True),
        ),
    ]
