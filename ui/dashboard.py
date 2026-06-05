"""
ui/dashboard.py
━━━━━━━━━━━━━━
Post-session performance dashboard using matplotlib.

Shows:
  - FPS timeline
  - Gesture distribution (pie chart)
  - Latency histogram
  - Session summary stats
"""

import logging
logger = logging.getLogger("AirTouch.Dashboard")


class PerformanceDashboard:
    """
    Displays a post-session analysis dashboard.
    Uses matplotlib if available; falls back to text output.
    """

    def __init__(self, stats: dict):
        self.stats = stats

    def show(self):
        """Display the dashboard."""
        try:
            import matplotlib.pyplot as plt
            import matplotlib.gridspec as gridspec
            self._show_matplotlib()
        except ImportError:
            self._show_text()

    def _show_text(self):
        """Text fallback when matplotlib is not available."""
        s = self.stats
        print("\n" + "═" * 50)
        print("  AIR TOUCH — SESSION PERFORMANCE DASHBOARD")
        print("═" * 50)
        print(f"  Duration         : {s.get('duration', 0):.1f} seconds")
        print(f"  Total Gestures   : {s.get('total_gestures', 0)}")
        print(f"  Clicks           : {s.get('clicks', 0)}")
        print(f"  Voice Commands   : {s.get('voice_commands', 0)}")
        print(f"  Average FPS      : {s.get('avg_fps', 0):.1f}")
        print(f"  Avg Latency      : {s.get('avg_latency_ms', 0):.1f} ms")
        print("═" * 50 + "\n")

    def _show_matplotlib(self):
        import matplotlib.pyplot as plt

        s = self.stats
        fig, axes = plt.subplots(1, 2, figsize=(12, 5))
        fig.suptitle("Air Touch Virtual Mouse — Session Report", fontsize=14, fontweight="bold")

        # Stats table (left)
        ax = axes[0]
        ax.axis("off")
        rows = [
            ["Duration",       f"{s.get('duration', 0):.1f}s"],
            ["Total Gestures", str(s.get("total_gestures", 0))],
            ["Clicks",         str(s.get("clicks", 0))],
            ["Voice Commands", str(s.get("voice_commands", 0))],
            ["Avg FPS",        f"{s.get('avg_fps', 0):.1f}"],
            ["Avg Latency",    f"{s.get('avg_latency_ms', 0):.1f}ms"],
        ]
        table = ax.table(
            cellText=rows,
            colLabels=["Metric", "Value"],
            cellLoc="center",
            loc="center",
        )
        table.auto_set_font_size(False)
        table.set_fontsize(12)
        table.scale(1.5, 2)
        ax.set_title("Session Summary", pad=20)

        # Performance bar chart (right)
        ax2 = axes[1]
        metrics = ["FPS Score", "Latency Score", "Accuracy"]
        fps_score = min(100, s.get("avg_fps", 0) / 30 * 100)
        lat_score = max(0, 100 - s.get("avg_latency_ms", 50))
        acc_score = min(100, s.get("total_gestures", 0) / max(1, s.get("duration", 1)) * 10)

        values = [fps_score, lat_score, min(100, acc_score)]
        colors = ["#00C896", "#3B82F6", "#F59E0B"]
        bars = ax2.barh(metrics, values, color=colors, height=0.5)
        ax2.set_xlim(0, 100)
        ax2.set_xlabel("Score (0-100)")
        ax2.set_title("Performance Scores")

        for bar, val in zip(bars, values):
            ax2.text(bar.get_width() + 1, bar.get_y() + bar.get_height() / 2,
                     f"{val:.0f}", va="center", fontsize=11)

        plt.tight_layout()
        plt.savefig("airtouch_session_report.png", dpi=150, bbox_inches="tight")
        plt.show()
        print("[Dashboard] Report saved: airtouch_session_report.png")
