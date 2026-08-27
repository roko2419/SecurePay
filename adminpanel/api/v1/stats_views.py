from django.db.models import Count, Sum

from rest_framework.views import Response

from adminpanel.permissions import AdminAPIView
from payments.models.orderinfo import OrderInfo
from payments.models.enquirydata import EnquiryData
from payments.models.merchantinfo import MerchantInfo


class AdminStatsView(AdminAPIView):
    def get(self, request):
        total_orders = OrderInfo.objects.count()
        total_merchants = MerchantInfo.objects.count()
        total_enquiries = EnquiryData.objects.count()
        total_amount = OrderInfo.objects.aggregate(total=Sum("order_amount"))["total"] or 0

        orders_by_status = list(
            OrderInfo.objects.values("order_status").annotate(count=Count("id")).order_by("-count")
        )
        enquiries_by_status = list(
            EnquiryData.objects.values("status").annotate(count=Count("id")).order_by("-count")
        )

        return Response(
            {
                "total_orders": total_orders,
                "total_merchants": total_merchants,
                "total_enquiries": total_enquiries,
                "total_amount": total_amount,
                "orders_by_status": orders_by_status,
                "enquiries_by_status": enquiries_by_status,
            }
        )
