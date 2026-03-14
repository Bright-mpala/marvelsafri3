from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('properties', '0008_property_listing_fee_amount_and_more'),
        ('bookings', '0005_booking_commission_amount_booking_commission_rate_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='booking',
            name='room_type',
            field=models.ForeignKey(
                blank=True,
                help_text='Selected room type for property bookings',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='bookings',
                to='properties.roomtype',
            ),
        ),
        migrations.AddIndex(
            model_name='booking',
            index=models.Index(fields=['room_type', 'check_in_date', 'check_out_date'], name='bookings_bo_room_ty_a911d5_idx'),
        ),
    ]
