"""
╔══════════════════════════════════════════════════════════════╗
║         AIR TOUCH VIRTUAL MOUSE — MAIN ENTRY POINT          ║
║     Computer Vision + AI + Voice Controlled Mouse System     ║
╚══════════════════════════════════════════════════════════════╝

Usage:
    python main.py                        # Default mode
    python main.py --mode gaming          # Gaming mode
    python main.py --mode presentation    # Presentation mode
    python main.py --mode accessibility   # Accessibility mode
    python main.py --calibrate            # Run calibration
    python main.py --dashboard            # Show performance dashboard
"""

import argparse
import sys
import os
import logging
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from core.virtual_mouse import VirtualMouse
from core.calibration import CalibrationSystem
from ui.dashboard import PerformanceDashboard
from utils.logger import setup_logger
from utils.config import Config

def parse_args():
    parser = argparse.ArgumentParser(
        description="Air Touch Virtual Mouse — Touchless Computer Control"
    )
    parser.add_argument(
        "--mode",
        choices=["default", "gaming", "presentation", "accessibility"],
        default="default",
        help="Operating mode"
    )
    parser.add_argument(
        "--calibrate",
        action="store_true",
        help="Run the user calibration wizard"
    )
    parser.add_argument(
        "--dashboard",
        action="store_true",
        help="Show performance dashboard after session"
    )
    parser.add_argument(
        "--profile",
        type=str,
        default="default",
        help="User profile name to load"
    )
    parser.add_argument(
        "--no-voice",
        action="store_true",
        help="Disable voice command recognition"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging and visual overlays"
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # Setup logging
    log_level = logging.DEBUG if args.debug else logging.INFO
    logger = setup_logger("AirTouch", log_level)

    logger.info("=" * 60)
    logger.info("  AIR TOUCH VIRTUAL MOUSE  —  Starting Up")
    logger.info("=" * 60)

    # Load config
    config = Config(profile=args.profile)
    config.set("mode", args.mode)
    config.set("debug", args.debug)
    config.set("voice_enabled", not args.no_voice)

    # Run calibration if requested
    if args.calibrate:
        logger.info("Launching Calibration Wizard...")
        cal = CalibrationSystem(config)
        cal.run()
        config.save()
        logger.info("Calibration complete. Settings saved.")
        return

    # Start the virtual mouse
    logger.info(f"Mode: {args.mode.upper()} | Profile: {args.profile}")
    logger.info("Press 'Q' in the camera window to quit.")
    logger.info("Say 'stop' or press ESC to exit.")

    mouse = VirtualMouse(config)

    try:
        mouse.run()
    except KeyboardInterrupt:
        logger.info("Interrupted by user.")
    finally:
        stats = mouse.get_session_stats()
        logger.info("\n── Session Summary ──────────────────")
        logger.info(f"  Duration      : {stats['duration']:.1f}s")
        logger.info(f"  Gestures      : {stats['total_gestures']}")
        logger.info(f"  Clicks        : {stats['clicks']}")
        logger.info(f"  Voice Cmds    : {stats['voice_commands']}")
        logger.info(f"  Avg FPS       : {stats['avg_fps']:.1f}")
        logger.info(f"  Avg Latency   : {stats['avg_latency_ms']:.1f}ms")
        logger.info("─────────────────────────────────────")
        mouse.cleanup()

        if args.dashboard:
            dash = PerformanceDashboard(stats)
            dash.show()


if __name__ == "__main__":
    main()
