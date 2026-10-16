from rest_framework import serializers
from apps.barcodes.models import Barcode


class BarcodeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Barcode
        fields = [
            "token",
            "target_type",
            "target_id",
            "is_active",
            "printed_at",
            "created_at",
        ]


class ScanRequestSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=24)


class ScanResponseSerializer(serializers.Serializer):
    target_type = serializers.CharField()
    target_id = serializers.IntegerField()
    display = serializers.CharField()
