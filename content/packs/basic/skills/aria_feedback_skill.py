from typing import Dict, Any

class AriaFeedbackSkill:
    """
    Skill for Aria to gather and process feedback data related to band success.
    Provides methods to collect user feedback, evaluate KPIs, and generate summary reports.
    """

    def __init__(self, artifact_store):
        self.artifact_store = artifact_store

    def collect_feedback(self, band_id: str, feedback_text: str, metrics: Dict[str, Any]):
        """Collect feedback including KPI data and qualitative text from band members."""
        feedback_artifact = {
            "band_id": band_id,
            "feedback_text": feedback_text,
            "metrics": metrics
        }
        # Persist feedback artifact
        self.artifact_store.save_artifact(
            artifact_type="aria_band_feedback",
            artifact_data=feedback_artifact
        )

    def generate_feedback_report(self, band_id: str) -> Dict[str, Any]:
        """Aggregate feedback artifacts and generate a summary report with KPIs and qualitative insights."""
        artifacts = self.artifact_store.get_artifacts(
            artifact_type="aria_band_feedback",
            filter_params={"band_id": band_id}
        )

        if not artifacts:
            return {"summary": "No feedback data available."}

        # Basic aggregation example
        total_engagement = 0
        total_growth = 0
        count = 0
        qualitative_comments = []

        for artifact in artifacts:
            metrics = artifact.get("metrics", {})
            total_engagement += metrics.get("engagement", 0)
            total_growth += metrics.get("growth", 0)
            comment = artifact.get("feedback_text", "")
            if comment:
                qualitative_comments.append(comment)
            count += 1

        avg_engagement = total_engagement / count if count > 0 else 0
        avg_growth = total_growth / count if count > 0 else 0

        report = {
            "average_engagement": avg_engagement,
            "average_growth": avg_growth,
            "number_of_feedbacks": count,
            "comments": qualitative_comments
        }

        return report
