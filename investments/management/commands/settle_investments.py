from django.core.management.base import BaseCommand

from investments.services import settle_due_investments


class Command(BaseCommand):
    help = "احتساب أرباح الاستثمارات التي انتهت مدتها"

    def handle(self, *args, **options):
        count = settle_due_investments()
        self.stdout.write(self.style.SUCCESS(f"تم احتساب أرباح {count} استثماراً."))
