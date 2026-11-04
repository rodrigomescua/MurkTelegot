"""Safe presentation of Telegram message data; original JSON remains the source."""
import json
import re
from html import escape
from urllib.parse import urlsplit

from markupsafe import Markup
from telethon.helpers import add_surrogate, del_surrogate, within_surrogate


def safe_url(value):
    if not isinstance(value, str) or re.search(r'[\x00-\x20\x7f]', value):
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() in ('https', 'http') and parsed.hostname:
            return value
        if parsed.scheme.lower() in ('mailto', 'tel', 'tg') and (parsed.path or parsed.netloc):
            return value
    except ValueError:
        pass
    return None


def rich_text(text, entities=()):
    """Use UTF-16 offsets, escape content, and reopen overlapping spans as valid HTML."""
    text = add_surrogate(text or '')
    spans = []
    tags = {
        'MessageEntityBold': ('<strong>', '</strong>'),
        'MessageEntityItalic': ('<em>', '</em>'),
        'MessageEntityUnderline': ('<u>', '</u>'),
        'MessageEntityStrike': ('<del>', '</del>'),
        'MessageEntityCode': ('<code>', '</code>'),
        'MessageEntityPre': ('<pre><code>', '</code></pre>'),
        'MessageEntityBlockquote': ('<blockquote>', '</blockquote>'),
        'MessageEntitySpoiler': ('<span class="spoiler" tabindex="0" role="button" aria-expanded="false" aria-label="Revelar spoiler">', '</span>'),
    }
    for index, entity in enumerate(entities or []):
        start, length = entity.get('offset'), entity.get('length')
        if not isinstance(start, int) or not isinstance(length, int) or start < 0 or length <= 0 or start >= len(text):
            continue
        end = min(len(text), start + length)
        if within_surrogate(text, start):
            start -= 1
        if within_surrogate(text, end):
            end += 1
        kind = entity.get('_')
        tag = tags.get(kind)
        fragment = del_surrogate(text[start:end])
        url = None
        if kind == 'MessageEntityTextUrl':
            url = entity.get('url')
        elif kind == 'MessageEntityUrl':
            url = fragment
        elif kind == 'MessageEntityEmail':
            url = 'mailto:' + fragment
        elif kind == 'MessageEntityPhone':
            url = 'tel:' + re.sub(r'[^+0-9]', '', fragment)
        elif kind == 'MessageEntityMention' and re.fullmatch(r'@[A-Za-z0-9_]+', fragment):
            url = 'https://t.me/' + fragment[1:]
        elif kind == 'MessageEntityMentionName' and isinstance(entity.get('user_id'), int):
            url = 'tg://user?id=' + str(entity['user_id'])
        if safe_url(url):
            tag = (f'<a href="{escape(url, quote=True)}" target="_blank" rel="noopener noreferrer" title="{escape(url, quote=True)}">', '</a>')
        if tag:
            spans.append((start, end, index, *tag))
    boundaries = sorted({0, len(text), *(x for span in spans for x in span[:2])})
    result, opened = [], []
    for start, end in zip(boundaries, boundaries[1:]):
        active = sorted((s for s in spans if s[0] <= start < s[1]), key=lambda s: (s[0], -s[1], s[2]))
        common = 0
        while common < min(len(opened), len(active)) and opened[common] == active[common]:
            common += 1
        result.extend(s[4] for s in reversed(opened[common:]))
        result.extend(s[3] for s in active[common:])
        result.append(escape(del_surrogate(text[start:end])))
        opened = active
    result.extend(s[4] for s in reversed(opened))
    return Markup(''.join(result))


def source_data(offer):
    try:
        value = json.loads(offer.get('source_json') or '{}')
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        return {}



def preview_lines(parts):
    """Keep two nonempty lines without exposing Telegram spoiler entities."""
    lines = []
    for part in parts:
        text = add_surrogate(part.get('body') or '')
        characters = list(text)
        for entity in source_data(part).get('entities') or []:
            if entity.get('_') != 'MessageEntitySpoiler':
                continue
            start, length = entity.get('offset'), entity.get('length')
            if not isinstance(start, int) or not isinstance(length, int) or start < 0 or length <= 0 or start >= len(text):
                continue
            end = min(len(text), start + length)
            if within_surrogate(text, start):
                start -= 1
            if within_surrogate(text, end):
                end += 1
            for offset in range(start, end):
                if text[offset] not in ('\n', '\r'):
                    characters[offset] = '•'
        for line in del_surrogate(''.join(characters)).splitlines():
            if line.strip():
                lines.append(line.strip())
                if len(lines) == 2:
                    return lines
    return lines

