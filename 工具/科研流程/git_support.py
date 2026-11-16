"""Trust only this authorized workspace's repositories in child processes.

The desktop app and its isolated executor can create files as different Windows
users. Git's ownership check still applies everywhere else. No global setting,
ownership, ACL or wildcard exception is changed.
"""
import os
import workspace_runtime as w


def environment():
    result=os.environ.copy()
    count=int(result.get('GIT_CONFIG_COUNT','0'))
    if count<0:raise ValueError('Git process configuration is invalid')
    for repository in (w.HERE,w.ROOT/'数据/数据版本',w.ROOT/'数据/软件验证/数据版本'):
        result['GIT_CONFIG_KEY_'+str(count)]='safe.directory'
        result['GIT_CONFIG_VALUE_'+str(count)]=repository.resolve().as_posix()
        count+=1
    result['GIT_CONFIG_COUNT']=str(count)
    return result
