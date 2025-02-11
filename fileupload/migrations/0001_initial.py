# -*- coding: utf-8 -*-
# Generated by Django 1.11.13 on 2018-06-20 03:13
from __future__ import unicode_literals

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import fileupload.models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Archivo',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('file', models.FileField(max_length=255, upload_to=fileupload.models.getUploadPath)),
                ('slug', models.SlugField(blank=True)),
                ('nombre', models.CharField(blank=True, max_length=128)),
                ('extension', models.CharField(blank=True, max_length=15)),
                ('owner', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='fileupload_archivo_owner', to=settings.AUTH_USER_MODEL, verbose_name='owner')),
            ],
            options={
                'abstract': False,
            },
        ),
    ]
