# Generated by Django 3.2.18 on 2023-09-16 12:44

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import ohmg.api.models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Key',
            fields=[
                ('value', models.CharField(default=ohmg.api.models.generate_key, editable=False, max_length=22, primary_key=True, serialize=False)),
                ('active', models.BooleanField(default=True)),
                ('request_count', models.IntegerField(default=0, editable=False)),
                ('account', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]