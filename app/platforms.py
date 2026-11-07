"""Platform URL and gallery-dl metadata normalization, without network side effects."""
import re
from urllib.parse import urlparse


def parse_profile_url(value):
    url = urlparse(value.strip())
    host = (url.hostname or '').lower()
    parts = [part for part in url.path.split('/') if part]
    if url.scheme not in {'https', 'http'}:
        raise ValueError('请输入完整的平台主页链接')
    if host in {'instagram.com', 'www.instagram.com'}:
        if not parts or not re.fullmatch(r'[A-Za-z0-9._]{1,30}', parts[0]) or parts[0].lower() in {'p', 'reel', 'reels', 'stories', 'explore', 'accounts'}:
            raise ValueError('请输入 Instagram 用户主页链接')
        return 'instagram', parts[0].lower()
    if host in {'weibo.com', 'www.weibo.com', 'm.weibo.cn'}:
        if len(parts) >= 2 and parts[0] == 'u' and parts[1].isdigit():
            return 'weibo', parts[1]
        raise ValueError('请输入包含数字用户 ID 的微博主页链接')
    raise ValueError('不支持的平台主页链接')


def media_metadata(platform, item):
    """Use platform-prefixed post IDs so ignore records cannot collide across sites."""
    if platform == 'instagram':
        post_id, date, number = item.get('post_id'), item.get('date'), item.get('num')
    elif platform == 'weibo':
        status = item.get('status') or {}
        post_id, date, number = status.get('id'), status.get('date'), item.get('num')
    else:
        raise ValueError('不支持的平台')
    if post_id is None or date is None or not isinstance(number, int) or number < 1:
        raise ValueError('媒体缺少稳定的帖子编号、发文时间或媒体序号')
    return {'tweet_id': f'{platform}:{post_id}', 'date': date, 'num': number,
            'extension': item.get('extension', '')}