def media_info(source):
    media = source.get('media') or {}
    if media.get('ttl_seconds') or media.get('view_once'):
        return {'kind': 'unsupported', 'label': 'Mídia temporária — abra no Telegram'}
    webpage = media.get('webpage') or {}
    document = media.get('document') or webpage.get('document')
    photo = media.get('photo') or webpage.get('photo')
    if document and document.get('_') == 'Document':
        mime = document.get('mime_type') or 'application/octet-stream'
        attributes = document.get('attributes') or []
        name = next((a.get('file_name') for a in attributes if a.get('_') == 'DocumentAttributeFilename'), None) or 'arquivo'
        name = re.sub(r'[\x00-\x1f\x7f/\\]', '_', name)[:180]
        kind = 'file'
        if mime in ('image/jpeg', 'image/png', 'image/webp', 'image/gif'):
            kind = 'photo'
        elif mime in ('video/mp4', 'video/webm'):
            kind = 'video'
        elif mime in ('audio/mpeg', 'audio/ogg', 'audio/mp4', 'audio/wav', 'audio/webm', 'audio/flac'):
            kind = 'audio'
        return {'kind': kind, 'mime': mime, 'name': name, 'size': document.get('size') or 0,
                'identity': 'document-' + str(document.get('id')), 'thumbnail': bool(document.get('thumbs')),
                'spoiler': bool(media.get('spoiler'))}
    if photo and photo.get('_') == 'Photo':
        return {'kind': 'photo', 'mime': 'image/jpeg', 'name': 'foto.jpg', 'size': 0,
                'identity': 'photo-' + str(photo.get('id')), 'thumbnail': True,
                'spoiler': bool(media.get('spoiler'))}
    return None


def message_link(chat_id, message_id):
    return f'https://t.me/c/{str(chat_id)[4:]}/{message_id}' if str(chat_id).startswith('-100') else None


def text_value(value):
    return value.get('text', '') if isinstance(value, dict) else (value or '')


def present(offer):
    source = source_data(offer)
    media = source.get('media') or {}
    reply = source.get('reply_to') or {}
    forwarded = source.get('fwd_from') or {}
    webpage = media.get('webpage') or {}
    poll = media.get('poll') or {}
    result = {**offer, 'html': rich_text(offer['body'], source.get('entities')), 'media': media_info(source),
              'legacy': not bool(source), 'edited': bool(source.get('edit_date')),
              'author': source.get('post_author') or source.get('_sender_name'), 'views': source.get('views'),
              'forwarded': (forwarded.get('from_name') or forwarded.get('post_author') or 'Mensagem encaminhada') if forwarded else None,
              'reply': reply.get('reply_to_msg_id'),
              'reply_url': message_link(offer['chat_id'], reply['reply_to_msg_id']) if reply.get('reply_to_msg_id') else None,
              'quote': rich_text(reply.get('quote_text', ''), reply.get('quote_entities')),
              'preview': {'title': webpage.get('title') or webpage.get('site_name'),
                          'description': webpage.get('description'), 'url': safe_url(webpage.get('url'))} if webpage else None,
              'poll': None, 'contact': None, 'location': None, 'buttons': [], 'reactions': [], 'unsupported': None}
    if poll:
        results = media.get('results') or {}
        votes = {v.get('option'): v.get('voters', 0) for v in results.get('results') or []}
        result['poll'] = {'question': text_value(poll.get('question')), 'closed': bool(poll.get('closed')),
                          'total': results.get('total_voters') or 0,
                          'answers': [{'text': text_value(a.get('text')), 'votes': votes.get(a.get('option'), 0)} for a in poll.get('answers') or []]}
    if media.get('_') == 'MessageMediaContact':
        result['contact'] = {'name': ' '.join(filter(None, (media.get('first_name'), media.get('last_name')))),
                             'phone': media.get('phone_number')}
    geo = media.get('geo') or {}
    if isinstance(geo.get('lat'), (float, int)) and isinstance(geo.get('long'), (float, int)):
        lat, lon = geo['lat'], geo['long']
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            result['location'] = {'title': media.get('title') or 'Localização', 'address': media.get('address'),
                                  'url': f'https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=16/{lat}/{lon}'}
    for row in (source.get('reply_markup') or {}).get('rows') or []:
        result['buttons'].append([{'text': b.get('text') or 'Abrir no Telegram',
                                   'url': safe_url(b.get('url')) if b.get('_') == 'KeyboardButtonUrl' else None}
                                  for b in row.get('buttons') or []])
    for reaction in (source.get('reactions') or {}).get('results') or []:
        result['reactions'].append({'emoji': (reaction.get('reaction') or {}).get('emoticon') or 'Reação personalizada',
                                    'count': reaction.get('count') or 0})
    if media and not any((result['media'], result['preview'], result['poll'], result['contact'], result['location'])):
        result['unsupported'] = 'Conteúdo ' + media.get('_', 'Telegram').removeprefix('MessageMedia') + ' — abra no Telegram'
    return result
