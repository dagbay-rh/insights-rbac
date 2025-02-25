# Generated by Django 4.2.10 on 2024-10-21 15:55

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0014_auto_20220726_1743"),
        ("management", "0055_tenantmapping"),
    ]

    operations = [
        migrations.AlterField(
            model_name="tenantmapping",
            name="tenant",
            field=models.OneToOneField(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="tenant_mapping",
                to="api.tenant",
            ),
        ),
    ]
