"""Refresh/check lightweight handoff metadata. Never imports GUI or robot drivers."""
import argparse,datetime,hashlib,json,subprocess
from pathlib import Path

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def git(repo,*args):
    try:return subprocess.check_output(['git','-C',str(repo),*args],text=True,encoding='utf-8',stderr=subprocess.DEVNULL).strip()
    except (OSError,subprocess.CalledProcessError):return None

def collect(repo):
    manifest_path=repo/'software/inspection_gui/build_manifest.json'
    manifest=json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else {}
    names=set(manifest.get('modules',{}))|{'manual_control.py','dobot_feedback.py','probe_trigger.py','global_wall.py','wall_guard.py','simulation_scene3d.py'}
    paths={f'software/inspection_gui/{name}' for name in names}|{'software/app.py','software/detect_core.py','software/inspection_gui/devices_view.py'}
    source={name:digest(repo/name) if (repo/name).is_file() else None for name in sorted(paths)}
    runtime=repo.parent/'inspection_app';differences=[];checked=0
    if runtime.is_dir():
        for name,hash_value in source.items():
            other=runtime/Path(name).relative_to('software');checked+=1
            if not other.is_file() or digest(other)!=hash_value:differences.append(name)
    dirty=git(repo,'status','--porcelain','--untracked-files=normal')
    validation_path=repo/'docs/handoff/last_validation.json'
    return dict(schema_version=1,build_id=manifest.get('build_id'),
        git=dict(head=git(repo,'rev-parse','HEAD'),remote=git(repo,'remote','get-url','origin'),dirty_entries=len(dirty.splitlines()) if dirty else 0 if dirty is not None else None,remote_fetched_during_snapshot=False,publish_status='Not inferred; see UPDATES.md',head_note='HEAD when snapshot was generated; may precede the commit containing this snapshot'),
        local_paths=dict(repository=str(repo),runtime=str(runtime) if runtime.is_dir() else None,development_python=str(repo/'.venv/Scripts/python.exe')),
        source_sha256=source,manifest_sha256=digest(manifest_path) if manifest_path.exists() else None,
        runtime_comparison=dict(available=runtime.is_dir(),checked_files=checked,different_or_missing=differences),
        validation=json.loads(validation_path.read_text(encoding='utf-8')) if validation_path.exists() else None,
        notes=['Lightweight snapshot, not a guarantee of complete project or hardware acceptance.','No model weights, raw probe records, credentials or hardware connections read.','Update prose STATUS and UPDATES separately; this script does not infer progress.'])

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--check',action='store_true');args=parser.parse_args()
    repo=Path(__file__).resolve().parents[1];path=repo/'docs/handoff/state.json';snapshot=collect(repo)
    if args.check:
        previous=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        keys=('build_id','manifest_sha256','source_sha256','runtime_comparison','validation')
        changed=[key for key in keys if previous.get(key)!=snapshot.get(key)]
        # Commits containing this snapshot necessarily advance HEAD; content hashes decide freshness.
        print(json.dumps(dict(snapshot_current=not changed,changed_fields=changed,runtime_differences=snapshot['runtime_comparison']['different_or_missing']),ensure_ascii=False))
        return 1 if changed else 0
    snapshot['generated_at']=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat()
    path.parent.mkdir(parents=True,exist_ok=True);temporary=path.with_suffix('.json.tmp');temporary.write_text(json.dumps(snapshot,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');temporary.replace(path)
    print(json.dumps(dict(snapshot=str(path),build_id=snapshot['build_id'],runtime_differences=snapshot['runtime_comparison']['different_or_missing']),ensure_ascii=False));return 0
if __name__=='__main__':raise SystemExit(main())
