# -*- coding: utf-8 -*-
# Generated by Django 1.11.13 on 2018-10-15 19:20
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('maps', '0004_auto_20180620_1920'),
    ]

    operations = [
        migrations.AddField(
            model_name='mapserverlayer',
            name='bandas',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AlterField(
            model_name='mapa',
            name='tipo_de_mapa',
            field=models.CharField(blank=True, choices=[(b'', b''), (b'layer', b'layer'), (b'layer_original_srs', b'layer_original_srs'), (b'user', b'user'), (b'public_layers', b'public_layers'), (b'general', b'general'), (b'layer_raster_band', b'layer_raster_band')], default=b'', max_length=30, verbose_name=b'Tipo de Mapa'),
        ),
    ]
