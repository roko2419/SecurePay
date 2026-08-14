# payments/urls.py
from django.urls import path
from tracking.api.v1.track_shipments import CreateShipment, UpdateShipment, CreateBulkShipment, TrackShipmentShipsagar
from tracking.api.v1.pdf_parser import PDFTrackingView, ParseLabelWithLLMView

urlpatterns = [
    path('create_shipment/', CreateShipment.as_view(), name='create_payment'),
    path('track_shipment/<str:awb>/', CreateShipment.as_view(), name='track_shipment'),
    path('track_shipment/<str:awb>/delivered', UpdateShipment.as_view(), name='track_shipment_query'),  # for ?awb= query param
    path('create_shipments_bulk/', CreateBulkShipment.as_view(), name='create_shipments_bulk'),
    path('track_shipment/shipsagar/<str:awb>/', TrackShipmentShipsagar.as_view(), name='track_shipment_shipsagar'),  # for ?awb= query param
    path('pdf/upload', ParseLabelWithLLMView.as_view(), name='upload_pdf'),
]