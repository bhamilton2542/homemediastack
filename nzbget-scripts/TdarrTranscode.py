#!/usr/bin/env python3
##############################################################################
### NZBGET POST-PROCESSING SCRIPT                                          ###

# Send finished downloads through Tdarr before Sonarr/Radarr import them.
#
# NZBGet doesn't report a download as complete until this script exits, so
# Sonarr/Radarr only import after Tdarr is done. The script is fail-safe: if
# Tdarr is unreachable, errors, or never picks the file up, the original file
# is left alone and the download still completes normally.

##############################################################################
### OPTIONS                                                                ###

# Tdarr server URL.
#TdarrUrl=http://tdarr:8265

# Tdarr library to scan (must exist, folder watching OFF).
#LibraryName=Downloads

# Categories to process (comma separated).
#Categories=Movies,TV Shows

# Maximum minutes to wait for Tdarr per download.
#MaxWaitMinutes=720

# Tdarr API key (leave empty if API auth is not enabled).
#ApiKey=

### NZBGET POST-PROCESSING SCRIPT                                          ###
##############################################################################

import json
import os
import sys
import time
import urllib.request

SUCCESS, FAILURE, NONE = 93, 94, 95

VIDEO_EXTS = {".mkv", ".mp4", ".m4v", ".avi", ".mov", ".ts", ".m2ts", ".wmv", ".mpg", ".mpeg"}
TERMINAL = {"Transcode success", "Transcode error", "Not required", "Transcode cancelled"}

# Test hooks (environment only; NZBGet never sets these).
POLL_SECONDS = float(os.environ.get("TDARR_POLL_SECONDS", "15"))
REGISTER_WAIT = float(os.environ.get("TDARR_REGISTER_WAIT", "90"))
MIN_VIDEO_BYTES = int(float(os.environ.get("TDARR_MIN_VIDEO_MB", "50")) * 1024 * 1024)


def log(level, msg):
    print("[%s] %s" % (level, msg), flush=True)


def opt(name, default=""):
    return os.environ.get("NZBPO_" + name.upper(), "").strip() or default


