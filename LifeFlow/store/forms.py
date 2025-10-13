from django import forms
from .models import Price


class PriceAdminForm(forms.ModelForm):
    class Meta:
        model = Price
        fields = "__all__"

    def clean(self):
        cleaned_data = super().clean()
        is_subscription = cleaned_data.get("is_subscription")
        billing_interval = cleaned_data.get("billing_interval")

        if is_subscription and not billing_interval:
            raise forms.ValidationError("Please select a billing interval for a subscription.")

        if not is_subscription and billing_interval:
            raise forms.ValidationError("Billing interval should be empty for non-subscription prices.")

        return cleaned_data
