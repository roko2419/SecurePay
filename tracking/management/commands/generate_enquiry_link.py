from django.core.management.base import BaseCommand, CommandError

from tracking.signing import build_enquiry_link


class Command(BaseCommand):
    help = "Generate a signed order-enquiry link for a given order_id."

    def add_arguments(self, parser):
        parser.add_argument("order_id", type=str)
        parser.add_argument(
            "--base-url",
            type=str,
            default="http://localhost:5173/enquiry",
            help="Frontend origin + /enquiry path (default: http://localhost:5173/enquiry)",
        )

    def handle(self, *args, **options):
        order_id = options["order_id"]
        if not order_id:
            raise CommandError("order_id is required")

        link = build_enquiry_link(options["base_url"], order_id)
        self.stdout.write(link)
