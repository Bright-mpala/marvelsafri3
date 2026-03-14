from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('properties', '0010_rename_properties_p_user_id_b648fe_idx_properties__user_id_76fc16_idx_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='property',
            name='accepted_payment_methods',
            field=models.CharField(
                blank=True,
                default='card,paynow,ecocash,bank_transfer',
                help_text='Comma-separated list of accepted guest payment methods.',
                max_length=200,
                verbose_name='accepted payment methods',
            ),
        ),
    ]
