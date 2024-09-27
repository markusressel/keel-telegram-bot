from dataclasses import dataclass


@dataclass
class DailyStats:
    """
    Timestamp         int `json:"timestamp"`
	WebhooksReceived  int `json:"webhooksReceived"`
	ApprovalsApproved int `json:"approvalsApproved"`
	ApprovalsRejected int `json:"approvalsRejected"`
	Updates           int `json:"updates"`
    """
    timestamp: int
    webhooks_received: int
    approvals_approved: int
    approvals_rejected: int
    updates: int

    @staticmethod
    def from_dict(data: dict):
        return DailyStats(
            timestamp=data["timestamp"],
            webhooks_received=data["webhooksReceived"],
            approvals_approved=data["approvalsApproved"],
            approvals_rejected=data["approvalsRejected"],
            updates=data["updates"],
        )

    def __str__(self):
        return f"Daily stats for {self.timestamp}:\n" \
               f"Webhooks received: {self.webhooks_received}\n" \
               f"Approvals approved: {self.approvals_approved}\n" \
               f"Approvals rejected: {self.approvals_rejected}\n" \
               f"Updates: {self.updates}"
