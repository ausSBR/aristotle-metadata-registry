# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('aristotle_mdr', '0013_representationclass'),
    ]

    operations = [
        migrations.AddField(
            model_name='dataelement',
            name='representationClass',
            field=models.ForeignKey(verbose_name='Representation Class', blank=True, to='aristotle_mdr.RepresentationClass', null=True),
        ),
    ]
