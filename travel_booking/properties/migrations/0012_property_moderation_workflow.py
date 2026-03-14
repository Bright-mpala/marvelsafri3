from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("properties", "0011_property_accepted_payment_methods"),
    ]

    operations = [
        migrations.AddField(
            model_name="property",
            name="submitted_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="submitted at"),
        ),
        migrations.AlterField(
            model_name="property",
            name="status",
            field=models.CharField(
                choices=[
                    ("draft", "Draft"),
                    ("pending_review", "Pending Review"),
                    ("approved", "Approved"),
                    ("rejected", "Rejected"),
                    ("suspended", "Suspended"),
                    ("active", "Active"),
                    ("inactive", "Inactive"),
                ],
                default="draft",
                max_length=20,
                verbose_name="status",
            ),
        ),
    ]
