#!/usr/bin/env python3
import base64
import datetime
import feedgen.feed
import html
import json
import logging
import os
import re
import requests
import rsa
import subprocess
import sys
import time
import urllib.parse

logging.basicConfig(
    level=logging.DEBUG,
    format='[%(levelname)s] %(message)s',
)

weibo_username = os.environ['WEIBO_USERNAME']
weibo_password = os.environ['WEIBO_PASSWORD']
owner, repo = os.environ['GITHUB_REPOSITORY'].split('/')
feed_url = os.environ['FEED_URL']
hub_url = os.environ['HUB_URL']

session = requests.Session()

def request(method, url, *, user_agent='Googlebot/2.1 (+http://www.google.com/bot.html)', retry=4, retry_interval=1, status_code=200, **kwargs):
    kwargs.setdefault('headers', {})['User-Agent'] = user_agent
    kwargs.setdefault('timeout', 15)
    for i in range(retry+1):
        if i > 0:
            logging.error(f'retry #{i}')
        try:
            rsp = session.request(method, url, **kwargs)
            if rsp.status_code == status_code:
                return rsp
            logging.error(f'{rsp.status_code} {rsp.reason}')
        except Exception:
            logging.exception('exception during HTTP request')
        time.sleep(retry_interval)

def get(url, **kwargs):
    return request('GET', url, **kwargs)

def post(url, **kwargs):
    return request('POST', url, **kwargs)

def weibo_login(username, password):
    rsp = get('https://login.sina.com.cn/sso/prelogin.php',
        params={
            'entry': 'sso',
            'callback': 'sinaSSOController.preloginCallBack',
            'su': urllib.parse.quote_plus(username),
            'rsakt': 'mod',
        },
    )
    # sinaSSOController.preloginCallBack({...})
    prelogin = json.loads(re.search('\((.*)\)$', rsp.text).group(1))

    pub_key = rsa.PublicKey(n=int(prelogin['pubkey'], 16), e=0x10001)
    message = (str(prelogin['servertime']) + '\t' + prelogin['nonce'] + '\n' + password).encode()

    form = {
        'servertime': prelogin['servertime'],
        'nonce': prelogin['nonce'],
        'rsakv': prelogin['rsakv'],
        'su': base64.b64encode(urllib.parse.quote(username).encode()),
        'sp': rsa.encrypt(message, pub_key).hex(),
        'pwencode': 'rsa2',
        'url': 'https://www.weibo.com/',
    }
    rsp = post('https://login.sina.com.cn/sso/login.php', data=form)
    match = re.search(r'location\.replace\("(.*?)"\);', rsp.text)
    assert match, rsp.text
    url = match.group(1)

    rsp = get(url)
    match = re.search(r"location\.replace\('(.*?)'\);", rsp.text)
    assert match, rsp.text
    url = match.group(1)

    get(url)

feed = feedgen.feed.FeedGenerator()
feed.id('urn:uuid:18019db5-cd10-4a0a-b32c-bb060bf1b2fe')
feed.link(rel='self', href=feed_url)
feed.link(rel='hub', href=hub_url)
feed.logo('https://xlab.tencent.com/cn/wp-content/themes/twentysixteen/images/small_logo_144.png')
feed.title('每日安全动态推送')
feed.author({'name': '腾讯安全玄武实验室', 'uri': 'https://xlab.tencent.com/'})
feed.language('zh-CN')

try:
    with open('gh-pages/timestamp.txt') as f:
        timestamp = datetime.datetime.fromisoformat(f.read())
except Exception:
    timestamp = datetime.datetime.fromtimestamp(0, datetime.timezone.utc)

logging.info('logging in Weibo')
weibo_login(weibo_username, weibo_password)

logging.info('fetching article list')
body = get('https://www.weibo.com/p/1006065582522936/wenzhang').text
articles = []
new_article_available = False
CST = datetime.timezone(datetime.timedelta(hours=8))
for match in re.finditer(r'(?s) date="(\d+)".*?title="([^"]+)".*?action-data="url=(https%3A%2F%2Fweibo.com%2Fttarticle%2Fp%2Fshow%3Fid%3D\d+)', body):
    publish_time, title, url = match.groups()
    publish_time = datetime.datetime.fromtimestamp(int(publish_time) / 1000, tz=CST)
    title = html.unescape(title)
    url = urllib.parse.unquote(url)
    articles.append((url, title, publish_time))
    if publish_time > timestamp:
        new_article_available = True
        timestamp = publish_time

if not new_article_available:
    logging.info('new articles not found')
    sys.exit(0)

for url, title, publish_time in articles:
    logging.info('fetching article %s', title)
    body = get(url).text
    match = re.search(r'(?s)<div class="WB_editor_iframe_new" node-type="contentBody" style="visibility: hidden">\s*(.*?)<p img-box="img-box" class="picbox">', body)
    assert match, body

    for idx, item in enumerate(match.group(1).split('\n<ul><br></ul>\n')):
        if '查看或搜索历史推送内容请访问' in item:
            continue
        lines = item.split('\n')
        title, link = re.fullmatch(r'<p align="justify">(.*?):<a href="([^"]*)"><br>.*?</a></p>', lines[0]).groups()
        content = '<br>'.join(re.fullmatch(r'<p align="justify">・\xa0(.*?)\xa0–\xa0<a href="https://sec\.today/user/[-0-9a-f]+/pushes/">.*?</a></p>', line).group(1) for line in lines[1:])
        title = html.unescape(title).replace('<i>', '').replace('</i>', '')
        content = html.unescape(content)
        entry = feed.add_entry(order='append')
        entry.id(f'{url}#{idx}')
        entry.updated(publish_time)
        entry.title(title)
        entry.link(href=link)
        entry.content(content, type='html')
        logging.info('entry: %s', title)

feed.updated(timestamp)

with open('gh-pages/atom.xml', 'wb') as f:
    f.write(feed.atom_str(pretty=True))
with open('gh-pages/timestamp.txt', 'w') as f:
    f.write(timestamp.isoformat())
