from datetime import datetime

# separate counters for each prefix
prefix_counters = {}


def generate_project_id(series_prefix=None):
    if series_prefix:
        if series_prefix not in prefix_counters:
            prefix_counters[series_prefix] = 1
        else:
            prefix_counters[series_prefix] += 1

        return f"{series_prefix}{prefix_counters[series_prefix]:03d}"
    else:
        # default mode
        return "PRJ-" + datetime.now().strftime("%Y%m%d%H%M%S")