# -*- coding: utf-8 -*-
# Generated by Django 1.11.13 on 2018-09-23 21:51
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('layerimport', '0003_auto_20180906_0211'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='archivoraster',
            name='cantidad_de_bandas',
        ),
        migrations.RemoveField(
            model_name='archivoraster',
            name='extent',
        ),
        migrations.RemoveField(
            model_name='archivoraster',
            name='formato',
        ),
        migrations.RemoveField(
            model_name='archivoraster',
            name='heigth',
        ),
        migrations.RemoveField(
            model_name='archivoraster',
            name='width',
        ),
        migrations.AddField(
            model_name='archivoraster',
            name='formato_driver_longname',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name='archivoraster',
            name='formato_driver_shortname',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AlterField(
            model_name='archivoraster',
            name='srid',
            field=models.IntegerField(blank=True, null=True),
        ),
    ]
