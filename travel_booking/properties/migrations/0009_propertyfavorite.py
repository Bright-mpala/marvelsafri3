from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('properties', '0008_property_listing_fee_amount_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='PropertyFavorite',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('property', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='favorites', to='properties.property')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='property_favorites', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'property favorite',
                'verbose_name_plural': 'property favorites',
                'ordering': ['-created_at'],
                'indexes': [
                    models.Index(fields=['user', 'created_at'], name='properties_p_user_id_b648fe_idx'),
                    models.Index(fields=['property', 'created_at'], name='properties_p_propert_ad9ec2_idx'),
                ],
                'constraints': [
                    models.UniqueConstraint(fields=('user', 'property'), name='unique_property_favorite'),
                ],
            },
        ),
    ]
