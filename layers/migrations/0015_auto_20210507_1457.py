# -*- coding: utf-8 -*-
# Generated by Django 1.11.13 on 2021-05-07 14:57
from __future__ import unicode_literals

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('layers', '0014_auto_20190324_1416'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='rasterdatasource',
            options={'ordering': ['timestamp_modificacion']},
        ),
        migrations.AlterModelOptions(
            name='vectordatasource',
            options={'ordering': ['timestamp_modificacion']},
        ),
    ]
