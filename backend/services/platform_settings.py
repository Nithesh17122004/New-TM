# -*- coding: utf-8 -*-
"""Platform-wide fee and contact settings stored in MongoDB."""

# Billing model (customer-facing):
#   food          = restaurant menu price            → 100% to restaurant
#   delivery_fee  = ₹PER_KM × ROAD km (shortest route, fractional, e.g. 1.1 km → ₹16.5)
#   service_charge= SERVICE_PCT % of (food + delivery_fee)  → platform
#   gst           = GST_FOOD_PCT % of food + GST_DELIVERY_PCT % of delivery_fee
#   total         = food + delivery_fee + service_charge + gst
# All rates are editable any time from the admin portal.
DEFAULT_PLATFORM_FEE = 0.0           # legacy flat charge — superseded by service_charge_pct
DEFAULT_DELIVERY_PER_KM_FEE = 15.0   # rupees per road-km, paid to the rider
DEFAULT_MIN_DELIVERY_FEE = 0.0       # no floor — fractional km billed accurately (e.g. 1.1 km → ₹16.5)
DEFAULT_DELIVERY_BASE_FEE = 16.5     # legacy fallback, kept for old code paths that reference it
DEFAULT_SERVICE_CHARGE_PCT = 15.0    # % of (food + delivery fee), platform's fee
DEFAULT_GST_FOOD_PCT = 5.0           # GST on food
DEFAULT_GST_DELIVERY_PCT = 18.0      # GST on delivery fee


def get_platform_settings(db=None):
    """Return platform fee config from MongoDB, with sensible defaults."""
    if db is None:
        try:
            from flask import current_app
            db = current_app.extensions.get("mongo_db")
        except RuntimeError:
            db = None

    defaults = {
        "platform_fee": DEFAULT_PLATFORM_FEE,
        "delivery_per_km_fee": DEFAULT_DELIVERY_PER_KM_FEE,
        "min_delivery_fee": DEFAULT_MIN_DELIVERY_FEE,
        "delivery_base_fee": DEFAULT_DELIVERY_BASE_FEE,
        "service_charge_pct": DEFAULT_SERVICE_CHARGE_PCT,
        "gst_food_pct": DEFAULT_GST_FOOD_PCT,
        "gst_delivery_pct": DEFAULT_GST_DELIVERY_PCT,
        "support_phone": "",
    }
    if db is None:
        return defaults

    doc = db.settings.find_one({"_id": "platform"}) or {}

    # One-time migration: if the new billing keys aren't stored yet, ignore the
    # legacy flat fee values (₹12/km, ₹20 flat, ₹15 min) and roll the new model.
    if "service_charge_pct" not in doc:
        out = {
            "platform_fee": float(doc.get("platform_fee", DEFAULT_PLATFORM_FEE)),
            "delivery_per_km_fee": DEFAULT_DELIVERY_PER_KM_FEE,
            "min_delivery_fee": DEFAULT_MIN_DELIVERY_FEE,
            "delivery_base_fee": DEFAULT_DELIVERY_BASE_FEE,
            "service_charge_pct": DEFAULT_SERVICE_CHARGE_PCT,
            "gst_food_pct": DEFAULT_GST_FOOD_PCT,
            "gst_delivery_pct": DEFAULT_GST_DELIVERY_PCT,
            "support_phone": str(doc.get("support_phone", "")),
        }
        return out

    return {
        "platform_fee": float(doc.get("platform_fee", DEFAULT_PLATFORM_FEE)),
        "delivery_per_km_fee": float(doc.get("delivery_per_km_fee", DEFAULT_DELIVERY_PER_KM_FEE)),
        "min_delivery_fee": float(doc.get("min_delivery_fee", DEFAULT_MIN_DELIVERY_FEE)),
        "delivery_base_fee": float(doc.get("delivery_base_fee", DEFAULT_DELIVERY_BASE_FEE)),
        "service_charge_pct": float(doc.get("service_charge_pct", DEFAULT_SERVICE_CHARGE_PCT)),
        "gst_food_pct": float(doc.get("gst_food_pct", DEFAULT_GST_FOOD_PCT)),
        "gst_delivery_pct": float(doc.get("gst_delivery_pct", DEFAULT_GST_DELIVERY_PCT)),
        "support_phone": str(doc.get("support_phone", "")),
    }
