# Generated by Django 4.2.5 on 2024-10-04 17:56

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('db', '0013_volunteer'),
    ]

    operations = [
        migrations.AddField(
            model_name='eventregistration',
            name='include_in_attendee_list',
            field=models.BooleanField(default=False),
        ),
        migrations.AlterField(
            model_name='volunteer',
            name='event',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='volunteers', to='db.event'),
        ),
    ]
