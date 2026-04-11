"""Experiment logging and analysis — tracks win rates and calibration."""

import json
import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from database.models import (
    Experiment,
    ExperimentType,
    ExperimentVariation,
    PostPerformance,
    QueuedPost,
)

logger = logging.getLogger(__name__)

PROGRAM_PATH = Path(__file__).resolve().parent / "program.md"


class ExperimentLog:
    """Analyzes experiment history and maintains calibration data."""

    def __init__(self, db: Session):
        self.db = db

    def get_win_rates(self) -> dict[str, dict[str, float]]:
        """Compute win rates by parameter value for each experiment type.

        Returns: {experiment_type: {parameter_value: win_rate}}
        """
        results = {}
        for exp_type in ExperimentType:
            # Count total appearances and wins per parameter value
            variations = (
                self.db.query(ExperimentVariation)
                .join(Experiment, ExperimentVariation.experiment_id == Experiment.id)
                .filter(Experiment.experiment_type == exp_type)
                .all()
            )
            if not variations:
                continue

            counts = defaultdict(lambda: {"total": 0, "wins": 0, "avg_score": 0, "scores": []})
            for v in variations:
                label = v.variation_label or "unknown"
                counts[label]["total"] += 1
                counts[label]["scores"].append(v.virality_score or 0)
                if v.is_winner:
                    counts[label]["wins"] += 1

            type_results = {}
            for label, data in counts.items():
                win_rate = data["wins"] / data["total"] if data["total"] > 0 else 0
                avg_score = sum(data["scores"]) / len(data["scores"]) if data["scores"] else 0
                type_results[label] = {
                    "win_rate": round(win_rate * 100, 1),
                    "avg_score": round(avg_score, 1),
                    "total_appearances": data["total"],
                    "total_wins": data["wins"],
                }

            if type_results:
                results[exp_type.value] = type_results

        return results

    def get_winning_parameters(self) -> dict[str, dict]:
        """Return the best-performing parameter for each experiment dimension.

        Returns: {experiment_type: {"label": str, "avg_score": float, "win_rate": float}}
        Used by content_strategy.py to bias template/tone/hook selection.
        """
        win_rates = self.get_win_rates()
        winners = {}
        for exp_type, params in win_rates.items():
            if not params:
                continue
            best_label, best_data = max(params.items(), key=lambda x: x[1]["avg_score"])
            winners[exp_type] = {
                "label": best_label,
                "avg_score": best_data["avg_score"],
                "win_rate": best_data["win_rate"],
                "total_experiments": best_data["total_appearances"],
            }
        return winners

    def calibrate(self) -> list[dict]:
        """Compare predicted virality scores vs actual engagement for posted experiments.

        Updates Experiment.actual_engagement_score and calibration_delta.
        Returns list of calibration entries.
        """
        # Find experiments with queued posts that have been posted and have performance data
        experiments = (
            self.db.query(Experiment)
            .filter(
                Experiment.queued_post_id.isnot(None),
                Experiment.actual_engagement_score.is_(None),
            )
            .all()
        )

        calibration_entries = []
        for exp in experiments:
            post = self.db.query(QueuedPost).filter(QueuedPost.id == exp.queued_post_id).first()
            if not post or not post.performance:
                continue

            perf = post.performance
            actual_score = perf.likes + perf.comments * 3 + perf.shares * 5
            if actual_score == 0:
                continue  # No engagement data yet

            exp.actual_engagement_score = actual_score
            exp.calibration_delta = (exp.winner_score or 0) - actual_score

            calibration_entries.append({
                "experiment_id": exp.id,
                "predicted": exp.winner_score,
                "actual": actual_score,
                "delta": exp.calibration_delta,
                "date": exp.created_at.strftime("%Y-%m-%d") if exp.created_at else "",
            })

        if calibration_entries:
            self.db.commit()

        return calibration_entries

    def get_summary(self) -> dict:
        """Get a summary of all experiments for the dashboard."""
        total = self.db.query(Experiment).count()
        by_type = dict(
            self.db.query(Experiment.experiment_type, func.count(Experiment.id))
            .group_by(Experiment.experiment_type)
            .all()
        )

        avg_winner_score = (
            self.db.query(func.avg(Experiment.winner_score))
            .filter(Experiment.winner_score.isnot(None))
            .scalar()
        )

        avg_spread = (
            self.db.query(func.avg(Experiment.score_spread))
            .filter(Experiment.score_spread.isnot(None))
            .scalar()
        )

        queued_count = (
            self.db.query(Experiment)
            .filter(Experiment.queued_post_id.isnot(None))
            .count()
        )

        calibrated = (
            self.db.query(Experiment)
            .filter(Experiment.actual_engagement_score.isnot(None))
            .all()
        )
        avg_delta = None
        if calibrated:
            deltas = [e.calibration_delta for e in calibrated if e.calibration_delta is not None]
            if deltas:
                avg_delta = round(sum(deltas) / len(deltas), 1)

        return {
            "total_experiments": total,
            "by_type": {k.value if hasattr(k, 'value') else k: v for k, v in by_type.items()},
            "avg_winner_score": round(avg_winner_score, 1) if avg_winner_score else None,
            "avg_score_spread": round(avg_spread, 1) if avg_spread else None,
            "queued_winners": queued_count,
            "calibrated_experiments": len(calibrated),
            "avg_calibration_delta": avg_delta,
        }

    def update_program_win_rates(self):
        """Write win rates to program.md."""
        win_rates = self.get_win_rates()
        if not win_rates or not PROGRAM_PATH.exists():
            return

        content = PROGRAM_PATH.read_text()

        # Build win rates text
        lines = []
        for exp_type, params in win_rates.items():
            sorted_params = sorted(params.items(), key=lambda x: -x[1]["win_rate"])
            param_strs = [
                f"{label} ({data['win_rate']}%, avg={data['avg_score']})"
                for label, data in sorted_params
            ]
            lines.append(f"- **{exp_type}**: {', '.join(param_strs)}")

        win_rates_text = "\n".join(lines)

        # Replace section
        marker = "## Win Rates by Parameter"
        next_section = "## Calibration Log"
        if marker in content and next_section in content:
            before = content[:content.index(marker) + len(marker)]
            after = content[content.index(next_section):]
            content = before + "\n\n<!-- Auto-populated by log.py -->\n" + win_rates_text + "\n\n" + after
            PROGRAM_PATH.write_text(content)

    def update_program_calibration(self):
        """Write calibration data to program.md."""
        entries = self.calibrate()
        if not entries or not PROGRAM_PATH.exists():
            return

        content = PROGRAM_PATH.read_text()
        cal_marker = "| Experiment | Predicted | Actual | Delta | Date |"
        cal_sep = "|------------|-----------|--------|-------|------|"

        if cal_marker in content:
            new_rows = []
            for e in entries:
                new_rows.append(
                    f"| {e['experiment_id']} | {e['predicted']} | {e['actual']:.0f} | "
                    f"{e['delta']:+.0f} | {e['date']} |"
                )
            insert_pos = content.index(cal_sep) + len(cal_sep)
            content = content[:insert_pos] + "\n" + "\n".join(new_rows) + content[insert_pos:]
            PROGRAM_PATH.write_text(content)
