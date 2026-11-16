"""Shared bounded work and success semantics; clocks stay in their callers."""
def checked(result):
    if result.get('status')=='needs_configuration':raise ValueError(result.get('message') or '请先配置 DeepSeek。')
    if result.get('stopped'):raise __import__('project_profiles').AutomaticStopped(result.get('message','项目处理已停止。'))
    if result.get('busy'):raise ValueError('正在同步，将于后台空闲后重试。')
    if result.get('errors'):raise ValueError('部分资料未同步，详情见运行记录。')
    return result

def materials(project):
    from organization import organize
    return checked(organize({'project':project}))
