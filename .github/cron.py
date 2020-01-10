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
token = os.environ['GITHUB_PERSONAL_ACCESS_TOKEN']
owner, repo = os.environ['GITHUB_REPOSITORY'].split('/')
feed_url = f'https://{owner}.github.io/{repo}/atom.xml'
hub_url = 'https://pubsubhubbub.appspot.com/'

session = requests.Session()

def request(method, url, *, user_agent='Googlebot/2.1 (+http://www.google.com/bot.html)', **kwargs):
    kwargs.setdefault('headers', {})['User-Agent'] = user_agent
    return session.request(method, url, **kwargs)

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

logging.info('fetching article list')
body = get('https://www.weibo.com/p/1006065582522936/wenzhang').text
articles = []
new_article_available = False
CST = datetime.timezone(datetime.timedelta(hours=8))
for match in re.finditer(r'<a target="_blank" href="([^"]+)" class="W_autocut S_txt1">\s*(.*?)</a>\s*</div>\s*</div>\s*<div class="subinfo_box">\s*<span class="subinfo S_txt2">(\d{4,}) 年 (\d{2}) 月 (\d{2}) 日 (\d{2}):(\d{2})</span>', body):
    uri, title, *publish_time = match.groups()
    uri = html.unescape(uri)
    if uri.endswith('&mod=zwenzhang'):
        uri = uri[:-14]
    assert uri.startswith('/')
    url = f'https://www.weibo.com{uri}'
    title = html.unescape(title)
    publish_time = datetime.datetime(*(int(s) for s in publish_time), tzinfo=CST)
    articles.append((url, title, publish_time))
    if publish_time > timestamp:
        new_article_available = True
        timestamp = publish_time

if not new_article_available:
    logging.info('new articles not found')
    sys.exit(0)

logging.info('logging in Weibo')
weibo_login(weibo_username, weibo_password)

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

with open('gh-pages/atom.xml', 'wb') as f:
    f.write(feed.atom_str(pretty=True))
with open('gh-pages/timestamp.txt', 'w') as f:
    f.write(timestamp.isoformat(timespec='minutes'))

subprocess.check_call(['.github/commit.sh'])

logging.info('deploy GitHub Pages')
url = f'https://api.github.com/repos/{owner}/{repo}/pages'
headers = {
    'Authorization': f'token {token}',
    'Accept': 'application/vnd.github.v3+json',
}
status = post(url+'/builds', headers=headers).json()['status']
while status not in ('built', 'errored'):
    time.sleep(5)
    status = get(url, headers=headers).json()['status']
assert status == 'built', f'GitHub Pages build failed'

logging.info('notify WebSub hub')
post(hub_url,
    data={
        'hub.mode': 'publish',
        'hub.url': feed_url,
    },
)
