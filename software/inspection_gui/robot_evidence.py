"""Read only local vendor connection history, never treat it as live telemetry."""
import re
from pathlib import Path


LOG = Path.home() / 'AppData/Roaming/DobotStudioPro4.6/logs/DobotStudioPro.log'


def local_robot_evidence():
    try:
        with LOG.open('rb') as stream:
            stream.seek(max(0, LOG.stat().st_size - 4_000_000))
            text = stream.read().decode('utf-8', errors='replace')
        matches = list(re.finditer(
            r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})[^\n]*Manually connect the robot, '
            r'the robot\s+is\s+([A-Za-z0-9_-]+), the port is\s+([0-9.]+)', text))
        if matches:
            last = matches[-1]
            return {'model': last[2], 'address': last[3], 'time': last[1], 'source': str(LOG)}
    except OSError:
        pass
    return None
