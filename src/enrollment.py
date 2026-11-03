"""Enrollment changes membership only, preserving existing parameter choices."""
from config_store import validate_config


def enroll(config, group_id, avatar_id, avatars):
    group = next((g for g in config['groups'] if g['id'] == group_id), None)
    if group is None:
        return None, '目标分组已不存在'
    owner = next((g for g in config['groups'] if avatar_id in g['avatars']), None)
    if owner:
        return None, '' if owner['id'] == group_id else f'模型属于“{owner["name"]}”，已跳过'
    avatar = avatars.get(avatar_id)
    if not avatar or not avatar.get('saved_names'):
        return None, '等待模型的本地参数与保存记录，准备好后自动添加'
    updated = validate_config(config)
    next(g for g in updated['groups'] if g['id'] == group_id)['avatars'].append(avatar_id)
    return validate_config(updated), ''