class Tdarr:
    def __init__(self, base, api_key=""):
        self.base = base.rstrip("/")
        self.api_key = api_key

    def call(self, path, data, timeout=30):
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        req = urllib.request.Request(
            self.base + path,
            data=json.dumps({"data": data}).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
        try:
            return json.loads(raw)
        except ValueError:
            return raw

    def find_library(self, name):
        libs = self.call("/api/v2/cruddb", {
            "collection": "LibrarySettingsJSONDB", "mode": "getAll", "docID": "", "obj": {}})
        for lib in libs:
            if lib.get("name") == name:
                return lib
        return None

    def records(self, stem, lib_id, release_dir):
        found = self.call("/api/v2/search-db", {
            "string": stem, "lessThanGB": 10000, "greaterThanGB": 0})
        prefix = release_dir.rstrip("/") + "/"
        return [r for r in found
                if r.get("DB") == lib_id and str(r.get("file", "")).startswith(prefix)]

    def scan_files(self, lib_id, paths):
        self.call("/api/v2/scan-files", {"scanConfig": {
            "dbID": lib_id, "mode": "scanFolderWatcher", "arrayOrPath": paths}})

    def scan_folder(self, lib_id, folder):
        self.call("/api/v2/scan-files", {"scanConfig": {
            "dbID": lib_id, "mode": "scanFindNew", "arrayOrPath": folder}})


def list_videos(folder, min_bytes=None):
    if min_bytes is None:
        min_bytes = MIN_VIDEO_BYTES
    videos = []
    for root, _dirs, files in os.walk(folder):
        for name in files:
            if os.path.splitext(name)[1].lower() not in VIDEO_EXTS:
                continue
            path = os.path.join(root, name)
            try:
                if os.path.getsize(path) >= min_bytes:
                    videos.append(path)
            except OSError:
                pass
    return sorted(videos)


def wait_for_tdarr(tdarr, lib_id, release_dir, stems, max_wait_seconds):
    """Return {stem: [verdicts]} once every file has a final Tdarr verdict."""
    start = time.time()
    stems = set(stems)
    fallback_done = False
    stable = 0
    last_summary = None

    while True:
        statuses = {s: [r.get("TranscodeDecisionMaker", "") for r in tdarr.records(s, lib_id, release_dir)]
                    for s in stems}
        missing = [s for s, v in statuses.items() if not v]
        pending = [s for s, v in statuses.items() if v and any(x not in TERMINAL for x in v)]
        elapsed = time.time() - start

        if missing and elapsed > REGISTER_WAIT and not fallback_done:
            log("INFO", "Tdarr hasn't registered %d file(s); trying a folder scan" % len(missing))
            tdarr.scan_folder(lib_id, release_dir)
            fallback_done = True

        if missing and elapsed > REGISTER_WAIT * 2:
            for s in missing:
                log("WARNING", "Tdarr never picked up '%s'; it will import untranscoded" % s)
                stems.discard(s)
                statuses.pop(s, None)
            missing = []

        if not stems:
            return {}

        if not missing and not pending:
            stable += 1
            if stable >= 2:  # two clean polls in a row (record may be re-created after a remux)
                return statuses
        else:
            stable = 0

        summary = (len(missing), len(pending))
        if summary != last_summary:
            log("INFO", "Waiting on Tdarr: %d not yet registered, %d in progress" % summary)
            last_summary = summary

        if elapsed > max_wait_seconds:
            log("WARNING", "Gave up waiting for Tdarr after %d minutes" % (max_wait_seconds // 60))
            return statuses
        time.sleep(POLL_SECONDS)


def process(release_dir):
    base = opt("TdarrUrl", "http://tdarr:8265")
    lib_name = opt("LibraryName", "Downloads")
    max_wait = int(opt("MaxWaitMinutes", "720")) * 60
    tdarr = Tdarr(base, opt("ApiKey"))

    videos = list_videos(release_dir)
    if not videos:
        log("INFO", "No video files found in %s; nothing to do" % release_dir)
        return SUCCESS

    lib = tdarr.find_library(lib_name)
    if not lib:
        log("WARNING", "Tdarr library '%s' not found; skipping transcode" % lib_name)
        return SUCCESS
    if lib.get("folderWatching"):
        log("WARNING", "Library '%s' has folder watching ON; turn it off so only this script feeds it" % lib_name)
    folder = str(lib.get("folder", "")).rstrip("/") + "/"
    if not (release_dir.rstrip("/") + "/").startswith(folder):
        log("WARNING", "%s is outside library folder %s; skipping transcode" % (release_dir, folder))
        return SUCCESS

    stems = [os.path.splitext(os.path.basename(v))[0] for v in videos]
    log("INFO", "Sending %d file(s) to Tdarr library '%s'" % (len(videos), lib_name))
    tdarr.scan_files(lib["_id"], videos)

    results = wait_for_tdarr(tdarr, lib["_id"], release_dir, stems, max_wait)
    for stem, verdicts in sorted(results.items()):
        for v in verdicts:
            level = "WARNING" if v == "Transcode error" else "INFO"
            extra = " - original kept, imports as-is" if v == "Transcode error" else ""
            log(level, "%s: %s%s" % (stem, v or "no verdict", extra))

    if not list_videos(release_dir, min_bytes=1):
        log("ERROR", "No video file left in %s after Tdarr; failing so the download is retried" % release_dir)
        return FAILURE
    return SUCCESS


def main():
    # Manual testing: TdarrTranscode.py --check | --run <folder>
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        tdarr = Tdarr(opt("TdarrUrl", "http://tdarr:8265"), opt("ApiKey"))
        lib = tdarr.find_library(opt("LibraryName", "Downloads"))
        log("INFO", "Connected to Tdarr. Library: %s" % (
            "found (id %s, folder %s, folderWatching=%s)" % (lib["_id"], lib.get("folder"), lib.get("folderWatching"))
            if lib else "NOT FOUND"))
        return 0 if lib else 1

    if len(sys.argv) > 2 and sys.argv[1] == "--run":
        release_dir = sys.argv[2]
    else:
        status = os.environ.get("NZBPP_TOTALSTATUS", "")
        category = os.environ.get("NZBPP_CATEGORY", "")
        release_dir = os.environ.get("NZBPP_DIRECTORY", "")
        wanted = [c.strip() for c in opt("Categories", "Movies,TV Shows").split(",") if c.strip()]
        if status == "FAILURE" or not release_dir:
            return NONE
        if category not in wanted:
            log("INFO", "Category '%s' not handled by this script" % category)
            return NONE

    try:
        return process(release_dir)
    except Exception as exc:  # fail safe: never block or fail a download over Tdarr trouble
        log("WARNING", "Tdarr step skipped (%s: %s); download continues untouched" % (type(exc).__name__, exc))
        return SUCCESS


if __name__ == "__main__":
    sys.exit(main())
