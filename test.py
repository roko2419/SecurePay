import requests

m1 = {'message': 'Merchant created successfully.', 'merchant_id': 7, 'merchant_key': '78865926', 'merchant_salt': '60254581'}
o1 = {'amount': 10000, 'amount_due': 10000, 'amount_paid': 0, 'attempts': 0, 'created_at': 1786104359, 'currency': 'INR', 'entity': 'order', 'id': 'order_TMsE53nxA2d0b1', 'notes': [], 'offer_id': None, 'receipt': None, 'status': 'created'}

generate_order = True

create_merchant = False

if create_merchant:
    url  = 'http://127.0.0.1:8000/create_merchant/'

    data = {
        'merchant_name': 'test',
        'merchant_email': 'test@test.com',
        'merchant_phone': '9999999999',
        'merchant_address': 'test'
    }

    response = requests.post(url, data=data)
    print(response.json())



if generate_order:
    url = 'http://127.0.0.1:8000/payments/generate_order/'

    data = {
        "id": 7,
        "merchant_order_id": 1,
        "customer_name": 'customer1',
        "customer_email": 'customer1@test.com',
        "customer_phone": '8888888888',
        "amount": 100,
        "auth_token": "78699ad49590fe8ed0ee813fe64c1a3a7d0b31ca5ce5d39a35b854212f9c99060e9e905b0ac606462877579e9d51dedf9b1ffc7df04039cc9cca297f5bdea055"
    }

    response = requests.post(url, data=data)
    print(response.json())