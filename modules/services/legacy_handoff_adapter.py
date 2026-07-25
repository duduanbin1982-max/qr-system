"""Compatibility boundary for the retired handoff-review persistence model."""

from modules.repositories.handoff_review_repository import HandoffReviewRepository


class LegacyHandoffAdapter:
    @staticmethod
    def create_compatibility_record(payload, db):
        return HandoffReviewRepository.insert_review(payload, db)

    @staticmethod
    def sync_compatibility_status(review_id, evaluation_status, reviewer_id, note, db):
        legacy_status = "pending" if evaluation_status == "pending_verification" else evaluation_status
        HandoffReviewRepository.update_status(
            review_id,
            {
                "status": legacy_status,
                "confirmed_by": reviewer_id,
                "confirm_note": note,
            },
            db,
        )
