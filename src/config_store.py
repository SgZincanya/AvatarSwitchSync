"""Portable configuration schema. No avatars or groups are shipped by default."""
import copy
import json
from pathlib import Path
import uuid

VERSION = "0.8.1"


def empty_config():
    return {"version": 1, "groups": []}


def validate_config(value):
    if not isinstance(value, dict) or value.get("version") != 1 or not isinstance(value.get("groups"), list):
        raise ValueError("配置格式不正确，或版本暂不支持。")
    if len(value['groups']) > 500:
        raise ValueError("分组数量超过支持范围。")
    seen_ids, seen_avatars = set(), set()
    for group in value['groups']:
        if not isinstance(group, dict):
            raise ValueError("分组格式不正确。")
        gid, name = group.get('id'), group.get('name')
        if not isinstance(gid, str) or not gid or gid in seen_ids or not isinstance(name, str) or not name.strip():
            raise ValueError("分组名称或标识无效。")
        seen_ids.add(gid)
        avatars = group.get('avatars')
        if (not isinstance(avatars, list) or len(avatars) < 1 or
                any(not isinstance(a, str) or not a.startswith('avtr_') for a in avatars) or
                len(set(avatars)) != len(avatars) or seen_avatars.intersection(avatars)):
            raise ValueError("每组需要至少一个模型，同一个模型不能重复加入分组。")
        seen_avatars.update(avatars)
        parameters = group.get('parameters')
        if not isinstance(parameters, list) or len(parameters) > 20000:
            raise ValueError("参数列表无效。")
        names = set()
        for item in parameters:
            if not isinstance(item, dict) or not isinstance(item.get('name'), str) or not item['name'] or item['name'] in names:
                raise ValueError("参数名称无效或重复。")
            names.add(item['name'])
            if item.get('type') not in ('Bool', 'Int', 'Float') or type(item.get('enabled')) is not bool:
                raise ValueError("参数类型或共享开关无效。")
            if not isinstance(item.get('reason', ''), str):
                raise ValueError("排除原因无效。")
            mapping = item.get('mapping', {})
            if not isinstance(mapping, dict) or any(k not in avatars or not isinstance(v, str) or not v for k, v in mapping.items()):
                raise ValueError("参数映射无效。")
    return copy.deepcopy(value)


def load_config(path):
    path = Path(path)
    if not path.exists():
        return empty_config()
    if path.stat().st_size > 10_000_000:
        raise ValueError("配置文件过大。")
    return validate_config(json.loads(path.read_text(encoding='utf-8-sig')))


def merge_config(current, incoming):
    """Import definitions only; new identities avoid replaying unrelated saved states."""
    result = validate_config(current)
    added = validate_config(incoming)
    for group in added['groups']:
        group['id'] = uuid.uuid4().hex
    result['groups'].extend(added['groups'])
    return validate_config(result)


def display_name(raw):
    import re
    name = re.sub(r'^__MA/AutoParam/', '', raw)
    return re.sub(r'\$[0-9a-fA-F]{8,}$', '', name)
