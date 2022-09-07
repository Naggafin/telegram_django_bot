# Generated by Django 3.1 on 2022-07-26 02:13

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('myapp', '0002_auto_20220718_1756'),
    ]

    operations = [
        migrations.AddField(
            model_name='category',
            name='some_demical',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=16, null=True),
        ),
        migrations.AddField(
            model_name='category',
            name='some_float',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='category',
            name='some_int',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='category',
            name='name',
            field=models.CharField(help_text='Введите данные без ошибок', max_length=128),
        ),
        migrations.AlterField(
            model_name='entity',
            name='name',
            field=models.CharField(help_text='Введите данные без ошибок', max_length=128),
        ),
        migrations.AlterField(
            model_name='entity',
            name='price',
            field=models.DecimalField(decimal_places=2, help_text='a', max_digits=16),
        ),
        migrations.AlterField(
            model_name='size',
            name='name',
            field=models.CharField(help_text='Введите данные без ошибок', max_length=128),
        ),
        migrations.AlterField(
            model_name='user',
            name='current_utrl_context_db',
            field=models.CharField(blank=True, default='{}', max_length=4096),
        ),
        migrations.AlterField(
            model_name='user',
            name='current_utrl_form_db',
            field=models.CharField(blank=True, default='{}', max_length=4096),
        ),
    ]
