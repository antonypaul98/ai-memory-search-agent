"""Strict physical Mac acceptance boundary for the existing OpenCV capture path."""
from __future__ import annotations
import argparse
import importlib
import json
import math
from datetime import timedelta

from .hardware_smoke import run_hardware_smoke

# Physical acceptance is a short diagnostic, not an unrestricted camera session.
MAX_HARDWARE_ACCEPTANCE_FRAMES = 120

def validate_config(session_id,user_id,source_id,location,device_index,max_frames,confirmations,min_interval_seconds,min_confidence,require_event,allow_physical_camera):
    if not all(isinstance(v, str) and v.strip() for v in (session_id,user_id,source_id,location)):
        raise ValueError("session_id, user_id, source_id and location are required")
    if allow_physical_camera is not True:
        raise ValueError("physical camera access requires explicit opt-in")
    if type(device_index) is not int or device_index < 0:
        raise ValueError("device_index must be a non-negative integer")
    if type(max_frames) is not int or max_frames < 1:
        raise ValueError("max_frames must be >= 1")
    if max_frames > MAX_HARDWARE_ACCEPTANCE_FRAMES:
        raise ValueError(f"max_frames must be <= {MAX_HARDWARE_ACCEPTANCE_FRAMES}")
    if type(confirmations) is not int or confirmations < 1:
        raise ValueError("confirmations must be >= 1")
    if (type(min_interval_seconds) not in (int, float)
            or not math.isfinite(min_interval_seconds) or min_interval_seconds <= 0):
        raise ValueError("min_interval_seconds must be finite and positive")
    # Validate timedelta representability before loading the capture factory.
    try:
        interval = timedelta(seconds=min_interval_seconds)
    except OverflowError as exc:
        raise ValueError("min_interval_seconds exceeds timedelta range") from exc
    if interval <= timedelta(0):
        raise ValueError("min_interval_seconds must be at least one microsecond")
    if (type(min_confidence) not in (int, float)
            or not math.isfinite(min_confidence) or not 0.0 <= min_confidence <= 1.0):
        raise ValueError("min_confidence must be finite and between 0 and 1")
    if require_event is not True:
        raise ValueError("physical hardware acceptance requires --require-event")
    if require_event and max_frames < confirmations + 1:
        raise ValueError("strict hardware acceptance requires max_frames >= confirmations + 1")

def load_capture_factory(spec):
    if not isinstance(spec, str):
        raise ValueError("capture factory must use module:callable syntax")
    module_name, separator, attribute = spec.partition(":")
    if (not separator or not module_name.strip() or not attribute.isidentifier()
            or module_name.startswith(".")):
        raise ValueError("capture factory must use module:callable syntax")
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:
        # Adapter import failures can include private local device paths.
        raise ValueError("capture factory module could not be imported") from exc
    try:
        factory = getattr(module, attribute, None)
    except Exception as exc:
        # Module-level __getattr__ may include private camera/device details.
        raise ValueError("capture factory attribute could not be resolved") from exc
    if not callable(factory):
        raise ValueError("capture factory is not callable")
    return factory

def run_cli(capture_factory, *, allow_physical_camera=False, **kwargs):
    """Validate direct Python calls before constructing a physical capture."""
    validate_config(allow_physical_camera=allow_physical_camera, **kwargs)
    try:
        capture = capture_factory()
    except Exception as exc:
        # Do not expose adapter/device details in CLI diagnostics.
        raise ValueError("camera capture factory could not be initialized") from exc
    try:
        return run_hardware_smoke(capture=capture, min_interval=timedelta(seconds=kwargs.pop("min_interval_seconds")), **kwargs)
    except OSError:
        # The CLI handles camera I/O errors with a separate bounded code.
        raise
    except Exception as exc:
        raise ValueError("camera acceptance execution failed") from exc

def main(argv=None):
    parser=argparse.ArgumentParser(description="Strict Home Agent Mac/webcam acceptance runner")
    parser.add_argument("--capture-factory",required=True)
    parser.add_argument("--session-id",required=True)
    parser.add_argument("--user-id",required=True)
    parser.add_argument("--source-id",required=True)
    parser.add_argument("--location",required=True)
    parser.add_argument("--device-index",type=int,default=0)
    parser.add_argument("--max-frames",type=int,default=3)
    parser.add_argument("--confirmations",type=int,default=2)
    parser.add_argument("--min-interval-seconds",type=float,default=1.0)
    parser.add_argument("--min-confidence",type=float,default=0.8)
    parser.add_argument("--require-event",action="store_true")
    parser.add_argument("--allow-physical-camera",action="store_true")
    args=parser.parse_args(argv)
    try:
        validate_config(
            session_id=args.session_id, user_id=args.user_id, source_id=args.source_id,
            location=args.location, device_index=args.device_index, max_frames=args.max_frames,
            confirmations=args.confirmations, min_interval_seconds=args.min_interval_seconds,
            min_confidence=args.min_confidence, require_event=args.require_event,
            allow_physical_camera=args.allow_physical_camera,
        )
        factory=load_capture_factory(args.capture_factory)
        result=run_cli(factory,session_id=args.session_id,user_id=args.user_id,source_id=args.source_id,location=args.location,device_index=args.device_index,max_frames=args.max_frames,confirmations=args.confirmations,min_interval_seconds=args.min_interval_seconds,min_confidence=args.min_confidence,require_event=args.require_event,allow_physical_camera=args.allow_physical_camera)
        print(json.dumps(result.__dict__,sort_keys=True,default=str))
        return 0 if result.passed else 1
    except OSError:
        # Do not expose device paths or driver details in the diagnostic output.
        print(json.dumps({"passed":False,"error":"camera I/O error during acceptance"},sort_keys=True))
        return 2
    except (ValueError,RuntimeError) as exc:
        print(json.dumps({"passed":False,"error":str(exc)},sort_keys=True))
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
