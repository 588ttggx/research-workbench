"""Technical execution policy; project and scientific rules stay with their owners."""
SAFE_RETRY = frozenset({'weekly', 'administrator_tick', 'discover', 'sync', 'professional_cluster', 'collect', 'relation_tick', 'knowledge_extraction', 'rspace_sync', 'memory_reuse', 'formal_analysis_update', 'run_registration', 'versions', 'bibliometrics', 'data_remote_verify', 'data_remote_sync', 'weekly_refresh'})
COALESCED = frozenset(('discover','sync','versions','administrator_tick','relation_tick','knowledge_extraction','data_remote_sync','rspace_sync','formal_analysis_update'))
PROJECT_AUTOMATIC = frozenset(('organize','analyze','directions','notes','maintain','canvas_organize','change_followup'))
def policy(kind):return {'safe_retry':kind in SAFE_RETRY or kind=='document_repair','coalesce':kind in COALESCED or kind=='document_repair'}
