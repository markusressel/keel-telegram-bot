from dataclasses import dataclass
from datetime import datetime
from typing import List


@dataclass
class AuditLogStats:
    date: datetime.date
    webhooks: int
    approved: int
    rejected: int
    updates: int

    @staticmethod
    def from_dict(data: dict):
        return AuditLogStats(
            date=datetime.fromisoformat(data["date"]),
            webhooks=data["webhooks"],
            approved=data["approved"],
            rejected=data["rejected"],
            updates=data["updates"],
        )

    def __str__(self):
        return f"Audit log stats for {self.date}:\n" \
               f"Webhooks: {self.webhooks}\n" \
               f"Approved: {self.approved}\n" \
               f"Rejected: {self.rejected}\n" \
               f"Updates: {self.updates}"


@dataclass
class DailyStats:
    stats: List[AuditLogStats]

    @staticmethod
    def from_dict(data: List[dict]):
        return DailyStats(
            stats=[AuditLogStats.from_dict(stats) for stats in data]
        )

    def __str__(self):
        return "\n".join([str(stats) for stats in self.stats])
