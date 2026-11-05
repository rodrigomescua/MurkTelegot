import http.client
import json
import re
from html import escape
from html.parser import HTMLParser
import urllib.error
import urllib.request
from urllib.parse import quote, urlsplit

from app.messages import media_info, rich_text, safe_url, source_data


def validate_gotify_url(value):
    value = value.strip().rstrip('/')
    if not value:
        return ''
    try:
        parts = urlsplit(value)
        valid = (parts.scheme in ('http', 'https') and parts.hostname and parts.port != 0
                 and parts.username is None and parts.password is None and '?' not in value and '#' not in value
                 and not any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value))
    except ValueError:
        valid = False
    if not valid:
        raise ValueError('Informe uma URL HTTP ou HTTPS válida, sem credenciais ou parâmetros.')
    return value


def validate_gotify_token(token):
    if token and any(ord(char) < 33 or ord(char) > 126 for char in token):
        raise ValueError('O token Gotify não pode conter espaços ou caracteres inválidos.')
    return token


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class MarkdownFromHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = []
        self.stack = [('root', {}, self.root)]

    def handle_starttag(self, tag, attrs):
        children = []
        self.stack[-1][2].append((tag, dict(attrs), children))
        self.stack.append((tag, dict(attrs), children))

    def handle_endtag(self, tag):
        if len(self.stack) > 1 and self.stack[-1][0] == tag:
            self.stack.pop()

    def handle_data(self, data):
        self.stack[-1][2].append(data)


def markdown_text(value):
    value = escape(value, quote=False)
    return re.sub(r'([\\`*_{}\[\]()#+.!|~>-])', r'\\\1', value).replace('\n', '  \n')


def markdown_nodes(nodes, plain=False):
    output = []
    for node in nodes:
        if isinstance(node, str):
            output.append(node if plain else markdown_text(node))
            continue
        tag, attrs, children = node
        if tag == 'span' and 'spoiler' in attrs.get('class', '').split():
            output.append('[spoiler oculto]' if plain else r'\[spoiler oculto\]')
            continue
        if plain:
            output.append(markdown_nodes(children, plain=True))
            continue
        if tag in ('pre', 'code'):
            text = markdown_nodes(children, plain=True)
            longest = max((len(match.group()) for match in re.finditer(r'`+', text)), default=0)
            fence = '`' * max(3 if tag == 'pre' else 1, longest + 1)
            output.append(('\n\n' + fence + '\n' + text + '\n' + fence + '\n\n') if tag == 'pre'
                          else (fence + ' ' + text + ' ' + fence if '`' in text else fence + text + fence))
            continue
        content = markdown_nodes(children, plain=plain)
        if tag in ('strong', 'em', 'del'):
            marker = {'strong': '**', 'em': '*', 'del': '~~'}[tag]
            output.append(marker + content + marker)
        elif tag == 'a' and safe_url(attrs.get('href')):
            target = quote(attrs['href'], safe=":/?#[]@!$&'*+,;=%~-._")
            output.append(f'[{content}]({target})')
        elif tag == 'blockquote':
            output.append('\n\n' + '\n'.join('> ' + line for line in content.splitlines()) + '\n\n')
        else:
            output.append(content)
    return ''.join(output)


def gotify_message(offer):
    source = source_data(offer)
    parser = MarkdownFromHTML()
    parser.feed(str(rich_text(offer.get('body', ''), source.get('entities'))))
    result = markdown_nodes(parser.root)
    if media_info(source):
        result += '\n\n📎 Mídia disponível no Telegram.'
    if safe_url(offer.get('url')):
        result += '\n\n[Abrir oferta no Telegram](' + quote(offer['url'], safe=":/?#[]@!$&'*+,;=%~-._") + ')'
    return result.strip()


def send_gotify(url, token, title, message):
    try:
        request = urllib.request.Request(url + '/message', data=json.dumps({
            'title': title, 'message': message, 'priority': 5,
            'extras': {'client::display': {'contentType': 'text/markdown'}},
        }).encode(), headers={'Content-Type': 'application/json', 'X-Gotify-Key': token}, method='POST')
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=5) as response:
            return 200 <= response.status < 300
    except (urllib.error.URLError, OSError, ValueError, UnicodeError, http.client.HTTPException):
        return False
