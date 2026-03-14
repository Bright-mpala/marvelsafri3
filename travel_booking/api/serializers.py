from rest_framework import serializers
from properties.models import Property
from bookings.models import Booking

class PropertySerializer(serializers.ModelSerializer):
    """Serializer for Property model."""
    
    class Meta:
        model = Property
        fields = [
            'id', 'name', 'slug', 'description', 'property_type', 
            'star_rating', 'address', 'city', 'state', 'postal_code', 
            'country', 'latitude', 'longitude', 'phone', 'email', 
            'website', 'check_in_time', 'check_out_time', 'status'
        ]

class BookingSerializer(serializers.ModelSerializer):
    """Serializer for Booking model."""
    
    class Meta:
        model = Booking
        fields = '__all__'

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['total_price'] = data.get('total_amount')
        data['platform_commission'] = data.get('commission_amount')
        data['owner_payout'] = data.get('host_payout_amount')
        return data
