# Generated by Django 2.2.20 on 2022-11-18 19:39

import django.contrib.postgres.fields.jsonb
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('georeference', '0006_auto_20221012_2136'),
    ]

    operations = [
        migrations.AddField(
            model_name='itembase',
            name='lock_details',
            field=django.contrib.postgres.fields.jsonb.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='itembase',
            name='lock_enabled',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='sessionbase',
            name='user_input_duration',
            field=models.IntegerField(blank=True, null=True),
        ),
    ]