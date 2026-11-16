"""Run the installed DVC CLI with UTF-8 config serialization in this child only.

DVC 3.67.1 constructs ConfigObj without an encoding when saving remote URLs.
ConfigObj then uses ASCII, which rejects Chinese Windows/NAS paths. Selecting
its supported UTF-8 option preserves DVC's own parser, validation and writes.
No installed dependency or user setting is modified.
"""
import sys
import configobj


class Utf8ConfigObj(configobj.ConfigObj):
    def __init__(self,*args,**kwargs):
        kwargs.setdefault('encoding','utf-8')
        super().__init__(*args,**kwargs)


if __name__=='__main__':
    configobj.ConfigObj=Utf8ConfigObj
    if sys.argv[1:]==['--workspace-remotes-json']:
        import json
        from dvc.config import Config
        print(json.dumps(Config(dvc_dir='.dvc').get('remote',{}),ensure_ascii=False))
    else:
        from dvc.cli import main
        raise SystemExit(main(sys.argv[1:]))
