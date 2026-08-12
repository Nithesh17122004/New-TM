from api.v1.payments import _use_mock_mode, PAYMENT_MOCK_MODE, RAZORPAY_KEY_ID
print(f'PAYMENT_MOCK_MODE constant: {PAYMENT_MOCK_MODE}')
print(f'_use_mock_mode(): {_use_mock_mode()}')
print(f'RAZORPAY_KEY_ID starts with: {RAZORPAY_KEY_ID[:20] if RAZORPAY_KEY_ID else "EMPTY"}')